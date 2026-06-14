#!/usr/bin/env python3
"""Twin Cobra host smoke harness -- run the 68000 program on Musashi
(machine68k), STUB the TMS32010 DSP and Z80, and watch where it stalls.

Goal: boot the real 68000 ROM far enough that it demands the DSP, then
report exactly which PC/loop and which address it's polling -- that tells
us precisely what the DSP must provide before we write a TMS32010 core.

Memory map + ROM interleave are taken from games/twincobr/io_map.json /
META.toml (verified vs MAME toaplan/twincobr.cpp). No IRQ injection yet
(machine68k exposes no set-irq), so this reaches the boot/self-test/DSP
handshake but not the vblank-driven main loop -- which is exactly the
phase we want to observe first.

    python3 tests/host/twincobr_host.py [max_million_cycles]
"""
import sys, collections
import machine68k
from machine68k import CPUType, Register

ROOT = "games/twincobr"
MAXMC = next((int(a) for a in sys.argv[1:] if a.isdigit()), 20)

def rd(p):
    return open(f"{ROOT}/{p}", "rb").read()

def interleave(even, odd):
    out = bytearray(len(even) * 2)
    out[0::2] = even
    out[1::2] = odd
    return bytes(out)

# ---- 68000 program: even/odd ROM_LOAD16_BYTE pairs ----
low  = interleave(rd("maincpu/b30_01.7j"), rd("maincpu/b30_03.7h"))      # 0x00000-0x1ffff
high = interleave(rd("maincpu/b30_26_ii.8j"), rd("maincpu/b30_27_ii.8h"))# 0x20000-0x2ffff
ROM  = low + high
assert len(ROM) == 0x30000, hex(len(ROM))

m   = machine68k.Machine(CPUType.M68000, 1024)   # 1 MB flat (covers 0..0xfffff)
mem = m.mem
cpu = m.cpu
mem.w_block(0x000000, ROM)                       # ROM (incl. reset vectors @0/4)

# ---- idle input values (Toaplan inputs active-low: 0xffff = nothing) ----
INPUTS = {0x078000: 0xffff,  # DSW1
          0x078002: 0xffff,  # DSW2
          0x078004: 0xffff,  # P1
          0x078006: 0xffff,  # P2
          0x078008: 0xffff}  # SYS (vblank+coin/service)
z80_shared = bytearray(0x1000)           # 0x07a000-0x07afff
regs = {}                                # scroll/CRTC/latch writes (logged)
io_writes = []                           # (pc, addr, val, width) of control writes
latch = [0] * 8                          # mainlatch LS259 (q0..q7)
intenable = [0]                          # latch bit2 -> vblank IRQ4 enable

# ---- tilemap VRAM (twincobr_v.cpp): explicit offset reg + data port, no auto-inc.
txvram = [0] * 0x800                      # 64x32, tx
bgvram = [0] * 0x2000                     # 64x64 x2 banks, bg
fgvram = [0] * 0x1000                     # 64x64, fg
txoffs = [0]; bgoffs = [0]; fgoffs = [0]
scroll = {"txx":0,"txy":0,"bgx":0,"bgy":0,"fgx":0,"fgy":0}

# ---- TMS320C10 DSP (real core) + the twincobr_m.cpp host bridge ----
sys.path.insert(0, "tools")
from tms320c10 import TMS320C10
def _il_dsp():
    e = rd("dsp/dsp_21.bin"); o = rd("dsp/dsp_22.bin")   # 21=even(0x0000)=hi byte
    return [((e[i] << 8) | o[i]) for i in range(len(e))]  # big-endian program word
dsp_seg = [0]; dsp_addr = [0]; dsp_done = [False]
def dsp_io_in(port):
    if port == 1: return mem.r16((dsp_seg[0] + dsp_addr[0]) & 0xffffff)
    return 0
def dsp_io_out(port, val):
    if port == 0:
        dsp_seg[0]  = (val & 0xe000) << 3
        dsp_addr[0] = (val & 0x1fff) << 1
    elif port == 1:
        if dsp_seg[0] in (0x30000, 0x40000, 0x50000):
            mem.w16((dsp_seg[0] + dsp_addr[0]) & 0xffffff, val & 0xffff)
        if dsp_seg[0] == 0x30000 and dsp_addr[0] < 3 and val == 0:
            dsp_done[0] = True               # "execute" -> release the 68K
def dsp_bio(): return False
DSP = TMS320C10(_il_dsp(), dsp_io_in, dsp_io_out, dsp_bio)
dsp_runs = [0]
DSP_TRACE = ("--dsptrace" in sys.argv)
def run_dsp(max_steps=200000):
    """68K asserted dsp_int (0x0d -> 0x07800c). Run the DSP until it writes the
    done flag (0 to 0x030000) or the step cap. Persistent state across calls."""
    dsp_done[0] = False
    DSP.int_pending = True
    dsp_runs[0] += 1
    trace = DSP_TRACE and dsp_runs[0] == 1
    seen = []
    for i in range(max_steps):
        if trace and i < 120:
            seen.append((DSP.PC, DSP.P[DSP.PC & 0xfff], DSP.INTM, DSP.int_pending))
        DSP.step()
        if dsp_done[0]:
            if trace: _dsp_dump(seen, i)
            return True
    if trace: _dsp_dump(seen, max_steps); print(f"  DSP run #1 did NOT finish in {max_steps} steps")
    return False
def _dsp_dump(seen, n):
    print(f"  --- DSP run #1 trace ({n} steps), seg={dsp_seg[0]:#x} addr={dsp_addr[0]:#x} ---")
    for pc, op, intm, ip in seen[:60]:
        print(f"    PC={pc:03x} op={op:04x} INTM={intm} intp={ip}")

# ---- synthesize the vblank IRQ4 (machine68k has no IRQ-inject API) ----
# Standard 68000 autovector exception: if int_enable and the SR mask allows
# level 4, push PC+SR to the supervisor stack and vector via 0x70.
irq_count = [0]
def do_vblank_irq():
    if not intenable[0]: return False
    old_sr = cpu.r_sr()
    if ((old_sr >> 8) & 7) >= 4: return False           # IRQ4 currently masked
    old_pc = cpu.r_pc()
    ssp = cpu.r_sp() if (old_sr & 0x2000) else cpu.r_isp()
    ssp = (ssp - 6) & 0xffffff
    mem.w16(ssp, old_sr)                                 # frame: [SP]=SR
    mem.w32(ssp + 2, old_pc)                             #        [SP+2]=PC
    handler = mem.r32(0x000070)                          # level-4 autovector
    cpu.w_sr((old_sr & 0x00ff) | 0x2400)                # S=1, T=0, mask=4
    cpu.w_isp(ssp); cpu.w_sp(ssp)
    cpu.w_pc(handler)
    irq_count[0] += 1
    return True

def page060_r16(a): return 0
def page060_w16(a, v): regs[a] = v        # CRTC addr/reg

# VBLANK lives in bit 7 of 0x078009 (low byte of the SYS word). The game spins
# on it, so we must toggle it like a real ~60Hz vblank. machine68k gives no
# IRQ injection, but this source is POLLED, so toggling the read satisfies it.
_sysr = [0]
def sys_word():
    _sysr[0] += 1
    v = 0xffff
    if (_sysr[0] >> 9) & 1:        # spend ~half the "frames" with vblank clear
        v &= ~0x0080               # clear bit7 of the low byte (0x078009)
    return v

def page070_r8(a):
    if a in (0x07800d, 0x07800b): return 0
    # Z80 sound stub: the 68K writes a command at 0x07a000 then polls 0x07a001
    # for the Z80's 0xff ack. With no Z80, fake an instant ack so boot proceeds.
    if a == 0x07a001: return 0xff
    if 0x07a000 <= a < 0x07b000: return z80_shared[a - 0x07a000]
    base = a & ~1
    if base == 0x078008:
        w = sys_word(); return (w >> 8) if (a & 1) == 0 else (w & 0xff)
    if base in INPUTS:
        w = INPUTS[base]
        return (w >> 8) if (a & 1) == 0 else (w & 0xff)   # 68k big-endian
    return regs.get(a, 0xff)

def page070_r16(a):
    if a == 0x078008: return sys_word()
    if a == 0x07e000: return txvram[txoffs[0]]
    if a == 0x07e002: return bgvram[bgoffs[0] + (latch[4] * 0x1000)]
    if a == 0x07e004: return fgvram[fgoffs[0]]
    if a in INPUTS: return INPUTS[a]
    if 0x07a000 <= a < 0x07b000:
        hi = z80_shared[a-0x07a000]
        lo = 0xff if (a+1-0x07a000) == 1 else z80_shared[a+1-0x07a000]  # Z80 ack @0x07a001
        return (hi << 8) | lo
    return regs.get(a, 0xffff)

def page070_w8(a, v):
    if 0x07a000 <= a < 0x07b000: z80_shared[a-0x07a000] = v & 0xff; return
    regs[a] = v
    if a in (0x07800d, 0x07800b):
        io_writes.append((cpu.r_pc(), a, v, 8))

def page070_w16(a, v):
    if 0x07a000 <= a < 0x07b000:
        z80_shared[a-0x07a000] = (v >> 8) & 0xff; z80_shared[a-0x07a000+1] = v & 0xff; return
    # ---- video offset regs / scroll / VRAM data ports ----
    if   a == 0x070000: scroll["txx"] = v; return
    elif a == 0x070002: scroll["txy"] = v; return
    elif a == 0x070004: txoffs[0] = v % 0x800; return
    elif a == 0x072000: scroll["bgx"] = v; return
    elif a == 0x072002: scroll["bgy"] = v; return
    elif a == 0x072004: bgoffs[0] = v % 0x1000; return
    elif a == 0x074000: scroll["fgx"] = v; return
    elif a == 0x074002: scroll["fgy"] = v; return
    elif a == 0x074004: fgoffs[0] = v % 0x1000; return
    elif a == 0x07e000: txvram[txoffs[0]] = v; return
    elif a == 0x07e002: bgvram[bgoffs[0] + (latch[4] * 0x1000)] = v; return
    elif a == 0x07e004: fgvram[fgoffs[0]] = v; return
    regs[a] = v
    if a in (0x07800c, 0x07800a, 0x07800d, 0x07800b):
        io_writes.append((cpu.r_pc(), a, v, 16))
        # mainlatch LS259 @0x07800d (low byte of the word): idx=(b>>1)&7, data=b&1.
        # bit2=int_enable(vblank IRQ4), bit6=dsp_int(run DSP), bit7=display_on.
        if a == 0x07800c:
            b = v & 0xff; idx = (b >> 1) & 7; data = b & 1
            latch[idx] = data
            if idx == 2: intenable[0] = data
            if idx == 6 and data == 1: run_dsp()

mem.set_special_range_read_funcs (0x060000, 1, None, page060_r16, None)
mem.set_special_range_write_funcs(0x060000, 1, None, page060_w16, None)
mem.set_special_range_read_funcs (0x070000, 1, page070_r8, page070_r16, None)
mem.set_special_range_write_funcs(0x070000, 1, page070_w8, page070_w16, None)

cpu.pulse_reset()
ssp = mem.r32(0x000000); pc0 = mem.r32(0x000004)
print(f"ROM 0x{len(ROM):x} loaded.  reset SSP=0x{ssp:06x}  PC=0x{pc0:06x}")
print(f"  PC=0x{cpu.r_pc():06x} after reset")

# ---- run with a PC histogram to catch the stall loop ----
ring   = collections.deque(maxlen=64)
hist   = collections.Counter()
crash  = [None]
pchits = {0x20194:0, 0x25a36:0, 0x23e88:0, 0x23f06:0}
def ih(pc):
    ring.append(pc)
    hist[pc] += 1
    if pc in pchits: pchits[pc] += 1
    if not (pc < 0x030000 or 0x030000 <= pc < 0x100000):
        if crash[0] is None:
            crash[0] = pc; m.abort_execute(m.create_execute_end("end"))
cpu.set_instr_hook_callback(ih)
import atexit
atexit.register(lambda: print("PCHITS restart(20194)=%d demo(25a36)=%d mainloop(23e88)=%d bra20194(23f06)=%d"%(
    pchits[0x20194],pchits[0x25a36],pchits[0x23e88],pchits[0x23f06])))

CHUNK = 100_000
total = 0
stall_pc = None
# Persistence-based stall: the PC window must stay tiny AND not move on for
# several consecutive chunks (transient init loops escape; a real wait won't).
stuck_chunks = 0
prev_window = None
prev_regs = None
max_pc = 0
chunk_i = 0
DA = [getattr(Register, p + str(i)) for p in "DA" for i in range(8)]
def reg_snapshot():
    return tuple(cpu.r_reg(r) for r in DA)
cyc_since_vbl = 0
while total < MAXMC * 1_000_000:
    ring.clear()
    # ~60Hz vblank: 7MHz/60 ~= 116k cycles. Inject IRQ4 when due + enabled.
    cyc_since_vbl += CHUNK
    if cyc_since_vbl >= 116000:
        cyc_since_vbl = 0
        do_vblank_irq()
    try:
        ran = m.execute(CHUNK).cycles
    except Exception as e:
        print(f"  EXCEPTION at PC=0x{cpu.r_pc():06x}: {e}"); break
    total += ran; chunk_i += 1
    if crash[0] is not None: break
    pc = cpu.r_pc(); rsnap = reg_snapshot(); max_pc = max(max_pc, max(ring) if ring else 0)
    w = (min(ring), max(ring)) if ring else (0, 0)
    tight = (w[1] - w[0]) < 0x80 and len(set(ring)) <= 12
    # TRUE poll-wait = tight loop where NO data/addr register advances between
    # chunks. Checksums/RAM-marches advance a register; a real wait does not.
    if tight and w == prev_window and rsnap == prev_regs:
        stuck_chunks += 1
        if stuck_chunks >= 4:
            stall_pc = pc; break
    else:
        stuck_chunks = 0
    prev_window = w if tight else None
    prev_regs = rsnap
    if chunk_i % 40 == 0:
        print(f"  ..{total//1000:>7}k cyc  PC=0x{pc:06x}  maxPC=0x{max_pc:06x}")

def _nz(base, length):
    b = mem.r_block(base, length); return sum(1 for x in b if x)
print(f"\nran ~{total:,} cycles  PC=0x{cpu.r_pc():06x}  (stuck={stall_pc is not None})")
print(f"  vblank IRQ4 injected: {irq_count[0]}   DSP triggered: {dsp_runs[0]}")
print(f"  display RAM nonzero bytes:  sprites(0x40000)={_nz(0x040000,0x1000)}/4096"
      f"  palette(0x50000)={_nz(0x050000,0x0e00)}/3584  workRAM(0x30000)={_nz(0x030000,0x4000)}/16384")
print(f"  tilemaps nonzero: tx={sum(1 for x in txvram if x)}/2048"
      f"  bg={sum(1 for x in bgvram if x)}/8192  fg={sum(1 for x in fgvram if x)}/4096"
      f"  | banks bg={latch[4]} fg={latch[5]}  scroll={scroll}")
if crash[0] is not None:
    print(f"  WILD PC / fault near 0x{crash[0]:06x}")
print("  regs: " + "  ".join(
    f"A{i}=0x{cpu.r_reg(getattr(Register,'A'+str(i))):06x}" for i in range(0,3)) +
    "  " + "  ".join(f"D{i}=0x{cpu.r_reg(getattr(Register,'D'+str(i))):04x}" for i in range(0,5)))

print("\n--- hottest PCs (the stall loop) ---")
for pc, n in hist.most_common(10):
    try:
        sz, txt = cpu.disassemble(pc)
    except Exception:
        txt = "?"
    print(f"  0x{pc:06x} x{n:<8} {txt}")

print("\n--- control-latch / DSP writes seen (pc -> addr=val) ---")
for pc, a, v, w in io_writes[-15:]:
    tag = "DSP_CTRL" if a in (0x07800c,0x07800d) else ("COIN_LATCH" if a in (0x07800a,0x07800b) else "")
    print(f"  pc=0x{pc:06x}  [0x{a:06x}]={v:#06x} ({w}b) {tag}")

print("\n--- disassembly around final PC (the wait) ---")
p = (cpu.r_pc() - 8) & 0xfffffe
for _ in range(10):
    try:
        sz, txt = cpu.disassemble(p)
    except Exception:
        sz, txt = 2, "?"
    mark = " <=" if p == cpu.r_pc() else ""
    print(f"  0x{p:06x}: {txt}{mark}")
    p += sz if sz else 2

# ---- optional: render the captured attract screen to a PPM ----
if "--render" in sys.argv:
    from twincobr_render import render_attract
    sb = bytes(mem.r_block(0x040000, 0x1000))   # sprite RAM
    pb = bytes(mem.r_block(0x050000, 0x0e00))   # palette RAM (1792 words)
    out = render_attract(txvram, bgvram, fgvram, scroll, latch, sb, pb,
                         "/tmp/twincobr_attract.ppm")
    print("wrote", out)

#!/usr/bin/env python3
"""Run the native Moon Cresta transcode on the HOST via machine68k (Musashi).

Loads the flat-linked transcode (tools build) + the ROM into a 64K Z80 space,
runs cpu_init + the entry/init + the NMI handler, and reports whether they
return and what they write to VRAM. Lets us debug the native 68k transcode on
the host instead of blind-iterating ADFs on the Amiga.

Layout: code @ 0x40000 (flat, base must match the link), Z80 space (a6) @
0x10000 (ROM 0..0x3fff, RAM/VRAM/objram/IO above), 68k stack @ 0x8000.
"""
import sys
import machine68k
from machine68k import CPUType, Register

FLAT   = "/tmp/mc_flat.bin"
ROMDIR = "games/mooncrst/roms"
ROMS   = ["epr194","epr195","epr196","epr197","epr198","epr199","epr200","epr201"]

CODE_BASE = 0x40000
MEMBASE   = 0x10000          # a6 = Z80 address space
STACK     = 0x0000F000
ZSTACK    = MEMBASE + 0x8400
SENT      = 0x00002000       # mapped sentinel return address

# Read linked symbol addresses from the vlink map (auto-tracks offsets).
SYM = {}
for ln in open("map.txt"):
    m = __import__("re").match(r'\s*0x([0-9a-f]+)\s+(\S+):', ln)
    if m: SYM.setdefault(m.group(2), int(m.group(1), 16))
CPU_INIT    = SYM["cpu_init"]
L_0000      = SYM["l_0000"]
L_0066      = SYM["l_0066"]
L_0287      = SYM["l_0287"]  # ROM idle/vblank-wait loop
L_02BC      = SYM["l_02bc"]
Z80_SP_BASE = SYM["z80_sp_base"]
Z80JMP_BAD  = SYM.get("z80jmp_bad")
Z80_RET16   = SYM.get("z80_ret16")
RUN_IDLE = "--run-idle" in sys.argv
WATCH_SCHED = "--watch-sched" in sys.argv
TRACE_RET16 = "--trace-ret16" in sys.argv

m   = machine68k.Machine(CPUType.M68020, 4096)
mem = m.mem
cpu = m.cpu

mem.w_block(CODE_BASE, open(FLAT, "rb").read())
rom = b"".join(open(f"{ROMDIR}/{f}", "rb").read() for f in ROMS)
mem.w_block(MEMBASE, rom)
mem.w8(MEMBASE + 0xb000, 0x00)        # idle DSW

# reset vectors so pulse_reset is happy, then drive manually
mem.w_block(0, STACK.to_bytes(4, "big"))
mem.w_block(4, CPU_INIT.to_bytes(4, "big"))
mem.w_block(SENT, b"\x60\xfe")          # bra.s *; keeps delayed abort quiet
cpu.pulse_reset()

# Per-instruction hook: stop at the sentinel return, and catch the first
# jump into a wild address (the crash), reporting the source instruction.
END = m.create_execute_end("end")
def valid(pc):
    return (CODE_BASE <= pc < CODE_BASE + 0x20000) or \
           (MEMBASE <= pc < MEMBASE + 0x10000)
import collections
_ring = collections.deque(maxlen=160)  # (pc, sp) pairs
_crash = [None]
_returned = [False]
_idle_hit = [False]
_idle_ok = [False]
_watch_sched = [None]
_ret16_seen = 0
def ih(pc):
    # Returning to the sentinel = clean return to driver. abort_execute() from
    # the hook doesn't halt instantly, so SENT contains a valid spin loop.
    if SENT <= pc < SENT + 2:
        _returned[0] = True
        m.abort_execute(END); return
    if Z80JMP_BAD is not None and pc == Z80JMP_BAD and _crash[0] is None:
        _crash[0] = (f"z80jmp_bad target d6=${cpu.r_reg(Register.D6) & 0xffff:04x}", pc)
        m.abort_execute(END); return
    global _ret16_seen
    if TRACE_RET16 and Z80_RET16 is not None and pc == Z80_RET16 and _ret16_seen < 20:
        target = int.from_bytes(mem.r_block(cpu.r_sp(), 2), "big")
        prev = _ring[-1][0] if _ring else 0
        print(f"RET16 target=${target:04x} prev={prev:06x} sp={cpu.r_sp():06x}")
        _ret16_seen += 1
    if WATCH_SCHED and _watch_sched[0] is not None and _crash[0] is None:
        cur = bytes(mem.r_block(MEMBASE + 0x8002, 2))
        if cur != _watch_sched[0]:
            _crash[0] = (f"sched base changed {cur[0]:02x} {cur[1]:02x}", pc)
            m.abort_execute(END); return
    # In the async/native model, a frame does not return like a C subroutine.
    # The Z80 NMI handler does its work and falls back into the ROM's idle loop
    # until the next vblank interrupt redirects execution to frame_entry.
    if _idle_ok[0] and not RUN_IDLE and L_0287 <= pc < L_02BC:
        _idle_hit[0] = True
        m.abort_execute(END); return
    sp = cpu.r_sp()
    if valid(pc):
        _ring.append((pc, sp))
    elif _crash[0] is None:
        _crash[0] = (_ring[-1][0] if _ring else 0, pc)
        m.abort_execute(END)
cpu.set_instr_hook_callback(ih)

def dump_ring():
    print("   --- last instructions (pc : sp) ---")
    for pc, sp in list(_ring)[-80:]:
        print("     %06x  sp=%06x" % (pc, sp))

def call(addr, name, maxcyc=8_000_000, idle_ok=False, resume=None):
    cpu.w_reg(Register.A6, MEMBASE)
    cpu.w_sp(ZSTACK)
    ret = SENT if resume is None else resume
    mem.w_block(ZSTACK, ret.to_bytes(4, "big"))   # return/resume address
    mem.w_block(Z80_SP_BASE, ZSTACK.to_bytes(4, "big"))  # ld sp,$8400 resets here
    cpu.w_pc(addr)
    _crash[0] = None
    _returned[0] = False
    _idle_hit[0] = False
    _idle_ok[0] = idle_ok
    r = m.execute(maxcyc)
    pc = cpu.r_pc()
    _idle_ok[0] = False
    if _returned[0] or SENT <= pc < SENT + 2:
        return ("returned OK", "pc=%06x" % pc)
    if _idle_hit[0]:
        return ("idle OK", "pc=%06x" % pc)
    if _crash[0]:
        if isinstance(_crash[0][0], str):
            return ("CRASH: " + _crash[0][0], "pc=%06x src=%06x" % (pc, _crash[0][1]))
        return ("CRASH: wild jump %#x -> %#x" % _crash[0], "pc=%06x" % pc)
    return ("timeout/loop", "pc=%06x" % pc)

def vram_stats():
    v = mem.r_block(MEMBASE + 0x9000, 0x400)
    nz = sum(1 for b in v if b)
    distinct = len(set(v))
    return nz, distinct

def ram_sig():
    # work RAM 0x8000-0x87ff: nonzero count + cheap checksum (state advancing?)
    r = mem.r_block(MEMBASE + 0x8000, 0x800)
    return sum(1 for b in r if b), sum(r) & 0xffffff

def sched_sig():
    b = mem.r_block(MEMBASE + 0x8000, 0x40)
    return " ".join(f"{x:02x}" for x in b[:0x30])

print("== cpu_init ==", call(CPU_INIT, "cpu_init", 5_000_000))
st = call(L_0000, "l_0000(entry+init)")
print(f"== init -> {st}")
if WATCH_SCHED:
    _watch_sched[0] = bytes(mem.r_block(MEMBASE + 0x8002, 2))
    print(f"   watch sched-base {_watch_sched[0][0]:02x} {_watch_sched[0][1]:02x}")
if "OK" not in st[0]:
    dump_ring()
nz, d = vram_stats(); print(f"   VRAM nonzero={nz}/1024 distinct={d}")
print(f"   sched {sched_sig()}")
FRAMES = next((int(a) for a in sys.argv[1:] if a.isdigit()), 300)
ok = bad = 0
for f in range(FRAMES):
    st = call(L_0066, "frame", maxcyc=3_000_000, idle_ok=True, resume=L_0287)
    nz, d = vram_stats(); rnz, rsum = ram_sig()
    good = "OK" in st[0] or (RUN_IDLE and st[0] == "timeout/loop")
    if good: ok += 1
    else: bad += 1
    if f < 3 or (f+1) % 20 == 0 or not good:
        print(f"   frame {f+1:4d}: {st[0]:14s} {st[1]:10s} VRAM nz={nz:4d} | workRAM nz={rnz:4d} sum={rsum:06x}")
        print(f"      sched {sched_sig()}")
        if RUN_IDLE and "OK" in st[0] and f < 3:
            dump_ring()
    if not good:
        print("   ^^ first non-returning frame -- where is it spinning?")
        dump_ring(); break
print(f"== {ok} returned OK, {bad} not ==")

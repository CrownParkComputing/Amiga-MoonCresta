#!/usr/bin/env python3
"""Drive the Moon Cresta z80268k transcode the JotD way + a machine.c-style
I/O trap (Galaxian overlaps DSW-read / NMI-write at 0xb000 etc., so flat
memory corrupts it). Foreground main loop runs continuously; the vblank NMI
is injected each frame by pushing the foreground 68k PC onto the Z80 stack
and jumping to l_0066 (z80_ret's hybrid rts returns to the foreground).
Validate vs the interpreter (attract -> score header in VRAM).
    python3 tools/mc_attract.py [frames]
"""
import sys, re
import machine68k
from machine68k import CPUType, Register

FLAT="/tmp/mc_flat.bin"; ROMDIR="games/mooncrst/roms"
ROMS=["epr194","epr195","epr196","epr197","epr198","epr199","epr200","epr201"]
CODE_BASE=0x40000; MEMBASE=0x10000; ZSTACK=MEMBASE+0x8400; STACK=0xF000; SENT=0x2000
FRAMES=int(sys.argv[1]) if len(sys.argv)>1 else 700

SYM={}
for ln in open("map.txt"):
    mm=re.match(r'\s*0x([0-9a-f]+)\s+(\S+):',ln)
    if mm: SYM.setdefault(mm.group(2), int(mm.group(1),16))
CPU_INIT=SYM["cpu_init"]; L_0000=SYM["l_0000"]; L_0066=SYM["l_0066"]
# vlink map mislists data symbols for the rawbin -> derive z80_sp_base from the
# 'movea.l (abs).l,a7' (0x2E79) instruction the transcode actually uses.
_flat=open(FLAT,"rb").read(); _i=_flat.find(b"\x2e\x79")
Z80_SP_BASE=int.from_bytes(_flat[_i+2:_i+6],"big")

m=machine68k.Machine(CPUType.M68020,4096); mem=m.mem; cpu=m.cpu
mem.w_block(CODE_BASE, open(FLAT,"rb").read())

# ---- Z80 64K address space, machine.c-style, in a shadow + I/O trap ----
rom=b"".join(open(f"{ROMDIR}/{f}","rb").read() for f in ROMS)
gmem=bytearray(0x10000); gmem[0:len(rom)]=rom[:0x4000]
io={"in0":0x00,"in1":0x80,"dsw":0x00,"nmi":0}
def rd8(a):
    o=a-MEMBASE
    if o<0x4000: return gmem[o]                 # ROM
    if 0x8000<=o<0xa000: return gmem[o]         # RAM/VRAM/OBJ
    g=o&0xf800
    if g==0xa000: return io["in0"]
    if g==0xa800: return io["in1"]
    if g==0xb000: return io["dsw"]
    return 0xff
def wr8(a,v):
    o=a-MEMBASE; v&=0xff
    if o<0x4000: return                          # ROM: ignore
    if 0x8000<=o<0xa000: gmem[o]=v; return        # RAM/VRAM/OBJ
    g=o&0xf800
    if g==0xb000 and (o&7)==0: io["nmi"]=v&1      # NMI enable (b000 bit0)
def rd16(a): return (rd8(a)<<8)|rd8(a+1)
def wr16(a,v): wr8(a,(v>>8)&0xff); wr8(a+1,v&0xff)
mem.set_special_range_read_funcs (MEMBASE,1, rd8, rd16, None)
mem.set_special_range_write_funcs(MEMBASE,1, wr8, wr16, None)

mem.w_block(0, STACK.to_bytes(4,"big")); mem.w_block(4, CPU_INIT.to_bytes(4,"big"))
mem.w_block(SENT, b"\x60\xfe")
cpu.pulse_reset()
def run(cyc):
    try: m.execute(cyc)
    except Exception as e: print("exc @pc=0x%06x: %s"%(cpu.r_pc(),e))

# cpu_init, then enter the game reset
cpu.w_reg(Register.A6, MEMBASE); cpu.w_sp(ZSTACK)
mem.w_block(ZSTACK, SENT.to_bytes(4,"big")); mem.w_block(Z80_SP_BASE, ZSTACK.to_bytes(4,"big"))
cpu.w_pc(CPU_INIT); run(3_000_000)
cpu.w_reg(Register.A6, MEMBASE); cpu.w_sp(ZSTACK)
mem.w_block(Z80_SP_BASE, ZSTACK.to_bytes(4,"big")); cpu.w_pc(L_0000)
run(800_000)                                     # short init
print("after init: PC=0x%06x  nmi=%d  sp=0x%06x"%(cpu.r_pc(), io["nmi"], cpu.r_sp()))

FRAME_CYC=120_000
for f in range(FRAMES):
    if io["nmi"]:                                # only when the game enabled NMI
        pc=cpu.r_pc(); sp=(cpu.r_sp()-4)&0xffffff
        mem.w32(sp,pc); cpu.w_sp(sp); cpu.w_pc(L_0066)
    run(FRAME_CYC)
    if f<3 or (f+1)%100==0:
        nz=sum(1 for b in gmem[0x9000:0x9400] if b)
        print("  frame %4d: PC=0x%06x nmi=%d VRAMnz=%d/1024"%(f+1,cpu.r_pc(),io["nmi"],nz))

nz=sum(1 for b in gmem[0x9000:0x9400] if b); distinct=len(set(gmem[0x9000:0x9400]))
print("FINAL VRAM nonzero=%d/1024 distinct=%d"%(nz,distinct))
print("  vram[0x40..0x60]:", " ".join("%02x"%b for b in gmem[0x9040:0x9060]))

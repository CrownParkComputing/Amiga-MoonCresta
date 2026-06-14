import sys; sys.path.insert(0,"tools")
from tms320c10 import TMS320C10
e=open(sys.argv[1],'rb').read(); o=open(sys.argv[2],'rb').read(); steps=int(sys.argv[3])
prog=[(e[i]<<8)|o[i] for i in range(2048)]
fakemem=[((i*31+7)&0xffff) for i in range(0x40000)]
latch=[0]
def io_in(port):
    return fakemem[(latch[0]>>1)&0x3ffff] if port==1 else 0
def io_out(port,v):
    if port==0: latch[0]=((v&0xe000)<<3)+((v&0x1fff)<<1)
    elif port==1: fakemem[(latch[0]>>1)&0x3ffff]=v
def bio(): return False
t=TMS320C10(prog,io_in,io_out,bio); t.int_pending=True
for i in range(steps):
    print("%03x"%t.PC)
    if i%800==799: t.int_pending=True
    t.step()

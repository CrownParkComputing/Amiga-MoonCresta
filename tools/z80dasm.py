#!/usr/bin/env python3
"""Generic Z80 disassembler for arcade ROM transcoding.

Decodes one Z80 instruction at a time into MAME-style text, so the
output can be fed (with addresses + bytes) to JotD's z80268k.py for
68k transcoding. Uses the algorithmic opcode decode (Christian Dinu's
"Decoding Z80 Opcodes": x/y/z/p/q fields) for full, compact coverage
of the unprefixed / CB / ED / DD / FD / DDCB / FDCB tables.

Output mnemonics are lowercase with `$` hex (MAME / z80268k mot style).

API:
    insn = disasm_one(mem, addr)
      -> Insn(addr, length, text, raw, targets, stops)
         targets : addresses this instruction may branch/call to
         stops   : True if linear flow does not continue past it
                   (unconditional jp/jr/ret/reti/retn/jp (hl))

This module is game-agnostic; the driver (recursive descent + an
execution-trace code map) decides what to disassemble.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Insn:
    addr: int
    length: int
    text: str
    raw: bytes
    targets: list = field(default_factory=list)
    stops: bool = False


# ---- operand name tables (Dinu) ---------------------------------------
R   = ["b", "c", "d", "e", "h", "l", "(hl)", "a"]
RP  = ["bc", "de", "hl", "sp"]
RP2 = ["bc", "de", "hl", "af"]
CC  = ["nz", "z", "nc", "c", "po", "pe", "p", "m"]
ALU = ["add\ta,", "adc\ta,", "sub\t", "sbc\ta,", "and\t", "xor\t", "or\t", "cp\t"]
ROT = ["rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl"]
IM  = ["0", "0/1", "1", "2", "0", "0/1", "1", "2"]


def _h8(v):  return f"${v & 0xff:02x}"
def _h16(v): return f"${v & 0xffff:04x}"


def _rd(mem, a):
    return mem[a & 0xffff] if 0 <= (a & 0xffff) < len(mem) else 0


class _Stream:
    """Sequential byte reader from addr, wrapping the 64K space."""
    def __init__(self, mem, addr):
        self.mem = mem
        self.start = addr & 0xffff
        self.n = 0
    def byte(self):
        b = _rd(self.mem, self.start + self.n)
        self.n += 1
        return b
    def sbyte(self):
        b = self.byte()
        return b - 256 if b >= 128 else b
    def word(self):
        lo = self.byte(); hi = self.byte()
        return lo | (hi << 8)


def disasm_one(mem, addr):
    """Disassemble one instruction at `addr`. Returns an Insn."""
    s = _Stream(mem, addr)
    txt, targets, stops = _decode(s, addr)
    length = s.n
    raw = bytes(_rd(mem, addr + i) for i in range(length))
    return Insn(addr & 0xffff, length, txt, raw, targets, stops)


def _ixiy_reg(prefix):
    return "ix" if prefix == 0xDD else "iy"


def _decode(s, addr, prefix=None):
    op = s.byte()

    if op in (0xDD, 0xFD):
        return _decode(s, addr, prefix=op)
    if op == 0xCB:
        return _decode_cb(s, prefix)
    if op == 0xED:
        return _decode_ed(s)

    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1

    # register names, adjusted for DD/FD (hl->ix/iy, (hl)->(ix+d))
    def reg(i):
        if prefix and i in (4, 5, 6):
            ii = _ixiy_reg(prefix)
            if i == 6:
                d = s.sbyte()
                return f"({ii}{'+' if d >= 0 else '-'}${abs(d):02x})"
            return ii + ("h" if i == 4 else "l")
        return R[i]

    def rpname(i):
        if prefix and i == 2:
            return _ixiy_reg(prefix)
        return RP[i]

    def rp2name(i):
        if prefix and i == 2:
            return _ixiy_reg(prefix)
        return RP2[i]

    T, tgt, stop = "", [], False

    if x == 0:
        if z == 0:
            if y == 0: T = "nop"
            elif y == 1: T = "ex\taf,af'"
            elif y == 2:
                d = s.sbyte(); dest = (addr + s.n + d) & 0xffff
                T = f"djnz\t{_h16(dest)}"; tgt = [dest]
            elif y == 3:
                d = s.sbyte(); dest = (addr + s.n + d) & 0xffff
                T = f"jr\t{_h16(dest)}"; tgt = [dest]; stop = True
            else:
                d = s.sbyte(); dest = (addr + s.n + d) & 0xffff
                T = f"jr\t{CC[y-4]},{_h16(dest)}"; tgt = [dest]
        elif z == 1:
            if q == 0:
                nn = s.word(); T = f"ld\t{rpname(p)},{_h16(nn)}"
            else:
                T = f"add\t{rpname(2)},{rpname(p)}"
        elif z == 2:
            if q == 0:
                if p == 0: T = "ld\t(bc),a"
                elif p == 1: T = "ld\t(de),a"
                elif p == 2: nn = s.word(); T = f"ld\t({_h16(nn)}),{rpname(2)}"
                else: nn = s.word(); T = f"ld\t({_h16(nn)}),a"
            else:
                if p == 0: T = "ld\ta,(bc)"
                elif p == 1: T = "ld\ta,(de)"
                elif p == 2: nn = s.word(); T = f"ld\t{rpname(2)},({_h16(nn)})"
                else: nn = s.word(); T = f"ld\ta,({_h16(nn)})"
        elif z == 3:
            T = f"{'inc' if q == 0 else 'dec'}\t{rpname(p)}"
        elif z == 4:
            T = f"inc\t{reg(y)}"
        elif z == 5:
            T = f"dec\t{reg(y)}"
        elif z == 6:
            r = reg(y); n = s.byte(); T = f"ld\t{r},{_h8(n)}"
        else:  # z == 7
            T = ["rlca", "rrca", "rla", "rra", "daa", "cpl", "scf", "ccf"][y]
    elif x == 1:
        if z == 6 and y == 6:
            T = "halt"
        else:
            # DD/FD subtlety: when (ix+d) is one operand, the OTHER register
            # is the real h/l (not ixh/ixl). The half-registers are only used
            # by register-only `ld r,r'`. Without this we emit invalid
            # instructions like `ld ixh,(ix+d)`.
            idx = prefix and (y == 6 or z == 6)
            def rg(i):
                return R[i] if (idx and i in (4, 5)) else reg(i)
            T = f"ld\t{rg(y)},{rg(z)}"
    elif x == 2:
        T = f"{ALU[y]}{reg(z)}"
    else:  # x == 3
        if z == 0:
            T = f"ret\t{CC[y]}"
        elif z == 1:
            if q == 0:
                T = f"pop\t{rp2name(p)}"
            else:
                if p == 0: T = "ret"; stop = True
                elif p == 1: T = "exx"
                elif p == 2: T = f"jp\t({rpname(2)})"; stop = True
                else: T = f"ld\tsp,{rpname(2)}"
        elif z == 2:
            nn = s.word(); T = f"jp\t{CC[y]},{_h16(nn)}"; tgt = [nn]
        elif z == 3:
            if y == 0: nn = s.word(); T = f"jp\t{_h16(nn)}"; tgt = [nn]; stop = True
            elif y == 1: T = "(cb prefix)"   # handled above; unreachable
            elif y == 2: n = s.byte(); T = f"out\t({_h8(n)}),a"
            elif y == 3: n = s.byte(); T = f"in\ta,({_h8(n)})"
            elif y == 4: T = f"ex\t(sp),{rpname(2)}"
            elif y == 5: T = "ex\tde,hl"
            elif y == 6: T = "di"
            else: T = "ei"
        elif z == 4:
            nn = s.word(); T = f"call\t{CC[y]},{_h16(nn)}"; tgt = [nn]
        elif z == 5:
            if q == 0:
                T = f"push\t{rp2name(p)}"
            else:
                if p == 0: nn = s.word(); T = f"call\t{_h16(nn)}"; tgt = [nn]
                else: T = "(dd/fd/ed prefix)"  # handled above
        elif z == 6:
            n = s.byte(); T = f"{ALU[y]}{_h8(n)}"
        else:  # z == 7  -- rst
            dest = y * 8
            T = f"rst\t{_h8(dest)}"; tgt = [dest]
    return T, tgt, stop


def _decode_cb(s, prefix):
    # DDCB/FDCB carry a displacement byte before the opcode
    disp = None
    if prefix:
        disp = s.sbyte()
    op = s.byte()
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    if prefix:
        ii = _ixiy_reg(prefix)
        loc = f"({ii}{'+' if disp >= 0 else '-'}${abs(disp):02x})"
        operand = loc
    else:
        operand = R[z]
    if x == 0:
        return f"{ROT[y]}\t{operand}", [], False
    elif x == 1:
        return f"bit\t{y},{operand}", [], False
    elif x == 2:
        return f"res\t{y},{operand}", [], False
    else:
        return f"set\t{y},{operand}", [], False


def _decode_ed(s):
    op = s.byte()
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    if x == 1:
        if z == 0:
            return (f"in\t{R[y]},(c)" if y != 6 else "in\t(c)"), [], False
        if z == 1:
            return (f"out\t(c),{R[y]}" if y != 6 else "out\t(c),0"), [], False
        if z == 2:
            op2 = "sbc" if q == 0 else "adc"
            return f"{op2}\thl,{RP[p]}", [], False
        if z == 3:
            nn = s.word()
            if q == 0: return f"ld\t(${nn:04x}),{RP[p]}", [], False
            return f"ld\t{RP[p]},(${nn:04x})", [], False
        if z == 4:
            return f"neg", [], False
        if z == 5:
            return ("reti" if y == 1 else "retn"), [], True
        if z == 6:
            return f"im\t{IM[y]}", [], False
        if z == 7:
            return ["ld\ti,a", "ld\tr,a", "ld\ta,i", "ld\ta,r",
                    "rrd", "rld", "nop", "nop"][y], [], False
    if x == 2:
        bli = {
            (4, 0): "ldi", (5, 0): "ldd", (6, 0): "ldir", (7, 0): "lddr",
            (4, 1): "cpi", (5, 1): "cpd", (6, 1): "cpir", (7, 1): "cpdr",
            (4, 2): "ini", (5, 2): "ind", (6, 2): "inir", (7, 2): "indr",
            (4, 3): "outi", (5, 3): "outd", (6, 3): "otir", (7, 3): "otdr",
        }
        m = bli.get((y, z))
        if m:
            return m, [], False
    return f"db\t$ed,${op:02x}", [], False


# ---- self-test ---------------------------------------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        data = open(sys.argv[1], "rb").read()
        mem = bytearray(0x10000)
        mem[:len(data)] = data[:0x10000]
        addr = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0
        end = int(sys.argv[3], 16) if len(sys.argv) > 3 else addr + 0x40
        while addr < end:
            i = disasm_one(mem, addr)
            bs = " ".join(f"{b:02x}" for b in i.raw)
            print(f"{addr:04X}: {bs:<12} {i.text}")
            addr += i.length or 1
    else:
        # built-in sanity: Moon Cresta entry
        mem = bytearray([0xaf, 0x32, 0x00, 0xb0, 0xc3, 0xad, 0x00])
        a = 0
        while a < 7:
            i = disasm_one(mem, a)
            print(f"{a:04X}: {' '.join(f'{b:02x}' for b in i.raw):<12} {i.text}"
                  f"   targets={[hex(t) for t in i.targets]} stop={i.stops}")
            a += i.length

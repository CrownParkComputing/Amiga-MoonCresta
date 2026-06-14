"""TMS320C10 (TMS32010) DSP interpreter -- Python, for the Twin Cobra host
harness. Ported from MAME's tms320c1x core (ISA) + toaplan_dsp/twincobr_m
bridge semantics. Validate here against the real 68000 self-test (must make
the DSP compute the expected results), THEN port the proven logic to C for
the Amiga target.

Bridge (twincobr_m.cpp dsp_host_*):
  OUT port0 v -> seg=(v&0xe000)<<3 ; addr=(v&0x1fff)<<1   (68K byte address)
  IN  port1   -> read_word(seg+addr)
  OUT port1 v -> write_word(seg+addr, v); done when seg==0x30000 & addr<3 & v==0
  port3 bit15 -> BIO line (polled by BIOZ)
"""

def s32(x): x &= 0xffffffff; return x - 0x100000000 if x & 0x80000000 else x
def s16(x): x &= 0xffff;     return x - 0x10000     if x & 0x8000     else x
def s13(x): x &= 0x1fff;     return x - 0x2000      if x & 0x1000     else x


class TMS320C10:
    def __init__(self, prog_words, io_in, io_out, bio):
        self.P = list(prog_words) + [0] * (0x1000 - len(prog_words))  # program mem (words)
        self.D = [0] * 256          # data RAM (only 0..143 real, but allow 256)
        self.io_in = io_in          # f(port)->u16
        self.io_out = io_out        # f(port, u16)
        self.bio = bio              # f()->bool (BIO asserted?)
        self.reset()

    def reset(self):
        self.ACC = 0                # 32-bit
        self.P_reg = 0              # 32-bit product
        self.T = 0                  # 16-bit
        self.AR = [0, 0]            # aux regs
        self.ARP = 0
        self.DP = 0
        self.OV = 0; self.OVM = 0; self.INTM = 1
        self.PC = 0
        self.STACK = [0, 0, 0, 0]
        self.int_pending = False

    # ---- stack ----
    def push(self, v):
        self.STACK = [self.STACK[1], self.STACK[2], self.STACK[3], v & 0xfff]
    def pop(self):
        v = self.STACK[3]
        self.STACK = [self.STACK[0], self.STACK[0], self.STACK[1], self.STACK[2]]
        return v

    # ---- data addressing ----
    def _ea(self, op):
        """Effective data address from low byte; apply indirect AR/ARP updates."""
        lo = op & 0xff
        if lo & 0x80:                       # indirect
            ea = self.AR[self.ARP] & 0xff
            ar = self.AR[self.ARP]
            if lo & 0x20:   ar = (ar & 0xfe00) | ((ar + 1) & 0x1ff)
            elif lo & 0x10: ar = (ar & 0xfe00) | ((ar - 1) & 0x1ff)
            self.AR[self.ARP] = ar & 0xffff
            if not (lo & 0x08):             # bit3=0 -> change ARP to bit0
                self.ARP = lo & 1
            return ea
        return (self.DP << 7) | (lo & 0x7f)  # direct

    def getmem(self, op, shift=0, signext=False):
        ea = self._ea(op)
        v = self.D[ea] & 0xffff
        if signext: v = s16(v)
        return (v << shift) & 0xffffffff if not signext else (s16(v) << shift)

    def putmem(self, op, val):
        ea = self._ea(op)
        self.D[ea] = val & 0xffff
        return ea

    def _ovf_add(self, old, res):
        # res is a full-precision Python signed int. Set ACC, detect 32-bit
        # overflow, saturate if OVM. (old kept for signature symmetry.)
        if res > 0x7fffffff or res < -0x80000000:
            self.OV = 1
            self.ACC = (0x7fffffff if res > 0 else 0x80000000) if self.OVM else (res & 0xffffffff)
        else:
            self.ACC = res & 0xffffffff

    # ---- single instruction ----
    def step(self):
        # interrupt: vector to addr 2 if enabled
        if self.int_pending and not self.INTM:
            self.int_pending = False
            self.INTM = 1
            self.push(self.PC)
            self.PC = 2
        op = self.P[self.PC & 0xfff]
        self.PC = (self.PC + 1) & 0xfff
        hi = op >> 8

        if hi <= 0x0f:                       # ADD shift
            self._ovf_add(self.ACC, s32(self.ACC) + self.getmem(op, hi & 0x0f, True))
        elif hi <= 0x1f:                     # SUB shift
            self._ovf_add(self.ACC, s32(self.ACC) - self.getmem(op, hi & 0x0f, True))
        elif hi <= 0x2f:                     # LAC shift
            self.ACC = (self.getmem(op, hi & 0x0f, True)) & 0xffffffff
        elif hi in (0x30, 0x31):             # SAR ARn
            self.putmem(op, self.AR[hi & 1])
        elif hi in (0x38, 0x39):             # LAR ARn
            self.AR[hi & 1] = self.getmem(op) & 0xffff
        elif 0x40 <= hi <= 0x47:             # IN
            self.putmem(op, self.io_in(hi & 7) & 0xffff)
        elif 0x48 <= hi <= 0x4f:             # OUT
            self.io_out(hi & 7, self.getmem(op) & 0xffff)
        elif hi == 0x50:                     # SACL
            self.putmem(op, self.ACC & 0xffff)
        elif 0x58 <= hi <= 0x5f:             # SACH shift
            self.putmem(op, (self.ACC << (hi & 7)) >> 16 & 0xffff)
        elif hi == 0x60: self._ovf_add(self.ACC, s32(self.ACC) + (s16(self.getmem(op)) << 16))  # ADDH
        elif hi == 0x61: self._ovf_add(self.ACC, s32(self.ACC) + (self.getmem(op) & 0xffff))     # ADDS
        elif hi == 0x62: self._ovf_add(self.ACC, s32(self.ACC) - (s16(self.getmem(op)) << 16))  # SUBH
        elif hi == 0x63: self._ovf_add(self.ACC, s32(self.ACC) - (self.getmem(op) & 0xffff))     # SUBS
        elif hi == 0x64:                     # SUBC
            ea = self._ea(op); tmp = s32(self.ACC) - ((self.D[ea] & 0xffff) << 15)
            if tmp >= 0: self.ACC = ((tmp << 1) | 1) & 0xffffffff
            else:        self.ACC = (self.ACC << 1) & 0xffffffff
        elif hi == 0x65:                     # ZALH
            self.ACC = (self.getmem(op) & 0xffff) << 16
        elif hi == 0x66:                     # ZALS
            self.ACC = self.getmem(op) & 0xffff
        elif hi == 0x67:                     # TBLR
            self.putmem(op, self.P[self.ACC & 0xfff] & 0xffff)
        elif hi == 0x68:                     # MAR / LARP
            self._ea(op)
        elif hi == 0x69:                     # DMOV
            ea = self._ea(op); self.D[(ea + 1) & 0xff] = self.D[ea] & 0xffff
        elif hi == 0x6a:                     # LT
            self.T = self.getmem(op) & 0xffff
        elif hi == 0x6b:                     # LTD
            ea = self._ea(op); self.T = self.D[ea] & 0xffff
            self.D[(ea + 1) & 0xff] = self.D[ea] & 0xffff
            self._ovf_add(self.ACC, s32(self.ACC) + s32(self.P_reg))
        elif hi == 0x6c:                     # LTA
            self.T = self.getmem(op) & 0xffff
            self._ovf_add(self.ACC, s32(self.ACC) + s32(self.P_reg))
        elif hi == 0x6d:                     # MPY
            self.P_reg = (s16(self.getmem(op)) * s16(self.T)) & 0xffffffff
        elif hi == 0x6e:                     # LDPK
            self.DP = op & 1
        elif hi == 0x6f:                     # LDP
            self.DP = self.getmem(op) & 1
        elif hi in (0x70, 0x71):             # LARK
            self.AR[hi & 1] = op & 0xff
        elif hi == 0x78: self.ACC = (self.ACC ^ (self.getmem(op) & 0xffff)) & 0xffffffff  # XOR
        elif hi == 0x79: self.ACC = (self.ACC & ((0xffff0000) | (self.getmem(op) & 0xffff)))  # AND (low 16)
        elif hi == 0x7a: self.ACC = (self.ACC | (self.getmem(op) & 0xffff)) & 0xffffffff  # OR
        elif hi == 0x7b:                     # LST
            self.D_lst(self.getmem(op) & 0xffff)
        elif hi == 0x7c:                     # SST
            ea = 0x80 | (op & 0x7f); self.D[ea] = self.status()
        elif hi == 0x7d:                     # TBLW
            self.P[self.ACC & 0xfff] = self.getmem(op) & 0xffff
        elif hi == 0x7e:                     # LACK
            self.ACC = op & 0xff
        elif hi == 0x7f:                     # extended (MAME decodes low & 0x1f)
            self._ext(op & 0x1f)
        elif 0x80 <= hi <= 0x9f:             # MPYK
            self.P_reg = (s13(op) * s16(self.T)) & 0xffffffff
        elif 0xf0 <= hi <= 0xff:             # branch group (2-word)
            self._branch(hi)
        # else: illegal/NOP

    def status(self):
        return ((self.OV << 15) | (self.OVM << 14) | (self.INTM << 13)
                | (self.ARP << 8) | self.DP | 0x1efe) & 0xffff
    def D_lst(self, v):                      # LST: load status (INTM preserved)
        self.OV = (v >> 15) & 1; self.OVM = (v >> 14) & 1
        self.ARP = (v >> 8) & 1; self.DP = v & 1

    def _ext(self, lo):
        if   lo == 0x00: pass                            # NOP
        elif lo == 0x01: self.INTM = 1                   # DINT
        elif lo == 0x02: self.INTM = 0                   # EINT
        elif lo == 0x08:                                 # ABS
            if s32(self.ACC) < 0: self.ACC = (-s32(self.ACC)) & 0xffffffff
        elif lo == 0x09: self.ACC = 0                    # ZAC
        elif lo == 0x0a: self.OVM = 0                    # ROVM
        elif lo == 0x0b: self.OVM = 1                    # SOVM
        elif lo == 0x0c: self.push(self.PC); self.PC = self.ACC & 0xfff   # CALA
        elif lo == 0x0d: self.PC = self.pop()            # RET
        elif lo == 0x0e: self.ACC = self.P_reg           # PAC
        elif lo == 0x0f: self._ovf_add(self.ACC, s32(self.ACC) + s32(self.P_reg))  # APAC
        elif lo == 0x10: self._ovf_add(self.ACC, s32(self.ACC) - s32(self.P_reg))  # SPAC
        elif lo == 0x14: self.push(self.ACC & 0xfff)     # PUSH
        elif lo == 0x15: self.ACC = self.pop()           # POP

    def _branch(self, hi):
        target = self.P[self.PC & 0xfff]
        self.PC = (self.PC + 1) & 0xfff
        acc = s32(self.ACC)
        take = False
        if   hi == 0xf4:                                  # BANZ
            take = (self.AR[self.ARP] & 0x1ff) != 0
            self.AR[self.ARP] = (self.AR[self.ARP] & 0xfe00) | ((self.AR[self.ARP] - 1) & 0x1ff)
        elif hi == 0xf5: take = bool(self.OV); self.OV = 0   # BV
        elif hi == 0xf6: take = self.bio()                   # BIOZ
        elif hi == 0xf8: self.push(self.PC); self.PC = target; return  # CALL
        elif hi == 0xf9: self.PC = target; return            # BR
        elif hi == 0xfa: take = acc < 0                      # BLZ
        elif hi == 0xfb: take = acc <= 0                     # BLEZ
        elif hi == 0xfc: take = acc > 0                      # BGZ
        elif hi == 0xfd: take = acc >= 0                     # BGEZ
        elif hi == 0xfe: take = acc != 0                     # BNZ
        elif hi == 0xff: take = acc == 0                     # BZ
        if take: self.PC = target

#!/usr/bin/env python3
"""Post-process z80268k.py MIT output into assemblable 68k.

z80268k.py (MIT mode) emits a few systematic things that don't assemble as-is.
This applies the mechanical, game-agnostic fixes so the transcode builds with
m68k-amigaos-as -- run it on every game's transcode (it's part of the pipeline,
not a per-game hand-edit):

  * `ERROR "..."` reminder lines  -> dropped (kept as comments)
  * `ld sp,nn`/`ld sp,hl` -> `move.b ...,a7` (illegal) -> mapped to the
    prepared Z80 stack pointer or to a pointer inside the Z80 memory block.
  * Z80 `ret`/`retn`/`reti` -> shared `z80_ret`, which can return via a real
    68k return address or pop a 16-bit Z80 PC from a scheduler task stack.
  * missing `DAA` macro            -> appended to the .inc (stub; see note).

What it CANNOT fix (genuine per-game hand work, left as comments to review):
  * `jp (hl)` computed jumps / jump tables
  * Z80 flag-test edge cases, BCD arithmetic correctness (the DAA stub is a
    no-op -> BCD score math is approximate until a real DAA is supplied).

Usage: z80fixup.py game.68k game.inc
"""
import sys, re

# Z80 hardware/runtime addresses that the driver must call or reference.
# Some are not jp/call targets, so z80268k would otherwise keep them local.
VECTORS = (0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x66, 0x287)

def fix_68k(path):
    out, dropped_err, dropped_sp, labeled = [], 0, 0, 0
    labeled_addrs = set()
    prev_made_reg_address = None
    for line in open(path).read().split('\n'):
        s = line.strip()
        if prev_made_reg_address and re.match(r'GET_ADDRESS\s+(hl|de|bc),a0\b', s):
            out.append('| ' + s + ' (dropped: MAKE_AR_FROM_* already resolved register address)')
            prev_made_reg_address = None
            continue
        prev_made_reg_address = None
        if s.startswith('ERROR'):
            # retn/reti (return from NMI/IRQ) must use the hybrid return path:
            # Moon Cresta's scheduler can restore a pure 16-bit Z80 task stack.
            if 'instruction retn' in s or 'instruction reti' in s:
                out.append('\tjra\tz80_ret\t| (Z80 retn/reti -> hybrid return)')
            elif 'indirect jump' in s and 'jp\t(hl)' in line:
                # `jp (hl)` is a computed jump (jump table). HL is kept in d6
                # (16-bit). Dispatch through z80jmptab (built post-assembly from
                # all l_XXXX labels: Z80 addr -> 68k label address). All code is
                # in ROM (0..0x3fff), so mask the index there.
                out.append('\tand.l\t#0x3fff,d6\t| jp (hl): HL(d6) -> 68k via z80jmptab')
                out.append('\tlea\tz80jmptab,a0')
                out.append('\tmove.l\t(a0,d6.l*4),a0')
                out.append('\tjmp\t(a0)')
            else:
                out.append('| ' + s)
            dropped_err += 1; continue
        m = re.search(r'\b(inc|dec)\t(i[xy])\b', line)
        if m and (s.startswith('GET_ADDRESS') or s.startswith('|') or s == ''):
            op, reg = m.groups()
            areg = 'a2' if reg == 'ix' else 'a3'
            inst = 'addq.l' if op == 'inc' else 'subq.l'
            cmt = line.split('|', 1)[-1].strip() if '|' in line else line.strip()
            out.append(f'\t{inst}\t#1,{areg}\t| {cmt} (Z80 {op} {reg})')
            continue
        if re.match(r'rts\b', s) and re.search(r'\| \[\$[0-9a-f]{4}: ret', line):
            cmt = line.split('|', 1)[-1].strip()
            out.append(f'\tjra\tz80_ret\t| {cmt} (hybrid return)')
            continue
        # `ld hl,(nn)` / `ld de,(nn)` / `ld bc,(nn)` -- z80268k mis-converts the
        # 16-bit indirect load to a byte move into a dead register-pair cell
        # (`move.b (a0),hl`). Correct it to a little-endian word load into the
        # split byte regs (HL=d5:d6, DE=d3:d4, BC=d1:d2; low byte = .b reg,
        # high byte = the MSB reg). a0 = membase+nn was set by GET_ADDRESS.
        # A move with a register-PAIR cell (hl/de/bc) as operand is z80268k's
        # broken 16-bit indirect load/store (`move.b (a0),hl`). The pair lives
        # in a .w data reg (HL=d6, DE=d4, BC=d2) with its MSB shadowed (d5/d3/d1
        # via MAKE_H/D/B). Z80 RAM is little-endian, the 68k word read at (a0)
        # is big-endian -> byte-swap. a0 = membase+nn (set by GET_ADDRESS).
        RP = {'hl': ('d6', 'MAKE_H'), 'de': ('d4', 'MAKE_D'), 'bc': ('d2', 'MAKE_B')}
        m = re.match(r'move\.[bwl]\s+\(a0\),(hl|de|bc)\b', s)   # ld rr,(nn)
        if m:
            reg, mk = RP[m.group(1)]
            cmt = line.split('|', 1)[-1].strip()
            out.append(f'\tmove.b\t1(a0),{reg}\t| {cmt} (MSB; z80268k ld rr,(nn) fix)')
            out.append(f'\tlsl.w\t#8,{reg}')
            out.append(f'\tmove.b\t(a0),{reg}\t| (LSB) -> {reg}.w = rr')
            out.append(f'\t{mk}\t| sync MSB shadow')
            continue
        m = re.match(r'move\.[bwl]\s+(hl|de|bc),\(a0\)', s)     # ld (nn),rr
        if m:
            reg, _ = RP[m.group(1)]
            cmt = line.split('|', 1)[-1].strip()
            out.append(f'\tmove.b\t{reg},(a0)\t| {cmt} (LSB; z80268k ld (nn),rr fix)')
            out.append(f'\tror.w\t#8,{reg}')
            out.append(f'\tmove.b\t{reg},1(a0)\t| (MSB)')
            out.append(f'\trol.w\t#8,{reg}\t| restore {reg}.w')
            continue
        # `add hl,sp` -- when a7 points into the 64K Z80 memory block, the Z80
        # SP value is (a7 - a6), not the host pointer low word. z80268k maps
        # Z80 CALL/RET to 68k jbsr/rts, so an active subroutine return address
        # is 4 bytes instead of 2. Moon Cresta uses `add hl,sp` only in the task
        # stack saver, then increments twice to skip the Z80 call return. Bias
        # by +2 here so those two INCs land on the real post-rts stack top.
        if re.match(r'add\.w\s+a7,d6\b', s) and 'add\thl,sp' in line:
            cmt = line.split('|', 1)[-1].strip()
            out.append(f'\tmove.l\ta7,d7\t| {cmt} (Z80 SP = a7-a6)')
            out.append('\tsub.l\ta6,d7')
            out.append('\taddq.w\t#2,d7\t| compensate 68k jbsr return size')
            out.append('\tadd.w\td7,d6')
            continue
        # IX/IY are held as 68k pointers into the Z80 memory block, but the Z80
        # stack stores 16-bit register values. z80268k emits 32-bit pointer
        # push/pop, which breaks code that inspects or saves SP (Moon Cresta's
        # cooperative task scheduler). Store offsets on push and rebuild the
        # host pointer on pop.
        m = re.match(r'move\.l\s+(a[23]),-\(a7\)', s)
        if m and ('push\tix' in line or 'push\tiy' in line):
            reg = m.group(1)
            cmt = line.split('|', 1)[-1].strip()
            out.append(f'\tmove.l\t{reg},d7\t| {cmt} (push 16-bit Z80 index)')
            out.append('\tsub.l\ta6,d7')
            out.append('\tmove.w\td7,-(a7)')
            continue
        m = re.match(r'move\.l\s+\(a7\)\+,(a[23])', s)
        if m and ('pop\tix' in line or 'pop\tiy' in line):
            reg = m.group(1)
            cmt = line.split('|', 1)[-1].strip()
            out.append(f'\tmove.w\t(a7)+,d7\t| {cmt} (pop 16-bit Z80 index)')
            out.append('\tand.l\t#0xffff,d7')
            out.append(f'\tlea\t(0,a6,d7.l),{reg}')
            continue
        # `ld sp,nn`/`ld sp,hl` mis-convert to a byte move into a7 (illegal).
        if re.match(r'move\.[bwl]\s+\S+,a7\s*(\||$)', s) and 'ld\tsp' in line:
            # `ld sp,$nnnn` resets to the driver's prepared base pointer.
            # `ld sp,hl` is used by Moon Cresta's cooperative task scheduler:
            # map it to a real 68k stack pointer inside the Z80 memory block.
            if re.search(r'ld\tsp,\$', line):
                out.append('\tmove.l\tz80_sp_base,a7\t| ' + s.split('|',1)[-1].strip())
            else:
                out.append('\tmove.l\td6,d7\t| ' + s.split('|',1)[-1].strip() + ' (Z80 SP=HL)')
                out.append('\tand.l\t#0xffff,d7')
                out.append('\tlea\t(0,a6,d7.l),a7')
            dropped_sp += 1; continue
        lm_existing = re.match(r'^l_([0-9a-fA-F]+):\s*$', s)
        if lm_existing:
            labeled_addrs.add(int(lm_existing.group(1), 16))

        # Ensure a label at every converted Z80 instruction start, so jp(hl)
        # dispatch can land on computed targets that are not static branch
        # destinations. Do not insert alignment here: this is inside ordinary
        # code flow, whose 68k instruction boundaries are already even.
        m = re.search(r'\| \[\$([0-9a-f]{4}):', line)
        if m:
            a = int(m.group(1), 16)
            if a not in labeled_addrs:
                lbl = f"l_{a:04x}"
                if a in VECTORS:
                    out.append(f"\t.global\t{lbl}")   # callable from the driver
                out.append(f"{lbl}:")
                labeled += 1
                labeled_addrs.add(a)
        # Word-align every label: 68k call/jump targets must be even. z80268k
        # emits Z80 data bytes (DEFB) as odd-length `.byte` runs and renders
        # nops as 0-byte comments, so labels after them land on odd addresses
        # -> jbsr/jsr to an odd PC = address error. .even pads only in the
        # (unreachable, post-jump) data gaps, never inside real 68k code.
        lm = re.match(r'^l_([0-9a-fA-F]+):\s*$', s)
        if lm and int(lm.group(1), 16) in VECTORS and not any(
                x.strip() == f'.global\tl_{int(lm.group(1), 16):04x}' for x in out[-3:]):
            out.append(f'\t.global\tl_{int(lm.group(1), 16):04x}')
        if lm and not (out and out[-1].strip() == '.even'):
            out.append('\t.even')
        out.append(line)
        if re.match(r'MAKE_AR_FROM_(HL|DE|BC)\s+a0\b', s):
            prev_made_reg_address = True
    open(path, 'w').write('\n'.join(out))
    return dropped_err, dropped_sp, labeled

DAA_MACRO = """
* --- z80fixup: macros z80268k MIT output references but doesn't define ---
\t.macro\tDAA
| TODO: Z80 DAA not emulated here -> BCD score arithmetic is approximate.
| Supply a proper Z80 daa sequence (uses N/H/C) for correct scores.
\t.endm
"""

def fix_inc(path):
    text = open(path).read()
    # drop ERROR reminder *invocations* (keep the macro definition itself).
    lines = []
    for line in text.split('\n'):
        if line.strip().startswith('ERROR ') or line.strip().startswith('ERROR\t'):
            lines.append('| ' + line.strip()); continue
        lines.append(line)
    text = '\n'.join(lines)
    # GNU as needs `\dest\().l` (the \() separator) for the macro param to
    # substitute before the .l size; z80268k emits `\dest.l` which doesn't.
    text = text.replace('(a6,\\dest.l)', '(0,a6,\\dest\\().l)')
    text = text.replace('(\\dest,\\reg\\().l)', '(0,\\dest,\\reg\\().l)')
    if '\t.macro\tDAA' not in text:
        text += DAA_MACRO
    open(path, 'w').write(text)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(1)
    de, ds, lb = fix_68k(sys.argv[1])
    fix_inc(sys.argv[2])
    print(f"fixed {sys.argv[1]}: dropped {de} ERROR + {ds} SP lines, "
          f"added {lb} vector labels; patched {sys.argv[2]} (DAA + as syntax)")

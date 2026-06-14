#!/usr/bin/env python3
"""Generic Z80 arcade ROM disassembler -> MAME-style listing for z80268k.py.

Separates code from data by recursive descent from the CPU entry/interrupt
vectors (following branch/call targets via z80dasm), optionally seeded with
an execution-trace code map (tools/z80trace) for code only reachable through
computed jumps / jump tables. Emits the `AAAA: BB BB  mnemonic` format that
JotD's z80268k.py consumes; unreached bytes are emitted as `db` data.

Usage:
    z80disasm.py ROM[,ROM...] [--base 0] [--entry 0,0x38,0x66]
                 [--trace trace.txt] [-o out.asm]

ROMs are concatenated at --base (e.g. epr194..epr201 -> 0x0000). Default
entries cover the Z80 reset (0), the RST vectors, and the NMI (0x66) used
by Galaxian-family hardware.
"""
from __future__ import annotations
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z80dasm import disasm_one

UNKNOWN, CODE, CONT, DATA = 0, 1, 2, 3


def load_image(specs, base):
    mem = bytearray(0x10000)
    end = base
    for path in specs:
        data = open(path, "rb").read()
        mem[end:end + len(data)] = data
        end += len(data)
    return mem, base, end


def descend(mem, code_end, seeds):
    """Recursive descent. Returns a flags[] array over [0,code_end)."""
    flags = bytearray(code_end)
    # The execution trace comes from the emulator's hot fetch path and may
    # contain operand/immediate-byte reads as well as true instruction starts.
    # We process higher addresses first so explicit alternate entries can win
    # when they overlap linear-flow decoding (threaded code / jump-table
    # targets inside a block). Recursive descent still prevents later seeds
    # from splitting a start that was already claimed.
    work = sorted({a for a in seeds if 0 <= a < code_end})
    starts = {}                      # addr -> Insn (instruction starts)
    seen = set()
    while work:
        a = work.pop()
        if a < 0 or a >= code_end or a in seen:
            continue
        if flags[a] == CONT:
            continue
        seen.add(a)
        insn = disasm_one(mem, a)
        if a + insn.length > code_end:
            continue
        overlap = False
        for i in range(insn.length):
            f = flags[a + i]
            if (i == 0 and f == CONT) or (i > 0 and f == CODE):
                overlap = True
                break
        if overlap:
            continue
        starts[a] = insn
        for i in range(insn.length):
            flags[a + i] = CODE if i == 0 else CONT
        for t in insn.targets:
            if 0 <= t < code_end:
                work.append(t)
        if not insn.stops:
            work.append((a + insn.length) & 0xffff)
    return flags, starts


def emit(mem, base, code_end, flags, starts, out):
    a = base
    while a < code_end:
        if flags[a] == CODE and a in starts:
            insn = starts[a]
            # z80268k.py's instruction_re requires UPPERCASE hex bytes.
            bs = " ".join(f"{b:02X}" for b in insn.raw)
            out.write(f"{a:04X}: {bs:<14} {insn.text}\n")
            a += insn.length
        else:
            # gather a data run (anything not a code-start)
            run = []
            while a < code_end and not (flags[a] == CODE and a in starts):
                run.append(mem[a]); a += 1
            for i in range(0, len(run), 8):
                chunk = run[i:i+8]
                bs = " ".join(f"{b:02X}" for b in chunk)
                vals = ",".join(f"${b:02x}" for b in chunk)
                # `.db` (not `db`) so z80268k passes it through as `.byte` data.
                out.write(f"{a-len(run)+i:04X}: {bs:<14} .db\t{vals}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roms", help="comma-separated ROM files, concatenated at --base")
    ap.add_argument("--base", default="0", help="load/base address (hex ok)")
    ap.add_argument("--entry", default="0,0x8,0x10,0x18,0x20,0x28,0x30,0x38,0x66",
                    help="comma-separated entry addresses")
    ap.add_argument("--trace", help="execution-trace file: one hex address per line")
    ap.add_argument("-o", "--out", help="output listing (default stdout)")
    ns = ap.parse_args()

    base = int(ns.base, 0)
    mem, base, code_end = load_image(ns.roms.split(","), base)
    seeds = [int(x, 0) for x in ns.entry.split(",")]
    traced = 0
    if ns.trace:
        for line in open(ns.trace):
            line = line.strip()
            if line:
                try:
                    seeds.append(int(line, 16)); traced += 1
                except ValueError:
                    pass

    flags, starts = descend(mem, code_end, seeds)

    code_bytes = sum(1 for i in range(base, code_end) if flags[i] in (CODE, CONT))
    total = code_end - base
    sys.stderr.write(
        f"image ${base:04x}-${code_end:04x} ({total} bytes): "
        f"{len(starts)} instructions, {code_bytes} code bytes "
        f"({100*code_bytes//max(1,total)}%), {total-code_bytes} data/unreached"
        f"{f', {traced} trace seeds' if traced else ''}\n")

    out = open(ns.out, "w") if ns.out else sys.stdout
    out.write("; Disassembly by tools/z80disasm.py (recursive descent"
              + (" + trace" if traced else "") + ") -- feed to z80268k.py\n")
    emit(mem, base, code_end, flags, starts, out)
    if ns.out:
        out.close()


if __name__ == "__main__":
    main()

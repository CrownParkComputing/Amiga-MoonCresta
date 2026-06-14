"""namco_amiga: anchored-emulation conversion + build pipeline for Namco arcade ports.

Replaces the per-game `post_process.py` + Windows-only `create_amiga_archive.py`
scripts in jotd's `commando` and `amiga68ktools` repos with a single
typed, logging-aware Python package that supports multiple games.

Currently tracked games (in games/<name>/):
    pacland   - Namco Pac-Land 1984 (6809E x3 + Namco 05C0/5B/60A1)
    pacmania  - Namco Pac-Mania 1987 (68000 + 6809E + Namco C140)
    galaga90  - Namco Galaga '90 1989 (68000 + 6809E + Namco C140)

Sub-commands (exposed via `python -m namco_amiga ...`):
    games         list all known games and their config
    disasm        run MAME disassembly on a ROM set
    convert       run 6809to68k-style conversion on a disasm
    postprocess   apply the JSON I/O map and emit patched 68k
    archive       build a WHDLoad-installable directory
    validate      sanity-check a slave + binary pair
    version       print namco_amiga + toolchain versions
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]

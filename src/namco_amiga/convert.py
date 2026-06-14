"""Sub-command: `convert` -- run 6809to68k-style conversion on a disasm.

This is the *typed* entry point that will eventually call
amiga68ktools/tools/6809to68k.py. For now it's a stub that
shows the planned command line.
"""
from __future__ import annotations

import argparse
import logging

log = logging.getLogger("namco_amiga.convert")


def run_conversion(ns: argparse.Namespace) -> int:
    log.info("convert sub-command (stub)")
    log.warning("Real implementation will call 6809to68k.py:")
    log.warning("  python3 amiga68ktools/tools/6809to68k.py \\")
    log.warning("    --input-mode mot --output-mode mot \\")
    log.warning("    --code-output src/pacland_000.68k \\")
    log.warning("    src/pacland_000.asm")
    return 0

"""Sub-command: `disasm` -- run MAME disassembly on a ROM set.

Replaces the IRA / D68K pipeline. MAME's `-debug -dasm` is the
single source-of-truth disassembly format and gives cycle
counts that the old `m68kchecker` had to shell out to IRA for.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("namco_amiga.disasm")


def run_disassembly(ns: argparse.Namespace) -> int:
    """Stub -- real implementation will shell out to MAME.

    We deliberately don't shell out by default because MAME isn't
    in the standard CachyOS install and this scaffold must work
    even when MAME is absent. Once the user installs MAME and
    points the tool at their pacland.zip, this becomes a single
    `mame pacland -debug -dasm` invocation.
    """
    log.info("disasm sub-command (stub)")
    log.warning("MAME not invoked in the stub. Real implementation:")
    log.warning("  mame pacland -debug -dasm -window -noreadconfig > %s", ns.out or "(stdout)")
    log.warning("  -- then split CPU sections into per-CPU .asm files")
    return 0

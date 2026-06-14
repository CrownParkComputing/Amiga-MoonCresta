"""Sub-command: `archive` -- build a WHDLoad-installable directory.

Linux replacement for `commando/tools/create_amiga_archive.py`
which hardcoded `K:\\progs\\cli`, ran `cranker_windows.exe`,
and called `cmd /c` for every graphics-conversion step.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger("namco_amiga.archive")


def build_archive(ns: argparse.Namespace) -> int:
    proj = Path(ns.project_root).resolve()
    slave = proj / "build" / f"{ns.game}.slave"
    binary = proj / "build" / ns.game
    out = proj / "build" / f"{ns.game}_HD"

    for p in (slave, binary):
        if not p.exists():
            log.error("missing artefact: %s -- run `make` first", p)
            return 1

    if out.exists():
        log.info("clearing previous archive: %s", out)
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(slave, out / slave.name)
    shutil.copy(binary, out / binary.name)

    for opt_name in ("readme.md", "README.md"):
        src = proj / opt_name
        if src.exists():
            shutil.copy(src, out / opt_name)
            break

    icon = proj / "assets" / "amiga" / f"{ns.game.capitalize()}.info"
    if icon.exists():
        shutil.copy(icon, out / icon.name)

    log.info("archive ready: %s", out)
    for x in sorted(out.iterdir()):
        log.info("  %s  (%d bytes)", x.name, x.stat().st_size)
    return 0

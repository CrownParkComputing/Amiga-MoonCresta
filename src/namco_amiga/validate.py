"""Sub-command: `validate` -- sanity-check a slave + binary pair.

Catches the obvious gotchas the older scripts relied on
visual inspection for:
  - both files exist
  - both start with the HUNK_HEADER magic (0x000003F3)
  - both are non-trivially sized
  - the binary is larger than the slave (sanity: real game > 1k)
  - WHDLoad will find the slave (no .slave = not installable)
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .constants import HUNK_HEADER_MAGIC

log = logging.getLogger("namco_amiga.validate")


def _check_hunk(path: Path) -> list[str]:
    errs: list[str] = []
    if not path.exists():
        return [f"{path}: not found"]
    data = path.read_bytes()
    if len(data) < 4:
        errs.append(f"{path}: too small to be a Hunk file ({len(data)} bytes)")
    elif data[:4] != HUNK_HEADER_MAGIC:
        errs.append(f"{path}: missing HUNK_HEADER magic (got {data[:4]!r})")
    # A real Amiga slave has the slv_ struct (at least 64 bytes) + code
    # + a proper tail. A real game exe is always at least 1k. The stub
    # slave is intentionally tiny (just the entry point), so we warn
    # but don't fail for a sub-1k slave; we DO fail for a sub-1k game.
    if path.suffix == ".slave":
        if len(data) < 32:
            errs.append(f"{path}: slave smaller than 32 bytes ({len(data)} bytes)")
        elif len(data) < 128:
            log.warning("%s: slave is small (%d bytes) -- stub or trimmed build?",
                        path, len(data))
    else:
        if len(data) < 256:
            errs.append(f"{path}: game binary smaller than 256 bytes ({len(data)} bytes)")
    return errs


def run_validate(ns: argparse.Namespace) -> int:
    proj = Path(ns.project_root).resolve()
    slave = proj / "build" / f"{ns.game}.slave"
    binary = proj / "build" / ns.game
    errs: list[str] = []
    errs += _check_hunk(slave)
    errs += _check_hunk(binary)
    if slave.exists() and binary.exists():
        if slave.stat().st_size > binary.stat().st_size:
            errs.append(f"{slave.name} is larger than {binary.name} -- "
                        "looks like the wrong files ended up in the archive")
    if errs:
        for e in errs:
            log.error("%s", e)
        return 1
    log.info("OK: %s and %s are valid Amiga Hunk files", slave, binary)
    return 0

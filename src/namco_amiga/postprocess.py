"""Sub-command: `postprocess` -- apply the JSON I/O map and emit 68k.

This is the big one. It replaces ALL the per-game
`post_process.py` files in jotd's pipeline with a single
typed engine that reads the JSON I/O map and patches the
transcoded 68k output.

Plan:
    1. Read the transcode output (line-by-line).
    2. For every line that references an I/O address in the map,
       substitute the call to the named HAL handler.
    3. For every line that references a memory range in the map,
       wrap the access in the named backing buffer.
    4. Emit the patched file.
"""
from __future__ import annotations

import argparse
import logging

from .io_map import load_io_map

log = logging.getLogger("namco_amiga.postprocess")


def run_postprocess(ns: argparse.Namespace) -> int:
    log.info("postprocess sub-command (stub)")
    log.warning("Real implementation will:")
    log.warning("  1. load_io_map(Path(ns.io_map))")
    log.warning("  2. stream the transcode .68k file")
    log.warning("  3. patch every I/O reference via map.io_at(addr)")
    log.warning("  4. wrap every memory-range reference via map.address_in_range(addr)")
    log.warning("  5. write the patched file to --out")
    return 0

"""Sub-module: I/O dispatch table generator.

Reads `games/<name>/io_map.json` and emits a C source file
`build/<name>_io_dispatch.c` that defines:

    const hal_io_handler_t *hal_io_lut[256] = { ... };

One entry per I/O address (low 8 bits), pointing to a
handler struct (declared in hal_io.h). The handlers
themselves are 68k assembly stubs in src/hal/handlers.s.

This is the file that wires the JSON I/O map to the HAL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .io_map import load_io_map

log = logging.getLogger("namco_amiga.dispatch")


@dataclass(frozen=True)
class DispatchEntry:
    addr: int                       # full I/O address
    addr_high8: int                 # LUT key (chip-enable is a high address bit)
    kind: str                       # "sound_command", "tilemap_enable", etc.
    read_handler: str | None = None   # C base name for reads (_r suffix added at emit)
    write_handler: str | None = None  # C base name for writes (_w suffix added at emit)
    lut_key: int | None = None      # override the LUT key

    @property
    def access(self) -> str:
        r = self.read_handler is not None
        w = self.write_handler is not None
        return "RW" if (r and w) else ("R" if r else "W")

    @property
    def handler(self) -> str:
        """Back-compat: the handler base name. For a slot with the same
        handler on both directions (legacy single-handler entries) this
        is unambiguous; for split read/write slots it returns the read
        base (or the write base if read-only)."""
        return self.read_handler or self.write_handler  # type: ignore[return-value]


def _parse_access(s: str) -> str:
    s = s.strip().upper()
    if s in ("R", "W", "RW", "R/W"):
        return "RW" if s in ("RW", "R/W") else s
    raise ValueError(f"unrecognised access: {s!r}")


def _infer_access(kind: str) -> str:
    """Infer R/W/RW from a legacy entry's kind name when the io_map.json
    omits an explicit 'access' field."""
    raw = kind.lower()
    if any(kw in raw for kw in ("_write", "_enable", "flip_",
                                 "switch", "bank", "_ack",
                                 "mcu_reset", "reset")):
        return "W"
    if any(kw in raw for kw in ("watchdog", "_read",
                                 "vblank", "_irq",
                                 "dipsw", "input", "dsw",
                                 "tilemap_enable")):
        return "R"
    return "RW"


def parse_dispatch_entries(io_map_path: Path) -> list[DispatchEntry]:
    """Turn an io_map.json into a list of DispatchEntry records.

    Two input styles are merged into one per-address slot:

    * Legacy ``io_map`` block -- one handler per address, direction
      taken from the entry's ``access`` field or inferred from its
      ``kind`` name. Used by Namco games (pacland).
    * Split ``io_read`` / ``io_write`` blocks -- direction implied by
      the block, so the same address can hold *different* read and
      write handlers. Galaxian-family hardware (mooncrst) needs this:
      0xa800 is IN1 when read and a sound port when written.

    LUT key choice: the HIGH 8 BITS of the arcade address -- the
    chip-enable line is a high address bit (Namco A12-A15; Galaxian
    0xa0/0xa8/0xb0/0xb8 select the four I/O port groups). The low
    bits are a register/offset that the handler sub-decodes itself.
    """
    m = load_io_map(io_map_path)

    # addr -> [read_base, write_base, read_kind, write_kind]
    slots: dict[int, list] = {}

    def _slot(addr: int) -> list:
        return slots.setdefault(addr, [None, None, None, None])

    # Legacy single-handler block: split into directions by access.
    for addr, entry in m.io.items():
        access = (_parse_access(entry.access)
                  if entry.access is not None else _infer_access(entry.kind))
        s = _slot(addr)
        if "R" in access:
            s[0], s[2] = entry.handler, entry.kind
        if "W" in access:
            s[1], s[3] = entry.handler, entry.kind

    # Split blocks: direction is the block.
    for addr, entry in m.io_read.items():
        s = _slot(addr)
        s[0], s[2] = entry.handler, entry.kind
    for addr, entry in m.io_write.items():
        s = _slot(addr)
        s[1], s[3] = entry.handler, entry.kind

    out: list[DispatchEntry] = []
    for addr, (rh, wh, rk, wk) in slots.items():
        out.append(DispatchEntry(
            addr=addr,
            addr_high8=(addr >> 8) & 0xff,
            kind=rk or wk,
            read_handler=rh,
            write_handler=wh,
        ))
    out.sort(key=lambda e: e.addr_high8)
    return out


# ---- handler struct C declaration ----------------------------

def _emit_handler_struct(entry: DispatchEntry) -> str:
    """One C struct for one I/O entry. The handler functions are
    declared in src/hal/handlers.s (or wherever the user puts
    them); we just reference them by name here.

    The handler naming convention is:
        <handler>_r  for read  (e.g. hal_watchdog_kick_r)
        <handler>_w  for write (e.g. hal_watchdog_kick_w)
    The handler name from the I/O map is the BASE; we add _r/_w.
    """
    parts: list[str] = []
    if entry.read_handler is not None:
        parts.append(f"  .read  = {entry.read_handler}_r,")
    else:
        parts.append(f"  .read  = NULL,")
    if entry.write_handler is not None:
        parts.append(f"  .write = {entry.write_handler}_w,")
    else:
        parts.append(f"  .write = NULL,")
    body = "\n".join(parts)
    name = entry.read_handler or entry.write_handler
    # Unique C identifier: use the full 16-bit address to avoid clashes
    return (
        f"static const hal_io_handler_t _h_{entry.addr:04x} = {{\n"
        f"  .name = \"{name}\",\n"
        f"{body}\n"
        f"}};"
    )


def generate_dispatch_c(
    io_map_path: Path,
    out_path: Path,
    includes: tuple[str, ...] = ("hal_io.h", "hal_handlers.h"),
) -> int:
    """Emit a C source file defining the LUT for the given game.

    Returns the number of entries placed in the LUT.
    """
    entries = parse_dispatch_entries(io_map_path)
    log.info("generating %s: %d entries from %s", out_path, len(entries), io_map_path)

    inc_lines = "\n".join(f'#include "{inc}"' for inc in includes)
    handler_structs = "\n\n".join(_emit_handler_struct(e) for e in entries)

    # Build the LUT: 256 entries, keyed on the per-entry lut_key
    # (default: HIGH 8 bits of the I/O address -- the chip-enable
    # line is a high address bit, so the high byte is unique per
    # I/O port group), NULL where there's no handler. Multiple
    # entries can share a key -- the last one wins, and we log a
    # warning so the user can see the collision.
    lut_init: list[str] = []
    lut_covered: dict[int, DispatchEntry] = {}
    for e in entries:
        key = e.lut_key if e.lut_key is not None else e.addr_high8
        if key in lut_covered:
            prev = lut_covered[key]
            log.warning(
                "LUT key 0x%02x collision: %s (0x%04x) overwrites %s (0x%04x)",
                key, e.handler, e.addr, prev.handler, prev.addr)
        lut_covered[key] = e
    for high8 in range(256):
        if high8 in lut_covered:
            e = lut_covered[high8]
            lut_init.append(
                f"  [{high8:3d}] = &_h_{e.addr:04x},  "
                f"/* 0x{e.addr:04x} {e.handler} */"
            )
        else:
            lut_init.append(f"  [{high8:3d}] = NULL,")

    body = (
        f"/* AUTO-GENERATED from {io_map_path} -- do not edit by hand. */\n"
        f"/* Generator: namco_amiga.dispatch.generate_dispatch_c */\n\n"
        f"#include <stddef.h>\n"
        f"{inc_lines}\n\n"
        f"{handler_structs}\n\n"
        f"const hal_io_handler_t *hal_io_lut[256] = {{\n"
        + "\n".join(lut_init)
        + "\n};\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body)
    return len(entries)


# ---- sub-command handler -------------------------------------

import argparse  # noqa: E402


def run_generate_dispatch(ns: argparse.Namespace) -> int:
    proj = Path(ns.project_root).resolve()
    game = ns.game
    if not game:
        log.error("--game is required for dispatch")
        return 1
    io_map = (Path(ns.io_map) if ns.io_map
              else proj / "games" / game / "io_map.json")
    out = (Path(ns.out) if ns.out
           else proj / "build" / "c" / f"{game}_io_dispatch.c")
    if not io_map.exists():
        log.error("io_map not found: %s", io_map)
        return 1
    n = generate_dispatch_c(io_map, out)
    log.info("wrote %d handler entries to %s", n, out)
    return 0

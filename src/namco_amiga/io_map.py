"""JSON I/O map loader.

This is the **one** file that replaces the per-game
`post_process.py` regex files in jotd's `commando` /
`amiga68ktools` repos. Instead of writing 289 lines of
re.sub() per game, you write a small JSON file:

    {
      "game": "pacland",
      "io_map": {
        "0x6800": {"kind": "sound_command",  "handler": "hal_audio_cmd"},
        "0x7000": {"kind": "sprite_dma",     "handler": "hal_sprite_dma"},
        "0x7800": {"kind": "dsw_read",       "handler": "hal_read_dsw"}
      },
      "memory_map": {
        "0x0000-0x1fff":  {"kind": "ram",   "backing": "shared_68k_buffer"},
        "0x4000-0x7fff":  {"kind": "rom",   "backing": "sound_6809_rom"}
      }
    }

The validator and post-processor both use this. New game?
One small JSON file, no Python.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

log = logging.getLogger(__name__)

_RANGE_RE = re.compile(r"^0x([0-9a-fA-F]+)-0x([0-9a-fA-F]+)$")


@dataclass(frozen=True)
class IoEntry:
    kind: str
    handler: str
    access: str | None = None  # "R", "W", or "R/W" -- infer if None

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "IoEntry":
        kind = data.get("kind")
        handler = data.get("handler")
        access = data.get("access")  # may be absent
        if not isinstance(kind, str):
            raise ValueError(f"io entry missing string 'kind': {data!r}")
        if not isinstance(handler, str):
            raise ValueError(f"io entry missing string 'handler': {data!r}")
        if access is not None and not isinstance(access, str):
            raise ValueError(f"io entry 'access' must be string if set: {data!r}")
        return cls(kind=kind, handler=handler, access=access if isinstance(access, str) else None)


@dataclass(frozen=True)
class MemoryRange:
    start: int
    end: int
    kind: str
    backing: str

    @classmethod
    def from_json(cls, key: str, data: Mapping[str, object]) -> "MemoryRange":
        m = _RANGE_RE.match(key)
        if not m:
            raise ValueError(f"memory range key must be hex-hex, got {key!r}")
        start, end = int(m.group(1), 16), int(m.group(2), 16)
        if start > end:
            raise ValueError(f"memory range start > end: {key!r}")
        kind = data.get("kind")
        backing = data.get("backing")
        if not isinstance(kind, str) or not isinstance(backing, str):
            raise ValueError(f"memory entry needs string 'kind' + 'backing': {data!r}")
        return cls(start=start, end=end, kind=kind, backing=backing)


@dataclass(frozen=True)
class IoMap:
    game: str
    # Legacy single-handler block ("io_map"): one entry per address,
    # direction inferred or set via the entry's `access` field. Used
    # by Namco games (pacland) where read and write never collide.
    io: dict[int, IoEntry] = field(default_factory=dict)
    # Split blocks ("io_read"/"io_write"): direction is implied by the
    # block, so the *same* address can hold different read and write
    # handlers. Galaxian-family hardware (mooncrst) needs this -- e.g.
    # 0xa800 is IN1 when read and a sound port when written.
    io_read: dict[int, IoEntry] = field(default_factory=dict)
    io_write: dict[int, IoEntry] = field(default_factory=dict)
    memory: list[MemoryRange] = field(default_factory=list)

    def address_in_range(self, addr: int) -> MemoryRange | None:
        for r in self.memory:
            if r.start <= addr <= r.end:
                return r
        return None

    def io_at(self, addr: int) -> IoEntry | None:
        return self.io.get(addr) or self.io_read.get(addr) or self.io_write.get(addr)

    def read_at(self, addr: int) -> IoEntry | None:
        return self.io_read.get(addr) or self.io.get(addr)

    def write_at(self, addr: int) -> IoEntry | None:
        return self.io_write.get(addr) or self.io.get(addr)


def load_io_map(path: Path) -> IoMap:
    """Load and validate an I/O map from JSON.

    Raises:
        FileNotFoundError, json.JSONDecodeError, ValueError on bad data.
    """
    log.info("loading I/O map: %s", path)
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"I/O map root must be an object, got {type(raw).__name__}")
    game = raw.get("game")
    if not isinstance(game, str):
        raise ValueError("I/O map missing string 'game' field")

    def _parse_io_block(block: object, label: str) -> dict[int, IoEntry]:
        out: dict[int, IoEntry] = {}
        if not isinstance(block, dict):
            raise ValueError(f"{label!r} must be an object")
        for k, v in block.items():
            if not isinstance(v, dict):
                raise ValueError(f"{label} entry {k!r} must be an object")
            try:
                addr = int(k, 16)
            except ValueError as e:
                raise ValueError(f"{label} entry key must be hex: {k!r}") from e
            out[addr] = IoEntry.from_json(v)
        return out

    io_entries = _parse_io_block(raw.get("io_map", {}), "io_map")
    io_read = _parse_io_block(raw.get("io_read", {}), "io_read")
    io_write = _parse_io_block(raw.get("io_write", {}), "io_write")
    mem_entries: list[MemoryRange] = []
    mem_block = raw.get("memory_map", {})
    if not isinstance(mem_block, dict):
        raise ValueError("'memory_map' must be an object")
    for k, v in mem_block.items():
        if not isinstance(v, dict):
            raise ValueError(f"memory entry {k!r} must be an object")
        mem_entries.append(MemoryRange.from_json(k, v))
    return IoMap(game=game, io=io_entries, io_read=io_read,
                 io_write=io_write, memory=mem_entries)

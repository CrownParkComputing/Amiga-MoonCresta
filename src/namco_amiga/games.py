"""Sub-module: game discovery + META.toml loader.

The single source-of-truth for "what games does this project support".
Each game lives in `games/<name>/META.toml`. Adding a new game is:
    mkdir games/<name>
    # write META.toml (copy from games/pacland/META.toml)
    # write io_map.json
    make game-<name>

The discovery walks `games/` looking for `META.toml` files. TOML
parsing uses the stdlib `tomllib` (Python 3.11+).
"""
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

GAMES_DIRNAME = "games"
META_FILENAME = "META.toml"


@dataclass(frozen=True)
class GameMeta:
    name: str
    title: str
    year: int
    manufacturer: str
    rom_zip: str | None
    path: Path
    # The full dict is kept so future fields don't require a dataclass bump.
    raw: dict[str, Any]

    def to_summary(self) -> str:
        rom_status = self.rom_zip or "(rom not configured)"
        return (f"{self.name:<10s} {self.title:<14s} "
                f"{self.year}  {self.manufacturer:<10s}  {rom_status}")


def _discover_games_dir(project_root: Path) -> Path | None:
    candidate = project_root / GAMES_DIRNAME
    return candidate if candidate.is_dir() else None


def discover_games(project_root: Path) -> list[GameMeta]:
    """Walk `games/<name>/META.toml` and return a list of GameMeta.

    Skips directories that have no META.toml (the scaffold is fine
    with partially-populated game dirs).
    """
    gdir = _discover_games_dir(project_root)
    if gdir is None:
        log.warning("no %s/ directory at %s", GAMES_DIRNAME, project_root)
        return []
    out: list[GameMeta] = []
    for entry in sorted(gdir.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / META_FILENAME
        if not meta_path.is_file():
            log.debug("skipping %s: no %s", entry.name, META_FILENAME)
            continue
        try:
            meta = load_game_meta(meta_path)
        except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError) as e:
            log.error("failed to load %s: %s", meta_path, e)
            continue
        out.append(meta)
    return out


def load_game_meta(path: Path) -> GameMeta:
    """Load a single META.toml."""
    log.debug("loading META: %s", path)
    raw = tomllib.loads(path.read_text())
    g = raw.get("game")
    if not isinstance(g, dict):
        raise ValueError(f"{path}: missing [game] table")
    name = g.get("name")
    title = g.get("title")
    year = g.get("year")
    manufacturer = g.get("manufacturer")
    rom_zip = g.get("rom_zip")  # may be None / empty
    if not isinstance(name, str) or not name:
        raise ValueError(f"{path}: game.name missing or empty")
    if not isinstance(title, str):
        raise ValueError(f"{path}: game.title missing")
    if not isinstance(year, int):
        raise ValueError(f"{path}: game.year must be int")
    if not isinstance(manufacturer, str):
        raise ValueError(f"{path}: game.manufacturer missing")
    if rom_zip is not None and not isinstance(rom_zip, str):
        raise ValueError(f"{path}: game.rom_zip must be string if set")
    return GameMeta(
        name=name, title=title, year=year, manufacturer=manufacturer,
        rom_zip=rom_zip or None, path=path.parent, raw=raw,
    )


def find_game(project_root: Path, name: str) -> GameMeta:
    """Look up a single game by short name. Raises KeyError if absent."""
    for g in discover_games(project_root):
        if g.name == name:
            return g
    raise KeyError(f"no game named {name!r} in {project_root/GAMES_DIRNAME}")


# ---- sub-command handler ----------------------------------------

def list_games(ns: argparse.Namespace) -> int:  # type: ignore[name-defined]
    proj = Path(ns.project_root).resolve()
    games = discover_games(proj)
    if not games:
        log.warning("no games discovered in %s", proj / GAMES_DIRNAME)
        return 0
    print(f"{'NAME':<10s} {'TITLE':<14s} {'YEAR':<6s} {'MANUFACT.':<10s} ROM")
    print("-" * 80)
    for g in games:
        print(g.to_summary())
    return 0

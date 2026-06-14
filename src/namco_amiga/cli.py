"""Typed, logging-aware CLI for pacland_tools.

Why this exists:
    The older jotd scripts each do their own argparse setup, print()
    warnings in random styles, and some (z80268k_legacy.py, 6809to68k.py)
    even keep commented-out ``import simpleeval`` / ``import count_usage``
    dependencies. This module is the single typed entrypoint that
    replaces all of them.

Design:
    - One sub-command parser with shared --verbose / --quiet / --log-file
      options so every tool can be silenced for CI and made loud for
      interactive use.
    - Sub-commands are dispatched via dict-of-functions so adding a
      new one is a 5-line change.
    - No global state, no ``sys.path`` munging, no hardcoded
      ``K:\\\\progs\\\\cli`` paths in environment variables.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, Sequence

from . import __version__
from .archive import build_archive
from .convert import run_conversion
from .disasm import run_disassembly
from .dispatch import run_generate_dispatch
from .constants import DEFAULT_LINUX_TOOLCHAIN, TOOLCHAIN_ENV
from .games import list_games
from .postprocess import run_postprocess
from .validate import run_validate
from .version import tool_versions

log = logging.getLogger("namco_amiga")


def _setup_logging(verbose: int, quiet: bool, log_file: str | None) -> None:
    """One consistent logger config for every sub-command.

    -v / -vv  -> DEBUG / INFO  (or stacked: -vvv adds 1 more level)
    -q        -> WARNING only
    --log-file -> tee everything to a file
    """
    if quiet:
        level = logging.WARNING
    else:
        # -v = INFO, -vv = DEBUG, -vvv = NOTSET (show library internals)
        level = max(logging.WARNING - 10 * verbose, logging.NOTSET)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, mode="w"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


# sub-command registry -------------------------------------------------
Handler = Callable[[argparse.Namespace], int]


def _version_cmd(_ns: argparse.Namespace) -> int:
    for k, v in tool_versions().items():
        print(f"{k:20s} {v}")
    return 0


_SUBCOMMANDS: dict[str, tuple[Handler, str, str]] = {
    # name:        (handler,           help,                                   description)
    "games":       (list_games,        "list all known games in games/",       "games"),
    "disasm":      (run_disassembly,   "disassemble a ROM set via MAME",       "disasm"),
    "convert":     (run_conversion,    "run the 6809to68k conversion",         "convert"),
    "postprocess": (run_postprocess,   "apply the JSON I/O map and emit 68k",  "postprocess"),
    "dispatch":    (run_generate_dispatch,
                                    "emit the I/O dispatch C table from io_map.json",
                                                                        "dispatch"),
    "archive":     (build_archive,     "build a WHDLoad-installable directory","archive"),
    "validate":    (run_validate,      "sanity-check a slave + binary pair",   "validate"),
    "version":     (_version_cmd,      "print tool versions",                  "version"),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="namco_amiga",
        description=(
            "Anchored-emulation build pipeline for Namco arcade ports. "
            "Replaces jotd's per-game Windows post_process.py + "
            "create_amiga_archive.py scripts with a single typed CLI."
        ),
    )
    p.add_argument(
        "-V", "--version", action="version",
        version=f"namco_amiga {__version__}",
    )
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="increase verbosity (stackable: -v, -vv, -vvv)")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="warnings only")
    p.add_argument("--log-file", metavar="PATH", default=None,
                   help="also tee all output to this file")
    p.add_argument("--toolchain-dir", metavar="DIR", default=None,
                   help=f"override {TOOLCHAIN_ENV} (default: "
                        f"{DEFAULT_LINUX_TOOLCHAIN})")
    sub = p.add_subparsers(dest="command", required=True)
    for name, (_h, help_, _desc) in _SUBCOMMANDS.items():
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(_handler_name=name)
        # Sub-commands that touch project files all need the same
        # --project-root + --game options. Add them once here so
        # individual handlers don't have to repeat the boilerplate.
        if name in ("archive", "validate", "games", "dispatch"):
            sp.add_argument("--project-root", required=True,
                            help="absolute path to the project root")
            sp.add_argument("--game", default=None,
                            help="game name (optional for `games` subcommand)")
            if name == "dispatch":
                sp.add_argument("--io-map", default=None,
                                help="override io_map.json path")
                sp.add_argument("--out", default=None,
                                help="override output .c file path")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    _setup_logging(ns.verbose, ns.quiet, ns.log_file)
    handler, _help, _desc = _SUBCOMMANDS[ns.command]
    log.debug("running sub-command: %s", ns.command)
    return handler(ns)


if __name__ == "__main__":
    raise SystemExit(main())

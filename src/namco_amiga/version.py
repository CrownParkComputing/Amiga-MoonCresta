"""Toolchain + library version reporter (replaces 30 ad-hoc version checks)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .constants import DEFAULT_LINUX_TOOLCHAIN, TOOLCHAIN_ENV

# The m68k cross-compiler installed by the project Makefile.
# Overridable via AMIGA_GCC_HOME; default matches the Makefile.
AMIGA_GCC_HOME_ENV = "AMIGA_GCC_HOME"
DEFAULT_AMIGA_GCC_HOME = "/home/jon/amiga-amigaos"


def _which(prog: str) -> str | None:
    return shutil.which(prog)


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None


def tool_versions() -> dict[str, str]:
    """Report toolchain versions; graceful when missing."""
    vers: dict[str, str] = {}
    vers["namco_amiga"] = "0.1.0"

    toolchain = os.environ.get(TOOLCHAIN_ENV, DEFAULT_LINUX_TOOLCHAIN)
    vers["toolchain_dir"] = toolchain

    amiga_gcc = os.environ.get(AMIGA_GCC_HOME_ENV, DEFAULT_AMIGA_GCC_HOME)
    vers["amiga_gcc_home"] = amiga_gcc

    asm = _which("vasmm68k_mot") or str(Path(toolchain) / "vasmm68k_mot")
    if _which(asm):
        v = _run([asm, "--version"]) or _run([asm, "-version"]) or _run([asm])
        vers["vasm"] = v or "unknown"

    if _which("vlink"):
        v = _run(["vlink", "-V"]) or _run(["vlink", "--version"])
        vers["vlink"] = v or "unknown"

    # Bebbo's m68k cross-compiler, lives at $AMIGA_GCC_HOME/bin
    for tool in ("m68k-amigaos-gcc", "m68k-amigaos-as", "m68k-amigaos-ld"):
        path = _which(tool) or str(Path(amiga_gcc) / "bin" / tool)
        if _which(path):
            v = _run([path, "--version"])
            vers[tool] = v or "unknown"
        else:
            vers[tool] = "not installed"

    for tool in ("mame", "amiberry", "fs-uae", "python3"):
        path = _which(tool)
        if path:
            v = _run([tool, "--version"])
            vers[tool] = v or path
        else:
            vers[tool] = "not installed"

    return vers

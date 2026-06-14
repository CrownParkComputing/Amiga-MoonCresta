"""Constants shared across pacland_tools sub-modules.

Lives in its own module to avoid circular imports
(cli <-> version used to dance around each other).
"""
from __future__ import annotations

#: Env-var that overrides the Amiga toolchain location.
TOOLCHAIN_ENV = "PACLAND_TOOLCHAIN_DIR"

#: Default Linux toolchain directory (matches Bebbo's typical install).
DEFAULT_LINUX_TOOLCHAIN = "/opt/amiga-toolchain/bin"

#: Amiga HUNK_HEADER magic. Every well-formed Amiga .exe or .slave
#: starts with these four bytes: 0x00 0x00 0x03 0xF3.
HUNK_HEADER_MAGIC = b"\x00\x00\x03\xf3"

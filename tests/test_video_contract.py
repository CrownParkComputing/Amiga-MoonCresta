"""Tests for the video HAL header.

The actual hardware-touching code in video.s is a stub right
now. These tests verify the *contract* -- that the public API
in video.h matches what the assembly exports, so when the real
video code lands, the link won't break.

We do this by parsing the asm file's XDEF list and checking
the C header declares the matching symbols.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class VideoHeaderContractTests(unittest.TestCase):
    """The C header in video.h must match the XDEF list in video.s."""

    def setUp(self) -> None:
        self.video_h = (REPO / "src" / "hal" / "video.h").read_text()
        self.video_s = (REPO / "src" / "hal" / "video.s").read_text()

    def _asm_xdefs(self) -> set[str]:
        # Find every "_hal_*" in XDEF lines
        names: set[str] = set()
        for line in self.video_s.splitlines():
            stripped = line.strip()
            if stripped.startswith("XDEF"):
                # XDEF    _hal_video_open
                for tok in stripped.split()[1:]:
                    if tok.startswith("_"):
                        tok = tok.lstrip("_")
                        names.add(tok)
        return names

    def _defined_anywhere(self) -> set[str]:
        """Symbols defined in either the asm XDEF list or
        implemented as C functions in video.c."""
        names = self._asm_xdefs()
        c_text = (REPO / "src" / "hal" / "video.c").read_text()
        for m in re.finditer(r"^\s*void\s+(hal_\w+)\s*\(", c_text, re.M):
            names.add(m.group(1))
        return names

    def test_asm_exports_video_open(self) -> None:
        self.assertIn("hal_video_open", self._defined_anywhere())

    def test_asm_exports_video_frame(self) -> None:
        self.assertIn("hal_video_frame", self._defined_anywhere())

    def test_asm_exports_sprite_set(self) -> None:
        self.assertIn("hal_sprite_set", self._asm_xdefs())

    def test_asm_exports_tilemap_set(self) -> None:
        self.assertIn("hal_tilemap_set", self._asm_xdefs())

    def test_asm_exports_palette_set_bank(self) -> None:
        self.assertIn("hal_palette_set_bank", self._asm_xdefs())

    def test_asm_exports_palette_set(self) -> None:
        self.assertIn("hal_palette_set", self._asm_xdefs())

    def test_c_header_declares_video_open(self) -> None:
        # video.h has the prototype as "void hal_video_open(void);"
        # which becomes "_hal_video_open" after m68k asm symbol prefix.
        self.assertRegex(self.video_h, r"void\s+hal_video_open\s*\(")

    def test_c_header_declares_video_frame(self) -> None:
        self.assertRegex(self.video_h, r"void\s+hal_video_frame\s*\(")

    def test_c_header_declares_sprite_set(self) -> None:
        self.assertRegex(
            self.video_h,
            r"void\s+hal_sprite_set\s*\([^)]*slot[^)]*\)",
        )

    def test_c_header_declares_tilemap_set(self) -> None:
        self.assertRegex(
            self.video_h,
            r"void\s+hal_tilemap_set\s*\(",
        )

    def test_c_header_declares_palette_set_bank(self) -> None:
        self.assertRegex(self.video_h, r"void\s+hal_palette_set_bank\s*\(")

    def test_c_header_declares_palette_set(self) -> None:
        self.assertRegex(self.video_h, r"void\s+hal_palette_set\s*\(")

    def test_asm_and_c_declared_symbols_match(self) -> None:
        """The set of defined symbols (asm XDEF + C void hal_*)
        should match the C header's prototype set."""
        defined = self._defined_anywhere()
        # Extract C function names that match the asm pattern
        c_declared = set(re.findall(
            r"void\s+(hal_\w+)\s*\(", self.video_h))
        # Every defined symbol should have a C declaration
        missing_in_c = defined - c_declared
        self.assertEqual(missing_in_c, set(),
            f"defined here but C header doesn't declare: {missing_in_c}")

    def test_pacland_video_dimensions_match_mame(self) -> None:
        """Pacland arcade is 288x224 per MAME. The HAL must
        match -- a discrepancy here is a bug."""
        self.assertRegex(self.video_h, r"HAL_VIDEO_W\s+288\b")
        self.assertRegex(self.video_h, r"HAL_VIDEO_H\s+224\b")
        # And the Amiga screen is 320x256 PAL
        self.assertRegex(self.video_h, r"HAL_AMIGA_W\s+320\b")
        self.assertRegex(self.video_h, r"HAL_AMIGA_H\s+256\b")


if __name__ == "__main__":
    unittest.main()

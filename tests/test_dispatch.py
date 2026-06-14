"""Tests for the I/O dispatch generator.

The generator is the glue between games/<name>/io_map.json
(declarative) and build/c/<name>_io_dispatch.c (executable).
These tests pin down the contract so future changes don't
silently break the wire-up.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from namco_amiga import dispatch, io_map

REPO = Path(__file__).resolve().parents[1]


def _write_io_map(d: Path, payload: dict) -> Path:
    p = d / "io_map.json"
    p.write_text(json.dumps(payload))
    return p


class DispatchGeneratorTests(unittest.TestCase):
    def test_parse_pacland_has_9_entries(self) -> None:
        m = REPO / "games" / "pacland" / "io_map.json"
        entries = dispatch.parse_dispatch_entries(m)
        # pacland/io_map.json has 9 I/O addresses
        self.assertEqual(len(entries), 9)

    def test_lut_keyed_on_high_byte(self) -> None:
        """LUT position is the HIGH 8 bits of the I/O address,
        because Namco decodes on A12-A15 (chip-enable lines)."""
        m = REPO / "games" / "pacland" / "io_map.json"
        entries = dispatch.parse_dispatch_entries(m)
        for e in entries:
            self.assertEqual(e.addr_high8, (e.addr >> 8) & 0xff)
            self.assertNotEqual(e.addr_high8, e.addr & 0xff,
                msg=f"low 8 bits collide (0x{e.addr:04x}); "
                    f"Namco I/O chips decode on high byte")

    def test_lut_entries_unique(self) -> None:
        """No two entries should share the same high byte -- that
        would mean two different I/O chips on the same CS line."""
        m = REPO / "games" / "pacland" / "io_map.json"
        entries = dispatch.parse_dispatch_entries(m)
        keys = [e.addr_high8 for e in entries]
        self.assertEqual(len(keys), len(set(keys)),
            "duplicate high-byte keys in pacland io_map.json")

    def test_handler_name_suffix(self) -> None:
        """Handler base names from io_map.json get _r or _w
        depending on access type."""
        m = REPO / "games" / "pacland" / "io_map.json"
        entries = dispatch.parse_dispatch_entries(m)
        watchdog = next(e for e in entries if e.handler == "hal_watchdog_kick")
        self.assertEqual(watchdog.access, "R")
        # The generated C file will reference hal_watchdog_kick_r
        body = dispatch._emit_handler_struct(watchdog)
        self.assertIn("hal_watchdog_kick_r", body)
        self.assertNotIn("hal_watchdog_kick_w", body)

    def test_writes_get_w_suffix(self) -> None:
        m = REPO / "games" / "pacland" / "io_map.json"
        entries = dispatch.parse_dispatch_entries(m)
        tilemap = next(e for e in entries if e.handler == "hal_tilemap_enable")
        self.assertEqual(tilemap.access, "W")
        body = dispatch._emit_handler_struct(tilemap)
        self.assertIn("hal_tilemap_enable_w", body)

    def test_generate_dispatch_c_writes_valid_c(self) -> None:
        m = REPO / "games" / "pacland" / "io_map.json"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dispatch.c"
            n = dispatch.generate_dispatch_c(m, out)
            self.assertEqual(n, 9)
            self.assertTrue(out.exists())
            text = out.read_text()
            # Should contain all 9 handler struct names
            self.assertEqual(text.count("static const hal_io_handler_t"), 9)
            # LUT has exactly 9 non-NULL slots (one per handler)
            self.assertEqual(text.count("= &_h_"), 9)
            # The LUT array is 256 entries
            lut_match = re.search(
                r"hal_io_lut\[256\] = \{([^}]+)\}", text, re.DOTALL)
            self.assertIsNotNone(lut_match)
            lut_body = lut_match.group(1)
            # Count [N] entries
            slot_count = len(re.findall(r"\[\s*\d+\s*\]", lut_body))
            self.assertEqual(slot_count, 256,
                "LUT must have 256 slot initialisers")
            # Non-NULL slots in the LUT
            non_null = lut_body.count("= &_h_")
            self.assertEqual(non_null, 9)
            # NULL slots = 256 - 9 = 247
            null_count = lut_body.count("NULL,")
            self.assertEqual(null_count, 256 - 9)

    def test_explicit_access_in_json_overrides_inference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # kind=watchdog_kick would infer R, but we mark W explicitly
            io = _write_io_map(td, {
                "game": "x",
                "io_map": {
                    "0x1200": {"kind": "watchdog_kick",
                                "handler": "hal_wd",
                                "access": "W"}
                },
                "memory_map": {},
            })
            entries = dispatch.parse_dispatch_entries(io)
            self.assertEqual(entries[0].access, "W",
                "explicit access in JSON should override the keyword heuristic")


class SplitDispatchTests(unittest.TestCase):
    """Galaxian-family games (mooncrst) use io_read/io_write blocks, so a
    single LUT slot can carry distinct read and write handlers."""

    def setUp(self) -> None:
        self.mc = REPO / "games" / "mooncrst" / "io_map.json"

    def test_mooncrst_has_4_slots(self) -> None:
        entries = dispatch.parse_dispatch_entries(self.mc)
        # 4 port groups: 0xa000, 0xa800, 0xb000, 0xb800
        self.assertEqual(len(entries), 4)
        self.assertEqual({e.addr_high8 for e in entries},
                         {0xA0, 0xA8, 0xB0, 0xB8})

    def test_overlap_slot_has_both_handlers(self) -> None:
        entries = {e.addr: e for e in dispatch.parse_dispatch_entries(self.mc)}
        a800 = entries[0xA800]
        self.assertEqual(a800.read_handler, "hal_input_in1")
        self.assertEqual(a800.write_handler, "hal_sound_ctrl")
        self.assertEqual(a800.access, "RW")
        body = dispatch._emit_handler_struct(a800)
        self.assertIn(".read  = hal_input_in1_r,", body)
        self.assertIn(".write = hal_sound_ctrl_w,", body)

    def test_write_only_slot(self) -> None:
        entries = {e.addr: e for e in dispatch.parse_dispatch_entries(self.mc)}
        b800 = entries[0xB800]
        self.assertEqual(b800.access, "W")
        body = dispatch._emit_handler_struct(b800)
        self.assertIn(".read  = NULL,", body)
        self.assertIn(".write = hal_sound_pitch_w,", body)

    def test_lut_keyed_on_high_byte_no_collision(self) -> None:
        # Regression guard for the LUT-key fix: pacland's addresses all
        # have low byte 0x00, so a low-byte key collapsed all 9 handlers
        # into one slot. The LUT must key on the high byte.
        m = REPO / "games" / "pacland" / "io_map.json"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "d.c"
            dispatch.generate_dispatch_c(m, out)
            self.assertEqual(out.read_text().count("= &_h_"), 9)


class DispatchEndToEndTests(unittest.TestCase):
    """Verify the generated C file compiles with a real Amiga C compiler.

    This is the regression test that catches the "we changed the generator
    but didn't check the C actually compiles" failure mode.
    """

    @unittest.skipUnless(
        Path("/home/jon/amiga-amigaos/bin/m68k-amigaos-gcc").exists(),
        "m68k-amigaos-gcc not installed")
    def test_generated_c_compiles(self) -> None:
        gcc = "/home/jon/amiga-amigaos/bin/m68k-amigaos-gcc"
        m = REPO / "games" / "pacland" / "io_map.json"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            c_out = td / "dispatch.c"
            dispatch.generate_dispatch_c(m, c_out)
            # Compile it as a standalone TU with a fake hal_io.h
            # providing the types the generator references.
            (td / "hal_io.h").write_text(
                "#include <stdint.h>\n"
                "typedef uint8_t (*hal_io_read_handler_t)(uint16_t);\n"
                "typedef void    (*hal_io_write_handler_t)(uint16_t, uint8_t);\n"
                "typedef struct { const char *name;\n"
                "  hal_io_read_handler_t read;\n"
                "  hal_io_write_handler_t write;\n"
                "} hal_io_handler_t;\n"
            )
            (td / "hal_handlers.h").write_text(
                "#include <stdint.h>\n"
                "extern void hal_tilemap_enable_w(uint16_t,uint8_t);\n"
                "extern void hal_mcu_reset_w(uint16_t,uint8_t);\n"
                "extern void hal_flip_screen_w(uint16_t,uint8_t);\n"
                "extern void hal_bank_switch_w(uint16_t,uint8_t);\n"
                "extern void hal_sound_wave_write_w(uint16_t,uint8_t);\n"
                "extern void hal_sound_reg_write_w(uint16_t,uint8_t);\n"
                "extern void hal_irq_enable_w(uint16_t,uint8_t);\n"
                "extern uint8_t hal_watchdog_kick_r(uint16_t);\n"
                "extern uint8_t hal_vblank_ack_r(uint16_t);\n"
            )
            # The C file should compile without errors
            r = subprocess.run(
                [gcc, "-m68000", "-noixemul", "-c", str(c_out),
                 "-I", str(td), "-o", str(td / "dispatch.o")],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0,
                msg=f"generated C failed to compile:\n{r.stderr}")
            self.assertTrue((td / "dispatch.o").exists())


if __name__ == "__main__":
    unittest.main()

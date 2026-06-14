"""Tests for namco_amiga.

Run with:
    cd /home/jon/pacland-amiga
    make test
"""
import tempfile
import unittest
from pathlib import Path

from namco_amiga import games, io_map

REPO = Path(__file__).resolve().parents[1]


class IoMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.good = REPO / "games" / "pacland" / "io_map.json"

    def test_loads_pacland(self) -> None:
        m = io_map.load_io_map(self.good)
        self.assertEqual(m.game, "pacland")
        self.assertGreater(len(m.io), 0)
        self.assertGreater(len(m.memory), 0)

    def test_io_at(self) -> None:
        m = io_map.load_io_map(self.good)
        # pacland MAME mem-map: 0x7800 R = watchdog kick
        entry = m.io_at(0x7800)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "watchdog_reset")
        self.assertEqual(entry.handler, "hal_watchdog_kick")

    def test_memory_range_lookup(self) -> None:
        m = io_map.load_io_map(self.good)
        # 0x9000 is the start of the main 6809 banked program ROM
        r = m.address_in_range(0x9000)
        self.assertIsNotNone(r)
        self.assertEqual(r.kind, "rom")
        self.assertEqual(r.backing, "main_6809_banked_rom")

    def test_rejects_bad_game(self) -> None:
        import json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"io_map": {}}, f)
            name = f.name
        with self.assertRaises(ValueError):
            io_map.load_io_map(Path(name))

    def test_rejects_bad_range(self) -> None:
        import json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"game": "x", "memory_map": {"foo": {}}}, f)
            name = f.name
        with self.assertRaises(ValueError):
            io_map.load_io_map(Path(name))


class SplitIoMapTests(unittest.TestCase):
    """The io_read / io_write blocks let the same address carry
    different read and write handlers (Galaxian-family hardware)."""

    def setUp(self) -> None:
        self.mc = REPO / "games" / "mooncrst" / "io_map.json"

    def test_mooncrst_loads(self) -> None:
        m = io_map.load_io_map(self.mc)
        self.assertEqual(m.game, "mooncrst")
        self.assertEqual(len(m.io), 0, "mooncrst uses split blocks, not legacy io_map")
        self.assertEqual(len(m.io_read), 3)
        self.assertEqual(len(m.io_write), 4)
        self.assertGreater(len(m.memory), 0)

    def test_read_write_overlap_distinct_handlers(self) -> None:
        m = io_map.load_io_map(self.mc)
        # 0xa800 is IN1 on read but a sound port on write -- the whole
        # point of the split model.
        self.assertEqual(m.read_at(0xA800).handler, "hal_input_in1")
        self.assertEqual(m.write_at(0xA800).handler, "hal_sound_ctrl")
        self.assertEqual(m.read_at(0xB800), None, "0xb800 is write-only")
        self.assertEqual(m.write_at(0xB800).handler, "hal_sound_pitch")

    def test_rejects_bad_io_read_block(self) -> None:
        import json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"game": "x", "io_read": {"nothex": {"kind": "k",
                       "handler": "h"}}}, f)
            name = f.name
        with self.assertRaises(ValueError):
            io_map.load_io_map(Path(name))


class GamesDiscoveryTests(unittest.TestCase):
    def test_discover_all_three(self) -> None:
        gs = games.discover_games(REPO)
        names = {g.name for g in gs}
        self.assertIn("pacland", names)
        self.assertIn("pacmania", names)
        self.assertIn("galaga90", names)

    def test_pacland_meta_fields(self) -> None:
        gs = {g.name: g for g in games.discover_games(REPO)}
        g = gs["pacland"]
        self.assertEqual(g.title, "Pac-Land")
        self.assertEqual(g.year, 1984)
        self.assertEqual(g.manufacturer, "Namco")
        self.assertIsNotNone(g.rom_zip)
        self.assertTrue(g.path.joinpath("io_map.json").exists())

    def test_pacmania_is_skeleton(self) -> None:
        gs = {g.name: g for g in games.discover_games(REPO)}
        g = gs["pacmania"]
        # rom_zip is commented out -> None means the game is a skeleton
        self.assertIsNone(g.rom_zip)

    def test_find_game(self) -> None:
        g = games.find_game(REPO, "galaga90")
        self.assertEqual(g.year, 1989)

    def test_find_game_missing_raises(self) -> None:
        with self.assertRaises(KeyError):
            games.find_game(REPO, "doesnotexist")


if __name__ == "__main__":
    unittest.main()

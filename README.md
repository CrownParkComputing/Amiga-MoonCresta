# Amiga Moon Cresta

A native **Amiga (AGA / A1200)** port of *Moon Cresta*. It runs the original
arcade Z80 program through a compact Z80 interpreter and a hand-written AGA
display driver — tiles, hardware-style sprites, bullets, a custom starfield,
sound on Paula, a title screen and on-screen branding.

> **You must supply your own Moon Cresta ROM.** The ROM is copyrighted
> (Nichibutsu) and is **not** included in this repository or in any release.

---

## What it does

- **Z80 core + machine layer** (`src/cores/z80.c`, `src/hal/machine.c`) run the
  unmodified arcade program ROM.
- **AGA renderer** (`src/hal/mc_render.c`, `src/hal/mc_video.c`): 5-bitplane
  320×256 screen, pre-rotated tile cache, Galaxian-style sprites + bullets, a
  custom multicolour starfield, the upright (ROT90) layout, double-buffered.
- **Paula sound** (`src/hal/mc_audio.c`): background throb, fire and explosion
  synthesised from the game's own sound-register writes (DMA-driven).
- **Title screen** with the ROM's rocket sprite and "PRESS FIRE".

## Speed / hardware

The Z80 is *interpreted*, so a stock 68020 can't quite hold 60 Hz. For full
speed:

- **Real hardware:** an A1200 with an **030 (or faster) accelerator**.
- **Amiberry / WinUAE:** enable **JIT** (or pick an 030+ CPU).

## Controls

| Input | Action |
|-------|--------|
| Left / Right | move |
| Fire (button 1) | shoot, **and** start a game |
| Up | insert coin |

---

## The ROM is loaded at runtime

The program does **not** contain the ROM. At startup it loads **`mooncrst.rom`**
from disk (next to the program). So the build and any release are ROM-free, and
each user supplies their own `mooncrst.rom`. If it's missing the screen is solid
**red**.

## Quick start — package a runnable disk from your MAME romset

If you just want to play, use the packager. Point it at **your own** MAME
Moon Cresta romset (the `mooncrst` set — **split or merged**, `.zip` / `.7z` /
a folder) and it assembles the ROM and builds the disk images for you:

```
python3 tools/build_release.py            # interactive: prompts for the romset
python3 tools/build_release.py mooncrst.zip
```

It matches the ROMs by **CRC32** (so filenames and split-vs-merged don't
matter) and writes to `dist/`:

| Output | What it is |
|--------|-----------|
| `dist/MoonCresta.adf` | bootable floppy image |
| `dist/MoonCresta_HD/` | hard-drive drawer — copy anywhere, run `mooncrst` |
| `dist/MoonCresta.lha` | the HD drawer as an archive (needs `lha`/`jlha` — see below) |

The packager needs `xdftool` (`pip install amitools`) and a prebuilt ROM-free
program (it's in `build/` after `make adf`, or download the **ROM-free ADF**
from this repo's CI artifacts and pass `--adf`/`--exe`). For the `.lha` output
install a creating-capable LhA: Debian/Ubuntu `apt install jlha-utils`, macOS
`brew install lhasa`, or build [`jca02266/lha`](https://github.com/jca02266/lha).
Nothing it writes (the ROM, the populated disks) is ever committed — `dist/`
is git-ignored.

## Building from source

Needs a bare-metal m68k Amiga cross-toolchain (Bebbo's `m68k-amigaos-gcc`),
`vasm`/`vlink`, and Python `amitools` (for `xdftool`). See `docs/TOOLCHAIN.md`.

1. **Build the (ROM-free) program + ADF:**
   ```
   make GAME=mooncrst adf             # -> build/mooncrst (exe) + build/mooncrst.adf
   ```
2. **Make your `mooncrst.rom`** from a Moon Cresta ROM set you own — put the
   files under:
   ```
   games/mooncrst/roms/  epr194 … epr201
   games/mooncrst/gfx/   mcs_a mcs_b mcs_c mcs_d
   games/mooncrst/mmi6331.6l
   ```
   then:
   ```
   python3 tools/make_rom.py          # -> build/mooncrst.rom (24608 bytes)
   ```

## Running

Put **`mooncrst.rom`** next to the program:

- **ADF:** write `mooncrst.rom` into the disk root next to `mooncrst`.
- **WHDLoad / hard drive:** drop `mooncrst.rom` in the same directory as the
  program/slave.

Then boot on an A1200 (Kickstart 3.1, AGA). Example Amiberry configs are in
`run/`. Enable **JIT** (or use an **030+**) for full speed.

---

## Notes

- `src/` is a shared multi-game framework; Moon Cresta is the focus here.
- ROMs, ROM-derived files, disk images, and third-party reference material are
  **git-ignored** and never published — see `.gitignore`.

## Credits

Port & code: **Whitty Arcade**. *Moon Cresta* © Nichibutsu — ROM not included.

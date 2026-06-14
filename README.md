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

## Building

Needs a bare-metal m68k Amiga cross-toolchain (Bebbo's `m68k-amigaos-gcc`),
`vasm`/`vlink`, and Python `amitools` (for `xdftool`). See `docs/TOOLCHAIN.md`.

1. **Provide your ROM** — put your own files under:
   ```
   games/mooncrst/roms/  epr194 … epr201
   games/mooncrst/gfx/   mcs_a mcs_b mcs_c mcs_d
   games/mooncrst/mmi6331.6l
   ```
2. **Embed the ROM:**
   ```
   python3 tools/make_romdata.py      # writes src/hal/mc_romdata.c (git-ignored)
   ```
3. **Build the ADF:**
   ```
   make GAME=mooncrst adf             # -> build/mooncrst.adf
   ```

## Running

Boot `build/mooncrst.adf` on an A1200 (Kickstart 3.1, AGA). Example Amiberry
configs are in `run/`. Enable JIT or use an 030+ for full speed.

---

## Notes

- `src/` is a shared multi-game framework; Moon Cresta is the focus here.
- ROMs, ROM-derived files, disk images, and third-party reference material are
  **git-ignored** and never published — see `.gitignore`.

## Credits

Port & code: **Whitty Arcade**. *Moon Cresta* © Nichibutsu — ROM not included.

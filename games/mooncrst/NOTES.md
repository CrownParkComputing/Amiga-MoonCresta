# Moon Cresta port notes

## MAME source

- `src/mame/drivers/galdrvr.c` (lines for `mooncrstg` ROM_START)
- `src/mame/video/galaxian.c` (the Galaxian hardware video emulation)
- `src/mame/audio/galaxian.c` (the discrete analog sound)

## CPU architecture

- 1× Z80 @ 3.072 MHz (3.072 = 18.432 MHz / 6)
- 24 KB program ROM (8 × 2K eproms in 8 slots)
- 2 KB work RAM
- NO 6809, NO 68000, NO sound CPU
- The Z80 does everything including writing to the sound board

## Video hardware (Galaxian family)

- 1× 256×224 visible bitmap (288×224 virtual)
- 32×32 tilemap, 8×8 tiles, 2 bpp
- 8 sprites (player ship + 6 enemies + bullet sprite)
- 8 hardware bullets (the "alien rockets" in attract mode)
- **No sprite vs background priority mask** — sprites are drawn
  on top of tiles in the order they're listed in sprite RAM
- Color palette: 32 bytes from the 82s123 PROM, each byte
  selects a 4-color pen set from a 256-byte color RAM
- **Stars**: hardware-generated, not in main RAM. The star
  field is a 5-bit LFSR that updates per scanline. Stars have
  their own address space and color table. For our Amiga
  port we'll skip the LFSR and just display a fixed star
  pattern, or implement the LFSR in the HAL (simpler).

## Memory map (from MAME)

```
0x0000-0x3fff  ROM (16K) -- 8 eproms
0x8000-0x87ff  Work RAM (2K)
0x9000-0x93ff  Video RAM (1K, 32x32)
0x9400-0x97ff  Video RAM mirror (R only)
0x9800-0x983f  Tile attribute RAM (color + flip)
0x9840-0x985f  Sprite RAM (8 sprites)
0x9860-0x987f  Bullet RAM (8 bullets)
0xfffc-0xffff  NMI vector mirror
```

## I/O map (from MAME)

```
0xa000          IN0 (joystick + coin + start)  R
0xa003          Coin counter                    W
0xa004-0xa007   Sound LFO frequency             W
0xa800          IN1 (button + tilt + coin2)     R
0xa800-0xa807   Sound (3 enable + 2 vol)        W
0xb000          DSW0                            R
0xb000          NMI enable                      W
0xb004          Stars enable                    W
0xb006          Flip screen X                   W
0xb007          Flip screen Y                   W
0xb800          Watchdog reset                  R
0xb800          Sound pitch                     W
```

## The 3 things we have to invent (no MAME equivalent)

1. **The Amiga 4 bpp bitplane layout.** The arcade is 2 bpp;
   we go to 4 bpp (16 colors) for cleaner output. The tilemap
   + sprites need conversion to 4 bpp tile format. Trivial.

2. **The palette conversion.** The 32-byte PROM holds
   nybbles, and each color RAM entry is 4 bpp. We decode the
   PROM to build a 256×4-bit palette, then convert to 4 bpp
   Amiga format (0xRGB). One-time Python script.

3. **The star field LFSR.** Skipped in v1, draw a fixed
   star pattern or just leave it off. The hardware LFSR is
   5 bits, updated per scanline, with a 256-byte lookup
   table for the 5-bit positions. Simple to implement, but
   not needed for the first demo.

## Build status

- [x] META.toml
- [x] io_map.json  (split io_read/io_write model -- mirrors zarcade MoonCrestaBoard.kt)
- [x] ROMs extracted and CRCs verified against MAME
- [ ] MAME source extracted
- [x] Game discovery lists mooncrst
- [x] io_map dispatch generated for mooncrst (build/c/mooncrst_io_dispatch.c)
- [ ] Handlers.s with mooncrst-specific symbols
      (need: hal_input_in0/in1/dsw0 [reads]; hal_port_a000, hal_sound_ctrl,
       hal_port_b000, hal_sound_pitch [writes]. hal_port_a000 sub-decodes
       (addr&7): 0-2 gfx bank, 3 coin, 4-7 LFO. hal_port_b000 sub-decodes
       (addr&7): 0 nmi-enable, 4 stars, 6 flipX, 7 flipY.)
- [x] Builds: `make GAME=mooncrst all` -> build/mooncrst (52K hunk exe)
- [x] Handlers.s + hal_handlers.h have mooncrst stub symbols (links)
- [x] **Boots on A1200/AGA in Amiberry** -- shows hal_video_open's test
      pattern (red COLOR00 + 4-colour pattern block), no guru.
      Screenshot: docs/mooncrst-first-boot-a1200.png
- [x] **Z80 runs the real ROM** (host-validated, src/hal/machine.c):
      attract mode reached -- NMI enabled & firing, stars on, 11600 I/O
      writes/600 frames, and VRAM holds the attract score header
      (1UP/HI/2UP labels + "000000 000500 000000"). Proof harness:
      tests/host/mooncrst_host.c.
- [x] **Full gfx decode validated on host** -- char ROM + palette PROM
      + per-column colour + ROT90 render the correct attract screen
      (1ST/HI-SCORE/2ND header, scores, CREDIT 00). Reference image:
      docs/mooncrst-attract-host-reference.png. Confirmed: the
      Nichibutsu mcs_a..d char ROMs render the Gremlin program fine
      (no need for epr202/203).
- [x] amiga_main() runs machine_run_frame() each frame (hal_game_init /
      hal_game_frame hooks; default vs mooncrst chosen in the Makefile)
- [x] Host renderer ported to Amiga: src/hal/mc_video.c (5-bitplane AGA,
      32-colour palette from the PROM, ROT90 to upright). ROMs embedded
      (src/hal/mc_romdata.c). Builds: build/mooncrst (81K).
## Two Amiga-only bugs found via on-target diagnostics (host couldn't catch)

1. **Z80 endianness.** The vendored core defaulted to little-endian; the
   register-pair union is byte-order dependent, so on the big-endian 68k it
   ran garbage (worked on the x86 host). Fixed: z80emu.h auto-defines
   Z80_BIG_ENDIAN from __BYTE_ORDER__.
2. **Bitplane DMA never enabled.** mc_video.c wrote DMACON=0xE200, which sets
   only the master bit (bits 14/13 are read-only) -- BPLEN(0x100)/COPEN(0x80)
   were never set, so only COLOR00 displayed (black/solid). Fixed: DMACON=0x8380.
   The earlier test-pattern only worked by inheriting Kickstart's BPLEN.

Diagnosed with DIAG=1 builds (make GAME=mooncrst DIAG=1 all/adf): no display
takeover risk, drive COLOR00 from Z80 state (green=VRAM filling=>CPU alive) and
force a bitplane test block. Green-but-no-block pinned it to the DMA enable.
Also: 68000 has no hw multiply/divide -- keep geometry constant (no __mulsi3)
and avoid %/÷ in diag prints (no __udivsi3); print hex.

- [x] **RUNS on A1200/AGA from an ADF** (build/mooncrst.adf) -- Z80 emu ->
      VRAM -> tilemap -> PROM palette -> double-buffered 5-bitplane AGA
      display. Attract screen renders correctly.

## STATUS / handoff (resume here)

Working: ADF boots on A1200/AGA, runs the real Z80 ROM, renders the
tilemap (attract screen correct) at ~10-15fps. Build: `make GAME=mooncrst
all && make GAME=mooncrst adf` -> build/mooncrst.adf (run via
run/mooncrst-adf-a1200.uae). Host reference renderer + Z80 disasm toolchain
(tools/) also done.

Speed work so far: -m68020 build, inlined Z80 memory hot path, dropped
Z80_CATCH_DI/EI, blank-tile skip, and render-skip when the tilemap signature
is unchanged. Profiling showed cost split between Z80 emulation (red) and the
chip-RAM-bound renderer (green). C interpreter ceiling is ~10-15fps; full
60fps needs a faster/asm Z80 core (helps all Z80 games) or a native transcode
(tools/z80disasm.py -> z80268k.py -> link galaxian500 amiga.68k; gated on
full code-coverage of the ROM).

Remaining to COMPLETE Moon Cresta (next steps, in rough priority):
- [x] **Sprites** (ship/enemies): 8 hw sprites from objram 0x9840 rendered
      (mc_render.c render_sprites/draw_sprite16; extend_sprite uses gfxbank).
      Host-verified -- the "DOCKING TIME" attract shows the ship + module
      (docs/mooncrst-docking-sprites.png). Sprite RAM is inside the render-skip
      signature (0x9800-0x985f) so sprites trigger redraws.
- [x] **Input**: Amiga joystick (port 1, JOY1DAT + CIAA fire) read directly under
      the OS takeover -> machine_io.in0/in1 (mc_run.c poll_input). Controls:
      up=coin, down=start, left/right=move, fire=shoot. Coin/start are held
      (game debounces); switch to edge-pulse if it over-counts.
- [ ] **Bullets** (objram 0x9860): 8 shots (zarcade renderBullets). Extend the
      render-skip signature to 0x80 when added.
- [ ] **Starfield**: hardware LFSR background (zarcade renderStars / galaxian500).
- [ ] **Sound**: discrete Galaxian audio -> Paula (galaxian500 convert_sounds.py).
- [ ] **Speed**: faster Z80 core, or transcode for full speed.

### Display bugs found on-target (after the CPU/endian fix)
3. **Bitplane DMA off** -- DMACON=0xE200 set only the master bit; needs
   0x8380 (master|BPLEN|COPEN). Symptom: only COLOR00 showed.
4. **Single-buffer flicker** -- clear+redraw the displayed buffer every
   frame. Fixed: double buffer, swap on vblank (mc_present).
5. **OS fighting for the display** -- added LoadView(NULL)+Forbid()+Disable()
   to fully take over (no clean exit -> reboot to recover).
6. **Bitplane pointers ran off** (flashing green fill) -- BPLxPT auto-
   increment during DMA, so CPU-setting them once held for only one frame;
   the slow render left many frames fetching past the buffer. Fixed: the
   COPPER list re-seeds the 5 bitplane pointers every vblank (copper_point).

- [~] (historical) amiberry launch issue this session
      -- amiberry exits (~code 1) within 0.6s of launch, before Kickstart
      even boots, so our code never runs. Same config booted fine earlier
      this session (test pattern); the regression is amiberry's video init
      after repeated launch/kill cycles, NOT our binary. Retry:
          amiberry -f run/mooncrst-a1200.uae -s use_gui=no
      (the renderer is proven correct by the host reference image).

## Amiga render architecture (this pass)

- amiga.s calls `hal_game_init` once + `hal_game_frame` per loop iteration.
- `game_default.c` provides those for Pacland-style games (test pattern);
  `mc_run.c` provides them for mooncrst (boot Z80 + render each frame).
- `machine.c` is always linked; `in_impl`/`out_impl` come from hal_stubs.s
  on Amiga (host harness defines its own). No libc memset on Amiga -> the
  plane clear is a manual 32-bit loop.
- Display reuses video.c's known-good 320x256 timing but with 5 bitplanes
  (BPLCON0=0x5200) for the arcade's 32 colours; per-column colour attrs +
  pens index COLOR00..31.
- Renderer is plain C (per-pixel, ~50k px + 51200-byte clear per frame) ->
  a few fps on 020. Fine for first light; optimise (chunky->planar, or asm)
  later.

## Verified gfx decode (host reference renderer)

`tests/host/mooncrst_host.c` now also decodes graphics exactly like
zarcade GalaxianVideo, as the blueprint for the Amiga renderer:
- char ROM order: **mcs_b, mcs_d, mcs_a, mcs_c** (8 KB), planeSplit = 0x1000
- tile = 8x8 2bpp planar: pen = bit(p0) | bit(p1)<<1, bit = 7-x, pen 0 = transparent
- per-column attrs from objram: scrollY = obj[col*2], colorAttr = obj[col*2+1] & 7
- palette index = colorAttr*4 + pen; PROM (mmi6331.6l) resistor weights
  R:0x21/0x47/0x97 (bits 0-2), G:0x21/0x47/0x97 (bits 3-5), B:0x51/0xAE (bits 6-7)
- Moon Cresta tile bank (extend_tile): if gfxbank[2] && (code&0xC0)==0x80
  -> (code&0x3F) | (b0<<6) | (b1<<7) | 0x100
- ROT90 to upright 224x256: native[nx=fy][ny=239-fx]

## CPU is running -- how it's wired

`src/hal/machine.c` is the Galaxian machine layer (mirrors zarcade
MoonCrestaBoard): it traps the Z80's memory-mapped I/O (the core
otherwise hits a flat array), drives the vblank NMI, and holds the
hardware state (inputs, gfx bank, stars/flip). The vendored core's
data-access macros (src/cores/z80.c) were patched to call
machine_rd / machine_wr; opcode FETCH stays a direct array read.

Key facts confirmed:
- The **mooncrstg (Gremlin) program ROMs are UNENCRYPTED** -- they run
  raw (only the Nichibutsu `mooncrst`/mc* set needs decodeMoonCresta).
- Z80 `Z80_CATCH_DI/EI/HALT` make Z80Emulate stop early at those
  opcodes, so machine_run_frame loops until the frame's cycle budget
  (51200 = 3.072 MHz / 60) is spent, then fires the NMI.
- Inputs are active-high; idle = in0:0x00, in1:0x80, dsw:0x00.

Host test:
    gcc -O2 -Isrc/cores -Isrc/hal -o /tmp/mctest \
        tests/host/mooncrst_host.c src/cores/z80.c src/hal/machine.c
    /tmp/mctest games/mooncrst/roms 600

## Booting in Amiberry (A1200 / AGA)

Config: `run/mooncrst-a1200.uae` (A1200, 68020, AGA, Kickstart 3.1).
No ADF/LHA tooling needed yet -- a **UAE directory filesystem is
bootable**, so we mount `build/mooncrst_boot/` as DH0: and its
`S/Startup-Sequence` runs `SYS:mooncrst` straight from the boot shell.

    make GAME=mooncrst all
    rm -rf build/mooncrst_boot && mkdir -p build/mooncrst_boot/S
    cp build/mooncrst build/mooncrst_boot/
    printf 'SYS:mooncrst\n' > build/mooncrst_boot/S/Startup-Sequence
    amiberry -f run/mooncrst-a1200.uae -s use_gui=no

**Entry-point gotcha (fixed):** the exe is launched as a normal CLI
program, so `a6` is NOT ExecBase. amiga_main now loads ExecBase from
`4.w` (was `move.l a6,_SysBase`); trusting a6 caused error #80000004
(illegal instruction) when AllocMem jumped through a garbage _SysBase.

**Real ADF / LHA artifact (TODO):** booting via a directory FS is not a
literal .adf/.lha file. For a real ADF we need an image builder
(xdftool/amitools -- blocked, no pip; or a small pure-python OFS writer).
For a WHDLoad LHA we need a real slave header in slave.s (currently a
stub -- no _slv_ struct).

## I/O model decision (resolved)

Galaxian hardware overlaps read inputs and write controls at the same
address (0xa800 = IN1 read / sound write; 0xb000 = DSW read / NMI-enable
write). The old single-address io_map model could not represent this. We
now use **split `io_read` / `io_write` blocks** in io_map.json -- the
same model zarcade's `MoonCrestaBoard.read()/write()` uses. The dispatch
LUT is keyed on the **high address byte** (0xa0/0xa8/0xb0/0xb8 select the
four port groups); the low 3 bits are sub-decoded inside the handler.

The **Moon Cresta delta** vs base Galaxian: on the 0xa000 write port,
low bits 0-2 are the gfx tile-bank select (`writeGfxBank`); on base
Galaxian those bits are lamps/coin. This is the mcs_a/b/c/d "high-bit"
trick referenced in META.toml.

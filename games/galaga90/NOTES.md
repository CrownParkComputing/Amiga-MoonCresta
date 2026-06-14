Notes for Galaga '90 (Namco 1989):

- Same C140 sound chip as pacmania. Same 68000+6809E CPU split.
- 3 tilemap layers (1x 32x32 + 2x 16x16) is the unique part of the
  video HAL. Mappy / Baraduke era hardware had 2 layers, this is the
  3-layer revision.
- Multi-color sprites (8x8 sub-sprites packed into one 16x16 cell)
  require a different blitter pattern than pacland's 16x16x4bpp
  solid sprites. Plan: convert via the `tile_merger.py` tool from
  jotd's amiga68ktools first.
- The "stage intermissions" between levels have an extra fade-to-
  black step the C140 driver has to support. May be a separate
  pause flag in the audio CPU.

Layout (same convention as pacland):

  games/galaga90/
    META.toml
    io_map.json     TODO
    disasm/         TODO
    gfx/            TODO
    sfx/            TODO

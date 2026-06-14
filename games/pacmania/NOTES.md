Notes for Pac-Mania (Namco 1987):

- Main CPU is 68000 (NOT 6809 like pacland). The anchored-emulation HAL
  has to support a 68000 main + 6809 sound split, not a 3x 6809 like
  pacland. Plan to reuse MAME's `m68000` (Musashi) for the main CPU.
- Sound chip is C140, not C30. C140 voice format differs:
    C30:  8 channels, 8-bit wavetable + envelope
    C140: 8 channels, 4-bit/8-bit/16-bit PCM, multi-rate
  The HAL audio.s will need a C140 channel class; don't reuse the C30
  one from pacland.
- 128 sprite slots (vs 16 in pacland). Sprite DMA needs to be
  table-driven, not register-driven.
- Isometric tile math: the game computes screen-y from world-xy via
  a sin/cos table baked at build time. We can extract this from the
  MAME disasm's `pacmania_state::tilemap_draw` analog.

Layout (same convention as pacland):

  games/pacmania/
    META.toml
    io_map.json     TODO: extract from MAME namco/pacmania.cpp mem_map
    disasm/         TODO
    gfx/            TODO
    sfx/            TODO

Notes for the next contributor picking up pacland:

- Uses 60A1 4-bit MCU for DSW/coin handling. This is the part JotD's
  pipeline can't help with -- it must be hand-disassembled.
- All 3 main 6809 CPUs share the 6809to68k.py transcode tool.
- 4bpp 16x16 sprites packed 2-per-byte alignment in the rom bin.
- Tilemap chips are 5x*7B; register interface differs from Mappy-era
  chips, so the HAL will need its own register-set table.

Layout of the pacland game directory:

  games/pacland/
    META.toml       game metadata (rom path, video, audio, build flags)
    io_map.json     JSON I/O map (replaces per-game post_process.py)
    disasm/         (future) MAME disassembly dump
    gfx/            (future) converted graphics
    sfx/            (future) converted sound effects

/* src/hal/machine.h
 * ============================================================
 *  Moon Cresta (Galaxian-family) machine glue.
 * ============================================================
 *
 * The vendored Z80 core (src/cores/z80.c) accesses a flat 64 KB
 * array. Galaxian hardware is memory-mapped, with read inputs and
 * write controls overlapping at the same addresses, so we trap the
 * Z80's memory reads/writes here and route them exactly like
 * zarcade's MoonCrestaBoard.read()/write().
 *
 * This file is plain freestanding C: it builds with both the host
 * gcc (for tests/host/mooncrst_host.c) and m68k-amigaos-gcc.
 */
#ifndef NAMCO_AMIGA_MACHINE_H
#define NAMCO_AMIGA_MACHINE_H

#include "z80emu.h"   /* MY_LITTLE_Z80 */

/* Memory-access hooks the patched z80.c macros call. */
unsigned char machine_rd(MY_LITTLE_Z80 *z, unsigned int addr);
void          machine_wr(MY_LITTLE_Z80 *z, unsigned int addr, unsigned char val);

/* Lifecycle. prog points at the concatenated epr194..epr201 image
 * (up to 16 KB); it is copied into the Z80 ROM region 0x0000-0x3fff. */
void machine_init(MY_LITTLE_Z80 *z, const unsigned char *prog, unsigned int prog_len);

/* Run one video frame's worth of Z80 cycles, then deliver the
 * vblank NMI if the program has enabled it. */
void machine_run_frame(MY_LITTLE_Z80 *z);

/* Hardware state the renderer and the input layer touch. */
typedef struct {
    unsigned char in0, in1, dsw;     /* live input/DIP ports (active-high) */
    unsigned char nmi_enabled;
    unsigned char stars_enabled;
    unsigned char flip_x, flip_y;
    unsigned char gfx_bank;          /* 3-bit Moon Cresta tile bank (0xa000 b0-2) */
    /* ---- sound state (synthesised onto Paula by mc_audio.c) ---- */
    unsigned char snd_pitch;         /* 0xb800 pitch latch; 0xFF = background silent */
    unsigned char snd_vol;           /* VOL1|VOL2 (a806/a807) -> background loudness  */
    unsigned char snd_fire_lvl;      /* FIRE line level (for edge detect) */
    unsigned char snd_hit_lvl;       /* HIT  line level (for edge detect) */
    unsigned long snd_fire;          /* ++ on FIRE (a805) rising edge -> "pew"     */
    unsigned long snd_hit;           /* ++ on HIT  (a803) rising edge -> explosion  */
    unsigned long nmi_count;         /* diagnostics */
    unsigned long io_writes;         /* diagnostics: control-port writes seen */
} machine_io_t;

extern machine_io_t machine_io;

/* Galaxian VRAM / object RAM live in the Z80 array; these are the
 * offsets the renderer reads. */
#define MC_VRAM_BASE    0x9000u      /* 32x32 tile indices (0x400) */
#define MC_OBJRAM_BASE  0x9800u      /* attr/sprite/bullet (0x100)  */

#endif /* NAMCO_AMIGA_MACHINE_H */

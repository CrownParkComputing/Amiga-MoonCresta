/* src/hal/machine.c -- Moon Cresta (Galaxian) machine glue.
 * See machine.h. Routing mirrors zarcade MoonCrestaBoard.kt.
 */
#include "machine.h"

machine_io_t machine_io;

/* Z80 @ 3.072 MHz, ~60 Hz vblank -> cycles per frame. */
#define CYCLES_PER_FRAME  51200

/* ---- memory read: ROM/RAM/VRAM from the array, inputs from HW ---- */
unsigned char machine_rd(MY_LITTLE_Z80 *z, unsigned int a)
{
    a &= 0xffff;
    if (a < 0x4000)              return z->memory[a];          /* program ROM   */
    if (a >= 0x8000 && a < 0xa000) return z->memory[a];        /* RAM/VRAM/OBJ  */
    switch (a & 0xf800) {
        case 0xa000: return machine_io.in0;   /* IN0 */
        case 0xa800: return machine_io.in1;   /* IN1 */
        case 0xb000: return machine_io.dsw;   /* DSW */
        case 0xb800: return 0xff;             /* watchdog read */
    }
    return 0xff;                                               /* open bus */
}

/* Optional write log hook (host differential tester only; NULL on Amiga). */
void (*machine_wr_log)(MY_LITTLE_Z80 *z, unsigned int a, unsigned char v) = 0;

/* ---- memory write: RAM/VRAM to the array, control ports to HW ---- */
void machine_wr(MY_LITTLE_Z80 *z, unsigned int a, unsigned char v)
{
    a &= 0xffff;
    if (machine_wr_log) machine_wr_log(z, a, v);
    if (a < 0x4000) return;                                    /* ROM: ignore */
    if (a >= 0x8000 && a < 0xa000) { z->memory[a] = v; return; }

    machine_io.io_writes++;
    switch (a & 0xf800) {
        case 0xa000:                       /* gfx bank / coin / sound LFO */
            switch (a & 7) {
                case 0: case 1: case 2:    /* Moon Cresta tile-bank latches */
                    if (v & 1) machine_io.gfx_bank |=  (1u << (a & 3));
                    else       machine_io.gfx_bank &= ~(1u << (a & 3));
                    break;
                default: break;            /* 3=coin counter, 4-7=LFO freq */
            }
            return;
        case 0xa800: {                     /* sound enables + volume */
            int o = a & 7, bit = v & 1;
            if (o == 5) {                  /* FIRE: rising edge -> "pew" */
                if (bit && !machine_io.snd_fire_lvl) machine_io.snd_fire++;
                machine_io.snd_fire_lvl = (unsigned char)bit;
            } else if (o == 3) {           /* HIT: rising edge -> explosion */
                if (bit && !machine_io.snd_hit_lvl) machine_io.snd_hit++;
                machine_io.snd_hit_lvl = (unsigned char)bit;
            } else if (o == 6) {           /* VOL1 */
                if (bit) machine_io.snd_vol |= 1; else machine_io.snd_vol &= ~1;
            } else if (o == 7) {           /* VOL2 */
                if (bit) machine_io.snd_vol |= 2; else machine_io.snd_vol &= ~2;
            }
            return;
        }
        case 0xb000:                       /* nmi / stars / flip */
            switch (a & 7) {
                case 0: machine_io.nmi_enabled   = v & 1; break;
                case 4: machine_io.stars_enabled = v & 1; break;
                case 6: machine_io.flip_x        = v & 1; break;
                case 7: machine_io.flip_y        = v & 1; break;
                default: break;
            }
            return;
        case 0xb800:                       /* sound pitch latch -> background tone */
            machine_io.snd_pitch = v;
            return;
    }
}

/* Note: Galaxian uses no Z80 IN/OUT ports (all hardware is MMIO).
 * The required in_impl/out_impl symbols are provided by
 * src/hal/hal_stubs.s on the Amiga, and by the host harness. */

/* ---- lifecycle ---- */
void machine_init(MY_LITTLE_Z80 *z, const unsigned char *prog, unsigned int prog_len)
{
    unsigned int i;
    for (i = 0; i < (1u << 16); i++) z->memory[i] = 0;
    if (prog_len > 0x4000) prog_len = 0x4000;
    for (i = 0; i < prog_len; i++) z->memory[i] = prog[i];

    /* Active-high inputs; Moon Cresta default DIPs (from zarcade:
     * in1=0x80 coinage, in2=0x00). No coin / no buttons -> attract. */
    machine_io.in0 = 0x00;
    machine_io.in1 = 0x80;
    machine_io.dsw = 0x00;
    machine_io.nmi_enabled   = 0;
    machine_io.stars_enabled = 0;
    machine_io.flip_x = machine_io.flip_y = 0;
    machine_io.gfx_bank = 0;
    machine_io.snd_pitch = 0xFF;       /* background silent until the game writes pitch */
    machine_io.snd_vol = 0;
    machine_io.snd_fire_lvl = machine_io.snd_hit_lvl = 0;
    machine_io.snd_fire = machine_io.snd_hit = 0;
    machine_io.nmi_count = 0;
    machine_io.io_writes = 0;

    Z80Reset(&z->state);
}

void machine_run_frame(MY_LITTLE_Z80 *z)
{
    int remaining = CYCLES_PER_FRAME;

    /* Z80_CATCH_HALT/DI/EI make Z80Emulate stop early at those
     * instructions; loop until the frame's cycle budget is spent. */
    while (remaining > 0) {
        int ran = Z80Emulate(&z->state, remaining, z);
        if (ran <= 0) break;
        remaining -= ran;
        if (z->state.status == Z80_STATUS_HALT) break;  /* wait for NMI */
        /* DI/EI/RETI/RETN just resume on the next iteration. */
    }

    if (machine_io.nmi_enabled) {
        Z80NonMaskableInterrupt(&z->state, z);
        machine_io.nmi_count++;
    }
}

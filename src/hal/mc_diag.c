/* src/hal/mc_diag.c
 * ============================================================
 *  Bulletproof diagnostic build -- NO dos.library (that crashed
 *  the previous diag). It uses the same display setup as the real
 *  build (mc_video_open, which already produced a stable -- if
 *  black -- screen), then drives the BACKGROUND COLOUR from the
 *  Z80's state so we can read the result with our eyes:
 *
 *    whole screen GREEN  -> VRAM is filling => the Z80 IS running
 *                           on the 68k. (So the black-screen bug
 *                           is in the tile render / plane display.)
 *    whole screen RED    -> VRAM stays empty => the Z80 is NOT
 *                           running on the 68k (CPU/endian issue).
 *    a slow blue shimmer  -> the frame loop is alive (it cycles
 *                           every frame); if the screen is a solid
 *                           dead colour with no shimmer, the loop
 *                           itself isn't running.
 *    screen still BLACK   -> the display setup itself isn't working.
 *
 *  Built with `make GAME=mooncrst DIAG=1 all` (+ `... adf`).
 * ============================================================ */
#include "machine.h"

extern void mc_video_open(void);
extern const unsigned char mc_prog[];
extern const unsigned long mc_prog_len;
extern unsigned char *mc_planes;        /* the displayed bitplane buffer */

/* mc_render.c (linked, not called here) needs this. */
unsigned char mc_gfx_bank(void) { return machine_io.gfx_bank; }

#define COLORREG(n) (*(volatile unsigned short *)(0xdff180 + (n) * 2))

static MY_LITTLE_Z80 z80;

void hal_game_init(void)
{
    mc_video_open();                                   /* same display as the real build */

    /* Bitplane-display test: force a 64x64 WHITE block into plane 0
     * (pen 1), with COLOR01 forced white regardless of the PROM. If we
     * SEE a white block over the green background, the bitplanes display
     * their content AND colours work -> a black real screen then means
     * the tile render isn't drawing. If there's NO block (solid green),
     * the bitplane content isn't being displayed at all. */
    if (mc_planes) {
        for (int y = 96; y < 160; y++)
            for (int bx = 10; bx < 18; bx++)        /* x = 80..143 */
                mc_planes[y * 40 + bx] = 0xff;
    }
    COLORREG(1) = 0x0FFF;                            /* pen 1 = white */

    machine_init(&z80, mc_prog, (unsigned int)mc_prog_len);
}

static int fr = 0;
void hal_game_frame(void)
{
    machine_run_frame(&z80);
    fr++;

    int nz = 0;
    for (int a = 0x9000; a < 0x9400; a++) if (z80.memory[a]) nz++;

    /* Background colour = verdict. Green if the game has written a
     * meaningful amount of VRAM (Z80 alive), red otherwise. The low
     * blue nibble cycles every frame so a live loop shimmers. */
    unsigned short c = (nz > 50) ? 0x0F0 : 0xF00;
    c |= (unsigned short)(fr & 0x0F);
    COLORREG(0) = c;
}

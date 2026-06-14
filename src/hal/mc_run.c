/* src/hal/mc_run.c
 * ============================================================
 *  Moon Cresta game hooks. amiga_main calls hal_game_init()
 *  once, then hal_game_frame() every loop iteration. We run the
 *  Z80 for one frame and render the tilemap to the bitplanes.
 * ============================================================ */
#include "machine.h"

extern const unsigned char mc_prog[];
extern const unsigned long mc_prog_len;
extern void mc_video_open(void);
extern void mc_lockout_os(void);
extern void mc_audio_open(void);
extern void mc_audio_frame(void);
extern void mc_render(const unsigned char *mem);
extern void mc_brand(unsigned char *mem);
extern void mc_boot_draw(int count);
extern void mc_wait_frames(int n);
extern void mc_present(void);

/* One Z80 + its 64 KB address space (lives in BSS). */
static MY_LITTLE_Z80 z80;

/* Exposed to mc_video.c for the tile-bank decode. */
unsigned char mc_gfx_bank(void) { return machine_io.gfx_bank; }

/* ---- input: read the Amiga joystick (port 1) directly (OS is off) ----
 * Moon Cresta (active-high): in0 coin=0x01/left=0x04/right=0x08/fire=0x10,
 * in1 start1=0x01 (+ coinage dip 0x80). Joystick: up=coin, down=start,
 * left/right=move, fire button=fire. The game debounces coin/start. */
#define JOY1DAT  (*(volatile unsigned short *)0xdff00c)
#define CIAA_PRA (*(volatile unsigned char  *)0xbfe001)

static void poll_input(void)
{
    unsigned short j = JOY1DAT;
    int right = j & 0x0002;
    int left  = j & 0x0200;
    int down  = (j ^ (j >> 1)) & 0x0001;
    int up    = (j ^ (j >> 1)) & 0x0100;
    int fire  = !(CIAA_PRA & 0x80);          /* port-1 fire, active low */

    unsigned char in0 = 0x00;
    if (left)  in0 |= 0x04;
    if (right) in0 |= 0x08;
    if (fire)  in0 |= 0x10;                   /* fire = shoot only (no coin -> no credit pile-up) */
    if (up)    in0 |= 0x01;                   /* up = insert coin */
    machine_io.in0 = in0;

    unsigned char in1 = 0x80;                 /* coinage dip default */
    if (fire || down) in1 |= 0x01;            /* fire (or down) = start the game */
    machine_io.in1 = in1;
}

void hal_game_init(void)
{
    mc_video_open();
    mc_lockout_os();         /* disable OS ints so a window click can't corrupt our display */
    mc_audio_open();         /* set up Paula audio (DMA-driven, no interrupts) */

    /* title screen -- show until the player presses fire (or ~20s timeout) */
    mc_boot_draw(0);
    mc_present();
    { unsigned long t = 0;
      while ((CIAA_PRA & 0x80) && ++t < 1200) mc_wait_frames(1); }   /* wait for fire */

    machine_init(&z80, mc_prog, (unsigned int)mc_prog_len);
}

/* --- TEMP profiling: background colour shows where time goes ---
 * red = emulating Z80, green = rendering tiles, blue = waiting vblank.
 * Whichever colour dominates the screen is the bottleneck. */
#define MC_PROFILE 0
#define COLOR0(v) (*(volatile unsigned short *)0xdff180 = (unsigned short)(v))

void hal_game_frame(void)
{
#if MC_PROFILE
    COLOR0(0x0F00);              /* red: CPU emulation */
    machine_run_frame(&z80);
    COLOR0(0x00F0);              /* green: tile render */
    mc_render(z80.memory);
    COLOR0(0x000F);              /* blue: wait for vblank + swap */
    mc_present();
#else
    poll_input();            /* joystick -> machine_io.in0/in1 */
    machine_run_frame(&z80);
    mc_audio_frame();        /* drive Paula from the captured sound state */
    mc_brand(z80.memory);    /* swap the copyright tiles for our branding */
    mc_render(z80.memory);   /* draw into the back buffer */
    mc_present();            /* swap on vblank -> no flicker */
#endif
}

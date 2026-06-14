/* src/hal/mc_native.c
 * ============================================================
 *  Native (transcoded) Moon Cresta driver -- the 60fps path.
 *  Replaces the Z80 interpreter (mc_run.c) with JotD's z80268k
 *  68k transcode (games/mooncrst/transcode/mooncrst.68k).
 *
 *  Model (this first build, polled): run the transcoded entry/init
 *  once (it returns after the init->main-loop jp was patched to rts),
 *  then each frame call the transcoded NMI handler (l_0066) + render
 *  the shared 64 KB address space (mc_membase = a6) with the locked
 *  renderer. Proves native execution + speed on real hardware before
 *  wiring the full main-loop/interrupt model.
 * ============================================================ */

extern const unsigned char mc_prog[];
extern const unsigned long mc_prog_len;
extern void mc_video_open(void);
extern void mc_render(const unsigned char *mem);
extern void mc_present(void);

/* Transcode entry points (global labels, see tools/z80fixup.py).
 * gcc prefixes C symbols with '_' but GNU-as keeps them bare, so pin the
 * exact (bare) names with asm() for these C->asm references. */
extern void l_0000(void) asm("l_0000");   /* reset entry -> init (returns) */
extern void l_0066(void) asm("l_0066");   /* NMI handler (per-frame)       */

/* asm wrapper (mc_native_glue.s): a6=membase, cpu_init, then target. */
extern void mc_call(void *membase, void (*target)(void)) asm("mc_call");

/* The Z80 address space (a6). ROM at 0..0x3fff, RAM/VRAM/objram/IO above. */
unsigned char mc_membase[0x10000];

/* (de/hl/aprime/fprime register-spill cells are defined in
 * mc_native_glue.s with bare GNU-as names to match the transcode.) */

/* Renderer hook: static bank for this first build. */
unsigned char mc_gfx_bank(void) { return 0; }

/* TEMP staging diagnostic: background colour shows how far we get.
 * blue = display up; green = transcode init RETURNED (native ran!);
 * then cyan/magenta cycle each frame = frame loop + NMI alive.
 * Whatever colour it stalls on pinpoints the failure stage. */
#define COLOR0(v) (*(volatile unsigned short *)0xdff180 = (unsigned short)(v))

/* The async native runtime (mc_native_rt.s): runs init, takes over the
 * vblank interrupt, and drives the transcode foreground forever. Never
 * returns. */
extern void mc_run_native(void *membase) asm("mc_run_native");

void hal_game_init(void)
{
    unsigned int i;
    for (i = 0; i < 0x10000; i++) mc_membase[i] = 0;
    for (i = 0; i < mc_prog_len && i < 0x4000; i++) mc_membase[i] = mc_prog[i];
    mc_membase[0xb000] = 0x00;          /* idle DSW (flat-model best effort) */

    mc_video_open();                    /* locked renderer / display setup  */
    mc_run_native(mc_membase);          /* run init + vblank-driven frames (never returns) */
}

/* Unused in the async model -- the vblank ISR drives frames now. Kept as a
 * no-op so the amiga.s frame-loop fallback links. */
void hal_game_frame(void) { }

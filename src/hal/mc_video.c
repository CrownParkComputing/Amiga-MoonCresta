/* src/hal/mc_video.c
 * ============================================================
 *  Moon Cresta Amiga video: a 5-bitplane (32-colour) AGA screen,
 *  and a per-frame renderer that decodes the Galaxian tilemap into
 *  the bitplanes. This is the Amiga port of the host reference
 *  renderer in tests/host/mooncrst_host.c (same decode, planar
 *  output + ROT90 to upright).
 * ============================================================ */
#include <exec/exec.h>
#include <exec/memory.h>
#include <proto/exec.h>
#include <proto/graphics.h>
#include <graphics/gfxbase.h>
#include <stdint.h>

/* graphics.library, opened so we can take the display from the OS. */
struct GfxBase *GfxBase = 0;
static struct View *old_view = 0;

extern void *_SysBase;

/* Embedded palette PROM (src/hal/mc_romdata.c). */
extern const unsigned char mc_prom[32];

/* Render target published to the renderer (src/hal/mc_render.c). */
extern unsigned char *mc_planes;

#define CUSTOM   ((volatile uint16_t *)0xdff000)
#define R_DMACON   (0x096/2)
#define R_VPOSR    (0x004/2)
#define R_DIWSTRT  (0x08E/2)
#define R_DIWSTOP  (0x090/2)
#define R_DDFSTRT  (0x092/2)
#define R_DDFSTOP  (0x094/2)
#define R_BPLCON0  (0x100/2)
#define R_BPLCON1  (0x102/2)
#define R_BPLCON2  (0x104/2)
#define R_BPL1MOD  (0x108/2)
#define R_BPL2MOD  (0x10A/2)
#define R_BPL1PTH  (0x0E0/2)
#define R_COLOR00  (0x180/2)
#define R_COP1LCH  (0x080/2)
#define R_BLTCON0  (0x040/2)
#define R_BLTCON1  (0x042/2)
#define R_BLTDMOD  (0x066/2)
#define R_BLTDPTH  (0x054/2)
#define R_BLTSIZE  (0x058/2)
#define R_INTENA   (0x09A/2)
#define R_INTREQ   (0x09C/2)
#define DMACONR    ((volatile uint16_t *)0xdff002)

#define SCR_W      320
#define SCR_H      256
#define ROW_BYTES  (SCR_W / 8)            /* 40 */
#define PLANE_SZ   (ROW_BYTES * SCR_H)    /* 10240 */
#define NPLANES    5
#define COPPER_SZ  256

static uint8_t  *fb[2] = { 0, 0 };        /* double buffer: 5 planes each */
static uint16_t *copper = 0;
int mc_buffer_id = 1;                     /* which fb mc_planes points at (0/1) */

static int bitof(int v, int n) { return (v >> n) & 1; }
static int clamp255(int v) { return v > 255 ? 255 : v; }

/* Write the 5 bitplane pointers into the COPPER list, so the copper
 * re-seeds them every vblank. The hardware BPLxPT registers auto-
 * increment as the DMA fetches, so setting them once from the CPU only
 * holds for a single frame -- after that the display runs off the end
 * of the buffer (the flashing green garbage we saw). */
static void copper_point(uint8_t *buf)
{
    for (int p = 0; p < NPLANES; p++) {
        uint32_t a = (uint32_t)(buf + p * PLANE_SZ);
        copper[p*4 + 0] = (uint16_t)(0x00E0 + p * 4);   /* BPLxPTH register */
        copper[p*4 + 1] = (uint16_t)(a >> 16);
        copper[p*4 + 2] = (uint16_t)(0x00E2 + p * 4);   /* BPLxPTL register */
        copper[p*4 + 3] = (uint16_t)(a & 0xFFFF);
    }
    copper[NPLANES*4 + 0] = 0xFFFF;                     /* end of copper list */
    copper[NPLANES*4 + 1] = 0xFFFE;
}

/* WaitBlit: spin until the blitter is idle (BBUSY = DMACONR bit 14).
 * The dummy read works around the Agnus BBUSY-read-once-too-early bug. */
static void wait_blit(void)
{
    (void)*DMACONR;
    while (*DMACONR & 0x4000) ;
}

/* Kick the blitter to clear one 5-plane back buffer (51200 bytes =
 * 400 rows x 64 words) with zeros (D-channel only, minterm 0). Returns
 * immediately; the clear runs in the background (overlapping the Z80). */
static void kick_clear(uint8_t *buf)
{
    volatile uint16_t *c = CUSTOM;
    uint32_t a = (uint32_t)buf;
    wait_blit();
    c[R_BLTCON0] = 0x0100;                 /* use D, minterm 0 -> write 0 */
    c[R_BLTCON1] = 0x0000;
    c[R_BLTDMOD] = 0x0000;
    c[R_BLTDPTH] = (uint16_t)(a >> 16);
    c[R_BLTDPTH + 1] = (uint16_t)(a & 0xFFFF);
    c[R_BLTSIZE] = (uint16_t)((400 << 6) | 0);   /* h=400, w=64 words */
}

/* mc_render's clear hook: clear this back buffer with the blitter (instant
 * under the emulator; on real hw it offloads the 51200-byte clear from the
 * CPU's slow chip-RAM RMW). Called only when mc_render is actually redrawing
 * (after its skip check), so we never blank a buffer the skip wants to keep. */
extern void (*mc_clear_hook)(unsigned char *planes);
static void blit_clear(unsigned char *planes) { kick_clear(planes); wait_blit(); }

/* Full interrupt lockout for the interpreter frame loop. We poll the beam, so
 * we need NO interrupts -- and disabling them stops the OS vblank server from
 * reinstalling its own copper over ours (which corrupted the display when the
 * Amiberry window was clicked/focused, since the click wakes OS input/vblank
 * handling). The transcode runtime must NOT call this (it needs its own IRQ). */
void mc_lockout_os(void)
{
    volatile uint16_t *c = CUSTOM;
    c[R_INTENA] = 0x7FFF;          /* clear master + all interrupt enables */
    c[R_INTREQ] = 0x7FFF;          /* clear any already-pending requests   */
}

void mc_video_open(void)
{
    volatile uint16_t *c = CUSTOM;

    /* Take the display away from the OS so it stops reinstalling its
     * own copper list every vblank (which flashed the Workbench screen
     * / boot-console cursor over ours). */
    GfxBase = (struct GfxBase *)OpenLibrary((CONST_STRPTR)"graphics.library", 0);
    if (GfxBase) {
        old_view = GfxBase->ActiView;
        LoadView(0);
        WaitTOF();
        WaitTOF();
    }

    void *chunk = AllocMem(PLANE_SZ * NPLANES * 2 + COPPER_SZ, MEMF_CHIP | MEMF_CLEAR);
    if (!chunk) return;
    fb[0] = (uint8_t *)chunk;
    fb[1] = (uint8_t *)chunk + PLANE_SZ * NPLANES;
    copper = (uint16_t *)((uint8_t *)chunk + PLANE_SZ * NPLANES * 2);
    mc_planes = fb[1];             /* renderer draws into the back buffer */
    mc_clear_hook = blit_clear;   /* blitter clears the back buffer */

    /* Build the 32-entry palette from the PROM (Galaxian resistor
     * weights), down-converted to Amiga 12-bit RGB. */
    /* (Written to colour registers below.) */

    /* Copper list: seeds the 5 bitplane pointers every vblank. */
    copper_point(fb[0]);

    /* Wait for a safe vertical position before touching DMA regs. */
    { int s = 0; while (s++ < 100000) { if ((c[R_VPOSR] & 0x1FF) > 0x80) break; } }

    c[R_DMACON]  = 0x7FFF;                 /* all DMA off */
    c[R_DIWSTRT] = 0x2C81;          /* full image on screen (the main-area nudge is in mc_render) */
    c[R_DIWSTOP] = 0x2CC1;
    c[R_DDFSTRT] = 0x0038;
    c[R_DDFSTOP] = 0x00D0;
    c[R_BPLCON0] = 0x5200;                 /* 5 bitplanes */
    c[R_BPLCON1] = 0x0000;
    c[R_BPLCON2] = 0x0000;
    c[R_BPL1MOD] = 0x0000;
    c[R_BPL2MOD] = 0x0000;

    /* bitplane pointers are driven by the copper (copper_point above) */

    for (int i = 0; i < 32; i++) {
        int v = mc_prom[i];
        int r = bitof(v,0)*0x21 + bitof(v,1)*0x47 + bitof(v,2)*0x97;
        int g = bitof(v,3)*0x21 + bitof(v,4)*0x47 + bitof(v,5)*0x97;
        int b = bitof(v,6)*0x51 + bitof(v,7)*0xAE;
        uint16_t rgb12 = ((clamp255(r) >> 4) << 8)
                       | ((clamp255(g) >> 4) << 4)
                       |  (clamp255(b) >> 4);
        c[R_COLOR00 + i] = rgb12;
    }

    { uint32_t a = (uint32_t)copper;
      c[R_COP1LCH]     = (uint16_t)(a >> 16);
      c[R_COP1LCH + 1] = (uint16_t)(a & 0xFFFF); }

    /* Enable DMA: SET(0x8000) | DMAEN/master(0x0200) | BPLEN/bitplane
     * (0x0100) | COPEN/copper(0x0080). The old 0xE200 set only the
     * master bit (bits 14/13 are read-only BBUSY/BZERO), so bitplane
     * DMA was never actually turned on -> only COLOR00 showed. */
    c[R_DMACON] = 0x83C0;                  /* +BLTEN (0x40) for the clear blitter */

    /* Fully take over: stop multitasking and disable interrupts so the
     * OS's vblank handler can't reinstall its own copper list / Workbench
     * screen over ours (that was the flashing square). Our frame loop
     * polls the beam (waitvbl), so it needs no interrupts. The display
     * (copper + bitplane DMA) keeps running regardless of CPU ints.
     * NOTE: this does not get undone on exit -- reboot to recover. */
    Forbid();
    /* NOTE: we deliberately do NOT Disable() here. The native runtime
     * (mc_native_rt.s) installs its own level-3 (vblank) interrupt to
     * preempt the running transcode; Disable() would block it. setup_ints()
     * instead clears all OS interrupt enables (so the OS vblank server can't
     * reinstall its copper) and enables only VERTB to our handler. */
}

/* Re-point the copper + re-enable bitplane/copper DMA. Called once after
 * the native runtime takes over the interrupt system, so the OS can no
 * longer fight us for COP1LCH. */
void mc_reassert_display(void)
{
    volatile uint16_t *c = CUSTOM;
    if (!copper) return;
    uint32_t a = (uint32_t)copper;
    c[R_COP1LCH]     = (uint16_t)(a >> 16);
    c[R_COP1LCH + 1] = (uint16_t)(a & 0xFFFF);
    c[R_DMACON]      = 0x8380;
}

/* Present without waiting for the beam -- called FROM the vblank handler
 * (already in vertical blank, so the swap is safe now). Same as
 * mc_present() minus the waitvbl(). */
void mc_swap(void)
{
    if (!fb[0]) return;
    copper_point(mc_planes);                            /* show what we drew */
    mc_planes = (mc_planes == fb[0]) ? fb[1] : fb[0];   /* draw next elsewhere */
    mc_buffer_id = (mc_planes == fb[0]) ? 0 : 1;
}

/* Busy-wait until the beam is in the bottom vertical blank, so the
 * buffer swap doesn't tear the visible image. */
static void waitvbl(void)
{
    volatile uint32_t *vp = (volatile uint32_t *)0xdff004;  /* VPOSR|VHPOSR */
    unsigned long guard = 0;
    for (;;) {
        uint32_t r = *vp;
        uint32_t vpos = (((r >> 16) & 1) << 8) | ((r >> 8) & 0xff);
        if (vpos >= 300) break;
        /* Never hang: if the beam stalls (e.g. the Amiberry window is clicked
         * and the host briefly pauses the chipset), bail out so the game keeps
         * running and re-syncs when the display resumes -- instead of freezing
         * here forever. ~half a frame's worth of polls. */
        if (++guard > 500000UL) break;
    }
}

/* Wait n full frames (one beam cycle each). Used by the boot countdown. */
void mc_wait_frames(int n)
{
    volatile uint32_t *vp = (volatile uint32_t *)0xdff004;
    while (n-- > 0) {
        unsigned long g = 0;
        for (;;) { uint32_t r=*vp; uint32_t v=(((r>>16)&1)<<8)|((r>>8)&0xff);
                   if (v >= 300 || ++g > 600000UL) break; }   /* to bottom */
        g = 0;
        for (;;) { uint32_t r=*vp; uint32_t v=(((r>>16)&1)<<8)|((r>>8)&0xff);
                   if (v < 300 || ++g > 600000UL) break; }     /* back to top */
    }
}

/* Show the buffer the renderer just finished, and flip the render
 * target to the other buffer. Called once per frame after mc_render. */
void mc_present(void)
{
    if (!fb[0]) return;
    waitvbl();
    copper_point(mc_planes);                            /* display what we drew */
    mc_planes = (mc_planes == fb[0]) ? fb[1] : fb[0];   /* draw next elsewhere  */
    mc_buffer_id = (mc_planes == fb[0]) ? 0 : 1;
}

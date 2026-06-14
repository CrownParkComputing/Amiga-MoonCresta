/* tc_show.c -- minimal Twin Cobra static-image display for the Amiga.
 * Reuses the Moon Cresta 5-bitplane AGA path (mc_video.c) but just loads
 * one embedded attract frame (tc_img.c) instead of running a renderer.
 * Proves the host-emulation->Amiga-display pipeline end to end in an ADF.
 * hal_game_init() puts the picture up; hal_game_frame() idles.
 */
#include <exec/exec.h>
#include <exec/memory.h>
#include <proto/exec.h>
#include <proto/graphics.h>
#include <graphics/gfxbase.h>
#include <stdint.h>

struct GfxBase *GfxBase = 0;

extern const unsigned char  tc_planes[];   /* 5 planes x 40 x 256 */
extern const unsigned short tc_pal[32];

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
#define R_COLOR00  (0x180/2)
#define R_COP1LCH  (0x080/2)

#define SCR_W 320
#define SCR_H 256
#define ROW_BYTES (SCR_W/8)              /* 40 */
#define PLANE_SZ (ROW_BYTES*SCR_H)       /* 10240 */
#define NPLANES 5
#define COPPER_SZ 256

static uint8_t  *fb = 0;
static uint16_t *copper = 0;

static void copper_point(uint8_t *buf)
{
    for (int p = 0; p < NPLANES; p++) {
        uint32_t a = (uint32_t)(buf + p * PLANE_SZ);
        copper[p*4 + 0] = (uint16_t)(0x00E0 + p * 4);
        copper[p*4 + 1] = (uint16_t)(a >> 16);
        copper[p*4 + 2] = (uint16_t)(0x00E2 + p * 4);
        copper[p*4 + 3] = (uint16_t)(a & 0xFFFF);
    }
    copper[NPLANES*4 + 0] = 0xFFFF;
    copper[NPLANES*4 + 1] = 0xFFFE;
}

void hal_game_init(void)
{
    volatile uint16_t *c = CUSTOM;

    GfxBase = (struct GfxBase *)OpenLibrary((CONST_STRPTR)"graphics.library", 0);
    if (GfxBase) { LoadView(0); WaitTOF(); WaitTOF(); }

    void *chunk = AllocMem(PLANE_SZ * NPLANES + COPPER_SZ, MEMF_CHIP | MEMF_CLEAR);
    if (!chunk) return;
    fb = (uint8_t *)chunk;
    copper = (uint16_t *)((uint8_t *)chunk + PLANE_SZ * NPLANES);

    /* load the embedded attract frame into chip RAM */
    for (int i = 0; i < PLANE_SZ * NPLANES; i++) fb[i] = tc_planes[i];

    copper_point(fb);

    { int s = 0; while (s++ < 100000) { if ((c[R_VPOSR] & 0x1FF) > 0x80) break; } }

    c[R_DMACON]  = 0x7FFF;
    c[R_DIWSTRT] = 0x2C81;
    c[R_DIWSTOP] = 0x2CC1;
    c[R_DDFSTRT] = 0x0038;
    c[R_DDFSTOP] = 0x00D0;
    c[R_BPLCON0] = 0x5200;                 /* 5 bitplanes */
    c[R_BPLCON1] = 0x0000;
    c[R_BPLCON2] = 0x0000;
    c[R_BPL1MOD] = 0x0000;
    c[R_BPL2MOD] = 0x0000;

    for (int i = 0; i < 32; i++) c[R_COLOR00 + i] = tc_pal[i];

    { uint32_t a = (uint32_t)copper;
      c[R_COP1LCH]     = (uint16_t)(a >> 16);
      c[R_COP1LCH + 1] = (uint16_t)(a & 0xFFFF); }

    c[R_DMACON] = 0x8380;                   /* master|bitplane|copper */
    Forbid();
}

void hal_game_frame(void)
{
    volatile uint32_t *vp = (volatile uint32_t *)0xdff004;
    for (;;) {
        uint32_t r = *vp;
        uint32_t vpos = (((r >> 16) & 1) << 8) | ((r >> 8) & 0xff);
        if (vpos >= 300) break;
    }
}

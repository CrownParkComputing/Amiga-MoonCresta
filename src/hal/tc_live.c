/* tc_live.c -- LIVE Twin Cobra on the Amiga. Drives the C emulation
 * (machine_twincobr.c on Musashi + the TMS320C10) and the software
 * renderer (tc_render.c), composites to a 5-bitplane AGA screen with a
 * per-frame 32-colour quantise of the arcade palette. hal_game_init()
 * sets it up; hal_game_frame() runs one frame and shows it.
 *
 * Landscape (320x240 in a 320x256 screen) -- the arcade is vertical, so
 * it reads sideways, same as the static-image demo. Slow (interpreted
 * 68000 + software composite) -- wants an 030+/060.
 */
#include <exec/exec.h>
#include <exec/memory.h>
#include <proto/exec.h>
#include <proto/graphics.h>
#include <graphics/gfxbase.h>
#include <stdint.h>

struct GfxBase *GfxBase = 0;

/* ---- emulation + renderer (pure C, no Amiga deps) ---- */
extern void tc_init(const uint8_t*, int, const uint16_t*, int);
extern void tc_run_frame(void);
extern void tc_render_setgfx(const uint8_t*, const uint8_t*, const uint8_t*, const uint8_t*);
extern void tc_render_frame(uint16_t*, const uint16_t*, const uint16_t*, const uint16_t*,
                            const uint16_t*, const uint8_t*, const uint8_t*);
extern uint8_t  *tc_mem, *tc_latch;
extern int tc_intenable(void);
extern uint16_t *tc_txvram, *tc_bgvram, *tc_fgvram, tc_scroll[6];

/* ---- embedded ROMs (tc_romdata.c) ---- */
extern const uint8_t tc_prog[], tc_dsp_b[], tc_chars[], tc_bg[], tc_fg[], tc_spr[];

#define CUSTOM ((volatile uint16_t *)0xdff000)
#define R_DMACON (0x096/2)
#define R_VPOSR (0x004/2)
#define R_DIWSTRT (0x08E/2)
#define R_DIWSTOP (0x090/2)
#define R_DDFSTRT (0x092/2)
#define R_DDFSTOP (0x094/2)
#define R_BPLCON0 (0x100/2)
#define R_BPLCON1 (0x102/2)
#define R_BPL1MOD (0x108/2)
#define R_BPL2MOD (0x10A/2)
#define R_COLOR00 (0x180/2)
#define R_COP1LCH (0x080/2)

#define SCR_W 320
#define SCR_H 256
#define IMG_H 240
#define ROW_BYTES 40
#define PLANE_SZ (ROW_BYTES*SCR_H)
#define NP 5

static uint8_t  *fb2[2] = { 0, 0 };     /* double buffer */
static int       drawb = 0;             /* which buffer we draw into */
static uint16_t *copper = 0;
static uint16_t dsp_words[2048];
static uint16_t chunky[SCR_W*IMG_H];
static int16_t  amiga_of[2048];        /* arcade-index -> amiga colour (per frame) */
static uint16_t pal12[32];             /* current amiga palette (RGB12) */

static void copper_point(uint8_t *buf){
    for (int p=0;p<NP;p++){ uint32_t a=(uint32_t)(buf+p*PLANE_SZ);
        copper[p*4+0]=(uint16_t)(0x00E0+p*4); copper[p*4+1]=(uint16_t)(a>>16);
        copper[p*4+2]=(uint16_t)(0x00E2+p*4); copper[p*4+3]=(uint16_t)(a&0xFFFF); }
    copper[NP*4+0]=0xFFFF; copper[NP*4+1]=0xFFFE;
}

void hal_game_init(void){
    volatile uint16_t *c=CUSTOM;
    /* --- display FIRST so we get immediate visual feedback --- */
    GfxBase=(struct GfxBase*)OpenLibrary((CONST_STRPTR)"graphics.library",0);
    if (GfxBase){ LoadView(0); WaitTOF(); WaitTOF(); }
    void *chunk=AllocMem(PLANE_SZ*NP*2+256, MEMF_CHIP|MEMF_CLEAR);
    if (!chunk){ c[R_DMACON]=0x0080; c[R_COLOR00]=0x0F00; for(;;); } /* RED+halt = AllocMem failed */
    fb2[0]=(uint8_t*)chunk; fb2[1]=(uint8_t*)chunk+PLANE_SZ*NP;
    copper=(uint16_t*)((uint8_t*)chunk+PLANE_SZ*NP*2);
    copper_point(fb2[0]);
    { int s=0; while (s++<100000){ if ((c[R_VPOSR]&0x1FF)>0x80) break; } }
    c[R_DMACON]=0x7FFF;
    c[R_DIWSTRT]=0x2C81; c[R_DIWSTOP]=0x2CC1;
    c[R_DDFSTRT]=0x0038; c[R_DDFSTOP]=0x00D0;
    c[R_BPLCON0]=0x5200; c[R_BPL1MOD]=0; c[R_BPL2MOD]=0;
    { uint32_t a=(uint32_t)copper; c[R_COP1LCH]=(uint16_t)(a>>16); c[R_COP1LCH+1]=(uint16_t)(a&0xFFFF); }
    c[R_DMACON]=0x8380;
    c[R_COLOR00]=0x00FF;                 /* CYAN = display up */
    /* --- now the (slower) emulation init --- */
    for (int i=0;i<2048;i++) dsp_words[i]=(tc_dsp_b[i*2]<<8)|tc_dsp_b[i*2+1];
    tc_init(tc_prog, 0x30000, dsp_words, 2048);
    tc_render_setgfx(tc_chars, tc_bg, tc_fg, tc_spr);
    c[R_COLOR00]=0x00F0;                 /* GREEN = emulation init done */
    Forbid();

    /* FAST-FORWARD through the (black, slow) boot POST WITHOUT rendering --
     * just run the emulation until the game reaches its vblank-IRQ main loop
     * (tc_intenable()). Pulse the border so it's visibly working. */
    { int f=0; while (f++ < 1200 && !tc_intenable()){ c[R_COLOR00]=(uint16_t)((f<<4)&0x0FFF); tc_run_frame(); } }
    c[R_COLOR00]=0x0F0F;                 /* MAGENTA = POST done, starting to render the game */
}

static uint16_t rgb12_of(int idx){
    int w=(tc_mem[0x50000+idx*2]<<8)|tc_mem[0x50000+idx*2+1];   /* xBGR555 */
    int r=(w&0x1f), g=(w>>5)&0x1f, b=(w>>10)&0x1f;
    return ((r>>1)<<8)|((g>>1)<<4)|(b>>1);
}
static int nearest12(uint16_t v, int n){
    int br=0,bd=1<<20, vr=(v>>8)&0xf, vg=(v>>4)&0xf, vb=v&0xf;
    for (int i=0;i<n;i++){ int p=pal12[i];
        int dr=((p>>8)&0xf)-vr, dg=((p>>4)&0xf)-vg, db=(p&0xf)-vb;
        int d=dr*dr+dg*dg+db*db; if (d<bd){bd=d;br=i;} }
    return br;
}

void hal_game_frame(void){
    volatile uint16_t *c=CUSTOM;
    tc_run_frame();
    tc_render_frame(chunky, tc_txvram, tc_bgvram, tc_fgvram, tc_scroll, tc_latch, tc_mem+0x40000);

    /* Build the 5 bitplanes, ROTATED to upright (the arcade is vertical/ROT270)
     * and scaled to fit: the 240x320 rotated image -> 240 wide (centred in 320)
     * x 256 tall (320 scaled to 256). chunky is 320x240 unrotated; rotated
     * pixel (rx,ry) = chunky[rx*320 + (319-ry)].  Per-frame 32-colour quantise. */
    uint8_t *fb = fb2[drawb];            /* draw into the back buffer */
    for (int i=0;i<2048;i++) amiga_of[i]=-1;
    int nused=0;
    for (int i=0;i<PLANE_SZ*NP;i++) fb[i]=0;
    for (int fy=0; fy<SCR_H; fy++){
        uint8_t *row=fb+fy*ROW_BYTES;
        int ry=(fy*320)>>8;               /* 0..319, scaled */
        int sp=319-ry;                    /* chunky source index for rx=0 */
        for (int fx=40; fx<280; fx++){    /* 240 wide, centred in 320 */
            int idx=chunky[sp]; sp+=320;  /* next rx = +320 (no multiply) */
            int a=amiga_of[idx];
            if (a<0){ uint16_t v=rgb12_of(idx);
                if (nused<32){ a=nused++; pal12[a]=v; } else a=nearest12(v,32);
                amiga_of[idx]=a; }
            if (a){ int byte=(fx>>3), bit=0x80>>(fx&7);
                if (a&1) row[byte]|=bit;
                if (a&2) row[byte+PLANE_SZ]|=bit;
                if (a&4) row[byte+PLANE_SZ*2]|=bit;
                if (a&8) row[byte+PLANE_SZ*3]|=bit;
                if (a&16) row[byte+PLANE_SZ*4]|=bit; }
        }
    }
    for (int i=0;i<nused;i++) c[R_COLOR00+i]=pal12[i];

    /* wait for vblank, then show the buffer we just finished and flip */
    { volatile uint32_t *vp=(volatile uint32_t*)0xdff004;
      for(;;){ uint32_t r=*vp; uint32_t vpos=(((r>>16)&1)<<8)|((r>>8)&0xff); if(vpos>=300) break; } }
    copper_point(fb2[drawb]);            /* display the completed buffer */
    drawb ^= 1;                          /* draw the next frame in the other one */
}

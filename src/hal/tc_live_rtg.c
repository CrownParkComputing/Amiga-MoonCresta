/* tc_live_rtg.c -- LIVE Twin Cobra, RTG/chunky display path.
 * Opens an 8-bit screen and blits the rendered frame with WriteChunkyPixels
 * (fast direct copy on an RTG board, software c2p on AGA). The arcade frame
 * is quantised to <=256 colours per frame -- near-lossless (a TC frame uses
 * ~100-200 distinct colours). Keeps the OS up (RTG needs it); run from HD.
 */
#include <exec/exec.h>
#include <proto/exec.h>
#include <proto/intuition.h>
#include <proto/graphics.h>
#include <intuition/screens.h>
#include <graphics/gfxbase.h>
#include <stdint.h>

struct IntuitionBase *IntuitionBase = 0;
struct GfxBase *GfxBase = 0;
static struct Screen *scr = 0;

extern void tc_init(const uint8_t*, int, const uint16_t*, int);
extern void tc_run_frame(void);
extern void tc_render_setgfx(const uint8_t*, const uint8_t*, const uint8_t*, const uint8_t*);
extern void tc_render_frame(uint16_t*, const uint16_t*, const uint16_t*, const uint16_t*,
                            const uint16_t*, const uint8_t*, const uint8_t*);
extern uint8_t  *tc_mem, *tc_latch;
extern uint16_t *tc_txvram, *tc_bgvram, *tc_fgvram, tc_scroll[6];
extern const uint8_t tc_prog[], tc_dsp_b[], tc_chars[], tc_bg[], tc_fg[], tc_spr[];

#define W 320
#define H 240

static uint16_t dsp_words[2048];
static uint16_t chunky[W*H];        /* arcade palette indices */
static uint8_t  chunky8[W*H];       /* amiga 0..255 */
static int16_t  amiga_of[2048];
static uint32_t loadrgb[1 + 256*3 + 1];   /* LoadRGB32 table */
static uint8_t  pr[256], pg[256], pb[256];/* chosen amiga palette (8-bit comps) */

void hal_game_init(void){
    for (int i=0;i<2048;i++) dsp_words[i]=(tc_dsp_b[i*2]<<8)|tc_dsp_b[i*2+1];
    tc_init(tc_prog, 0x30000, dsp_words, 2048);
    tc_render_setgfx(tc_chars, tc_bg, tc_fg, tc_spr);

    IntuitionBase=(struct IntuitionBase*)OpenLibrary((CONST_STRPTR)"intuition.library",39);
    GfxBase=(struct GfxBase*)OpenLibrary((CONST_STRPTR)"graphics.library",40);
    scr=OpenScreenTags(0, SA_Width,W, SA_Height,256, SA_Depth,8,
                       SA_Quiet,1, SA_Type,CUSTOMSCREEN, SA_ShowTitle,0, TAG_END);
}

static int nearest(int r,int g,int b,int n){
    int br=0,bd=1<<28;
    for (int i=0;i<n;i++){ int dr=pr[i]-r,dg=pg[i]-g,db=pb[i]-b; int d=dr*dr+dg*dg+db*db;
        if (d<bd){bd=d;br=i;} }
    return br;
}

void hal_game_frame(void){
    tc_run_frame();
    tc_render_frame(chunky, tc_txvram, tc_bgvram, tc_fgvram, tc_scroll, tc_latch, tc_mem+0x40000);
    if (!scr) return;

    for (int i=0;i<2048;i++) amiga_of[i]=-1;
    int nused=0;
    for (int p=0;p<W*H;p++){
        int idx=chunky[p]; int a=amiga_of[idx];
        if (a<0){
            int w=(tc_mem[0x50000+idx*2]<<8)|tc_mem[0x50000+idx*2+1];   /* xBGR555 */
            int r=((w&0x1f))<<3, g=(((w>>5)&0x1f))<<3, b=(((w>>10)&0x1f))<<3;
            if (nused<256){ a=nused; pr[a]=r; pg[a]=g; pb[a]=b; nused++; }
            else a=nearest(r,g,b,256);
            amiga_of[idx]=a;
        }
        chunky8[p]=(uint8_t)a;
    }
    /* LoadRGB32 table: (count<<16)|first, then r,g,b as 32-bit (comp<<24) */
    loadrgb[0]=((uint32_t)nused<<16)|0;
    for (int i=0;i<nused;i++){
        loadrgb[1+i*3+0]=((uint32_t)pr[i])*0x01010101u;
        loadrgb[1+i*3+1]=((uint32_t)pg[i])*0x01010101u;
        loadrgb[1+i*3+2]=((uint32_t)pb[i])*0x01010101u;
    }
    loadrgb[1+nused*3]=0;
    LoadRGB32(&scr->ViewPort, loadrgb);
    WriteChunkyPixels(&scr->RastPort, 0,0, W-1,H-1, chunky8, W);
    WaitTOF();
}

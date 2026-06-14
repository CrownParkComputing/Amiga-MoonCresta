/* machine_twincobr.c -- Twin Cobra machine model for the Amiga port.
 * Drives Musashi (68000) + the TMS320C10 DSP + the MMIO/DSP/Z80/IRQ4
 * model. Direct C port of the validated tests/host/twincobr_host.py.
 * Musashi calls m68k_read/write_memory_*; we decode the arcade map here.
 *
 * The 68K address space (byte-addressed, big-endian):
 *   0x00000-0x2ffff ROM           0x30000-0x33fff work RAM (= DSP shared)
 *   0x40000-0x40fff sprite RAM    0x50000-0x50dff palette RAM
 *   0x60001/3 CRTC  0x70000-0x76005 scroll/offset  0x78000-0x7800f in/latch
 *   0x7a000-0x7afff Z80 shared     0x7e000/2/4 tx/bg/fg VRAM data ports
 */
#include <stdint.h>
#include "m68k.h"
#include "tms320c10.h"

#define MEMSZ 0x80000
static uint8_t mem[MEMSZ];               /* ROM + RAM-backed regions */

/* video / control state (mirrors the Python harness) */
static uint8_t  latch[8];
static int      intenable;
static uint16_t txvram[0x800], bgvram[0x2000], fgvram[0x1000];
static int      txoffs, bgoffs, fgoffs;
uint16_t        tc_scroll[6];            /* txx,txy,bgx,bgy,fgx,fgy (read by renderer) */
static uint32_t sysr;                    /* polled-vblank toggle */

/* expose VRAM to the renderer */
uint16_t *tc_txvram = txvram, *tc_bgvram = bgvram, *tc_fgvram = fgvram;
uint8_t  *tc_mem = mem;                  /* sprite RAM @0x40000, palette @0x50000 */
uint8_t  *tc_latch = latch;              /* mainlatch bits (bg/fg bank for renderer) */
int tc_irq_count = 0, tc_dsp_count = 0;  /* diagnostics */
long tc_cycles = 0;

/* ---- TMS320C10 DSP + twincobr_m.cpp host bridge ---- */
static tms320c10 dsp;
static uint32_t  dsp_seg, dsp_addr;
static int       dsp_done;

static uint16_t mem_r16(uint32_t a){ return (mem[a]<<8)|mem[a+1]; }
static void     mem_w16(uint32_t a, uint16_t v){ mem[a]=v>>8; mem[a+1]=v; }

static uint16_t dsp_in(void *c, int port){
    (void)c;
    if (port==1) return mem_r16((dsp_seg+dsp_addr) & (MEMSZ-1));
    return 0;
}
static void dsp_out(void *c, int port, uint16_t v){
    (void)c;
    if (port==0){ dsp_seg=(v&0xe000)<<3; dsp_addr=(v&0x1fff)<<1; }
    else if (port==1){
        if (dsp_seg==0x30000||dsp_seg==0x40000||dsp_seg==0x50000)
            mem_w16((dsp_seg+dsp_addr)&(MEMSZ-1), v);
        if (dsp_seg==0x30000 && dsp_addr<3 && v==0) dsp_done=1;
    }
}
static int dsp_bio(void *c){ (void)c; return 0; }

static void run_dsp(void){
    int i;
    dsp_done=0; dsp.int_pending=1; tc_dsp_count++;
    for (i=0;i<200000;i++){ tms_step(&dsp); if (dsp_done) return; }
}

/* ---- SYS port vblank bit (polled during boot) ---- */
static uint16_t sys_word(void){
    uint16_t v=0xffff; sysr++;
    if ((sysr>>9)&1) v &= ~0x0080;
    return v;
}

/* ---- Musashi memory callbacks ---- */
unsigned int m68k_read_memory_8(unsigned int a){
    a &= 0xffffff;
    if (a < 0x60000) return mem[a];
    if (a==0x7a001) return 0xff;                       /* Z80 ack */
    if (a>=0x7a000 && a<0x7b000) return mem[a];        /* Z80 shared RAM (mode/counter live here!) */
    if ((a&~1)==0x78008){ uint16_t w=sys_word(); return (a&1)?(w&0xff):(w>>8); }
    if (a>=0x78000 && a<0x7800a) return 0xff;          /* idle inputs/DSW */
    return 0xff;
}
unsigned int m68k_read_memory_16(unsigned int a){
    a &= 0xffffff;
    if (a < 0x60000) return mem_r16(a);
    if (a==0x78008) return sys_word();
    if (a==0x7e000) return txvram[txoffs];
    if (a==0x7e002) return bgvram[bgoffs + latch[4]*0x1000];
    if (a==0x7e004) return fgvram[fgoffs];
    if (a>=0x78000 && a<0x7800a) return 0xffff;
    if (a>=0x7a000 && a<0x7b000){
        uint8_t hi=mem[a]; uint8_t lo=((a+1-0x7a000)==1)?0xff:mem[a+1];
        return (hi<<8)|lo;
    }
    return 0xffff;
}
unsigned int m68k_read_memory_32(unsigned int a){
    return (m68k_read_memory_16(a)<<16)|m68k_read_memory_16(a+2);
}
/* the ONLY RAM-backed regions (the rest of 0x30000-0x5ffff is unmapped -- the
 * boot RAM-sizing test marches until readback fails, so phantom RAM hangs it) */
static int is_ram(unsigned int a){
    return (a>=0x30000 && a<0x34000)    /* work RAM (= DSP shared) */
        || (a>=0x40000 && a<0x41000)    /* sprite RAM */
        || (a>=0x50000 && a<0x50e00)    /* palette RAM */
        || (a>=0x7a000 && a<0x7b000);   /* Z80 shared */
}
void m68k_write_memory_8(unsigned int a, unsigned int v){
    a &= 0xffffff; v &= 0xff;
    if (is_ram(a)){ mem[a]=v; return; }
    /* (8-bit writes to latches/regs are rare on this 16-bit bus) */
}
void m68k_write_memory_16(unsigned int a, unsigned int v){
    a &= 0xffffff; v &= 0xffff;
    if (is_ram(a)){ mem_w16(a,v); return; }
    switch (a){
        case 0x70000: tc_scroll[0]=v; return;
        case 0x70002: tc_scroll[1]=v; return;
        case 0x70004: txoffs=v%0x800; return;
        case 0x72000: tc_scroll[2]=v; return;
        case 0x72002: tc_scroll[3]=v; return;
        case 0x72004: bgoffs=v%0x1000; return;
        case 0x74000: tc_scroll[4]=v; return;
        case 0x74002: tc_scroll[5]=v; return;
        case 0x74004: fgoffs=v%0x1000; return;
        case 0x7e000: txvram[txoffs]=v; return;
        case 0x7e002: bgvram[bgoffs+latch[4]*0x1000]=v; return;
        case 0x7e004: fgvram[fgoffs]=v; return;
        case 0x7800c: {
            int b=v&0xff, idx=(b>>1)&7, data=b&1;
            latch[idx]=data;
            if (idx==2){ intenable=data; if(!data) m68k_set_irq(0); } /* int_enable_w clears pending */
            if (idx==6 && data) run_dsp();
            return;
        }
        default: return;   /* CRTC / other regs: ignore */
    }
}
void m68k_write_memory_32(unsigned int a, unsigned int v){
    m68k_write_memory_16(a, v>>16); m68k_write_memory_16(a+2, v&0xffff);
}

/* single-pulse IRQ: clear the line the instant the CPU acknowledges it, so the
 * vblank handler runs exactly ONCE per assertion (matches the harness's manual
 * one-shot injection; holding the line let it re-fire and broke attract). */
static int tc_int_ack(int level){ if (level==4){ m68k_set_irq(0); tc_irq_count++; } return M68K_INT_ACK_AUTOVECTOR; }

/* ---- lifecycle ---- */
void tc_init(const uint8_t *rom, int rom_len, const uint16_t *dsprog, int dsp_len){
    int i;
    for (i=0;i<MEMSZ;i++) mem[i]=0;
    for (i=0;i<rom_len && i<0x30000;i++) mem[i]=rom[i];
    for (i=0;i<8;i++) latch[i]=0;
    intenable=0; txoffs=bgoffs=fgoffs=0; sysr=0;
    for (i=0;i<0x800;i++) txvram[i]=0;
    for (i=0;i<0x2000;i++) bgvram[i]=0;
    for (i=0;i<0x1000;i++) fgvram[i]=0;
    for (i=0;i<6;i++) tc_scroll[i]=0;
    tms_init(&dsp, dsprog, dsp_len, dsp_in, dsp_out, dsp_bio, &dsp);
    m68k_set_cpu_type(M68K_CPU_TYPE_68000);
    m68k_init();
    m68k_set_int_ack_callback(tc_int_ack);
    m68k_pulse_reset();
}

/* run one ~60Hz frame: assert the vblank IRQ4 (single-pulse via int-ack), then
 * execute a frame of cycles. */
void tc_run_frame(void){
    if (intenable) m68k_set_irq(4);
    tc_cycles += m68k_execute(116000);   /* 7MHz / 60 */
}

int tc_intenable(void){ return intenable; }

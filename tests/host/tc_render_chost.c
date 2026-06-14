/* tc_render_chost.c -- run the C machine model + the C renderer, render one
 * frame, write a PNG. Validates tc_render.c against tools/twincobr_render.py.
 *   gcc -O2 -I src/cores -I src/cores/m68k tests/host/tc_render_chost.c \
 *     src/hal/machine_twincobr.c src/hal/tc_render.c src/cores/tms320c10.c \
 *     src/cores/m68k/m68kcpu.c src/cores/m68k/m68kops.c \
 *     src/cores/m68k/softfloat/softfloat.c -lm -o /tmp/tcr
 *   /tmp/tcr games/twincobr 300 /tmp/tc_c_render.ppm
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

void tc_init(const uint8_t*, int, const uint16_t*, int);
void tc_run_frame(void);
unsigned int m68k_get_reg(void*, int);
extern int tc_irq_count, tc_dsp_count; int tc_intenable(void); extern long tc_cycles;
#define M68K_REG_PC 16
#define M68K_REG_SR 17
void tc_render_setgfx(const uint8_t*, const uint8_t*, const uint8_t*, const uint8_t*);
void tc_render_frame(uint16_t*, const uint16_t*, const uint16_t*, const uint16_t*,
                     const uint16_t*, const uint8_t*, const uint8_t*);
extern uint8_t  *tc_mem, *tc_latch;
extern uint16_t *tc_txvram, *tc_bgvram, *tc_fgvram, tc_scroll[6];

static uint8_t *slurp(const char*p,int*n){FILE*f=fopen(p,"rb");if(!f){perror(p);exit(1);}
    fseek(f,0,SEEK_END);*n=ftell(f);fseek(f,0,SEEK_SET);uint8_t*b=malloc(*n);
    if(fread(b,1,*n,f)!=(size_t)*n){};fclose(f);return b;}
static uint8_t *cat(const char*dir,const char**names,int cnt){
    int total=0,n; uint8_t*tmp[8];
    for(int i=0;i<cnt;i++){char p[256];sprintf(p,"%s/%s",dir,names[i]);tmp[i]=slurp(p,&n);total+=n;}
    uint8_t*out=malloc(total);int o=0;
    for(int i=0;i<cnt;i++){char p[256];sprintf(p,"%s/%s",dir,names[i]);int m;
        uint8_t*b=slurp(p,&m);for(int j=0;j<m;j++)out[o++]=b[j];free(b);free(tmp[i]);}
    return out;
}


/* trace: catch memory-test failure branches and log the failing address */
void m68k_set_instr_hook_callback(void(*)(unsigned int));
static unsigned maxpc2=0; static int dumped=0;
static void ihook(unsigned int pc){
    if(pc>maxpc2)maxpc2=pc;
    /* the restart-bound path / the bra $20194 */
    if((pc==0x23ec8||pc==0x23f06) && dumped<8){ dumped++;
        fprintf(stderr,"  RESTART-PATH pc=0x%06x D0=0x%04x 31732=%02x%02x 31735=%02x\n",
            pc, m68k_get_reg(0,0)&0xffff, tc_mem[0x31732],tc_mem[0x31733],tc_mem[0x31735]); }
}

int main(int argc,char**argv){
    char p[256]; int n; const char*dir=argv[1]; int frames=atoi(argv[2]);
    static uint8_t rom[0x30000]; uint16_t dsprog[2048];
    const char*ev[2]={"maincpu/b30_01.7j","maincpu/b30_26_ii.8j"};
    const char*od[2]={"maincpu/b30_03.7h","maincpu/b30_27_ii.8h"}; int off[2]={0,0x20000};
    for(int k=0;k<2;k++){sprintf(p,"%s/%s",dir,ev[k]);uint8_t*e=slurp(p,&n);
        sprintf(p,"%s/%s",dir,od[k]);uint8_t*o=slurp(p,&n);
        for(int i=0;i<n;i++){rom[off[k]+i*2]=e[i];rom[off[k]+i*2+1]=o[i];}free(e);free(o);}
    sprintf(p,"%s/dsp/dsp_21.bin",dir);uint8_t*de=slurp(p,&n);
    sprintf(p,"%s/dsp/dsp_22.bin",dir);uint8_t*dd=slurp(p,&n);
    for(int i=0;i<2048;i++)dsprog[i]=(de[i]<<8)|dd[i];

    /* gfx regions in ROM_LOAD offset order (verified) */
    const char*c1[3]={"gfx/chars/b30_08.8c","gfx/chars/b30_07.10b","gfx/chars/b30_06.8b"};
    const char*b1[4]={"gfx/bg/b30_12.16c","gfx/bg/b30_11.14c","gfx/bg/b30_10.12c","gfx/bg/b30_09.10c"};
    const char*f1[4]={"gfx/fg/b30_16.20b","gfx/fg/b30_15.18b","gfx/fg/b30_13.18c","gfx/fg/b30_14.20c"};
    const char*s1[4]={"gfx/sprites/b30_20.12d","gfx/sprites/b30_19.14d","gfx/sprites/b30_18.15d","gfx/sprites/b30_17.16d"};
    tc_render_setgfx(cat(dir,c1,3),cat(dir,b1,4),cat(dir,f1,4),cat(dir,s1,4));

    tc_init(rom,0x30000,dsprog,2048);
    m68k_set_instr_hook_callback(ihook);
    { int prev=-1; for(int f=0;f<frames;f++){
        int ie=tc_intenable();
        if(ie==1 && prev!=1) fprintf(stderr,"f%-4d MAINLOOP irq4=%d  31732=%02x%02x 31734=%02x 31735=%02x 31594=%02x%02x\n",
            f,tc_irq_count,tc_mem[0x31732],tc_mem[0x31733],tc_mem[0x31734],tc_mem[0x31735],tc_mem[0x31594],tc_mem[0x31595]);
        prev=ie;
        tc_run_frame();
    } }

    static uint16_t chunky[320*240];
    tc_render_frame(chunky,tc_txvram,tc_bgvram,tc_fgvram,tc_scroll,tc_latch,tc_mem+0x40000);

    /* diagnostics: distinct bg tile codes, distinct chunky indices */
    { int seen[8192]={0},bgd=0,j; for(j=0;j<0x2000;j++){int t=tc_bgvram[j]&0xfff;if(!seen[t]){seen[t]=1;bgd++;}}
      int s2[2048]={0},cd=0,nub=0; for(j=0;j<320*240;j++){int c=chunky[j];if(c<2048&&!s2[c]){s2[c]=1;cd++;}if(chunky[j]!=chunky[0])nub++;}
      fprintf(stderr,"diag: distinct bg-tilecodes=%d  distinct-chunky=%d  non-uniform-pixels=%d  bank bg=%d fg=%d  scroll=[%d,%d,%d,%d,%d,%d]\n",
              bgd,cd,nub,tc_latch[4],tc_latch[5],tc_scroll[0],tc_scroll[1],tc_scroll[2],tc_scroll[3],tc_scroll[4],tc_scroll[5]); }

    /* arcade palette (xBGR555) @0x50000 -> PPM */
    FILE*out=fopen(argv[3],"wb"); fprintf(out,"P6\n320 240\n255\n");
    for(int i=0;i<320*240;i++){
        int idx=chunky[i]; int w=(tc_mem[0x50000+idx*2]<<8)|tc_mem[0x50000+idx*2+1];
        int r=(w&0x1f)<<3,g=((w>>5)&0x1f)<<3,b=((w>>10)&0x1f)<<3;
        fputc(r,out);fputc(g,out);fputc(b,out);
    }
    fprintf(stderr,"  maxPC=0x%06x\n",maxpc2);
    fclose(out); fprintf(stderr,"  IRQ4=%d DSP=%d cycles=%ld (expected ~%d)\n",tc_irq_count,tc_dsp_count,tc_cycles,frames*116000);
    printf("wrote %s\n",argv[3]); return 0;
}

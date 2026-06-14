/* twincobr_chost.c -- host test for the C machine model (machine_twincobr.c
 * on Musashi). Boots the real ROM, runs N frames, and reports the same
 * populated-state metrics the Python harness produced (palette/sprites/
 * tilemaps), to prove the C HAL matches the validated reference.
 *   gcc -O2 -I src/cores -I src/cores/m68k tests/host/twincobr_chost.c \
 *       src/hal/machine_twincobr.c src/cores/tms320c10.c \
 *       src/cores/m68k/m68kcpu.c src/cores/m68k/m68kops.c \
 *       src/cores/m68k/softfloat/softfloat.c -o /tmp/tcc
 *   /tmp/tcc games/twincobr 300
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

void tc_init(const uint8_t*, int, const uint16_t*, int);
void tc_run_frame(void);
extern uint8_t  *tc_mem;
extern uint16_t *tc_txvram, *tc_bgvram, *tc_fgvram;

static uint8_t *slurp(const char *p, int *n){
    FILE *f=fopen(p,"rb"); if(!f){fprintf(stderr,"open %s\n",p);exit(1);}
    fseek(f,0,SEEK_END); *n=ftell(f); fseek(f,0,SEEK_SET);
    uint8_t *b=malloc(*n); fread(b,1,*n,f); fclose(f); return b;
}

int main(int argc,char**argv){
    char p[256]; int n; const char *dir=argv[1]; int frames=atoi(argv[2]);
    static uint8_t rom[0x30000]; uint16_t dsprog[2048];
    /* 68000: even/odd interleave of the 4 program ROMs */
    const char *ev[2]={"maincpu/b30_01.7j","maincpu/b30_26_ii.8j"};
    const char *od[2]={"maincpu/b30_03.7h","maincpu/b30_27_ii.8h"};
    int off[2]={0x00000,0x20000};
    for(int k=0;k<2;k++){
        sprintf(p,"%s/%s",dir,ev[k]); uint8_t*e=slurp(p,&n);
        sprintf(p,"%s/%s",dir,od[k]); uint8_t*o=slurp(p,&n);
        for(int i=0;i<n;i++){ rom[off[k]+i*2]=e[i]; rom[off[k]+i*2+1]=o[i]; }
        free(e); free(o);
    }
    sprintf(p,"%s/dsp/dsp_21.bin",dir); uint8_t*de=slurp(p,&n);
    sprintf(p,"%s/dsp/dsp_22.bin",dir); uint8_t*dod=slurp(p,&n);
    for(int i=0;i<2048;i++) dsprog[i]=(de[i]<<8)|dod[i];

    tc_init(rom,0x30000,dsprog,2048);
    for(int f=0;f<frames;f++) tc_run_frame();

    int pal=0,spr=0,tx=0,bg=0,fg=0;
    for(int i=0;i<0xe00;i++) if(tc_mem[0x50000+i]) pal++;
    for(int i=0;i<0x1000;i++) if(tc_mem[0x40000+i]) spr++;
    for(int i=0;i<0x800;i++) if(tc_txvram[i]) tx++;
    for(int i=0;i<0x2000;i++) if(tc_bgvram[i]) bg++;
    for(int i=0;i<0x1000;i++) if(tc_fgvram[i]) fg++;
    printf("after %d frames: palette=%d/3584 sprites=%d/4096 tx=%d/2048 bg=%d/8192 fg=%d/4096\n",
           frames,pal,spr,tx,bg,fg);
    return 0;
}

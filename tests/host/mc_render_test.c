/* tests/host/mc_render_test.c
 * Exercises the ACTUAL Amiga renderer (src/hal/mc_render.c) on the host:
 * runs the CPU, renders into a 5-plane buffer exactly like the Amiga,
 * then reconstructs the screen (planes + PROM palette) to a PPM. If this
 * shows the attract screen, the renderer logic is correct and a black
 * screen on the Amiga is a display-setup / speed issue, not the render.
 *
 *   gcc -O2 -Isrc/cores -Isrc/hal -o /tmp/mcr tests/host/mc_render_test.c \
 *       src/cores/z80.c src/hal/machine.c src/hal/mc_render.c src/hal/mc_romdata.c
 *   /tmp/mcr 120 /tmp/mc_amiga_render.ppm
 */
#include <stdio.h>
#include <stdlib.h>
#include "z80emu.h"
#include "machine.h"

extern void mc_render(const unsigned char *mem);
extern unsigned char *mc_planes;
extern const unsigned char mc_prog[]; extern const unsigned long mc_prog_len;
extern const unsigned char mc_prom[32];

static MY_LITTLE_Z80 z;
int mc_buffer_id = 0;            /* render-skip buffer id (mc_video.c on Amiga) */
unsigned char mc_gfx_bank(void) { return machine_io.gfx_bank; }
unsigned char in_impl(MY_LITTLE_Z80 *zz, int p) { (void)zz; (void)p; return 0xff; }
void out_impl(MY_LITTLE_Z80 *zz, int p, unsigned char v) { (void)zz;(void)p;(void)v; }

int main(int argc, char **argv)
{
    int frames = argc > 1 ? atoi(argv[1]) : 120;
    const char *ppm = argc > 2 ? argv[2] : "/tmp/mc_amiga_render.ppm";
    const int ROW = 40, PSZ = 10240;
    unsigned char *planes = calloc(PSZ * 5, 1);
    mc_planes = planes;

    machine_init(&z, mc_prog, (unsigned)mc_prog_len);
    for (int f = 0; f < frames; f++) machine_run_frame(&z);
    mc_render(z.memory);

    long nz = 0; for (int i = 0; i < PSZ * 5; i++) if (planes[i]) nz++;
    printf("frames=%d nmi=%lu gfx_bank=%u: non-zero plane bytes=%ld\n",
           frames, machine_io.nmi_count, machine_io.gfx_bank, nz);

    unsigned int pal[32];
    for (int i = 0; i < 32; i++) {
        int v = mc_prom[i];
        int r=((v>>0)&1)*0x21+((v>>1)&1)*0x47+((v>>2)&1)*0x97;
        int g=((v>>3)&1)*0x21+((v>>4)&1)*0x47+((v>>5)&1)*0x97;
        int b=((v>>6)&1)*0x51+((v>>7)&1)*0xAE;
        if(r>255)r=255; if(g>255)g=255; if(b>255)b=255;
        pal[i]=(r<<16)|(g<<8)|b;
    }
    FILE *f = fopen(ppm, "wb"); fprintf(f, "P6\n224 256\n255\n");
    for (int sy = 0; sy < 256; sy++) for (int sx = 0; sx < 224; sx++) {
        unsigned char *base = planes + sy*ROW + (sx>>3);
        unsigned char m = 0x80 >> (sx&7);
        int idx = 0;
        for (int p = 0; p < 5; p++) if (base[p*PSZ] & m) idx |= (1<<p);
        unsigned int c = pal[idx & 31];
        unsigned char px[3] = {(c>>16)&0xff,(c>>8)&0xff,c&0xff};
        fwrite(px,1,3,f);
    }
    fclose(f);
    printf("wrote %s\n", ppm);
    return 0;
}

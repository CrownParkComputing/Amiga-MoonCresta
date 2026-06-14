/* tests/host/mooncrst_host.c
 * ============================================================
 * Host-side smoke test + reference renderer for Moon Cresta.
 *
 * Runs the program ROM on the vendored Z80 core through the
 * machine layer (src/hal/machine.c), then decodes the char ROM +
 * palette PROM exactly like zarcade's GalaxianVideo and writes the
 * attract screen to a PPM -- so we can SEE the decode is right
 * before porting the renderer to the Amiga.
 *
 *   gcc -O2 -Isrc/cores -Isrc/hal -o /tmp/mctest \
 *       tests/host/mooncrst_host.c src/cores/z80.c src/hal/machine.c
 *   /tmp/mctest games/mooncrst 600 /tmp/mc.ppm
 * ============================================================ */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "z80emu.h"
#include "machine.h"

static MY_LITTLE_Z80 z;

/* Galaxian uses no Z80 I/O ports; the Amiga build gets these from
 * hal_stubs.s, the host build defines them here. */
unsigned char in_impl(MY_LITTLE_Z80 *zz, int port) { (void)zz; (void)port; return 0xff; }
void out_impl(MY_LITTLE_Z80 *zz, int port, unsigned char v) { (void)zz; (void)port; (void)v; }

static unsigned char charrom[0x2000];   /* 8 KB: mcs_b,mcs_d,mcs_a,mcs_c */
static unsigned char prom[64];
static unsigned int  palette[32];       /* 0x00RRGGBB */

static int load(const char *path, unsigned char *dst, unsigned int max)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return -1; }
    int n = (int)fread(dst, 1, max, f);
    fclose(f);
    return n;
}

static int bit(int v, int n) { return (v >> n) & 1; }
static int clamp255(int v) { return v > 255 ? 255 : v; }

static void build_palette(void)
{
    for (int i = 0; i < 32; i++) {
        int v = prom[i];
        int r = bit(v,0)*0x21 + bit(v,1)*0x47 + bit(v,2)*0x97;
        int g = bit(v,3)*0x21 + bit(v,4)*0x47 + bit(v,5)*0x97;
        int b = bit(v,6)*0x51 + bit(v,7)*0xAE;
        palette[i] = (clamp255(r) << 16) | (clamp255(g) << 8) | clamp255(b);
    }
}

/* Moon Cresta tile-bank extension (zarcade MoonCrestaVideoVariant). */
static int extend_tile(int code)
{
    int b0 = machine_io.gfx_bank & 1, b1 = (machine_io.gfx_bank >> 1) & 1,
        b2 = (machine_io.gfx_bank >> 2) & 1;
    if (b2 && (code & 0xC0) == 0x80)
        return (code & 0x3F) | (b0 << 6) | (b1 << 7) | 0x100;
    return code;
}

int main(int argc, char **argv)
{
    const char *gamedir = (argc > 1) ? argv[1] : "games/mooncrst";
    int frames          = (argc > 2) ? atoi(argv[2]) : 600;
    const char *ppm     = (argc > 3) ? argv[3] : "/tmp/mc.ppm";
    char path[1024];
    const char *progf[8] = { "epr194","epr195","epr196","epr197",
                             "epr198","epr199","epr200","epr201" };
    const char *charf[4] = { "mcs_b","mcs_d","mcs_a","mcs_c" }; /* planeSplit=0x1000 */
    unsigned char prog[0x4000]; unsigned int off = 0;

    for (int i = 0; i < 8; i++) {
        snprintf(path, sizeof path, "%s/roms/%s", gamedir, progf[i]);
        int n = load(path, prog + off, 2048); if (n < 0) return 1; off += n;
    }
    for (int i = 0; i < 4; i++) {
        snprintf(path, sizeof path, "%s/gfx/%s", gamedir, charf[i]);
        if (load(path, charrom + i*0x800, 0x800) < 0) return 1;
    }
    snprintf(path, sizeof path, "%s/mmi6331.6l", gamedir);
    if (load(path, prom, sizeof prom) < 0) return 1;
    build_palette();
    printf("loaded prog=%u char=8192 prom=32\n", off);

    machine_init(&z, prog, off);
    for (int f = 0; f < frames; f++) machine_run_frame(&z);

    printf("after %d frames: nmi=%lu io_w=%lu gfx_bank=%u stars=%d\n",
           frames, machine_io.nmi_count, machine_io.io_writes,
           machine_io.gfx_bank, machine_io.stars_enabled);

    /* ---- render native 256x256 (zarcade GalaxianVideo decode) ---- */
    static unsigned int native[256*256];
    memset(native, 0, sizeof native);
    const unsigned char *vram = z.memory + 0x9000;
    const unsigned char *obj  = z.memory + 0x9800;
    for (int row = 0; row < 32; row++) {
        for (int col = 0; col < 32; col++) {
            int tile = extend_tile(vram[(row*32+col) & 0x3ff]);
            int colorAttr = obj[(col*2+1) & 0xff] & 0x07;
            int scrollY   = obj[(col*2) & 0xff] & 0xff;
            int colorBase = colorAttr * 4;
            int px = col*8, py = (row*8 - scrollY) & 0xff;
            const unsigned char *p0 = charrom + tile*8;
            const unsigned char *p1 = charrom + tile*8 + 0x1000;
            for (int y = 0; y < 8; y++) {
                int b0 = p0[y], b1 = p1[y];
                for (int x = 0; x < 8; x++) {
                    int sh = 7 - x;
                    int pen = ((b0 >> sh) & 1) | (((b1 >> sh) & 1) << 1);
                    if (pen) native[(((py+y)&0xff)*256) + ((px+x)&0xff)]
                                 = palette[(colorBase+pen) & 31];
                }
            }
        }
    }

    /* ---- ROT90 -> upright 224x256 portrait, write PPM ---- */
    FILE *f = fopen(ppm, "wb");
    if (!f) { perror(ppm); return 1; }
    fprintf(f, "P6\n224 256\n255\n");
    for (int fy = 0; fy < 256; fy++) {
        for (int fx = 0; fx < 224; fx++) {
            int nx = fy, ny = (223 - fx) + 16;
            unsigned int c = native[((ny & 255)*256) + (nx & 255)];
            unsigned char px[3] = { (c>>16)&0xff, (c>>8)&0xff, c&0xff };
            fwrite(px, 1, 3, f);
        }
    }
    fclose(f);
    printf("wrote %s (224x256 upright)\n", ppm);
    return 0;
}

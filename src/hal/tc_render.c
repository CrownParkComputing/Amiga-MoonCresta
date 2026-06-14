/* tc_render.c -- Twin Cobra software renderer (pure C: host + Amiga, like
 * mc_render.c). Composites bg<fg<sprite<tx into a 320x240 chunky buffer of
 * ARCADE palette indices (0..1791; 0 = backdrop). A separate palette stage
 * maps those to the Amiga display. Ported from tools/twincobr_render.py;
 * tile/sprite formats verified vs toaplan/twincobr_v.cpp + toaplan_scu.cpp.
 *
 * gfx region pointers (caller supplies; from ROM):
 *   chars 0xc000 3bpp(planes 0,0x4000,0x8000) | bg 0x20000 4bpp(quarters)
 *   fg 0x40000 4bpp | spr 0x40000 4bpp 16x16
 */
#include <stdint.h>

#define W 320
#define H 240

static const uint8_t *g_chars, *g_bg, *g_fg, *g_spr;

void tc_render_setgfx(const uint8_t *chars, const uint8_t *bg,
                      const uint8_t *fg, const uint8_t *spr)
{ g_chars = chars; g_bg = bg; g_fg = fg; g_spr = spr; }

/* one 8x8 tile pixel (3 or 4 planes) */
static int tile_pix(const uint8_t *rom, const int *planes, int np, int code, int r, int x)
{
    int pen = 0, p;
    for (p = 0; p < np; p++)
        pen |= ((rom[planes[p] + code * 8 + r] >> (7 - x)) & 1) << p;
    return pen;
}
/* one 16x16 sprite pixel (4 planes, rows are 2 bytes) */
static int spr_pix(int code, int r, int x)
{
    static const int q[4] = {0, 0x10000, 0x20000, 0x30000};
    int pen = 0, p;
    for (p = 0; p < 4; p++) {
        int w = (g_spr[q[p] + code * 32 + r * 2] << 8) | g_spr[q[p] + code * 32 + r * 2 + 1];
        pen |= ((w >> (15 - x)) & 1) << p;
    }
    return pen;
}

/* composite a full frame of arcade palette indices into out[W*H]. */
void tc_render_frame(uint16_t *out,
                     const uint16_t *txvram, const uint16_t *bgvram,
                     const uint16_t *fgvram, const uint16_t *scroll,
                     const uint8_t *latch, const uint8_t *sprite_ram)
{
    static const int chp[3] = {0, 0x4000, 0x8000};
    static const int bgp[4] = {0, 0x8000, 0x10000, 0x18000};
    static const int fgp[4] = {0, 0x10000, 0x20000, 0x30000};
    int fgbank = latch[5] * 0x1000;
    int bgbank = latch[4] * 0x1000;
    int x, y;

    for (y = 0; y < H; y++) {
        int byb = (y + scroll[3]) & 511, fyb = (y + scroll[5]) & 511;
        int tyb = (y + scroll[1]) & 255;
        for (x = 0; x < W; x++) {
            /* bg (opaque) */
            int bx = (x + scroll[2]) & 511;
            int ent = bgvram[((byb >> 3) * 64 + (bx >> 3)) + bgbank];
            int pen = tile_pix(g_bg, bgp, 4, ent & 0xfff, byb & 7, bx & 7);
            int idx = 1024 + ((ent >> 12) & 0xf) * 16 + pen;
            /* fg (trans) */
            int fx = (x + scroll[4]) & 511;
            ent = fgvram[(fyb >> 3) * 64 + (fx >> 3)];
            pen = tile_pix(g_fg, fgp, 4, (ent & 0xfff) | fgbank, fyb & 7, fx & 7);
            if (pen) idx = 1280 + ((ent >> 12) & 0xf) * 16 + pen;
            out[y * W + x] = (uint16_t)idx;
            /* tx (trans, top) drawn after sprites below -- store bg/fg now */
        }
    }
    /* sprites (4 words; sx>>7 - 31, sy>>7 - 16; skip pri 0 / sy==0x100) */
    {
        int o;
        for (o = 0; o < 0x800; o += 4) {
            int attr = (sprite_ram[(o+1)*2] << 8) | sprite_ram[(o+1)*2+1];
            int sy, code, color, sx, fxf, fyf, r, c;
            if (!(attr & 0x0c00)) continue;
            sy = ((sprite_ram[(o+3)*2] << 8) | sprite_ram[(o+3)*2+1]) >> 7;
            if (sy == 0x0100) continue;
            code = ((sprite_ram[o*2] << 8) | sprite_ram[o*2+1]) & 0x7ff;
            color = attr & 0x3f; fxf = (attr >> 8) & 1; fyf = (attr >> 9) & 1;
            sx = (((sprite_ram[(o+2)*2] << 8) | sprite_ram[(o+2)*2+1]) >> 7) - 31;
            sy -= 16;
            for (r = 0; r < 16; r++) for (c = 0; c < 16; c++) {
                int pen = spr_pix(code, fyf ? 15 - r : r, fxf ? 15 - c : c);
                int px = sx + c, py = sy + r;
                if (pen && px >= 0 && px < W && py >= 0 && py < H)
                    out[py * W + px] = (uint16_t)(color * 16 + pen);
            }
        }
    }
    /* tx layer on top (64x32, 8x8, code&0x7ff, color=(ent>>11)&0x1f, base 1536) */
    for (y = 0; y < H; y++) {
        int tyb = (y + scroll[1]) & 255;
        for (x = 0; x < W; x++) {
            int tx = (x + scroll[0]) & 511;
            int ent = txvram[(tyb >> 3) * 64 + (tx >> 3)];
            int pen = tile_pix(g_chars, chp, 3, ent & 0x7ff, tyb & 7, tx & 7);
            if (pen) out[y * W + x] = (uint16_t)(1536 + ((ent >> 11) & 0x1f) * 8 + pen);
        }
    }
}

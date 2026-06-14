/* src/hal/mc_render.c
 * ============================================================
 *  Moon Cresta tilemap -> Amiga bitplane renderer. Pure C (no
 *  Amiga headers) so it builds for both m68k-amigaos-gcc and the
 *  host (tests/host/mc_render_test.c). mc_video.c sets mc_planes
 *  to the allocated 5-plane chip buffer; the host test points it
 *  at a malloc'd buffer.
 * ============================================================ */
#include "machine.h"

/* Render target -- set by mc_video_open() (Amiga) or the host test. */
unsigned char *mc_planes = 0;

/* Plane-clear hook. On Amiga, mc_video.c sets this to a WaitBlit -- the
 * blitter clears the back buffer at swap-time so the clear overlaps the
 * next frame's Z80 emulation (hiding ~3.6ms of CPU plane-clearing). NULL
 * on the host -> the CPU fallback clear below is used. */
void (*mc_clear_hook)(unsigned char *planes) = 0;

/* Pre-rotated tile cache: for each of the 512 char tiles, the ROT90'd
 * 8-row bit patterns (plane0 pens, plane1 pens, and the pen!=0 mask).
 * Built once; lets mc_render write whole 8-pixel runs as 1-2 byte ORs
 * instead of 64 per-pixel read-modify-writes. ~2.75x faster, and far
 * gentler on chip-RAM bandwidth on a real A1200. Verified pixel-identical
 * to the old per-pixel path on the host (tests/host A/B over 1500 frames). */
extern const unsigned char mc_char[8192];

/* Per-buffer signature of the last-drawn tilemap, so we skip the whole
 * redraw when nothing visible changed (most attract/idle frames). */
static unsigned int shadow_sig[2] = { 0xFFFFFFFFu, 0xFFFFFFFFu };

static unsigned char tc0[512][8], tc1[512][8], tcm[512][8];
static int tc_ready = 0;
static void build_tilecache(void)
{
    for (int t = 0; t < 512; t++) {
        const unsigned char *p0 = mc_char + t*8, *p1 = mc_char + t*8 + 0x1000;
        for (int x = 0; x < 8; x++) {
            unsigned r0 = 0, r1 = 0;
            for (int y = 0; y < 8; y++) {
                if ((p0[y] >> (7-x)) & 1) r0 |= 1u << y;
                if ((p1[y] >> (7-x)) & 1) r1 |= 1u << y;
            }
            tc0[t][x] = r0; tc1[t][x] = r1; tcm[t][x] = r0 | r1;
        }
    }
    tc_ready = 1;
}

/* Bitplane geometry. Compile-time constants on purpose: the 68000 has
 * no 32-bit multiply, so a runtime `sy * row_bytes` would pull in
 * __mulsi3 (not linked). 320-wide 5-plane screen -> 40 bytes/line. */
#define MC_ROW_BYTES  40
#define MC_PLANE_SZ   10240            /* 40 * 256 */
#define MC_HSHIFT     6                /* +48px: centre the 224-wide image in the 320 screen */
/* Nudge the playfield down 1 row (8px) while leaving the score header (top)
 * and the CREDIT line (bottom) pinned. The screen vertical is the bitplane
 * row; rows 24..247 are the "main area". */
#define MC_VMAIN(y)   (((y) >= 24 && (y) < 248) ? (y) + 8 : (y))

extern const unsigned char mc_char[8192];
extern unsigned char mc_gfx_bank(void);
extern int mc_buffer_id;            /* which double-buffer we're drawing (0/1) */

/* Moon Cresta tile-bank extend (zarcade MoonCrestaVideoVariant). */
static int extend_tile(int code)
{
    int gb = mc_gfx_bank();
    int b0 = gb & 1, b1 = (gb >> 1) & 1, b2 = (gb >> 2) & 1;
    if (b2 && (code & 0xC0) == 0x80)
        return (code & 0x3F) | (b0 << 6) | (b1 << 7) | 0x100;
    return code;
}

static void plot(int sx, int sy, int idx)
{
    /* NOTE: no MC_VMAIN here -- sprites/bullets must move as whole objects, not
     * per-pixel (a per-pixel shift slices any sprite crossing the boundary, e.g.
     * the ship rising from the bottom). The 1-row main-area nudge is applied to
     * tiles only (the fast path + the tile fallback). */
    unsigned char *base = mc_planes + sy * MC_ROW_BYTES + (sx >> 3) + MC_HSHIFT;
    unsigned char mask = 0x80 >> (sx & 7);
    if (idx & 1)  base[0]               |= mask;
    if (idx & 2)  base[MC_PLANE_SZ]     |= mask;
    if (idx & 4)  base[MC_PLANE_SZ*2]   |= mask;
    if (idx & 8)  base[MC_PLANE_SZ*3]   |= mask;
    if (idx & 16) base[MC_PLANE_SZ*4]   |= mask;
}

/* Plot one native (pre-rotation) pixel, applying the ROT90 -> upright map
 * (same as the tilemap) and the visible-window clip. */
static void plot_native(int nx, int ny, int idx)
{
    ny &= 0xff;
    if (ny < 16 || ny > 239) return;
    if ((unsigned)nx > 255u) return;            /* clip the vertical axis -- do NOT
                                                 * wrap (matches zarcade putNative
                                                 * bounds; stops a bottom-edge sprite
                                                 * slicing up under the hi-score). */
    plot(239 - ny, nx, idx);
}

/* Moon Cresta sprite tile-bank extension (zarcade MoonCrestaVideoVariant). */
static int extend_sprite(int code)
{
    int gb = mc_gfx_bank();
    int b0 = gb & 1, b1 = (gb >> 1) & 1, b2 = (gb >> 2) & 1;
    if (b2 && (code & 0x30) == 0x20)
        return (code & 0x0f) | (b0 << 4) | (b1 << 5) | 0x40;
    return code;
}

/* 16x16 sprite = four 8x8 sub-tiles at byte blocks 0/8/16/24, 2bpp planar. */
static void draw_sprite16(int code, int px, int py, int colorBase, int fx, int fy)
{
    const unsigned char *blk0 = mc_char + code * 32;
    const unsigned char *blk1 = mc_char + code * 32 + 0x1000;
    for (int y = 0; y < 16; y++) {
        for (int x = 0; x < 16; x++) {
            int sxp = fx ? 15 - x : x;
            int syp = fy ? 15 - y : y;
            int bi  = (syp < 8 ? 0 : 16) + (sxp < 8 ? 0 : 8) + (syp & 7);
            int bit = 7 - (sxp & 7);
            int pen = ((blk0[bi] >> bit) & 1) | (((blk1[bi] >> bit) & 1) << 1);
            if (pen) plot_native(px + x, py + y, (colorBase + pen) & 31);
        }
    }
}

/* 8 hardware sprites at objram 0x9840 (zarcade GalaxianVideo.renderSprites).
 * Lower-numbered sprites have priority -> draw high to low. */
static void render_sprites(const unsigned char *obj)
{
    for (int n = 7; n >= 0; n--) {
        int base = 0x40 + n * 4;
        int b0 = obj[base];          /* y */
        int b1 = obj[base + 1];      /* code + flip */
        int b2 = obj[base + 2];      /* color */
        int b3 = obj[base + 3];      /* x */
        if (b0 == 0 || b3 == 0) continue;     /* MoonCresta spriteVisible: hide Y==0/X==0 */
        int sy = (240 - (b0 - (n < 3 ? 1 : 0))) & 0xff;
        int code = extend_sprite(b1 & 0x3f);
        draw_sprite16(code, b3 + 1, sy, (b2 & 7) * 4, b1 & 0x40, b1 & 0x80);  /* +1 = spriteNativeX */
    }
}

/* ---- custom starfield -------------------------------------------------
 * The real Galaxian stars are a 17-bit LFSR with 64 colours -- too slow
 * per-pixel on the Amiga and they'd bust our 32-colour palette. Instead we
 * scatter a fixed set of stars (deterministic LCG) in a few bright palette
 * colours and scroll them vertically. Drawn LAST and only onto background
 * (empty) pixels, so tiles/sprites/bullets always sit on top. Gated by the
 * game's stars-enable latch (machine_io.stars_enabled). */
#define MC_NSTARS 192
static struct { unsigned char nx, ny, col; } mc_stars[MC_NSTARS];
static int mc_stars_built = 0;
static int mc_star_scroll = 0;
static void build_stars(void)
{
    static const unsigned char scol[4] = { 31, 5, 11, 9 };   /* white, cyan, yellow, magenta */
    unsigned int s = 0x13572468u;
    for (int i = 0; i < MC_NSTARS; i++) {
        s = s * 1103515245u + 12345u; int a = (s >> 16) & 0xff;
        s = s * 1103515245u + 12345u; int b = (s >> 16) & 0xff;
        mc_stars[i].nx = a;
        mc_stars[i].ny = 16 + (b * 224) / 256;        /* keep inside the visible window */
        mc_stars[i].col = scol[(s >> 8) & 3];
    }
    mc_stars_built = 1;
}
static void plot_star(int nx, int ny, int idx)
{
    int sx = 239 - ny, sy = nx & 0xff;                /* same ROT90 as plot_native */
    unsigned char *base = mc_planes + sy * MC_ROW_BYTES + (sx >> 3) + MC_HSHIFT;
    unsigned char m = 0x80 >> (sx & 7);
    if ((base[0] | base[MC_PLANE_SZ] | base[MC_PLANE_SZ*2]
                 | base[MC_PLANE_SZ*3] | base[MC_PLANE_SZ*4]) & m) return;  /* occupied */
    if (idx & 1)  base[0]             |= m;
    if (idx & 2)  base[MC_PLANE_SZ]   |= m;
    if (idx & 4)  base[MC_PLANE_SZ*2] |= m;
    if (idx & 8)  base[MC_PLANE_SZ*3] |= m;
    if (idx & 16) base[MC_PLANE_SZ*4] |= m;
}
static void render_stars(void)
{
    if (!mc_stars_built) build_stars();
    mc_star_scroll = (mc_star_scroll + 1) & 0xff;     /* slow vertical scroll */
    for (int i = 0; i < MC_NSTARS; i++)
        plot_star((mc_stars[i].nx + mc_star_scroll) & 0xff, mc_stars[i].ny, mc_stars[i].col);
}

/* Galaxian bullets: objram 0x60-0x7f, 8 slots x 4 bytes (Y at +1, X at +3).
 * Each active bullet is a 4-pixel streak (zarcade GalaxianVideo.renderBullets).
 * Slot 7 = player missile (yellow, idx 11); slots 0-2 are shells nudged one
 * line down. White = idx 31. Inactive bullets self-clip (y out of window). */
static void render_bullets(const unsigned char *obj)
{
    for (int slot = 0; slot < 8; slot++) {
        int rawY = obj[0x60 + slot*4 + 1];
        int rawX = obj[0x60 + slot*4 + 3];
        int y = (slot < 3) ? ((256 - rawY) & 0xff) : ((255 - rawY) & 0xff);
        if (y < 16 || y >= 240) continue;
        int nx  = (255 - rawX) & 0xff;
        int col = (slot == 7) ? 11 : 31;          /* missile yellow / shell white */
        for (int i = 0; i < 4; i++) plot_native(nx - 4 + i, y, col);
    }
}

/* Replace the original Nichibutsu copyright with custom branding
 * "WHITTY APPS 2026". The game redraws the copyright every frame, so this is
 * called each frame (before mc_render) to overwrite it. We detect that one
 * attract page by its logo signature tile (0x30 at col 26 row 12) so nothing
 * else is touched. Font: 0-9 = 0x00-0x09, A-Z = 0x0A.., blank = 0x24. The
 * tilemap is ROT90'd so a screen line is a VRAM column and higher VRAM row =
 * further left, hence the (23 - i) placement. */
void mc_brand(unsigned char *mem)
{
    unsigned char *vram = mem + 0x9000;
    if (vram[12*32 + 26] != 0x30) return;          /* copyright page not showing */
    for (int row = 0; row < 32; row++) { vram[row*32 + 26] = 0x24; vram[row*32 + 27] = 0x24; }
    /* W H I T T Y _ A R C A D E _ 2 0 2 6 */
    static const unsigned char txt[18] = {
        0x20,0x11,0x12,0x1d,0x1d,0x22,0x24,0x0a,0x1b,0x0c,0x0a,0x0d,0x0e,0x24,0x02,0x00,0x02,0x06 };
    for (int i = 0; i < 18; i++) vram[(25 - i)*32 + 26] = txt[i];
}

/* ---- boot splash + countdown (drawn in plain landscape, our own font) ---- */
static int chartile(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'Z') return 0x0A + (c - 'A');
    if (c >= 'a' && c <= 'z') return 0x0A + (c - 'a');
    return 0x24;                                  /* blank */
}
/* Draw a string the EXACT way the game draws its own (readable) tile text:
 * each char is one tile; chars advance along the VRAM "row" axis (which is the
 * horizontal reading direction), with the line pinned at tile-column `col`
 * (its vertical position). plot_native(col*8+x, row*8+y) is the game's own
 * tile->screen mapping, so the font reads upright. base_row = first char;
 * higher row = further left, so we count rows DOWN as we go right. */
static void boot_str(const char *s, int col, int base_row, int color)
{
    int colorBase = color * 4;
    for (int i = 0; *s; s++, i++) {
        int row = base_row - i;
        const unsigned char *p0 = mc_char + chartile(*s)*8, *p1 = p0 + 0x1000;
        for (int y = 0; y < 8; y++) {
            int b0 = p0[y], b1 = p1[y];
            for (int x = 0; x < 8; x++) {
                int pen = ((b0 >> (7-x)) & 1) | (((b1 >> (7-x)) & 1) << 1);
                if (pen) plot_native(col*8 + x, row*8 + y, (colorBase + pen) & 31);
            }
        }
    }
}
/* Title screen: the game's starfield + title text + a PRESS FIRE prompt, all
 * in the game's ROT90 orientation (so it reads upright, not sideways). */
void mc_boot_draw(int count)
{
    unsigned int *q = (unsigned int *)mc_planes;
    int n = (MC_PLANE_SZ * 5) / 4; while (n--) *q++ = 0;
    (void)count;
    if (!tc_ready) build_tilecache();
    if (!mc_stars_built) build_stars();
    for (int i = 0; i < MC_NSTARS; i++)                /* starfield backdrop */
        plot_star(mc_stars[i].nx, mc_stars[i].ny, mc_stars[i].col);
    /* the player rocket, drawn from the ROM's own sprites (codes 0x10-0x15) */
    { static const struct { unsigned char code, b0, b3, col; } rocket[6] = {
        {0x10,120,129,3},{0x12,112,137,4},{0x11,128,137,4},
        {0x14,112,153,5},{0x13,128,153,5},{0x15,120,169,6} };
      for (int i = 0; i < 6; i++)
        draw_sprite16(rocket[i].code, rocket[i].b3, (240 - rocket[i].b0) & 0xff,
                      rocket[i].col * 4, 0, 0); }
    /* args: (col = vertical line position, base_row = horizontal start, colour) */
    boot_str("MOON CRESTA",    4, 21, 6);              /* yellow title  */
    boot_str("WHITTY ARCADE",  7, 22, 1);              /* cyan branding */
    boot_str("2026",           9, 18, 9);
    boot_str("PRESS FIRE",    26, 21, 5);              /* prompt */
    boot_str("FULL SPEED",    28, 21, 3);              /* speed note */
    boot_str("030 OR JIT",    30, 21, 5);
}

/* mem points at the Z80's 64 KB array; VRAM @0x9000, objram @0x9800. */
void mc_render(const unsigned char *mem)
{
    const unsigned char *vram = mem + 0x9000;
    const unsigned char *obj  = mem + 0x9800;
    if (!mc_planes) return;

    if (!tc_ready) build_tilecache();

    /* Skip the whole redraw if the tilemap + per-column attr/scroll are
     * identical to what this buffer last drew. Most attract/idle frames are
     * unchanged -> near-zero cost, which matters a lot on a chip-RAM-bound
     * stock A1200. */
    {
        const unsigned char *v = vram, *o = obj;
        unsigned int sig = 2166136261u;
        for (int a = 0; a < 0x400; a++) sig = (sig ^ v[a]) * 16777619u;
        for (int a = 0; a < 0x60;  a++) sig = (sig ^ o[a]) * 16777619u;
        int id = mc_buffer_id & 1;
        /* don't skip while stars are scrolling -- the frame changes every tick */
        if (!machine_io.stars_enabled && sig == shadow_sig[id]) return;
        shadow_sig[id] = sig;
    }

    /* Clear the 5 planes. On Amiga the hook uses the blitter (instant under
     * the emulator; gentle on chip RAM on real hw). Host hook is NULL -> CPU. */
    if (mc_clear_hook) {
        mc_clear_hook(mc_planes);
    } else {
        unsigned int *q = (unsigned int *)mc_planes;
        int n = (MC_PLANE_SZ * 5) / 4;
        while (n--) *q++ = 0;
    }

    for (int row = 0; row < 32; row++) {
        for (int col = 0; col < 32; col++) {
            int tile = extend_tile(vram[(row * 32 + col) & 0x3ff]);
            int C  = obj[(col * 2 + 1) & 0xff] & 0x07;   /* colour set -> planes 2..4 */
            int scrollY = obj[(col * 2) & 0xff] & 0xff;
            int px = col * 8;
            int py = (row * 8 - scrollY) & 0xff;

            /* Skip fully-transparent tiles (most of the screen in attract). */
            const unsigned char *tm = tcm[tile];
            { int any = 0; for (int x = 0; x < 8; x++) any |= tm[x]; if (!any) continue; }

            /* Edge tiles that straddle the visible window: per-pixel fallback
             * (rare -- only the top/bottom row under per-column scroll). */
            if (!(py + 7 <= 239 && py >= 16)) {
                const unsigned char *p0 = mc_char + tile*8, *p1 = mc_char + tile*8 + 0x1000;
                for (int y = 0; y < 8; y++) {
                    int b0 = p0[y], b1 = p1[y], ny = (py + y) & 0xff;
                    if (ny < 16 || ny > 239) continue;
                    int sx = 239 - ny;
                    for (int x = 0; x < 8; x++) {
                        int sh = 7 - x, pen = ((b0 >> sh) & 1) | (((b1 >> sh) & 1) << 1);
                        if (pen) plot(sx, MC_VMAIN((px + x) & 0xff), (C*4 + pen) & 31);
                    }
                }
                continue;
            }

            /* Fast path: whole tile visible. Each of the 8 dest rows gets an
             * 8-pixel run (1-2 byte ORs per plane), shifted to the ROT90 X. */
            int leftX = 232 - py, byteX = leftX >> 3, sh = leftX & 7;
            int p2 = C & 1, p3 = (C >> 1) & 1, p4 = (C >> 2) & 1;
            for (int x = 0; x < 8; x++) {
                unsigned r0 = tc0[tile][x], r1 = tc1[tile][x], rm = tcm[tile][x];
                if (!rm) continue;
                int Y = MC_VMAIN((px + x) & 0xff);
                unsigned char *base = mc_planes + Y * MC_ROW_BYTES + byteX + MC_HSHIFT;
                unsigned v0 = ((unsigned)r0 << 8) >> sh;
                unsigned v1 = ((unsigned)r1 << 8) >> sh;
                unsigned vm = ((unsigned)rm << 8) >> sh;
                base[0]            |= v0 >> 8; base[1]              |= v0 & 0xff;
                base[MC_PLANE_SZ]  |= v1 >> 8; base[MC_PLANE_SZ+1]  |= v1 & 0xff;
                if (p2){ base[MC_PLANE_SZ*2] |= vm >> 8; base[MC_PLANE_SZ*2+1] |= vm & 0xff; }
                if (p3){ base[MC_PLANE_SZ*3] |= vm >> 8; base[MC_PLANE_SZ*3+1] |= vm & 0xff; }
                if (p4){ base[MC_PLANE_SZ*4] |= vm >> 8; base[MC_PLANE_SZ*4+1] |= vm & 0xff; }
            }
        }
    }

    render_sprites(obj);
    render_bullets(obj);
    if (machine_io.stars_enabled) render_stars();   /* background, empty pixels only */
}

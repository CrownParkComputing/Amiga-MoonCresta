"""Twin Cobra attract-screen renderer (host validation). Decodes the gfx ROMs
per MAME gfxdecode (chars 3bpp / bg+fg tiles 4bpp / sprites 16x16 4bpp),
applies the xBGR555 palette from palette RAM, composites bg<fg<sprite<tx with
scroll, and writes a ROT270 PPM. Driven by tests/host/twincobr_host.py state.
Layout/format constants verified vs toaplan/twincobr_v.cpp + toaplan_scu.cpp.
"""
G = "games/twincobr/gfx"
def _cat(d, names):
    return b"".join(open(f"{G}/{d}/{n}", "rb").read() for n in names)

# regions assembled in ROM_LOAD offset order (verified vs ROM_START)
CHARS = _cat("chars",   ["b30_08.8c", "b30_07.10b", "b30_06.8b"])               # 0xc000, 3bpp
BG    = _cat("bg",      ["b30_12.16c","b30_11.14c","b30_10.12c","b30_09.10c"])  # 0x20000,4bpp
FG    = _cat("fg",      ["b30_16.20b","b30_15.18b","b30_13.18c","b30_14.20c"])  # 0x40000,4bpp
SPR   = _cat("sprites", ["b30_20.12d","b30_19.14d","b30_18.15d","b30_17.16d"])  # 0x40000,4bpp

def _tile8(rom, planes, code, pbytes):
    """Decode one 8x8 tile -> 8x8 list of pens. planes=list of plane base offsets."""
    out = []
    for r in range(8):
        row = []
        for x in range(8):
            pen = 0
            for p, base in enumerate(planes):
                b = rom[base + code * 8 + r]
                pen |= ((b >> (7 - x)) & 1) << p
            row.append(pen)
        out.append(row)
    return out

def _spr16(code):
    """Decode one 16x16 4bpp sprite -> 16x16 pens."""
    q = 0x10000
    planes = [0, q, q * 2, q * 3]
    out = []
    for r in range(16):
        row = []
        for x in range(16):
            pen = 0
            for p, base in enumerate(planes):
                w = (SPR[base + code * 32 + r * 2] << 8) | SPR[base + code * 32 + r * 2 + 1]
                pen |= ((w >> (15 - x)) & 1) << p
            row.append(pen)
        out.append(row)
    return out

def render_attract(txvram, bgvram, fgvram, scroll, latch, sprite_bytes, palette_bytes, out):
    # palette: 1792 xBGR555 words (big-endian in 68K mem)
    pal = []
    for i in range(1792):
        w = (palette_bytes[i*2] << 8) | palette_bytes[i*2+1]
        r = (w & 0x1f) << 3; g = ((w >> 5) & 0x1f) << 3; b = ((w >> 10) & 0x1f) << 3
        pal.append((r, g, b))
    chp = [0, 0x4000, 0x8000]
    bgp = [0, 0x8000, 0x10000, 0x18000]
    fgp = [0, 0x10000, 0x20000, 0x30000]
    cache = {}
    def tile(kind, code):
        k = (kind, code)
        if k in cache: return cache[k]
        if   kind == "tx": t = _tile8(CHARS, chp, code, 8)
        elif kind == "bg": t = _tile8(BG, bgp, code, 8)
        elif kind == "fg": t = _tile8(FG, fgp, code, 8)
        else:              t = _spr16(code)
        cache[k] = t; return t

    W, H = 320, 240
    img = [[(0, 0, 0)] * W for _ in range(H)]
    fgbank = latch[5] * 0x1000

    def blit_layer(vram, cols, rows, sx, sy, kind, cmask, cshift, palbase, palstep, opaque):
        for y in range(H):
            vy = (y + sy) % (rows * 8)
            for x in range(W):
                vx = (x + sx) % (cols * 8)
                ent = vram[(vy // 8) * cols + (vx // 8)]
                if kind == "tx": code = ent & 0x7ff
                elif kind == "fg": code = (ent & 0xfff) | fgbank
                else: code = ent & 0xfff
                pen = tile(kind, code)[vy % 8][vx % 8]
                if pen == 0 and not opaque: continue
                color = (ent >> cshift) & cmask
                img[y][x] = pal[palbase + color * palstep + pen]

    # bg (opaque) -> fg -> sprites -> tx (top)
    blit_layer(bgvram, 64, 64, scroll["bgx"], scroll["bgy"], "bg", 0xf, 12, 1024, 16, True)
    blit_layer(fgvram, 64, 64, scroll["fgx"], scroll["fgy"], "fg", 0xf, 12, 1280, 16, False)
    # sprites (4 words each; sx>>7 - 31, sy>>7 - 16; skip pri 0 / sy==0x100)
    def w(i): return (sprite_bytes[i*2] << 8) | sprite_bytes[i*2+1]
    for offs in range(0, 0x800, 4):
        attr = w(offs + 1)
        if not (attr & 0x0c00): continue
        sy = w(offs + 3) >> 7
        if sy == 0x0100: continue
        code = w(offs) & 0x7ff; color = attr & 0x3f
        fx = (attr >> 8) & 1; fy = (attr >> 9) & 1
        sx = (w(offs + 2) >> 7) - 31; sy -= 16
        spr = tile("spr", code)
        for r in range(16):
            for c in range(16):
                pen = spr[15 - r if fy else r][15 - c if fx else c]
                if pen == 0: continue
                px, py = sx + c, sy + r
                if 0 <= px < W and 0 <= py < H:
                    img[py][px] = pal[color * 16 + pen]
    blit_layer(txvram, 64, 32, scroll["txx"], scroll["txy"], "tx", 0x1f, 11, 1536, 8, False)

    # also emit the unrotated 320x240 framebuffer (fits Amiga 320x256)
    with open(out.replace(".ppm", "_raw.ppm"), "wb") as f:
        f.write(f"P6\n{W} {H}\n255\n".encode())
        raw = bytearray(W * H * 3)
        for y in range(H):
            for x in range(W):
                o = (y * W + x) * 3
                raw[o], raw[o+1], raw[o+2] = img[y][x]
        f.write(raw)

    # ROT270 (vertical cab): 320x240 -> 240x320, pixel (x,y)->(y, W-1-x)
    RW, RH = H, W
    with open(out, "wb") as f:
        f.write(f"P6\n{RW} {RH}\n255\n".encode())
        buf = bytearray(RW * RH * 3)
        for y in range(H):
            for x in range(W):
                rx, ry = y, (W - 1 - x)
                o = (ry * RW + rx) * 3
                buf[o], buf[o+1], buf[o+2] = img[y][x]
        f.write(buf)
    return out

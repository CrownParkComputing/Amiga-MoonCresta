/* src/hal/video.h
 * ============================================================
 *  Video HAL -- public C API for the 68k assembly routines
 *  in src/hal/video.s.
 * ============================================================
 *
 * Mirrors the Namco Pacland video hardware (per MAME
 * namco/pacland.cpp), expressed in terms an Amiga can do:
 *
 *   - 2 tilemaps, 8x8 tiles, 64x32 cells (= 2048 tiles each)
 *   - 64 sprites, 4 bytes of state each (num, color, x_lo, y_lo+flags)
 *   - 1024 arcade colors / 4 banks / 256 visible at a time
 *   - Display 288x224 (NTSC Pacland) -- on Amiga 320x256 PAL
 *     this renders centred with a 16-pixel black border
 *
 * The HAL is game-agnostic. The video HW of Pacmania / Galaga90
 * differs in tilemap count and tile size; those differences
 * live in the per-game META.toml, not in this code.
 */
#ifndef NAMCO_AMIGA_HAL_VIDEO_H
#define NAMCO_AMIGA_HAL_VIDEO_H

#include <stdint.h>

/* ============================================================
 *  Display geometry (288x224 Pacland visible, 320x256 Amiga PAL)
 * ============================================================ */
#define HAL_VIDEO_W          288
#define HAL_VIDEO_H          224
#define HAL_VIDEO_BPP        4
#define HAL_VIDEO_TILE       8

/* Amiga screen dimensions (PAL lowres, overscan-ish) */
#define HAL_AMIGA_W          320
#define HAL_AMIGA_H          256
/* Black border around the 288x224 game image, centred */
#define HAL_AMIGA_XOFF       ((HAL_AMIGA_W - HAL_VIDEO_W) / 2)   /* 16 */
#define HAL_AMIGA_YOFF       ((HAL_AMIGA_H - HAL_VIDEO_H) / 2)   /* 16 */

/* ============================================================
 *  Tilemap geometry
 * ============================================================ */
#define HAL_TILEMAP_W        64
#define HAL_TILEMAP_H        32
#define HAL_TILEMAP_CELLS    (HAL_TILEMAP_W * HAL_TILEMAP_H)
#define HAL_NUM_TILEMAPS     2

/* ============================================================
 *  Sprite geometry
 * ============================================================ */
#define HAL_MAX_SPRITES      64
#define HAL_SPRITE_BYTES     4    /* num, color, x_lo, y_lo+flags */
#define HAL_SPRITE_SIZE      16   /* 16x16 sprite pixel size */

/* ============================================================
 *  Palette geometry
 * ============================================================ */
#define HAL_PALETTE_COLORS   32   /* Amiga 12-bit colour RAM limit */
#define HAL_PALETTE_BANKS    4    /* arcade has 4 banks of 256 */

/* ============================================================
 *  Public API -- called from amiga_main, from handlers, and
 *  from the 6809 emulator via the dispatch table.
 * ============================================================ */

/* Lifecycle: open the screen, set up the copper list, allocate
 * double-buffered bitplane RAM. Called once at startup. */
void hal_video_open(void);

/* Per-frame: upload all sprite + tilemap state from the 6809
 * RAM, swap the copper list, wait for vsync. */
void hal_video_frame(void);

/* Sprite DMA hook: called by the dispatch when the 6809 writes
 * to the sprite register window. Slot 0..HAL_MAX_SPRITES-1.
 * num: tile index into the GFX ROM
 * x,y: pixel position (y is negative for "off top of screen")
 * color: 0..255 (high bit = cookie-cut priority mask)
 * flags: TILE_FLIPX | TILE_FLIPY from the MAME source */
void hal_sprite_set(uint8_t slot, uint8_t num, uint8_t color,
                    uint16_t x, uint16_t y, uint8_t flags);

/* Tilemap upload: write one 8x8 tile's palette-indexed pixels
 * into the bitplane RAM. layer=0 (bg) or 1 (fg); col/row in
 * tile units. data is HAL_TILEMAP_TILE_BYTES bytes. */
void hal_tilemap_set(uint8_t layer, uint8_t col, uint8_t row,
                     const uint8_t *data);

/* Palette bank switch: 0..3. The arcade's CUS30/4A has 1024
 * colours; the visible 256 live in one of 4 banks. We map to
 * the Amiga's 32-color palette by hashing (bank + tile-color). */
void hal_palette_set_bank(uint8_t bank);

/* Direct palette write: index 0..31, r/g/b in 4-bit Amiga
 * 12-bit colour format. */
void hal_palette_set(uint8_t idx, uint16_t rgb12);

/* Read the current stub counter. The HAL bumps it on every
 * call; useful for "is anything happening?" diagnostics. */
extern uint32_t hal_video_frame_count;

#endif /* NAMCO_AMIGA_HAL_VIDEO_H */

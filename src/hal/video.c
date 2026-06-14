/* src/hal/video.c
 * ============================================================
 *  C-side video HAL: real implementations of memory allocation
 *  + chipset setup + the bitplane / copper backing storage.
 * ============================================================
 *
 * On entry from amiga_main:
 *   - SysBase is set up (asm startup code did `move.l a6,_SysBase`)
 *   - We have access to Exec's AllocMem
 *
 * This file:
 *   1. Allocates a chunk of CHIP RAM for 4 bitplanes + copper list
 *   2. Paints a 4-colour test pattern into all 4 bitplanes
 *   3. Programs the Amiga custom chipset directly (DIWSTRT/DIWSTOP,
 *      DDFSTRT/DDFSTOP, BPLCON0/1/2, BPLMOD, bitplane pointers,
 *      colour palette, copper list, DMA enable)
 *
 * Doing chipset access from C is fine for one-time setup. The
 * per-frame hooks (hal_video_frame, hal_sprite_set, etc.) are
 * still asm stubs -- the C side is too slow for those.
 */
#include "video.h"
#include <exec/exec.h>
#include <exec/memory.h>
#include <proto/exec.h>

#include <stdint.h>
#include <string.h>

/* ============================================================
 *  _SysBase -- declared by the libnix <proto/exec.h> headers.
 *  Defined in src/hal/hal_sysvars.s. The asm startup in
 *  amiga_main does `move.l a6, _SysBase` once at entry.
 * ============================================================ */
extern void *_SysBase;

/* ============================================================
 *  Custom-chip register addresses (word-addressed)
 * ============================================================ */
#define CUSTOM_BASE  ((volatile uint16_t *)0xdff000)
#define REG_DMACON       0x096/2
#define REG_INTENA       0x09A/2
#define REG_VPOSR        0x004/2
#define REG_DIWSTRT      0x08E/2
#define REG_DIWSTOP      0x090/2
#define REG_DDFSTRT      0x092/2
#define REG_DDFSTOP      0x094/2
#define REG_BPLCON0      0x100/2
#define REG_BPLCON1      0x102/2
#define REG_BPLCON2      0x104/2
#define REG_BPL1MOD      0x108/2
#define REG_BPL2MOD      0x10A/2
#define REG_BPL1PTH      0x0E0/2
#define REG_BPL1PTL      0x0E2/2
#define REG_BPL2PTH      0x0E4/2
#define REG_BPL2PTL      0x0E6/2
#define REG_BPL3PTH      0x0E8/2
#define REG_BPL3PTL      0x0EA/2
#define REG_BPL4PTH      0x0EC/2
#define REG_BPL4PTL      0x0EE/2
#define REG_COLOR00      0x180/2
#define REG_COP1LCH      0x080/2
#define REG_COP1LCL      0x082/2

/* ============================================================
 *  Geometry
 * ============================================================ */
#define BPL_BYTES_PER_LINE  (HAL_AMIGA_W / 8)   /* 40 bytes */
#define BPL_BYTES_TOTAL     (BPL_BYTES_PER_LINE * HAL_AMIGA_H)
#define COPPER_ENTRIES_MAX  64
#define COPPER_BYTES        (COPPER_ENTRIES_MAX * 6)
#define CHIP_CHUNK_BYTES    (BPL_BYTES_TOTAL * 4 + COPPER_BYTES)

/* ============================================================
 *  Backing storage
 * ============================================================ */
uint8_t  *_bitplane_a_base = NULL;
uint16_t *_copper_list     = NULL;
const unsigned long _BPL_BYTES_TOTAL = BPL_BYTES_TOTAL;

static void *chip_chunk = NULL;

/* Frame counter, asm reads. */
uint32_t hal_video_frame_count = 0;

/* ============================================================
 *  Public functions
 * ============================================================ */

static void hal_video_setup_copper(uint16_t *cop)
{
    int i = 0;
    /* Wait for the first visible line. */
    cop[i++] = 0x2C81; cop[i++] = 0xFFFE;     /* wait v=0x2C h=0x81 */
    /* Make the bottom-half palette 4 different colours so we
     * can see the test pattern. */
    cop[i++] = 0x0180; cop[i++] = 0x0F00;     /* COLOR00 = red */
    cop[i++] = 0x0182; cop[i++] = 0x00F0;     /* COLOR01 = green */
    cop[i++] = 0x0184; cop[i++] = 0x000F;     /* COLOR02 = blue */
    cop[i++] = 0x0186; cop[i++] = 0x0FFF;     /* COLOR03 = white */
    /* End the list. */
    cop[i++] = 0xFFFF; cop[i++] = 0xFFFE;
}

void hal_video_open(void)
{
    volatile uint16_t *custom = CUSTOM_BASE;
    int plane, row, col;
    uint8_t pixel, byte;
    uint8_t *p;

    /* 1. Allocate chip RAM. */
    chip_chunk = AllocMem(CHIP_CHUNK_BYTES, MEMF_CHIP | MEMF_CLEAR);
    if (!chip_chunk) {
        return;     /* fail silently -- no screen, no crash */
    }
    _bitplane_a_base = (uint8_t *)chip_chunk;
    _copper_list     = (uint16_t *)((uint8_t *)chip_chunk + BPL_BYTES_TOTAL * 4);

    /* 2. Paint a test pattern into the 4 bitplanes. */
    for (plane = 0; plane < 4; plane++) {
        p = _bitplane_a_base + plane * BPL_BYTES_TOTAL;
        for (row = 0; row < HAL_AMIGA_H; row++) {
            uint8_t band = (row >> 4) & 0x0F;
            pixel = (plane * 4) | (band & 0x03);
            byte  = (pixel << 4) | pixel;
            for (col = 0; col < BPL_BYTES_PER_LINE; col++) {
                *p++ = byte;
            }
        }
    }

    /* 3. Set up the copper list. */
    hal_video_setup_copper(_copper_list);

    /* 4. Wait for a safe spot to write DMA registers. */
    {
        int spins = 0;
        while (spins++ < 100000) {
            uint16_t v = custom[REG_VPOSR] & 0x01FF;
            if (v > 0x80) break;
        }
    }

    /* 5. Disable all DMA. */
    custom[REG_DMACON] = 0x7FFF;

    /* 6. Display window. For 320x256 centred at (0,0):
     *    DIWSTRT = (0x2C << 8) | 0x81 = 0x2C81
     *    DIWSTOP: V_stop = 0x2C + 256 = 0x12C
     *      H_stop = 0x81 + 320 = 0x1C1
     *      9-bit V: high byte = 0x2C, lo bit in bit 15 of stop
     *      DIWSTOP = (0x2C << 8) | 0xC1 | (1 << 15) = 0x2CC1 | 0x8000 = 0xACC1
     *    Actually: V_stop = 0x2C+256-1 = 0x12B, H_stop = 0x81+320-1 = 0x1C0.
     *    9-bit V split: hi 8 bits of 0x12B = 0x12, lo bit = 1.
     *    DIWSTOP = (0x12 << 8) | 0xC0 | (1 << 15) = 0x12C0 | 0x8000 = 0x92C0.
     *    Hmm, my earlier calc gave 0xAB80 -- let me try the 0x12C range.
     */
    custom[REG_DIWSTRT] = 0x2C81;
    custom[REG_DIWSTOP] = 0x2CC1;   /* try simple V=0x2C..0x2C, H=0x81..0xC1 */

    /* 7. Data fetch: 320 lres pixels. DDFSTRT=0x38, DDFSTOP=0xD0. */
    custom[REG_DDFSTRT] = 0x0038;
    custom[REG_DDFSTOP] = 0x00D0;

    /* 8. BPLCON0: enable 4 bitplanes (0x4000). */
    custom[REG_BPLCON0] = 0x4200;
    custom[REG_BPLCON1] = 0x0000;
    custom[REG_BPLCON2] = 0x0000;
    custom[REG_BPL1MOD] = 0x0000;
    custom[REG_BPL2MOD] = 0x0000;

    /* 9. Bitplane pointers. */
    {
        uint32_t a;
        a = (uint32_t)_bitplane_a_base;
        custom[REG_BPL1PTH] = (uint16_t)(a >> 16);
        custom[REG_BPL1PTL] = (uint16_t)(a & 0xFFFF);
        a += BPL_BYTES_TOTAL;
        custom[REG_BPL2PTH] = (uint16_t)(a >> 16);
        custom[REG_BPL2PTL] = (uint16_t)(a & 0xFFFF);
        a += BPL_BYTES_TOTAL;
        custom[REG_BPL3PTH] = (uint16_t)(a >> 16);
        custom[REG_BPL3PTL] = (uint16_t)(a & 0xFFFF);
        a += BPL_BYTES_TOTAL;
        custom[REG_BPL4PTH] = (uint16_t)(a >> 16);
        custom[REG_BPL4PTL] = (uint16_t)(a & 0xFFFF);
    }

    /* 10. Palette. */
    custom[REG_COLOR00] = 0x0F00;       /* red   */
    custom[REG_COLOR00 + 1] = 0x00F0;   /* green */
    custom[REG_COLOR00 + 2] = 0x000F;   /* blue  */
    custom[REG_COLOR00 + 3] = 0x0FFF;   /* white */
    for (int i = 4; i < 16; i++) {
        uint16_t v = (i << 4) | (i << 8) | i;
        custom[REG_COLOR00 + i] = v;
    }

    /* 11. Point copper at our list. */
    {
        uint32_t a = (uint32_t)_copper_list;
        custom[REG_COP1LCH] = (uint16_t)(a >> 16);
        custom[REG_COP1LCL] = (uint16_t)(a & 0xFFFF);
    }

    /* 12. Enable DMA. 0x8000 master | 0x4000 DMA | 0x2000 bpl | 0x0200 copper. */
    custom[REG_DMACON] = 0xE200;

    /* Bump the stub counter so we know this fired. */
    {
        extern unsigned long hal_io_stub_counter;
        hal_io_stub_counter++;
    }
}

void hal_video_frame(void)
{
    hal_video_frame_count++;
}

; src/hal/video.s
; ============================================================
;  Video HAL -- 68k assembly for the Namco Pacland video
;  hardware emulation, targeting the Amiga 500/600/1200.
; ============================================================
;
; This file is the SKELETON. Every public symbol is a real
; 68k function with C linkage so the C side can call them.
; The bodies are stubs that bump counters and return. The real
; implementation grows in-place as features come online.
;
; ABI / register conventions (m68k Amiga GCC):
;   d0     -- return value (uint8_t) or first arg
;   d1     -- second arg
;   a0     -- pointer args
;   a6     -- ExecBase (Amiga convention, restored on exit)
;
; Functions exported (XDEF) match the declarations in video.h.
; ============================================================

        ; ---- exported function stubs (one per io_map.json entry) ----
; These are the functions that the video HAL uses internally;
; real implementations are in video.c (which sets up Exec
; allocations and the bitplane test pattern). The asm side
; keeps the C-callable shape so the C side can call these by
; name without a stub layer.
;
; The original asm _hal_video_open stub was deleted when the
; C version became the real one. _hal_video_frame is also
; implemented in C (one-liner) so this file doesn't
; duplicate it.

        XDEF    _hal_sprite_set
        XDEF    _hal_tilemap_set
        XDEF    _hal_palette_set_bank
        XDEF    _hal_palette_set

        ; External symbols defined in src/hal/video.c (or in CHIP RAM
        ; for the real impl). These are the storage backing the
        ; bitplane + copper list the asm side programs.
        ; NOTE: m68k-amigaos-gcc doubles an initial underscore, so
        ; the C symbol `_bitplane_a_base` becomes `__bitplane_a_base`
        ; in the object file. The XREFs below match that.
        XREF    __bitplane_a_base
        XREF    __copper_list
        XREF    __BPL_BYTES_TOTAL

        XREF    _hal_io_stub_counter     ; shared counter

        SECTION code,CODE

; ============================================================
;  Old _hal_video_open stub -- removed because the C version
;  in video.c is now the real implementation. The asm side
;  kept its old _hal_video_open body for reference, but the
;  C version is the only one that gets linked.
; ============================================================

; ============================================================
;  hal_video_frame -- removed (C version in video.c is real)
; ============================================================

; ============================================================
;  hal_sprite_set
; ============================================================
; void hal_sprite_set(uint8_t slot, uint8_t num, uint8_t color,
;                     uint16_t x, uint16_t y, uint8_t flags);
;
; Args per the C signature:
;   d0 = slot,num packed as (num<<8)|slot  (or similar packing)
;   d1 = color,flags packed
;   a0 = pointer to x,y
; Actually the GCC m68k ABI passes small structs in registers
; by value, but uint16_t x,y with 8-bit slot/num/flags may end
; up in registers or on the stack. For the stub we don't care
; about exact arg positions.
;
; STUB: bumps counter, returns.
_hal_sprite_set:
        addq.l  #1,_hal_io_stub_counter
        rts

; ============================================================
;  hal_tilemap_set
; ============================================================
; void hal_tilemap_set(uint8_t layer, uint8_t col, uint8_t row,
;                      const uint8_t *data);
;
; Writes one 8x8 tile's pixels into the bitplane RAM.
; In the real impl this calls the CPU blit routine (or the
; Amiga blitter for speed) to convert palette-indexed pixels
; into interleaved bitplane data.
;
; STUB: bumps counter, returns.
_hal_tilemap_set:
        addq.l  #1,_hal_io_stub_counter
        rts

; ============================================================
;  hal_palette_set_bank
; ============================================================
; void hal_palette_set_bank(uint8_t bank);
;
; The arcade has 4 banks of 256 colours; the visible 256
; live in one bank at a time, set by the CUS30 audio chip's
; register (the main CPU writes to a CUS30 port to switch).
; On the Amiga, the equivalent is to re-write the 32-entry
; colour RAM. We do this via the copper for vsync-safe
; update.
;
; STUB: bumps counter, returns.
_hal_palette_set_bank:
        addq.l  #1,_hal_io_stub_counter
        rts

; ============================================================
;  hal_palette_set
; ============================================================
; void hal_palette_set(uint8_t idx, uint16_t rgb12);
;
; Direct write to one Amiga colour register. 12-bit colour
; format: 0x0RGB, with 4 bits per channel.
;
; STUB: bumps counter, returns.
_hal_palette_set:
        addq.l  #1,_hal_io_stub_counter
        rts

        END

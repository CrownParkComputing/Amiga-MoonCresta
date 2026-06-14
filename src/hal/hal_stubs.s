; src/hal/hal_stubs.s
; ============================================================
;  HAL stubs -- bridge between the C interpreter cores and the
;  Amiga runtime.
; ============================================================
;
; The vendored C cores in src/cores/ declare external symbols
; the host environment must provide. The linker errors from
; `make all` told us exactly which ones are missing; this file
; supplies minimal stubs so the binary links and runs.
;
; Symbols:
;   _setjmp         -- POSIX setjmp(buf) -> 0 on first call,
;                       nonzero on longjmp back
;   _longjmp        -- POSIX longjmp(buf, val) -> never returns
;   ___assert_func  -- Libnix's assert() target
;   _in_impl        -- z80 I/O port read (the game's I/O hook)
;   _out_impl       -- z80 I/O port write (the game's I/O hook)
;
; As the real HAL grows, only the in_impl / out_impl part is
; replaced (with io_map.json-driven dispatchers). The setjmp
; and assert stubs stay for the lifetime of the C cores.

        XDEF    _setjmp
        XDEF    _longjmp
        XDEF    ___assert_func
        XDEF    _in_impl
        XDEF    _out_impl

        SECTION code,CODE

; --- _setjmp ---
; On entry, a0 = jmp_buf* (a 12-longword array of saved regs).
; We save d2-d7, a2-a6, return 0.
; On longjmp, we restore d2-d7, a2-a6, return the val in d0.
;
; Layout of jmp_buf on Amiga: 12 longs, in order d2..d7 a2..a6.
; The C declaration is `int setjmp(jmp_buf)` returning int.

_setjmp:
        movem.l d2-d7/a2-a6,(a0)         ; save caller's regs
        moveq   #0,d0
        rts

; --- _longjmp ---
; On entry, a0 = jmp_buf*, d0 = val.
; We restore d2-d7, a2-a6, return the val in d0.
; Val 0 is normalized to 1 (POSIX requirement).

_longjmp:
        movem.l (a0),d2-d7/a2-a6         ; restore caller's regs
        tst.l   d0
        bne.s   .not_zero
        moveq   #1,d0                    ; longjmp(buf, 0) => 1
.not_zero:
        rts

; --- ___assert_func: Libnix's assert() target ---
___assert_func:
.loop:  bra.s   .loop                    ; hang so a debugger catches it

; --- _in_impl: z80 I/O port read, stub returns 0xff ---
_in_impl:
        moveq   #-1,d0
        rts

; --- _out_impl: z80 I/O port write, stub swallows ---
_out_impl:
        rts

        END

; src/amiga/amiga.s
; ============================================================
;  amiga_main -- the HAL entry point invoked by the WHDLoad slave
;  OR called directly as a CLI command.
; ============================================================
;
; On entry (WHDLoad slave case):
;   sp+4 = ExecBase (a6 was pushed by slave)
; On entry (CLI case):
;   a6 = ExecBase (passed by AmigaOS startup)
;   a4 may or may not be set (small-data base)
;
; We use the 68k asm to:
;   1. Set up SysBase (libnix-style: store a6 at _SysBase)
;   2. Allocate a small stack frame
;   3. Call the C-side hal_video_open (does AllocMem + chipset)
;   4. Enter a "wait for left mouse" loop so the screen is
;      visible until the user dismisses it
;   5. Return cleanly
;
; The interpreter cores (m6809, z80) and dispatch table are
; already linked in. Once the 6809 ROMs are loaded and
; dispatched, the per-frame orchestrator goes in here.
; ============================================================

        XDEF    amiga_main
        XREF    _SysBase
        XREF    _hal_game_init
        XREF    _hal_game_frame

        SECTION code,CODE

        SECTION bss,BSS

cpubase_save:  ds.l   1               ; execbase slot

        SECTION code,CODE

amiga_main:
        ; Load ExecBase the canonical way -- from absolute address 4.
        ; a6 is ExecBase under the WHDLoad slave contract, but NOT when
        ; we're launched as a normal CLI program from Startup-Sequence,
        ; so we must not trust it. Reading 4.w works in both cases.
        ; (Trusting a6 here caused error #80000004 -- illegal instruction
        ;  -- when AllocMem jumped through a garbage _SysBase.)
        move.l  4.w,a6
        ; Set _SysBase so the libnix-style C code can use AllocMem
        ; and other Exec functions. The symbol is declared in
        ; proto/exec.h.
        move.l  a6,_SysBase

        ; Stash registers, set up a small frame.
        link    a5,#-8
        movem.l d0-d7/a0-a5,-(sp)
        move.l  a6,cpubase_save

        ; One-time game init (sets up video, loads ROMs, resets CPU).
        bsr     _hal_game_init

.loop:
        ; Run + render one frame.
        bsr     _hal_game_frame

        ; Poll left mouse button via CIA-A PRA $bfe001 bit 6
        ; (active low).
        move.b  $bfe001,d0
        andi.b  #$40,d0               ; bit 6 = 0 means pressed
        bne.s   .loop                 ; loop until pressed

        ; Exit
        movem.l (sp)+,d0-d7/a0-a5
        unlk    a5
        moveq   #0,d0
        rts

        END

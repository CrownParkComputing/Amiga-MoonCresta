| src/hal/mc_native_glue.s  (GNU/MIT syntax, m68k-amigaos-as)
| ============================================================
|  mc_call(void *membase, void (*target)(void))
|  Run a transcoded routine with the z80268k register contract:
|  a6 = membase, registers zeroed by cpu_init. Saves/restores the
|  68k callee-saved registers the transcode clobbers (d2-d7/a2-a6).
| ============================================================
	.text
	.global	mc_call
	.global	cpu_init

mc_call:
	movem.l	d2-d7/a2-a6,-(sp)      | 11 longs = 44 bytes
	move.l	sp,mc_call_saved_sp
	move.l	48(sp),a6              | arg1: membase  (44 + 4 ret)
	move.l	52(sp),a0              | arg2: target
	jbsr	cpu_init               | zero data-reg high words (z80268k req)
	| Push our own return address inside the Z80 memory block. Moon Cresta uses
	| ld sp,hl to switch task stacks, so a7 must live in the emulated address
	| space, not on a private host stack.
	lea	mc_call_ret(pc),a1
	lea	0x8400(a6),a7
	move.l	a7,z80_sp_base
	move.l	a1,(a7)                | return address at Z80 SP base
	jmp	(a0)                   | enter target (return already pushed)
mc_call_ret:
	move.l	mc_call_saved_sp,sp
	movem.l	(sp)+,d2-d7/a2-a6
	rts

| Register-spill cells the transcode references (bare GNU-as names so they
| match z80268k's output -- defining these in C mismatched the symbol).
	.data
	.global	de
	.global	hl
	.global	aprime
	.global	fprime
	.global	z80_sp_base
de:	.long	0
hl:	.long	0
z80_sp_base:	.long	0
mc_call_saved_sp:	.long	0
aprime:	.byte	0
fprime:	.byte	0
	.even

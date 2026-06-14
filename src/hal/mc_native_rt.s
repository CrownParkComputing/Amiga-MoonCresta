| src/hal/mc_native_rt.s  (GNU/MIT syntax, m68k-amigaos-as)
| ============================================================
|  Native runtime -- the 60fps async model.
|
|  Moon Cresta is NMI-driven: the arcade CPU runs a main loop
|  continuously, and every vblank an NMI preempts it, runs one
|  frame of game logic (which never "returns" -- it resets the
|  stack and falls back into the main loop), and the cycle repeats.
|
|  We reproduce that exactly:
|   * run init once (l_0000, patched to rts after setup),
|   * take over the level-3 (vblank) interrupt,
|   * let the transcode run its main loop as the FOREGROUND,
|   * each vblank the ISR redirects execution into frame_entry,
|     which renders the frame the game just built, presents it,
|     then jumps into the Z80 NMI handler (l_0066) for the next
|     frame's logic. l_0066 ends back in the idle main loop until
|     the next vblank preempts it again.
| ============================================================
	.text
	.global	mc_run_native
	.global	cpu_init
	.global	l_0000
	.global	l_0066
	.global	l_0287

| void mc_run_native(void *membase) -- never returns.
mc_run_native:
	move.w	#0xf00,0xdff180       | red: native runtime entered
	move.l	4(sp),d0               | arg: membase
	move.l	d0,mc_membase_ptr
	move.l	d0,a0
	lea	0x8400(a0),a0          | Z80 stack base inside the 64K address space
	move.l	a0,z80_sp_base

	| --- run init (l_0000) to completion; it ends in a patched rts ---
	move.l	a0,a7                  | switch to the Z80 stack (abandon C stack)
	lea	after_init(pc),a1
	move.l	a1,(a0)                | [base] = where init's rts returns
	jbsr	cpu_init               | zero data-reg high words (z80268k contract)
	move.l	mc_membase_ptr,a6
	move.w	#0xf80,0xdff180       | orange: entering translated init
	jmp	l_0000                 | init: setup ... -> rts -> after_init

after_init:
	lea	mc_native_stack_top,a7  | C/Exec calls need a stable native stack
	move.w	#0x0f0,0xdff180       | green: init returned on native stack
	| --- take over the interrupt system (needs supervisor) ---
	move.l	_SysBase,a6
	lea	setup_ints(pc),a5
	jsr	-30(a6)                | Exec Supervisor(setup_ints)
	move.w	#0xff0,0xdff180       | yellow: interrupts installed
	jbsr	_mc_reassert_display   | re-point COP1LCH + DMACON (OS is now off)
	bra	frame_entry            | start the frame foreground

| Per-frame trampoline (re-entered from the vblank ISR via PC redirect).
| Render what the game built last frame, present it, then run the next
| frame's logic through the Z80 NMI handler.
frame_entry:
	lea	mc_native_stack_top,a7  | render/swap are C calls: use native stack
	move.w	#0x00f,0xdff180       | blue: rendering/presenting
	move.w	#0x0020,0xdff09a       | mask VERTB: render must be atomic (no
	|                                preempt-mid-render livelock if render is slow)
	move.l	mc_membase_ptr,-(sp)
	jbsr	_mc_render             | decode VRAM -> back buffer
	addq.l	#4,sp
	jbsr	_mc_swap               | present (no waitvbl -- we're in vblank)
	move.w	#0x0020,0xdff09c       | clear any VERTB that arrived during render
	move.w	#0x8020,0xdff09a       | re-arm VERTB before running game logic, so
	|                                a slow frame preempts/restarts the LOGIC, not
	|                                the render, and l_0066 always gets a fresh slot
	jbsr	cpu_init               | clean Z80 reg state for the frame
	move.l	mc_membase_ptr,a6
	move.l	z80_sp_base,a7
	move.l	#l_0287,(a7)           | simulate NMI return PC: resume idle foreground
	move.w	#0xf0f,0xdff180       | magenta: entering translated NMI
	jmp	l_0066                 | NMI handler -> frame work -> main loop idle

| --- supervisor: install our vblank vector, enable only VERTB ---
setup_ints:
	move.w	#0x2700,sr             | supervisor + ints masked during setup
	movec	vbr,a0                 | level-3 autovector lives at vbr+0x6c
	move.l	#vblank_isr,0x6c(a0)
	move.w	#0x7fff,0xdff09a       | INTENA: disable all OS interrupts
	move.w	#0x7fff,0xdff09c       | INTREQ: clear all pending
	move.w	#0xc020,0xdff09a       | enable INTEN(master) | VERTB
	rte                            | return to caller in user mode (ints on)

| --- level-3 (vblank) interrupt ---
| Exception frame on entry: 0(sp)=SR, 2(sp)=PC(.l), 6(sp)=format/vector.
| Acknowledge VERTB and redirect resumption to frame_entry. We never
| resume the interrupted foreground -- the NMI model discards it.
vblank_isr:
	move.w	#0x0020,0xdff09c       | ack VERTB
	move.l	#frame_entry,2(sp)     | overwrite the return PC
	rte

	.data
	.global	mc_membase_ptr
mc_membase_ptr:
	.long	0

	.bss
	.even
mc_native_stack:
	.space	8192
mc_native_stack_top:

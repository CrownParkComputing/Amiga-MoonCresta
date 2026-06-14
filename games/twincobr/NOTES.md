# Twin Cobra port notes

## Why this game (and the catch)

Picked as a 68000 arcade target so the **main CPU runs near-native on
Amiga** — no Z80-interpreter speed floor like Moon Cresta. That part holds.

The catch I flagged late: Twin Cobra is **three CPUs**, not one.

| CPU | Role | Amiga plan |
|-----|------|-----------|
| 68000 | main game logic | run near-native (the whole reason we're here) |
| Z80 | sound driver (YM3812/OPL2) | small; interpret with the vendored z80.c, or stub to samples |
| TMS32010 DSP | **protection + scroll/sprite math** | must emulate; the game hangs/misbehaves without it |

The DSP is the real work item. It's tiny (2KB program, simple Harvard DSP),
so an interpreter is cheap CPU-wise — but it does game-affecting math, so it
must be *correct*, not stubbed. Needs a TMS32010 core (none vendored yet;
MAME's tms32010 is the reference).

## No in-house oracle

Unlike Moon Cresta (zarcade had MoonCrestaBoard.kt), zarcade has **no Toaplan
model**. Validation reference = MAME `src/mame/drivers/twincobr.cpp` +
`video/twincobr.cpp`. No frame-accurate JVM oracle to diff against.

## Hardware (VERIFIED vs MAME toaplan/twincobr.cpp — full map in io_map.json)

Clocks (28 MHz XTAL): 68000 @ **7.0** (÷4), Z80 @ **3.5** (÷8), TMS32010 @
**14.0** (÷2).

68000 map highlights:
- `0x000000-0x02ffff` ROM ; `0x030000-0x033fff` work RAM **(= DSP shared window)**
- `0x040000-0x040fff` sprite RAM ; `0x050000-0x050dff` palette (xBGR555, 1792)
- `0x060001/3` CRTC addr/reg ; `0x070000-0x076003` per-layer scroll/offset
- `0x078000-0x078009` DSW1/DSW2/P1/P2/SYS(vblank+coin)
- `0x07800d` **DSP/system control latch** (the protection trigger)
- `0x07a000-0x07afff` Z80 shared RAM (= Z80 `0x8000-0x87ff`)
- `0x07e000/2/4` text/bg/fg VRAM **data ports**

⚠️ **Tile layers are not directly memory-mapped.** You set a VRAM address via
the CRTC (`0x060001/3`) then read/write through the data ports at `0x07e00x`
(Toaplan address-then-data). The renderer/HAL must model this indirection.

68000↔DSP: DSP reaches into `0x030000-0x033fff` via its ports 00(addr)/01(data);
68000 gates it through `0x07800d`. 68000↔Z80: `0x07a000` window. Get the DSP
handshake right *first* — scroll/sprite positions and protection depend on it.

## Build-status checklist

- [x] ROMs extracted + CRC32 verified, organized by role (maincpu/audiocpu/
      dsp/gfx/{chars,fg,bg,sprites}/proms)
- [x] META.toml
- [x] Verify 68000 byte-interleave + offsets vs twincobr.cpp ROM_START
      (even/odd ROM_LOAD16_BYTE; **also corrected an fg/bg gfx swap** my
      size-guess got wrong — fg=b30_13-16/64K, bg=b30_09-12/32K)
- [x] io_map.json — full 68000/Z80/DSP map, **verified verbatim against MAME
      `toaplan/twincobr.cpp`** (WebFetch, not from memory)
- [x] Host smoke harness — boots real 68000, maps the dependency chain
- [ ] Decide Z80 sound: interpret (z80.c, already vendored) vs sample-stub
- [x] **TMS32010 core (Python) — WRITTEN & VALIDATED**: `tools/tms320c10.py`,
      ported from MAME tms320c1x ISA + twincobr_m.cpp bridge. Wired into the
      harness; the DSP runs the real program, computes via the host bridge, and
      the 68000 **PASSES its self-test (the 0x76 result check)** and completes
      POST. Bug found/fixed in the port: ext-group opcodes decode as low&0x1f
      (EINT is 0x7f82→0x02), not low&0xff.
- [ ] Port the validated TMS320C10 to C (src/cores/) for the Amiga build.
- [x] **Vblank IRQ4 synthesized** in the harness (level-4 autovector @0x70:
      push PC+SR to SSP, PC=[0x70]) — machine68k has no IRQ API. mainlatch
      LS259 decoded (bit2=int_enable, bit6=dsp_int, etc.).
- [x] **ATTRACT MODE RUNS ON HOST.** Full stack: 68000 + real TMS320C10 +
      stubbed Z80 + synthesized IRQ4. Over 200M cycles: 825 IRQs serviced, 756
      DSP triggers, palette 2687/3584 loaded, sprite RAM 1785/4096 populated,
      not stuck. The harness is now the **validation oracle** for the port (the
      role zarcade played for Moon Cresta, which we lacked for Toaplan).
- [x] Model tilemap VRAM (offset regs 0x07x004 + data ports 0x07e00x; tx/bg/fg
      arrays in the harness; bg bank from latch bit4).
- [x] **ATTRACT SCREEN RENDERS CORRECTLY** (tools/twincobr_render.py -> PPM):
      decodes gfx ROMs (chars 3bpp planes {0,0x4000,0x8000}; bg/fg/sprite 4bpp
      RGN_FRAC quarters), xBGR555 palette, composites bg<fg<sprite<tx with
      scroll, ROT270. Output shows "GAME OVER" text + terrain bg + helicopter
      sprites = recognizable Twin Cobra. /tmp/twincobr_attract.png.
      Run: `python3 tests/host/twincobr_host.py 200 --render`.
- [x] **TMS320C10 ported to C** (src/cores/tms320c10.{c,h}). Compiles on host
      AND m68k-amigaos-gcc; PROVEN bit-identical to the Python core (4000-step
      PC-trace diff = 0, deterministic bridge). Test: tests/host/tms_ctest.c +
      tools/tms_pytrace.py.

## Amiga build (multi-session) -- execution-model decision

The arcade 68000 uses ABSOLUTE addresses ($040000 sprites, $050000 palette,
$07xxxx I/O) and runs from $0. Can't run natively on a no-MMU Amiga (those
addresses are chip RAM / the vector table). Two roads:
  - INTERPRET the 68000 (vendor a 68000 C core + machine.c-style HAL trapping
    MMIO) -- runs anywhere, SLOW (68k interpreting 7MHz 68k -> wants an 060).
    The proven Moon-Cresta pattern; port the validated Python harness 1:1.
  - MMU-NATIVE (030+): run arcade 68k native, MMU-fault on I/O. Fast, 030+ only.
Chosen: interpreter first (guaranteed boot, testable against the host oracle),
MMU-native as a later speed optimization.

- [x] **68000 core vendored (Musashi) + COMPILES FOR AMIGA.** Source from the
      machine68k bundle (same Musashi already running TC in our harness) ->
      src/cores/m68k/. Configured 68000-only (010/020/030/040/FPU/PMMU OFF;
      softfloat kept, inert). m68kmake generates m68kops.c. All compile clean
      with m68k-amigaos-gcc -m68020 (cpu 39K + ops 341K + softfloat 82K obj).
      BONUS: Musashi's C API has m68k_set_irq() -- the IRQ inject the Python
      machine68k binding lacked, so vblank IRQ4 is native on the Amiga build
      (no manual exception synthesis). HAL provides m68k_read/write_memory_*.
- [x] **machine_twincobr.c HAL DONE + VALIDATED + Amiga-compiles.** Direct C
      port of twincobr_host.py: Musashi memory callbacks decode the arcade map,
      DSP bridge, vblank IRQ4 via m68k_set_irq(4) (native!), Z80 ack, tilemap
      VRAM. Host test tests/host/twincobr_chost.c reproduces attract -- palette
      2687, tx 2048, bg 4096, fg 4096 all EXACT vs the Python reference; sprites
      populated. So the WHOLE emulation engine (68000+DSP+IRQ4+MMIO) runs in C.
      Compiles clean with m68k-amigaos-gcc. Link note: m68kcpu.c pulls sin/cos/
      sincos (inert 040 FPU code) -> the Amiga link needs tiny stubs for those.
- [x] **C renderer** src/hal/tc_render.c (pure C, host+Amiga): composites
      bg<fg<sprite<tx -> 320x240 arcade-index chunky buffer; tile/sprite decode
      verified. Host test tests/host/tc_render_chost.c -> PPM; text + sprites
      render correctly.
- [x] **LIVE EMULATION WORKS IN C — title screen renders!** Root cause of the
      restart loop FOUND + FIXED: init reads the game mode/counter from Z80 SHARED
      RAM (`move.w $7a00a,$31732`; `move.b $7a005,$31735`). m68k_read_memory_8 did
      NOT handle the 0x7a000-0x7b000 range (only the 16-bit reader did) -> it fell
      through to 0xff, so $31735=0xff (>=10) -> took the `bra $20194` restart path
      forever. Fix: read_memory_8 returns mem[a] for 0x7a000-0x7b000. Now IRQ4
      fires 398x (was 5-8), DSP 400x, NO restarts; the C HAL boots -> attract ->
      TITLE SCREEN (TWIN COBRA logo + helicopter + (C)1987 TOAPLAN) via tc_render.
      (POST still ~300 frames/5s due to vblank-synced mem tests -- a startup-delay
      perf nit, optimize sys_word later; not a blocker.)
- [ ] (was) boot POST memory tests -- RESOLVED above. Old notes:
      and grinds through per-region RAM-sizing tests (each marches mem until
      readback fails to find the region width). FIX so far: is_ram() limits
      RAM-backed regions to the REAL sizes (0x30000-0x33fff work, 0x40000-0x40fff
      sprite, 0x50000-0x50dff palette, 0x7a000-0x7afff z80) -- phantom RAM was
      thrashing it. Advanced boot (work-RAM test passes) BUT one region still
      mismatches -> POST RESTARTS in a loop (600fr=palette, 1500fr=back at work-
      RAM) -> IRQ4 only 1-8x vs ref 825, so the live main loop never runs.
      NARROWED: POST order = byte test (work RAM, 9 passes, D1=0x3ff9) PASSES;
      then WORD test (0x25d7a) on SPRITE RAM 0x40000 (D5=4 chunks x 0x200, A2=0x1ff
      words each) then PALETTE 0x50000 (A2=0x6ff). The sprite-RAM word test is
      FAILING its readback verify (trace: mismatch branch hit at A0=0x403fe),
      D7!=0 -> 0x25bf6 bne 0x25c7a (error) -> re-runs POST. NOT the watchdog
      (0x25b34 reset fires 0x), NOT a boot restart (0x20000 hit once). The word
      test does a VBLANK SYNC when D6==0x0a (polls 0x78009 bit7 before+after the
      write/verify) -- suspect the sprite-RAM readback or the vblank-sync timing
      (sys_word toggles on READ COUNT, not real frame time). NEXT: instruction-
      step the sprite-RAM word test in the C HAL vs a restricted-memory Python
      trace to find the exact mismatching word; fix; then C reaches live attract
      -> wire renderer to AGA + ADF. (Static-image ADF already works as the demo.)
- [ ] Wire renderer -> AGA bitplanes (extend tc_show.c; palette 1792->32/256
      quantize LUT) + Makefile/ADF (mirror mooncrst; stub sin/cos for the link).

## Static-image ADF (DONE -- "see it on Amiga" milestone)
build/twincobr.adf boots on A1200/AGA and shows a real attract frame (GAME
OVER + terrain + helicopters). Pipeline: render attract (tools/twincobr_render
.py -> /tmp/twincobr_attract_raw.ppm 320x240) -> quantize 32 colours -> 5
bitplanes (tools/tc_makeimg.py -> src/hal/tc_img.c) -> display via src/hal/
tc_show.c (reuses the mc_video.c 5-plane AGA path; hal_game_init shows it,
hal_game_frame idles). Built manually (vasm amiga.s+hal_sysvars.s+slave.s +
gcc tc_show.c+tc_img.c -> vlink build/twincobr_show 51K) -> xdftool ADF.
Config run/twincobr-a1200.uae. Image is LANDSCAPE (unrotated 320x240 fits
320x256); upright would need a taller/scaled mode. This is STATIC, not the
running game -- that's the interpreter+HAL+renderer build still ahead.
- [ ] Machine model: 68000 native exec model + DSP handshake + IRQ wiring
- [ ] Amiga HAL: 320x240 ROT270 render of text+fg+bg+sprites -> AGA bitplanes
- [ ] Host smoke test (mirror tests/host/mooncrst_host.c)

## Host smoke harness — findings (tests/host/twincobr_host.py)

Runs the real 68000 program on Musashi (machine68k), stubs DSP+Z80, traps
MMIO per io_map.json. It boots the ROM and surfaces each dependency in order.
**Validated: ROM interleave + reset vectors are correct** (reset SSP=0x032000,
PC=0x020194). Boot dependency chain it mapped (all addresses verbatim):

1. RAM march test over 0x030000-0x033fff — PASSES (slow in interp, ~18M cyc).
2. **Z80 sound test** @ 0x025e7e: writes cmd to 0x07a000, reads word back, low
   byte (0x07a001) must be 0xff (Z80 ack). Stubbed by faking the ack.
3. **DSP handshake** @ 0x023cb4: writes 0x0c then 0x0d to the 0x07800c control
   latch, then `tst.w 0x030000 / bne` waits for the DSP to ZERO 0x030000, then
   reads the result at 0x03000e.
4. **DSP RESULT VERIFY** @ 0x025e96: `bsr 0x23c98` (reads DSP output) then
   `cmpi.w #$76,D0` — boot HALTS unless the DSP computed 0x76.

**CONCLUSION (hard evidence): the TMS32010 is mandatory.** Faking only the
handshake (zero 0x030000) gets past step 3 but step 4 halts because the DSP's
*computed result* is checked. So the DSP can't be stubbed/HLE-handshaked away —
we need a real TMS32010 core OR faithful per-command HLE that reproduces its
math. This moves the DSP core to the critical path.

Known harness limit: machine68k exposes no IRQ injection. VBLANK here is a
POLLED bit (0x078009 bit7) so we toggle it; but the eventual vblank-driven
main loop will need an IRQ mechanism (or HLE the loop entry) later.

## Open questions / risks

1. **68000 execution model on Amiga.** It's 68k-on-68k, but NOT identical:
   different memory map, our renderer reads its VRAM, IRQ sources differ.
   Likely run the 68000 program in a relocated address window with a HAL that
   traps its MMIO (mirrors the machine.c approach, but for 68000).
2. **DSP correctness** is the make-or-break. Get the TMS32010 + the shared-RAM
   protection handshake right early; everything downstream depends on it.
3. **Asset size**: gfx total ~0.7MB (chars 48K + fg 128K + bg 256K + spr 256K).
   Converted to AGA bitplanes this is the main 2MB-budget consumer — measure
   before committing to a stock-A1200 target.

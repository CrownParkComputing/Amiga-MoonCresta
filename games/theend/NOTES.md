# The End -- conversion notes (next target after Moon Cresta)

**Hardware: Scramble family (Konami), NOT Galaxian.** ROMs staged here;
program confirmed unencrypted (entry `xor a; ld ($6801),a; jp $0069`).
Authoritative spec = zarcade `machine-scramble/` (port from it, same as we
did Moon Cresta from MoonCrestaBoard).

## What carries over from Moon Cresta
- The whole Amiga display path (`mc_video.c`: 5-bitplane AGA, double buffer,
  copper bitplane pointers, OS takeover) -- Scramble video is Galaxian-style.
- The tile renderer (`mc_render.c`) -- same 2bpp tiles + per-column attr/scroll;
  only the base addresses change (VRAM 0x4800, attr 0x5000, sprites 0x5040).
- The vendored Z80 core + the build/ADF pipeline + the generic disassembler.

## What's NEW for The End (the work)
1. **A Scramble machine model** (new `machine_scramble.c`, parallel to machine.c):
   - Memory map: ROM 0x0000-0x3fff, RAM 0x4000-0x47ff, VRAM 0x4800 (+mirror
     0x4c00), attr 0x5000, sprites 0x5040, bullets 0x5060.
   - Control writes: NMI 0x6801, coin 0x6802, stars 0x6804, flip 0x6806/7;
     watchdog 0x7000/0x7800.
   - **Two 8255 PPIs** at 0x8100 (inputs + sound command) / 0x8200 (dips +
     sound control + protection). Inputs are ACTIVE-LOW.
   - **Protection PAL** (nibble arithmetic) on PPI1 port C -- port
     `ScrambleMachine.protectionWrite/protectionResult` (state = (state<<4)|nibble;
     result read back on PPI1 port C bit7). Without it the game hangs.
2. **Render base-address parameterisation**: make mc_render take the VRAM/attr/
   sprite/bullet base (Moon Cresta 0x9000/0x9800 vs Scramble 0x4800/0x5000) so
   both share one renderer. (This is the start of the multi-board abstraction.)
3. **Sound** (later): second Z80 + 2x AY-3-8910; silent first.

## Build plan
- Add `machine_scramble.c` (memory routing + PPI + protection), select it for
  GAME=theend in the Makefile (like the mooncrst block).
- New `games/theend/io_map.json` (Scramble addresses).
- Reuse mc_video/mc_render (parameterised bases), embed ROMs (romdata gen),
  build ADF. Validate on host first (mc_render_test-style: run -> VRAM ->
  reconstruct attract) before Amiberry.

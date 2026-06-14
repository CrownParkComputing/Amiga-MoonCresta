#!/bin/bash
# Build the native (transcoded) Moon Cresta -> build/mooncrst_native + ADF.
# Pipeline: regenerate transcode -> z80fixup -> patch init -> assemble (GNU) +
# driver/renderer (gcc) -> link -> ADF. The 60fps path (no Z80 interpreter).
set -e
export PATH="/home/jon/amiga-amigaos/bin:$HOME/.local/bin:$PATH"
cd /home/jon/pacland-amiga
T=games/mooncrst/transcode
B=build/native
mkdir -p "$B"
Z80T=/home/jon/development/shinobi-amiga/refs/amiga68ktools/tools/z80268k.py

echo "== regenerate transcode + fixup =="
ROMS=games/mooncrst/roms/epr194,games/mooncrst/roms/epr195,games/mooncrst/roms/epr196,games/mooncrst/roms/epr197,games/mooncrst/roms/epr198,games/mooncrst/roms/epr199,games/mooncrst/roms/epr200,games/mooncrst/roms/epr201
python3 tools/z80disasm.py "$ROMS" \
    --trace "$T/coverage_trace.txt" \
    --entry 0,0x8,0x10,0x18,0x20,0x28,0x30,0x38,0x66,0x10a,0x326,0x380,0x3a3,0x3c6 \
    -o "$T/mooncrst_dis.asm"
python3 "$Z80T" -i mot -o mit -c "$T/mooncrst.68k" -I "$T/mooncrst.inc" "$T/mooncrst_dis.asm" 2>/dev/null | grep ratio | grep -iv 're\.' || true
python3 tools/z80fixup.py "$T/mooncrst.68k" "$T/mooncrst.inc"

echo "== patch init: jp \$0287 -> rts (init returns; runtime then drives frames) =="
# Async model: init runs to completion and returns to the runtime, which
# takes over the vblank interrupt and re-enters the game via l_0066. The
# reset path must include the $0072 setup block; only its final jump into
# the main idle loop is patched to return. The main loop is NOT patched --
# it idles as the foreground between vblanks.
python3 - <<'PY'
p='games/mooncrst/transcode/mooncrst.68k'
L=open(p).read().split('\n'); n=0
for i,l in enumerate(L):
    if 'jra\tl_0287' in l and '[$0091:' in l:
        L[i]='\trts\t| init returns to runtime (was jp $0287)'; n+=1; break
open(p,'w').write('\n'.join(L)); print(f"patched {n} site (init->rts)")
PY

echo "== generate jp(hl) dispatch table + append to transcode unit =="
# Append into mooncrst.68k so the (local) l_XXXX labels resolve in-unit.
python3 tools/gen_jmptab.py "$T/mooncrst.68k" >> "$T/mooncrst.68k"

echo "== assemble (GNU as): transcode(+jmptab) + glue =="
m68k-amigaos-as -m68020 --defsym MC68020=1 "$T/mooncrst.68k" -o "$B/mooncrst_z80.o"
m68k-amigaos-as -m68020 src/hal/mc_native_glue.s -o "$B/mc_native_glue.o"
m68k-amigaos-as -m68020 src/hal/mc_native_rt.s   -o "$B/mc_native_rt.o"

echo "== compile C (gcc -m68020): driver + renderer + romdata =="
GCC="m68k-amigaos-gcc -m68020 -noixemul -O2 -fomit-frame-pointer -I src/cores -I src/hal"
$GCC -c src/hal/mc_native.c  -o "$B/mc_native.o"
$GCC -c src/hal/mc_video.c   -o "$B/mc_video.o"
$GCC -c src/hal/mc_render.c  -o "$B/mc_render.o"
$GCC -c src/hal/mc_romdata.c -o "$B/mc_romdata.o"

echo "== assemble (vasm): startup glue =="
VASM="vasmm68k_mot -I src -I src/amiga -I src/hal -m68000 -phxass -nowarn=62 -Fhunk"
$VASM -o "$B/slave.o"       src/slave.s
$VASM -o "$B/amiga.o"       src/amiga/amiga.s
$VASM -o "$B/hal_sysvars.o" src/hal/hal_sysvars.s

echo "== link =="
vlink -b amigahunk -Bstatic -Cexestack -mrel -o build/mooncrst_native \
    "$B/slave.o" "$B/amiga.o" "$B/hal_sysvars.o" \
    "$B/mc_native.o" "$B/mc_video.o" "$B/mc_render.o" "$B/mc_romdata.o" \
    "$B/mc_native_glue.o" "$B/mc_native_rt.o" "$B/mooncrst_z80.o"
ls -la build/mooncrst_native

echo "== ADF =="
rm -rf "$B/boot"; mkdir -p "$B/boot/s"
cp build/mooncrst_native "$B/boot/mooncrst"
printf 'SYS:mooncrst\n' > "$B/startup-sequence"
rm -f build/mooncrst.adf
xdftool build/mooncrst.adf format "mooncrst" + boot install \
    + write build/mooncrst_native mooncrst \
    + makedir s + write "$B/startup-sequence" s/startup-sequence
echo "DONE -> build/mooncrst.adf (native)"

/* tools/z80trace_host.c
 * ============================================================
 * Execution-trace code coverage for the disassembler. Runs the game
 * via the REAL machine_run_frame path (same as the working renderer)
 * with the per-instruction PC hook (z80.c built -DZ80_TRACE_PC), and
 * drives a coin->start->play input script so the trace covers gameplay,
 * not just attract. Dumps executed instruction addresses for
 * tools/z80disasm.py --trace.
 *
 *   gcc -O2 -DZ80_TRACE_PC -Isrc/cores -Isrc/hal -o /tmp/z80trace \
 *       tools/z80trace_host.c src/cores/z80.c src/hal/machine.c
 *   /tmp/z80trace games/mooncrst/roms 6000 > trace.txt
 * ============================================================ */
#include <stdio.h>
#include <stdlib.h>
#include "z80emu.h"
#include "machine.h"

static MY_LITTLE_Z80 z;
static unsigned char cov[0x10000];

unsigned char in_impl(MY_LITTLE_Z80 *zz, int p) { (void)zz; (void)p; return 0xff; }
void out_impl(MY_LITTLE_Z80 *zz, int p, unsigned char v) { (void)zz;(void)p;(void)v; }

/* Called by z80.c (built -DZ80_TRACE_PC) for every executed instruction. */
void z80_trace_pc(int pc) { cov[pc & 0xffff] = 1; }

int main(int argc, char **argv)
{
    const char *romdir = (argc > 1) ? argv[1] : "games/mooncrst/roms";
    int frames         = (argc > 2) ? atoi(argv[2]) : 6000;
    const char *files[8] = { "epr194","epr195","epr196","epr197",
                             "epr198","epr199","epr200","epr201" };
    unsigned char prog[0x4000]; unsigned int off = 0;
    for (int i = 0; i < 8; i++) {
        char p[1024]; snprintf(p, sizeof p, "%s/%s", romdir, files[i]);
        FILE *f = fopen(p, "rb"); if (!f) { perror(p); return 1; }
        off += fread(prog + off, 1, 2048, f); fclose(f);
    }
    machine_init(&z, prog, off);

    for (int fr = 0; fr < frames; fr++) {
        /* Moon Cresta inputs (active-high): in0 coin=0x01/L=0x04/R=0x08/
         * fire=0x10; in1 start1=0x01 (+ coinage dip 0x80). Coin + start
         * every ~600 frames; play (wiggle + fire) in between. */
        machine_io.in0 = 0x00;
        machine_io.in1 = 0x80;
        int ph = fr % 600;
        if (ph < 5)        machine_io.in0 |= 0x01;          /* coin  */
        else if (ph < 12)  machine_io.in1 |= 0x01;          /* start */
        else {
            machine_io.in0 |= (fr & 2) ? 0x04 : 0x08;       /* move L/R */
            if ((fr & 7) < 4) machine_io.in0 |= 0x10;       /* fire     */
        }
        machine_run_frame(&z);
    }

    int n = 0;
    for (int a = 0; a < 0x4000; a++) if (cov[a]) { printf("%04x\n", a); n++; }
    fprintf(stderr, "traced %d frames, %d distinct code addrs in ROM\n", frames, n);
    return 0;
}

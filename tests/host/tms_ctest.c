/* tms_ctest.c -- equivalence test for the C TMS320C10 vs the Python core.
 * Runs the real Twin Cobra DSP ROM with a DETERMINISTIC fake bridge and
 * prints the PC each step. tools/tms_pytrace.py does the identical run; the
 * two PC streams must match exactly (proves the C port is faithful).
 *   gcc -O2 -I src/cores tests/host/tms_ctest.c src/cores/tms320c10.c -o /tmp/tmsc
 *   /tmp/tmsc games/twincobr/dsp/dsp_21.bin games/twincobr/dsp/dsp_22.bin 4000
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "tms320c10.h"

static uint16_t fakemem[0x40000];   /* shared "68K memory" */
static uint32_t latch;              /* combined byte address from port0 */

static uint16_t io_in(void *c, int port) {
    (void)c;
    if (port == 1) return fakemem[(latch >> 1) & 0x3ffff];
    return 0;
}
static void io_out(void *c, int port, uint16_t v) {
    (void)c;
    if (port == 0) latch = ((v & 0xe000) << 3) + ((v & 0x1fff) << 1);
    else if (port == 1) fakemem[(latch >> 1) & 0x3ffff] = v;
}
static int bio(void *c) { (void)c; return 0; }

int main(int argc, char **argv) {
    FILE *fe = fopen(argv[1], "rb"), *fo = fopen(argv[2], "rb");
    int steps = atoi(argv[3]), i;
    unsigned char e[2048], o[2048];
    uint16_t prog[2048];
    static tms320c10 t;
    if (!fe || !fo) { fprintf(stderr, "open fail\n"); return 1; }
    fread(e, 1, 2048, fe); fread(o, 1, 2048, fo);
    for (i = 0; i < 2048; i++) prog[i] = (e[i] << 8) | o[i];
    for (i = 0; i < 0x40000; i++) fakemem[i] = (uint16_t)((i * 31 + 7) & 0xffff);
    tms_init(&t, prog, 2048, io_in, io_out, bio, &t);
    t.int_pending = 1;
    for (i = 0; i < steps; i++) {
        printf("%03x\n", t.PC);
        if ((i % 800) == 799) t.int_pending = 1;   /* periodic INT */
        tms_step(&t);
    }
    return 0;
}

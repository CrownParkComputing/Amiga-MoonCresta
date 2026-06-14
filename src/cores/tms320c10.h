/* tms320c10.h -- TMS320C10 (TMS32010) DSP core for the Twin Cobra port.
 * Ported 1:1 from the validated Python core (tools/tms320c10.py), itself
 * from MAME tms320c1x. Freestanding (no stdlib); caller supplies the I/O
 * bridge callbacks (twincobr: port0=addr latch, port1=68K data, port3=BIO).
 */
#ifndef TMS320C10_H
#define TMS320C10_H

#include <stdint.h>

struct tms320c10;
typedef uint16_t (*tms_in_fn)(void *ctx, int port);
typedef void     (*tms_out_fn)(void *ctx, int port, uint16_t val);
typedef int      (*tms_bio_fn)(void *ctx);

typedef struct tms320c10 {
    uint32_t ACC;          /* 32-bit accumulator */
    uint32_t Preg;         /* 32-bit product */
    uint16_t T;            /* multiplicand */
    uint16_t AR[2];        /* aux registers */
    uint8_t  ARP, DP, OV, OVM, INTM;
    uint16_t PC;
    uint16_t STACK[4];     /* 4-level PC stack */
    int      int_pending;

    uint16_t P[0x1000];    /* program memory (words) */
    uint16_t D[256];       /* data RAM (0..143 real) */

    tms_in_fn  io_in;
    tms_out_fn io_out;
    tms_bio_fn bio;
    void      *ctx;
} tms320c10;

void tms_init(tms320c10 *t, const uint16_t *prog, int prog_words,
              tms_in_fn in, tms_out_fn out, tms_bio_fn bio, void *ctx);
void tms_reset(tms320c10 *t);
void tms_step(tms320c10 *t);

#endif

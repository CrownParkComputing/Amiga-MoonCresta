/* tms320c10.c -- see tms320c10.h. 1:1 port of tools/tms320c10.py. */
#include "tms320c10.h"

static int32_t s13(uint32_t x) { x &= 0x1fff; return (x & 0x1000) ? (int32_t)x - 0x2000 : (int32_t)x; }

void tms_reset(tms320c10 *t)
{
    int i;
    t->ACC = 0; t->Preg = 0; t->T = 0;
    t->AR[0] = t->AR[1] = 0;
    t->ARP = 0; t->DP = 0; t->OV = 0; t->OVM = 0; t->INTM = 1;
    t->PC = 0; t->int_pending = 0;
    for (i = 0; i < 4; i++) t->STACK[i] = 0;
}

void tms_init(tms320c10 *t, const uint16_t *prog, int n,
              tms_in_fn in, tms_out_fn out, tms_bio_fn bio, void *ctx)
{
    int i;
    for (i = 0; i < 0x1000; i++) t->P[i] = (i < n) ? prog[i] : 0;
    for (i = 0; i < 256; i++) t->D[i] = 0;
    t->io_in = in; t->io_out = out; t->bio = bio; t->ctx = ctx;
    tms_reset(t);
}

static void push(tms320c10 *t, uint16_t v)
{
    t->STACK[0] = t->STACK[1]; t->STACK[1] = t->STACK[2];
    t->STACK[2] = t->STACK[3]; t->STACK[3] = v & 0xfff;
}
static uint16_t pop(tms320c10 *t)
{
    uint16_t v = t->STACK[3];
    t->STACK[3] = t->STACK[2]; t->STACK[2] = t->STACK[1];
    t->STACK[1] = t->STACK[0];
    return v;
}

/* effective data address from low byte; apply indirect AR/ARP updates */
static int ea(tms320c10 *t, uint16_t op)
{
    int lo = op & 0xff;
    if (lo & 0x80) {                    /* indirect */
        int addr = t->AR[t->ARP] & 0xff;
        uint16_t ar = t->AR[t->ARP];
        if (lo & 0x20)      ar = (ar & 0xfe00) | ((ar + 1) & 0x1ff);
        else if (lo & 0x10) ar = (ar & 0xfe00) | ((ar - 1) & 0x1ff);
        t->AR[t->ARP] = ar;
        if (!(lo & 0x08)) t->ARP = lo & 1;
        return addr;
    }
    return (t->DP << 7) | (lo & 0x7f);  /* direct */
}

/* read data word; if signext, sign-extend before the (signed) shift */
static int32_t getmem(tms320c10 *t, uint16_t op, int shift, int signext)
{
    int a = ea(t, op);
    uint16_t v = t->D[a];
    if (signext) return ((int32_t)(int16_t)v) << shift;
    return (int32_t)(((uint32_t)v) << shift);
}
static int putmem(tms320c10 *t, uint16_t op, uint16_t val)
{
    int a = ea(t, op);
    t->D[a] = val;
    return a;
}

static void ovf_add(tms320c10 *t, int64_t res)
{
    if (res > 0x7fffffffLL || res < -0x80000000LL) {
        t->OV = 1;
        t->ACC = t->OVM ? (res > 0 ? 0x7fffffffu : 0x80000000u)
                        : (uint32_t)res;
    } else {
        t->ACC = (uint32_t)res;
    }
}

static uint16_t status(tms320c10 *t)
{
    return (uint16_t)((t->OV << 15) | (t->OVM << 14) | (t->INTM << 13)
                      | (t->ARP << 8) | t->DP | 0x1efe);
}
static void load_status(tms320c10 *t, uint16_t v)  /* LST (INTM preserved) */
{
    t->OV = (v >> 15) & 1; t->OVM = (v >> 14) & 1;
    t->ARP = (v >> 8) & 1; t->DP = v & 1;
}

static void ext(tms320c10 *t, int lo)
{
    switch (lo) {
    case 0x00: break;                                  /* NOP */
    case 0x01: t->INTM = 1; break;                     /* DINT */
    case 0x02: t->INTM = 0; break;                     /* EINT */
    case 0x08: if ((int32_t)t->ACC < 0) t->ACC = (uint32_t)(-(int32_t)t->ACC); break; /* ABS */
    case 0x09: t->ACC = 0; break;                      /* ZAC */
    case 0x0a: t->OVM = 0; break;                      /* ROVM */
    case 0x0b: t->OVM = 1; break;                      /* SOVM */
    case 0x0c: push(t, t->PC); t->PC = t->ACC & 0xfff; break;            /* CALA */
    case 0x0d: t->PC = pop(t); break;                  /* RET */
    case 0x0e: t->ACC = t->Preg; break;                /* PAC */
    case 0x0f: ovf_add(t, (int64_t)(int32_t)t->ACC + (int32_t)t->Preg); break; /* APAC */
    case 0x10: ovf_add(t, (int64_t)(int32_t)t->ACC - (int32_t)t->Preg); break; /* SPAC */
    case 0x14: push(t, t->ACC & 0xfff); break;         /* PUSH */
    case 0x15: t->ACC = pop(t); break;                 /* POP */
    default: break;
    }
}

static void branch(tms320c10 *t, int hi)
{
    uint16_t target = t->P[t->PC & 0xfff];
    int32_t acc = (int32_t)t->ACC;
    int take = 0;
    t->PC = (t->PC + 1) & 0xfff;
    switch (hi) {
    case 0xf4:                                         /* BANZ */
        take = (t->AR[t->ARP] & 0x1ff) != 0;
        t->AR[t->ARP] = (t->AR[t->ARP] & 0xfe00) | ((t->AR[t->ARP] - 1) & 0x1ff);
        break;
    case 0xf5: take = t->OV; t->OV = 0; break;         /* BV */
    case 0xf6: take = t->bio ? t->bio(t->ctx) : 0; break; /* BIOZ */
    case 0xf8: push(t, t->PC); t->PC = target; return; /* CALL */
    case 0xf9: t->PC = target; return;                 /* BR */
    case 0xfa: take = acc < 0; break;                  /* BLZ */
    case 0xfb: take = acc <= 0; break;                 /* BLEZ */
    case 0xfc: take = acc > 0; break;                  /* BGZ */
    case 0xfd: take = acc >= 0; break;                 /* BGEZ */
    case 0xfe: take = acc != 0; break;                 /* BNZ */
    case 0xff: take = acc == 0; break;                 /* BZ */
    default: break;
    }
    if (take) t->PC = target;
}

void tms_step(tms320c10 *t)
{
    uint16_t op; int hi, a;

    if (t->int_pending && !t->INTM) {     /* INT -> vector to addr 2 */
        t->int_pending = 0; t->INTM = 1;
        push(t, t->PC); t->PC = 2;
    }
    op = t->P[t->PC & 0xfff];
    t->PC = (t->PC + 1) & 0xfff;
    hi = op >> 8;

    if (hi <= 0x0f)        ovf_add(t, (int64_t)(int32_t)t->ACC + getmem(t, op, hi & 0xf, 1)); /* ADD sh */
    else if (hi <= 0x1f)   ovf_add(t, (int64_t)(int32_t)t->ACC - getmem(t, op, hi & 0xf, 1)); /* SUB sh */
    else if (hi <= 0x2f)   t->ACC = (uint32_t)getmem(t, op, hi & 0xf, 1);                      /* LAC sh */
    else if (hi == 0x30 || hi == 0x31) putmem(t, op, t->AR[hi & 1]);                           /* SAR */
    else if (hi == 0x38 || hi == 0x39) t->AR[hi & 1] = (uint16_t)getmem(t, op, 0, 0);          /* LAR */
    else if (hi >= 0x40 && hi <= 0x47) putmem(t, op, t->io_in(t->ctx, hi & 7));                /* IN */
    else if (hi >= 0x48 && hi <= 0x4f) t->io_out(t->ctx, hi & 7, (uint16_t)getmem(t, op, 0, 0)); /* OUT */
    else if (hi == 0x50)   putmem(t, op, (uint16_t)t->ACC);                                    /* SACL */
    else if (hi >= 0x58 && hi <= 0x5f) putmem(t, op, (uint16_t)((t->ACC << (hi & 7)) >> 16));  /* SACH sh */
    else if (hi == 0x60)   ovf_add(t, (int64_t)(int32_t)t->ACC + (((int32_t)(int16_t)getmem(t,op,0,0)) << 16)); /* ADDH */
    else if (hi == 0x61)   ovf_add(t, (int64_t)(int32_t)t->ACC + (uint16_t)getmem(t, op, 0, 0)); /* ADDS */
    else if (hi == 0x62)   ovf_add(t, (int64_t)(int32_t)t->ACC - (((int32_t)(int16_t)getmem(t,op,0,0)) << 16)); /* SUBH */
    else if (hi == 0x63)   ovf_add(t, (int64_t)(int32_t)t->ACC - (uint16_t)getmem(t, op, 0, 0)); /* SUBS */
    else if (hi == 0x64) {                                                                     /* SUBC */
        int64_t tmp; a = ea(t, op);
        tmp = (int64_t)(int32_t)t->ACC - (((uint32_t)t->D[a]) << 15);
        if (tmp >= 0) t->ACC = (uint32_t)((tmp << 1) | 1);
        else          t->ACC = t->ACC << 1;
    }
    else if (hi == 0x65)   t->ACC = ((uint32_t)(uint16_t)getmem(t, op, 0, 0)) << 16;           /* ZALH */
    else if (hi == 0x66)   t->ACC = (uint16_t)getmem(t, op, 0, 0);                             /* ZALS */
    else if (hi == 0x67)   putmem(t, op, t->P[t->ACC & 0xfff]);                                /* TBLR */
    else if (hi == 0x68)   ea(t, op);                                                          /* MAR/LARP */
    else if (hi == 0x69) { a = ea(t, op); t->D[(a + 1) & 0xff] = t->D[a]; }                    /* DMOV */
    else if (hi == 0x6a)   t->T = (uint16_t)getmem(t, op, 0, 0);                               /* LT */
    else if (hi == 0x6b) { a = ea(t, op); t->T = t->D[a]; t->D[(a+1)&0xff] = t->D[a];          /* LTD */
                           ovf_add(t, (int64_t)(int32_t)t->ACC + (int32_t)t->Preg); }
    else if (hi == 0x6c) { t->T = (uint16_t)getmem(t, op, 0, 0);                               /* LTA */
                           ovf_add(t, (int64_t)(int32_t)t->ACC + (int32_t)t->Preg); }
    else if (hi == 0x6d)   t->Preg = (uint32_t)((int32_t)(int16_t)getmem(t,op,0,0) * (int32_t)(int16_t)t->T); /* MPY */
    else if (hi == 0x6e)   t->DP = op & 1;                                                     /* LDPK */
    else if (hi == 0x6f)   t->DP = getmem(t, op, 0, 0) & 1;                                    /* LDP */
    else if (hi == 0x70 || hi == 0x71) t->AR[hi & 1] = op & 0xff;                              /* LARK */
    else if (hi == 0x78)   t->ACC = t->ACC ^ (uint16_t)getmem(t, op, 0, 0);                    /* XOR */
    else if (hi == 0x79)   t->ACC = t->ACC & (0xffff0000u | (uint16_t)getmem(t, op, 0, 0));    /* AND */
    else if (hi == 0x7a)   t->ACC = t->ACC | (uint16_t)getmem(t, op, 0, 0);                    /* OR */
    else if (hi == 0x7b)   load_status(t, (uint16_t)getmem(t, op, 0, 0));                      /* LST */
    else if (hi == 0x7c)   t->D[0x80 | (op & 0x7f)] = status(t);                               /* SST */
    else if (hi == 0x7d)   t->P[t->ACC & 0xfff] = (uint16_t)getmem(t, op, 0, 0);               /* TBLW */
    else if (hi == 0x7e)   t->ACC = op & 0xff;                                                 /* LACK */
    else if (hi == 0x7f)   ext(t, op & 0x1f);                                                  /* extended */
    else if (hi >= 0x80 && hi <= 0x9f) t->Preg = (uint32_t)(s13(op) * (int32_t)(int16_t)t->T); /* MPYK */
    else if (hi >= 0xf0)   branch(t, hi);                                                      /* branch group */
    /* else illegal/NOP */
}

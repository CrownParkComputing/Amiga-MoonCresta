/* src/hal/mc_audio.c
 * ============================================================
 *  Custom Paula sound for Moon Cresta. We don't model the Galaxian analog
 *  sound board -- we synthesise approximations on Paula, triggered by the
 *  sound-register writes the game already makes (captured into machine_io):
 *    - background "throb"  : ch0, square tone, period from the b800 pitch
 *                            latch (freq = 1536000/((256-pitch)*16)); louder
 *                            with the VOL1/VOL2 lines.
 *    - fire / "pew"        : ch1, a quick descending square (on FIRE edge).
 *    - explosion           : ch2, a decaying noise burst (on HIT edge).
 *  All DMA-driven (sample loops in chip RAM); we only poke period/volume
 *  each frame, so it works with interrupts fully disabled. The sample
 *  pointers/lengths are set once so changing pitch/volume doesn't click.
 * ============================================================ */
#include <exec/exec.h>
#include <exec/memory.h>
#include <proto/exec.h>
#include <stdint.h>
#include "machine.h"

#define CUSTOM   ((volatile uint16_t *)0xdff000)
#define R_DMACON (0x096/2)

/* Paula channel register word-indices (base 0xdff0a0, +0x10 per channel):
 *   +0 LCH  +1 LCL  +2 LEN(words)  +3 PER  +4 VOL */
#define A_LCH(ch) (((0x0A0 + (ch)*0x10)    )/2)
#define A_LEN(ch) (((0x0A0 + (ch)*0x10) + 4)/2)
#define A_PER(ch) (((0x0A0 + (ch)*0x10) + 6)/2)
#define A_VOL(ch) (((0x0A0 + (ch)*0x10) + 8)/2)

#define SOUND_CLOCK 1536000L
#define NOISE_WORDS 2048                /* 4KB noise -> loops slowly = smooth hiss, not a buzz */
#define PER_MIN 124
#define PER_MAX 32000

static int8_t *sq    = 0;               /* 1-word (+127,-128) square */
static int8_t *noise = 0;               /* looped noise for explosions */

static unsigned long last_fire = 0, last_hit = 0;
static int  fire_t = 0,  fire_per = 0;  /* fire effect countdown / current period */
static int  coin_t = 0,  coin_per = 0;  /* insert-coin blip */

/* Triggered from poll_input when a coin is inserted -> a quick rising blip. */
void mc_audio_coin(void) { coin_t = 14; coin_per = 520; }

static void aud_ptr(int ch, void *s, int words)
{
    volatile uint16_t *c = CUSTOM;
    uint32_t a = (uint32_t)s;
    c[A_LCH(ch)]     = (uint16_t)(a >> 16);
    c[A_LCH(ch) + 1] = (uint16_t)(a & 0xFFFF);
    c[A_LEN(ch)]     = (uint16_t)words;
}
static void aud_per(int ch, int per)
{
    if (per < PER_MIN) per = PER_MIN; else if (per > PER_MAX) per = PER_MAX;
    CUSTOM[A_PER(ch)] = (uint16_t)per;
}
static void aud_vol(int ch, int vol)
{
    if (vol < 0) vol = 0; else if (vol > 64) vol = 64;
    CUSTOM[A_VOL(ch)] = (uint16_t)vol;
}

void mc_audio_open(void)
{
    volatile uint16_t *c = CUSTOM;
    int8_t *mem = (int8_t *)AllocMem(2 + NOISE_WORDS*2, MEMF_CHIP | MEMF_CLEAR);
    if (!mem) return;
    sq = mem;
    sq[0] = 127; sq[1] = -128;                 /* one square cycle (1 word) */
    noise = mem + 2;
    { unsigned int s = 0x1234567u;
      for (int i = 0; i < NOISE_WORDS*2; i++) { s = s*1103515245u + 12345u; noise[i] = (int8_t)(s >> 17); } }

    /* fixed sample pointers/lengths; pitch+volume change per frame */
    aud_ptr(0, sq, 1);    aud_vol(0, 0); aud_per(0, 400);
    aud_ptr(1, sq, 1);    aud_vol(1, 0); aud_per(1, 400);
    aud_ptr(2, noise, NOISE_WORDS); aud_vol(2, 0); aud_per(2, 360);
    aud_ptr(3, sq, 1);    aud_vol(3, 0); aud_per(3, 400);   /* coin */

    c[R_DMACON] = 0x800F;                       /* enable audio DMA ch 0,1,2,3 */
}

void mc_audio_frame(void)
{
    /* ---- background throb (ch0) from the pitch latch ---- */
    if (machine_io.snd_pitch != 0xFF) {
        int div = 256 - machine_io.snd_pitch; if (div < 1) div = 1;
        long freq = SOUND_CLOCK / ((long)div * 20);   /* /20 (was /16) -> a bit lower */
        if (freq < 50) freq = 50;
        aud_per(0, (int)(3546895L / (freq * 2)));    /* 1-word square -> 2 samples/cycle */
        aud_vol(0, 20 + machine_io.snd_vol * 14);    /* VOL1/VOL2 lift it */
    } else {
        aud_vol(0, 0);
    }

    /* ---- fire "pew" (ch1): start on FIRE edge, sweep pitch down ---- */
    if (machine_io.snd_fire != last_fire) { last_fire = machine_io.snd_fire; fire_t = 7; fire_per = 520; }
    if (fire_t > 0) {
        aud_per(1, fire_per);
        aud_vol(1, 38);
        fire_per += 230;                              /* descending */
        if (--fire_t == 0) aud_vol(1, 0);
    }

    /* ---- explosion (ch2): a proper boom, level-driven from the HIT line ----
     * The board holds HIT high for the whole discharge, so a quick enemy pop
     * holds it only briefly while a *player death* holds it far longer. We open
     * with a bright noise "crack" on the rising edge, sweep the noise down into
     * a low rumble while the line stays held, then decay a short tail when it
     * releases. Result: enemy kills = short bright pop; player death = a long
     * falling rumble, no special-casing needed.
     *   period 230 (bright) .. 230+18*24=662 (deep rumble); age caps the sweep.
     *   tail = release decay length (also covers blasts too short to sample as
     *   "held", so even a 1-frame HIT still makes a pop). */
    {
        static int age = 0, tail = 0;
        if (machine_io.snd_hit != last_hit) {         /* new blast: reset sweep */
            last_hit = machine_io.snd_hit; age = 0; tail = 8;
        }
        if (machine_io.snd_hit_lvl) {                 /* held -> loud + sweeping down */
            aud_per(2, 230 + (age < 18 ? age : 18) * 24);
            aud_vol(2, 64);
            if (age < 100) age++;
            tail = 8;                                 /* re-arm release tail */
        } else if (tail > 0) {                        /* released -> decay the boom */
            aud_per(2, 230 + (age < 18 ? age : 18) * 24);  /* hold last sweep pitch */
            aud_vol(2, tail * 64 / 8);
            if (--tail == 0) aud_vol(2, 0);
        }
    }

    /* ---- insert-coin blip (ch3): a quick rising tone ---- */
    if (coin_t > 0) {
        aud_per(3, coin_per);
        aud_vol(3, 42);
        coin_per -= 30; if (coin_per < 170) coin_per = 170;
        if (--coin_t == 0) aud_vol(3, 0);
    }
}

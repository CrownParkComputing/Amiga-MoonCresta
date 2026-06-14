/* src/hal/hal_io.c -- implementation of the I/O dispatch layer.
 *
 * This file is the runtime side of the dispatch. The static
 * handler table that backs hal_io_lut[] is generated at build
 * time by namco_amiga.tools.generate_dispatch from the game's
 * io_map.json. For now (before the generator is wired in) we
 * use a placeholder table that just passes everything through.
 */
#include "hal_io.h"
#include <stddef.h>

/* The LUT itself is defined by the AUTO-GENERATED dispatch C file
 * (build/c/<game>_io_dispatch.c). We just declare it here so the
 * C code can access it. The placeholder below is dead code -- it
 * would only be referenced if a build ever produced a hal_io.o
 * without a corresponding *_io_dispatch.o. */
extern const hal_io_handler_t *hal_io_lut[256];

/* Counter: how many I/O ops have hit the stub handlers. Useful
 * for debugging (if it stays at 0, the dispatch isn't firing;
 * if it climbs, the game is alive and talking to the HAL). */
unsigned long hal_io_stub_counter = 0;

void hal_io_init(void)
{
    /* Nothing to do for the placeholder. The generated table
     * is statically initialised. Real init will scan the table
     * and validate handlers are non-NULL where expected. */
}

mc6809byte__t hal_io_read(struct mc6809 *cpu, mc6809addr__t addr, bool debug_fetch)
{
    (void)cpu;
    (void)debug_fetch;
    /* For the placeholder: every I/O address returns 0xff.
     * The real LUT replaces this with a handler call. */
    return 0xff;
}

void hal_io_write(struct mc6809 *cpu, mc6809addr__t addr, mc6809byte__t val)
{
    (void)cpu;
    (void)addr;
    (void)val;
    /* Placeholder: writes are swallowed. */
}

uint8_t _in_impl(uint16_t addr)
{
    (void)addr;
    return 0xff;
}

void _out_impl(uint16_t addr, uint8_t val)
{
    (void)addr;
    (void)val;
}

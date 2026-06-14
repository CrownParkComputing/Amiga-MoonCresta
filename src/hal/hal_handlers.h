/* src/hal/hal_handlers.h
 * ============================================================
 *  Forward declarations for the I/O handler assembly stubs.
 *  AUTO-INCLUDED by the generated dispatch C file so the C
 *  compiler can resolve the handler symbols at compile time.
 * ============================================================
 *
 * The assembly file src/hal/handlers.s exports one symbol per
 * handler, with a leading underscore to match m68k-amigaos-gcc's
 * C symbol convention:
 *
 *    C source name    : hal_tilemap_enable_w
 *    m68k symbol      : _hal_tilemap_enable_w
 *    vasm label       : _hal_tilemap_enable_w
 *
 * This header declares them all as `extern` so the C side can
 * take their address without complaint.
 *
 * Adding a new handler = add it to games/<name>/io_map.json +
 * add its declaration here + add the body in handlers.s.
 */
#ifndef NAMCO_AMIGA_HAL_HANDLERS_H
#define NAMCO_AMIGA_HAL_HANDLERS_H

#include <stdint.h>

/* Write handlers: d0=addr, d1=val. The dispatch C file references
 * them via .write in the LUT. */
extern void hal_tilemap_enable_w(uint16_t addr, uint8_t val);
extern void hal_mcu_reset_w(uint16_t addr, uint8_t val);
extern void hal_flip_screen_w(uint16_t addr, uint8_t val);
extern void hal_bank_switch_w(uint16_t addr, uint8_t val);
extern void hal_sound_wave_write_w(uint16_t addr, uint8_t val);
extern void hal_sound_reg_write_w(uint16_t addr, uint8_t val);
extern void hal_irq_enable_w(uint16_t addr, uint8_t val);

/* Read handlers: d0=addr, return d0=val. */
extern uint8_t hal_watchdog_kick_r(uint16_t addr);
extern uint8_t hal_vblank_ack_r(uint16_t addr);
extern uint8_t hal_tilemap_enable_r(uint16_t addr);
extern uint8_t hal_mcu_reset_r(uint16_t addr);
extern uint8_t hal_flip_screen_r(uint16_t addr);
extern uint8_t hal_bank_switch_r(uint16_t addr);
extern uint8_t hal_sound_wave_write_r(uint16_t addr);
extern uint8_t hal_sound_reg_write_r(uint16_t addr);
extern uint8_t hal_irq_enable_r(uint16_t addr);

/* ---- mooncrst (Galaxian-family) handlers -------------------------
 * Reads: IN0/IN1 (idle = 0xff, active-low) + DIP switches.
 * Writes: the four port groups; hal_port_a000 / hal_port_b000
 * sub-decode (addr & 7) internally (see games/mooncrst/io_map.json).
 */
extern uint8_t hal_input_in0_r(uint16_t addr);
extern uint8_t hal_input_in1_r(uint16_t addr);
extern uint8_t hal_input_dsw0_r(uint16_t addr);
extern void hal_port_a000_w(uint16_t addr, uint8_t val);   /* gfx bank / coin / LFO */
extern void hal_sound_ctrl_w(uint16_t addr, uint8_t val);
extern void hal_port_b000_w(uint16_t addr, uint8_t val);   /* nmi / stars / flip */
extern void hal_sound_pitch_w(uint16_t addr, uint8_t val);

#endif /* NAMCO_AMIGA_HAL_HANDLERS_H */

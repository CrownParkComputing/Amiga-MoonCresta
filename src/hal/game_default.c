/* src/hal/game_default.c
 * ============================================================
 *  Default game hooks for the Pacland-style (6809) games.
 *  amiga_main calls hal_game_init() once and hal_game_frame()
 *  per loop iteration. The Moon Cresta build replaces this file
 *  with src/hal/mc_run.c, which runs the Z80 + tilemap renderer.
 * ============================================================ */
extern void hal_io_init(void);
extern void hal_video_open(void);
extern void hal_video_frame(void);

void hal_game_init(void)  { hal_io_init(); hal_video_open(); }
void hal_game_frame(void) { hal_video_frame(); }

/* src/hal/mc_romload.c
 * ============================================================
 *  Runtime ROM loader. Instead of compiling the (copyrighted) Moon Cresta
 *  ROM into the program, we keep empty RAM buffers and load "mooncrst.rom"
 *  from disk at startup -- BEFORE the hardware takeover, while the OS/DOS is
 *  still alive. The user drops their own mooncrst.rom next to the program;
 *  it is never part of this source or any release.
 *
 *  mooncrst.rom layout (24608 bytes): program 16384 + chars 8192 + prom 32,
 *  produced by tools/make_rom.py from a Moon Cresta ROM set.
 * ============================================================ */
#include <exec/exec.h>
#include <proto/exec.h>
#include <proto/dos.h>
#include <dos/dos.h>

/* ROM lives in RAM now (BSS), filled by mc_load_rom(). */
unsigned char mc_prog[16384];
unsigned long mc_prog_len = 16384;
unsigned char mc_char[8192];
unsigned char mc_prom[32];

struct DosLibrary *DOSBase = 0;

/* Returns 1 if the full ROM was read, 0 otherwise. Call before mc_video_open. */
int mc_load_rom(void)
{
    int ok = 0;
    DOSBase = (struct DosLibrary *)OpenLibrary((CONST_STRPTR)"dos.library", 0);
    if (!DOSBase) return 0;

    BPTR fh = Open((CONST_STRPTR)"mooncrst.rom", MODE_OLDFILE);
    if (!fh) fh = Open((CONST_STRPTR)"PROGDIR:mooncrst.rom", MODE_OLDFILE);
    if (fh) {
        long a = Read(fh, mc_prog, 16384);
        long b = Read(fh, mc_char, 8192);
        long c = Read(fh, mc_prom, 32);
        Close(fh);
        ok = (a == 16384 && b == 8192 && c == 32);
    }
    CloseLibrary((struct Library *)DOSBase);
    DOSBase = 0;
    return ok;
}

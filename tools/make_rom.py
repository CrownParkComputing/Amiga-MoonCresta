#!/usr/bin/env python3
"""Build mooncrst.rom (the runtime ROM the program loads from disk) from YOUR
OWN Moon Cresta ROM set. The ROM is copyrighted (Nichibutsu) and is NOT part of
this project -- you must legally own it.

Place your files under games/mooncrst/ then run:
    python3 tools/make_rom.py [output_path]
Default output: build/mooncrst.rom  (drop it next to the program to run).

Layout: program 16384 + chars 8192 + prom 32 = 24608 bytes.
"""
import sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G    = os.path.join(ROOT, "games", "mooncrst")
OUT  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "mooncrst.rom")

PROG = ["roms/epr194","roms/epr195","roms/epr196","roms/epr197",
        "roms/epr198","roms/epr199","roms/epr200","roms/epr201"]
CHAR = ["gfx/mcs_b","gfx/mcs_d","gfx/mcs_a","gfx/mcs_c"]
PROM = "mmi6331.6l"

def rd(rel):
    p = os.path.join(G, rel)
    if not os.path.exists(p):
        sys.exit("ERROR: missing ROM file '%s'.\nSupply your own Moon Cresta ROM set." % p)
    return open(p, "rb").read()

prog = b"".join(rd(f) for f in PROG)
char = b"".join(rd(f) for f in CHAR)
prom = rd(PROM)[:32]
assert len(prog) == 16384 and len(char) == 8192 and len(prom) == 32

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "wb").write(prog + char + prom)
print("wrote %s  (%d bytes = 16384 prog + 8192 char + 32 prom)" % (OUT, len(prog)+len(char)+len(prom)))

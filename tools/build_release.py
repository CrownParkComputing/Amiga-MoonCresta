#!/usr/bin/env python3
"""
build_release.py -- command-line packager for the Amiga Moon Cresta port.

Point it at YOUR OWN MAME Moon Cresta romset (split or merged, .zip / .7z /
loose files) and it assembles mooncrst.rom (by CRC32, so filenames and
split-vs-merged don't matter) and builds, into dist/:
    MoonCresta.adf       -- bootable floppy image (ROM inside -- boot this!)
    MoonCresta_HD/       -- hard-drive drawer (run `mooncrst`)
    MoonCresta.lha       -- the HD drawer archived (needs lha/jlha)

The ROM is copyrighted (Nichibutsu) and you must legally own it. Nothing this
writes is committed; dist/ is git-ignored.

Usage:
    python3 tools/build_release.py                 # interactive
    python3 tools/build_release.py mooncrst.zip    # non-interactive
    python3 tools/build_release.py --romset PATH [--adf-only] [--no-build] [--out DIR]

For a point-and-click version, use tools/gui_packager.py (or the prebuilt app).
"""
import os, sys, argparse
import mc_pack
from mc_pack import PackError


def ask(prompt, default=None):
    s = input(prompt).strip()
    return s or default


def main():
    ap = argparse.ArgumentParser(description="Package the Amiga Moon Cresta ADF/HD/LHA from your MAME romset.")
    ap.add_argument("romset", nargs="?", help="path to your MAME mooncrst romset (.zip/.7z/dir)")
    ap.add_argument("--romset", dest="romset_opt", help="same as positional romset")
    ap.add_argument("--out", default=mc_pack.DIST, help="output directory (default: dist/)")
    ap.add_argument("--exe", help="ROM-free mooncrst program (default: build/mooncrst)")
    ap.add_argument("--adf", help="ROM-free mooncrst.adf (default: build/mooncrst.adf)")
    ap.add_argument("--adf-only", action="store_true", help="only produce the ADF")
    ap.add_argument("--no-lha", action="store_true", help="don't attempt the .lha")
    ap.add_argument("--no-build", action="store_true", help="never invoke make; require a prebuilt program")
    args = ap.parse_args()

    print("=== Amiga Moon Cresta -- release packager ===\n")
    romset = args.romset or args.romset_opt
    if not romset:
        print("You'll need your OWN MAME Moon Cresta romset (the 'mooncrst' set).")
        ask("Is it [s]plit or [m]erged?  (either works -- I match by CRC) [s/m]: ", "s")
        romset = ask("Path to your romset (.zip/.7z or a folder): ")
        if not romset:
            sys.exit("No romset given -- nothing to do.")

    try:
        mc_pack.build(
            romset, args.out,
            want_adf=True,
            want_hd=not args.adf_only,
            want_lha=(not args.adf_only and not args.no_lha),
            exe=args.exe, adf=args.adf, build_ok=not args.no_build,
            log=lambda m: print("  " + m),
        )
    except PackError as e:
        sys.exit("\nERROR: %s" % e)
    print("\nBoot dist/MoonCresta.adf on an AGA Amiga (it has the ROM inside).")


if __name__ == "__main__":
    main()

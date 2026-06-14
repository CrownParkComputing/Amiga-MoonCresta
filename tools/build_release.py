#!/usr/bin/env python3
"""
build_release.py -- one-stop packager for the Amiga Moon Cresta port.

Point it at YOUR OWN MAME Moon Cresta romset (split *or* merged, .zip / .7z /
loose files) and it will:

  1. Pull the exact ROMs out by CRC32 (so filenames / split-vs-merged don't
     matter) and assemble  mooncrst.rom  (24608 bytes).
  2. Drop that ROM into a copy of the ROM-free program to make:
        dist/MoonCresta.adf       -- bootable floppy image
        dist/MoonCresta_HD/       -- hard-drive drawer (run `mooncrst`)
        dist/MoonCresta.lha       -- only if `lha` is installed

The Moon Cresta ROM is copyrighted (Nichibutsu) and is NEVER bundled with this
project -- you must legally own it. Nothing this tool writes (the .rom, the
populated .adf, the .lha) is committed; dist/ is git-ignored.

Usage:
    python3 tools/build_release.py                 # interactive (prompts)
    python3 tools/build_release.py mooncrst.zip    # non-interactive
    python3 tools/build_release.py --romset PATH [--adf-only] [--no-build]
"""
import os, sys, zlib, zipfile, shutil, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")

# ---- ROM manifest -------------------------------------------------------
# Each part is (mame_name, crc32, size). We match the user's files by CRC32
# (just a checksum -- MAME publishes these freely, so it's safe to ship) and
# concatenate them region-by-region. This is the MAME `mooncrst` set
# (Moon Cresta, Nichibutsu, unencrypted).
ROM_NAME = "mooncrst.rom"
ROM_TOTAL = 24608
REGIONS = [
    ("program (CPU)", [
        ("epr194", "0e5582b1", 2048), ("epr195", "12cb201b", 2048),
        ("epr196", "18255614", 2048), ("epr197", "05ac1466", 2048),
        ("epr198", "c28a2e8f", 2048), ("epr199", "5a4571de", 2048),
        ("epr200", "b7c85bf1", 2048), ("epr201", "2caba07f", 2048),
    ]),
    ("graphics", [
        ("mcs_b", "fb0f1f81", 2048), ("mcs_d", "13932a15", 2048),
        ("mcs_a", "631ebb5a", 2048), ("mcs_c", "24cfd145", 2048),
    ]),
    ("colour PROM", [
        ("mmi6331.6l", "6a0c7d87", 32),
    ]),
]


def crc(data):
    return "%08x" % (zlib.crc32(data) & 0xffffffff)


def add_blob(data, found):
    """Index one file's bytes by CRC32 (and by its 2KB sub-chunks, so a romset
    that stores regions as one combined file still resolves)."""
    found.setdefault(crc(data), data)
    if len(data) > 2048 and len(data) % 2048 == 0:
        for i in range(0, len(data), 2048):
            chunk = data[i:i + 2048]
            found.setdefault(crc(chunk), chunk)


def scan_source(path, found):
    low = path.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not n.endswith("/"):
                    add_blob(z.read(n), found)
    elif low.endswith(".7z"):
        try:
            import py7zr
        except ImportError:
            sys.exit("ERROR: %s is a .7z archive. Either extract it first, or\n"
                     "       `pip install py7zr` and re-run." % path)
        with py7zr.SevenZipFile(path, "r") as z:
            for name, bio in z.readall().items():
                add_blob(bio.read(), found)
    else:
        with open(path, "rb") as f:
            add_blob(f.read(), found)


def collect(paths):
    found = {}
    for p in paths:
        if os.path.isdir(p):
            for r, _, files in os.walk(p):
                for fn in files:
                    scan_source(os.path.join(r, fn), found)
        elif os.path.exists(p):
            scan_source(p, found)
        else:
            sys.exit("ERROR: no such path: %s" % p)
    return found


def assemble_rom(found):
    out = bytearray()
    missing = []
    for region, parts in REGIONS:
        for name, want_crc, size in parts:
            data = found.get(want_crc)
            if data is None:
                missing.append((region, name, want_crc, size))
            else:
                out += data[:size]
    if missing:
        print("\nERROR: these ROMs were not found in the romset you supplied:")
        for region, name, c, sz in missing:
            print("   [%-13s] %-12s crc=%s (%d bytes)" % (region, name, c, sz))
        print("\nThis port needs the MAME 'mooncrst' set (Moon Cresta, Nichibutsu).")
        print("Make sure you pointed at the right .zip/.7z (split or merged both work).")
        sys.exit(1)
    if len(out) != ROM_TOTAL:
        sys.exit("ERROR: assembled %d bytes, expected %d." % (len(out), ROM_TOTAL))
    return bytes(out)


# ---- locating the ROM-free program --------------------------------------
def find_program(build_ok):
    """Return (exe_path, romfree_adf_path), building them if needed/allowed."""
    exe = os.path.join(BUILD, "mooncrst")
    adf = os.path.join(BUILD, "mooncrst.adf")
    if os.path.exists(exe) and os.path.exists(adf):
        return exe, adf
    if build_ok and shutil.which("make") and os.path.exists(os.path.join(ROOT, "Makefile")):
        print("ROM-free program not found -- building it (make GAME=mooncrst adf)...")
        subprocess.check_call(["make", "GAME=mooncrst", "adf"], cwd=ROOT)
        if os.path.exists(exe) and os.path.exists(adf):
            return exe, adf
    sys.exit("ERROR: ROM-free program not found (build/mooncrst[.adf]).\n"
             "  Either build it here (needs the m68k toolchain): make GAME=mooncrst adf\n"
             "  or download the ROM-free release from GitHub and pass --exe/--adf.")


def make_adf(romfree_adf, rom_bytes):
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "MoonCresta.adf")
    shutil.copyfile(romfree_adf, out)
    rom_tmp = os.path.join(DIST, ROM_NAME)
    with open(rom_tmp, "wb") as f:
        f.write(rom_bytes)
    xdftool = shutil.which("xdftool") or "xdftool"
    # write the ROM into the floppy root, next to the program
    subprocess.check_call([xdftool, out, "write", rom_tmp, ROM_NAME])
    print("  ADF  ->  %s" % out)
    return out


def make_hd(exe, rom_bytes):
    hd = os.path.join(DIST, "MoonCresta_HD")
    os.makedirs(hd, exist_ok=True)
    shutil.copyfile(exe, os.path.join(hd, "mooncrst"))
    with open(os.path.join(hd, ROM_NAME), "wb") as f:
        f.write(rom_bytes)
    with open(os.path.join(hd, "README"), "w") as f:
        f.write("Moon Cresta (Amiga AGA port) -- hard-drive install\n"
                "Copy this drawer anywhere on your A1200, then run `mooncrst`\n"
                "(it loads mooncrst.rom from this same drawer). Needs Kickstart\n"
                "3.x / AGA; use an 030+ or JIT for full speed.\n")
    print("  HD   ->  %s/  (run `mooncrst`)" % hd)
    return hd


def make_lha(hd):
    tool = shutil.which("lha") or shutil.which("jlha")
    if not tool:
        print("  LHA  ->  skipped (no `lha`/`jlha` on PATH; the HD drawer above is ready to use).")
        print("           Install one to get the .lha:  Debian/Ubuntu `apt install jlha-utils`,")
        print("           macOS `brew install lhasa`, or build github.com/jca02266/lha.")
        return None
    out = os.path.join(DIST, "MoonCresta.lha")
    if os.path.exists(out):
        os.remove(out)
    # archive the drawer itself (so it unpacks to MoonCresta_HD/...) from dist/
    subprocess.check_call([tool, "a", out, os.path.basename(hd)], cwd=DIST)
    print("  LHA  ->  %s" % out)
    return out


def ask(prompt, default=None):
    s = input(prompt).strip()
    return s or default


def main():
    ap = argparse.ArgumentParser(description="Package the Amiga Moon Cresta ADF/HD from your MAME romset.")
    ap.add_argument("romset", nargs="?", help="path to your MAME mooncrst romset (.zip/.7z/dir)")
    ap.add_argument("--romset", dest="romset_opt", help="same as positional romset")
    ap.add_argument("--exe", help="path to a ROM-free mooncrst program (default: build/mooncrst)")
    ap.add_argument("--adf", help="path to a ROM-free mooncrst.adf (default: build/mooncrst.adf)")
    ap.add_argument("--adf-only", action="store_true", help="only produce the ADF")
    ap.add_argument("--no-build", action="store_true", help="never invoke make; require prebuilt program")
    args = ap.parse_args()

    print("=== Amiga Moon Cresta -- release packager ===\n")
    romset = args.romset or args.romset_opt
    if not romset:
        print("You'll need your OWN MAME Moon Cresta romset (the 'mooncrst' set).")
        kind = ask("Is it [s]plit or [m]erged?  (either works -- I match by CRC) [s/m]: ", "s")
        hint = "mooncrst.zip" if kind.lower().startswith("s") else "merged mooncrst.zip (parent set)"
        romset = ask("Path to your romset %s (.zip/.7z or a folder): " % ("(" + hint + ")"))
        if not romset:
            sys.exit("No romset given -- nothing to do.")

    print("\nScanning romset for the Moon Cresta ROMs (by CRC32)...")
    found = collect([os.path.expanduser(romset)])
    rom = assemble_rom(found)
    print("  OK: assembled %s (%d bytes).\n" % (ROM_NAME, len(rom)))

    if args.exe and args.adf:
        exe, adf = args.exe, args.adf
    else:
        exe, adf = find_program(build_ok=not args.no_build)

    print("Packaging into dist/ ...")
    make_adf(adf, rom)
    if not args.adf_only:
        hd = make_hd(exe, rom)
        make_lha(hd)
    print("\nDone. Copy the ADF onto a disk (or mount it) and boot an AGA Amiga.")


if __name__ == "__main__":
    main()

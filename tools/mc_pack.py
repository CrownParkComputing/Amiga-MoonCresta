#!/usr/bin/env python3
"""
mc_pack.py -- core packaging logic for the Amiga Moon Cresta port, shared by
the CLI (build_release.py) and the GUI (gui_packager.py).

Given a MAME Moon Cresta romset it assembles mooncrst.rom (by CRC32, so split
vs merged and filenames don't matter) and produces a bootable ADF, a hard-drive
drawer, and/or an LHA. It needs a ROM-free build of the program (the Amiga exe
+ a ROM-free bootable ADF); when frozen by PyInstaller those are bundled inside
the executable, otherwise they're taken from build/ (or built via make).

Nothing here ever bundles or emits the copyrighted ROM into the repo -- the ROM
only ever exists in the user-chosen output directory.
"""
import os, sys, zlib, zipfile, shutil, subprocess

# repo root (only meaningful when running from a source checkout, not frozen)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")

ROM_NAME = "mooncrst.rom"
ROM_TOTAL = 24608

# MAME `mooncrst` set (Moon Cresta, Nichibutsu, unencrypted). Each part is
# (name, crc32, size); we match the user's files by CRC32 and concatenate.
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


class PackError(Exception):
    """A user-facing packaging failure (bad romset, missing program, ...)."""


# ---- romset -> mooncrst.rom (CRC-matched) -------------------------------
def _crc(data):
    return "%08x" % (zlib.crc32(data) & 0xffffffff)


def _add_blob(data, found):
    found.setdefault(_crc(data), data)
    if len(data) > 2048 and len(data) % 2048 == 0:        # combined-region files
        for i in range(0, len(data), 2048):
            chunk = data[i:i + 2048]
            found.setdefault(_crc(chunk), chunk)


def _scan(path, found):
    low = path.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not n.endswith("/"):
                    _add_blob(z.read(n), found)
    elif low.endswith(".7z"):
        try:
            import py7zr
        except ImportError:
            raise PackError("%s is a .7z archive -- extract it first, or "
                            "install py7zr." % os.path.basename(path))
        with py7zr.SevenZipFile(path, "r") as z:
            for _, bio in z.readall().items():
                _add_blob(bio.read(), found)
    else:
        with open(path, "rb") as f:
            _add_blob(f.read(), found)


def collect(paths):
    found = {}
    for p in paths:
        if os.path.isdir(p):
            for r, _, files in os.walk(p):
                for fn in files:
                    _scan(os.path.join(r, fn), found)
        elif os.path.exists(p):
            _scan(p, found)
        else:
            raise PackError("No such path: %s" % p)
    return found


def assemble_rom(romset_path):
    found = collect([os.path.expanduser(romset_path)])
    out, missing = bytearray(), []
    for region, parts in REGIONS:
        for name, want, size in parts:
            data = found.get(want)
            if data is None:
                missing.append("[%s] %s (crc %s)" % (region, name, want))
            else:
                out += data[:size]
    if missing:
        raise PackError(
            "These Moon Cresta ROMs were not found in your romset:\n  "
            + "\n  ".join(missing)
            + "\n\nThis port needs the MAME 'mooncrst' set (Nichibutsu). Split "
              "or merged both work -- check you picked the right archive.")
    if len(out) != ROM_TOTAL:
        raise PackError("Assembled %d bytes, expected %d." % (len(out), ROM_TOTAL))
    return bytes(out)


# ---- locating the ROM-free program --------------------------------------
def _resource_base():
    """Where PyInstaller unpacked bundled data, or None when run from source."""
    return getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None


def find_program(exe=None, adf=None, build_ok=True):
    """Return (exe_path, romfree_adf_path)."""
    exe_cands = [exe] if exe else []
    adf_cands = [adf] if adf else []
    base = _resource_base()
    if base:
        exe_cands.append(os.path.join(base, "mooncrst"))
        adf_cands.append(os.path.join(base, "mooncrst.adf"))
    for d in (BUILD, DIST):
        exe_cands.append(os.path.join(d, "mooncrst"))
        adf_cands.append(os.path.join(d, "mooncrst.adf"))
    exe_p = next((p for p in exe_cands if p and os.path.exists(p)), None)
    adf_p = next((p for p in adf_cands if p and os.path.exists(p)), None)
    if exe_p and adf_p:
        return exe_p, adf_p
    if build_ok and not base and shutil.which("make") and os.path.exists(os.path.join(ROOT, "Makefile")):
        subprocess.check_call(["make", "GAME=mooncrst", "adf"], cwd=ROOT)
        if os.path.exists(os.path.join(BUILD, "mooncrst")) and os.path.exists(os.path.join(BUILD, "mooncrst.adf")):
            return os.path.join(BUILD, "mooncrst"), os.path.join(BUILD, "mooncrst.adf")
    raise PackError(
        "Couldn't find the ROM-free program (mooncrst + mooncrst.adf).\n"
        "Build it with `make GAME=mooncrst adf`, or download the ROM-free ADF "
        "from the project's CI artifacts.")


# ---- ADF injection (in-process so it works inside a frozen exe) ----------
def inject_rom_into_adf(adf_path, rom_bytes):
    tmp = adf_path + ".rom.tmp"
    with open(tmp, "wb") as f:
        f.write(rom_bytes)
    try:
        try:
            from amitools.tools import xdftool
            rc = xdftool.main([adf_path, "write", tmp, ROM_NAME])
            if rc not in (0, None):
                raise PackError("xdftool returned %r writing the ROM into the ADF." % rc)
        except ImportError:
            tool = shutil.which("xdftool")
            if not tool:
                raise PackError("Need amitools/xdftool to write the ADF (pip install amitools).")
            subprocess.check_call([tool, adf_path, "write", tmp, ROM_NAME])
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---- output builders -----------------------------------------------------
def make_adf(romfree_adf, rom_bytes, out_dir, log=print):
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "MoonCresta.adf")
    shutil.copyfile(romfree_adf, out)
    inject_rom_into_adf(out, rom_bytes)
    log("ADF  ->  %s" % out)
    return out


def make_hd(exe, rom_bytes, out_dir, log=print):
    hd = os.path.join(out_dir, "MoonCresta_HD")
    os.makedirs(hd, exist_ok=True)
    shutil.copyfile(exe, os.path.join(hd, "mooncrst"))
    with open(os.path.join(hd, ROM_NAME), "wb") as f:
        f.write(rom_bytes)
    with open(os.path.join(hd, "README"), "w") as f:
        f.write("Moon Cresta (Amiga AGA port) -- hard-drive install\n"
                "Copy this drawer onto your A1200 and run `mooncrst` (it loads\n"
                "mooncrst.rom from this same drawer). Kickstart 3.x / AGA; use an\n"
                "030+ or JIT for full speed.\n")
    log("HD   ->  %s%smooncrst" % (hd, os.sep))
    return hd


def make_lha(hd_dir, out_dir, log=print):
    tool = shutil.which("lha") or shutil.which("jlha")
    if not tool:
        log("LHA  ->  skipped (no lha/jlha installed; the HD drawer is ready to use)")
        return None
    out = os.path.join(out_dir, "MoonCresta.lha")
    if os.path.exists(out):
        os.remove(out)
    subprocess.check_call([tool, "a", out, os.path.basename(hd_dir)], cwd=out_dir)
    log("LHA  ->  %s" % out)
    return out


def build(romset, out_dir, want_adf=True, want_hd=True, want_lha=False,
          exe=None, adf=None, build_ok=True, log=print):
    """Top-level: assemble the ROM and produce the requested outputs.
    Returns a dict of {kind: path}. Raises PackError on user-facing problems."""
    log("Reading romset (matching ROMs by CRC32)...")
    rom = assemble_rom(romset)
    log("Assembled %s (%d bytes)." % (ROM_NAME, len(rom)))
    exe_p, adf_p = find_program(exe, adf, build_ok)
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    if want_adf:
        results["adf"] = make_adf(adf_p, rom, out_dir, log)
    if want_hd or want_lha:
        hd = make_hd(exe_p, rom, out_dir, log)
        results["hd"] = hd
        if want_lha:
            lha = make_lha(hd, out_dir, log)
            if lha:
                results["lha"] = lha
    log("Done.")
    return results

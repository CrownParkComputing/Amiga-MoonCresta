# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Moon Cresta disk builder GUI. Produces a single
# self-contained executable that bundles the ROM-free program (the Amiga exe +
# a ROM-free bootable ADF) and amitools (to write the ROM into the ADF
# in-process). Build with:
#
#   pyinstaller tools/packager.spec --distpath gui_dist --workpath gui_build
#
# The bundled program is ROM-free -- the copyrighted ROM is only ever supplied
# by the end user at runtime and written to their chosen output folder.
import os
from PyInstaller.utils.hooks import collect_all

# ROM-free artifacts to bundle (built by `make GAME=mooncrst adf`).
datas = [('build/mooncrst', '.'), ('build/mooncrst.adf', '.')]
binaries = []
hiddenimports = ['mc_pack']

for pkg in ('amitools', 'machine68k'):          # amitools writes the ADF; machine68k is its dep
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['tools/gui_packager.py'],
    pathex=['tools'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='MoonCrestaDiskBuilder',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed GUI app
)

# Prebuilt ROM-free program

`mooncrst` (the Amiga AGA executable) and `mooncrst.adf` (a bootable, **ROM-free**
floppy image) are committed here so the disk-builder GUI can be packaged by CI
without an Amiga cross-toolchain. They are **our own compiled output and contain
no copyrighted ROM** — the user supplies their own ROM at runtime.

Regenerate after changing the Amiga code:
    make GAME=mooncrst adf
    cp build/mooncrst build/mooncrst.adf prebuilt/

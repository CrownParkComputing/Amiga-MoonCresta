# Adding the C cross-compiler for the interpreter cores

The `m6809.c` and `z80.c` files in `src/cores/` are written in
portable C99. They'll only link into the final binary once an
m68k-targeted C compiler is installed.

## Recommended: Bebbo's m68k-amigaos-gcc

```
git clone https://github.com/bebbo/amiga-gcc
cd amiga-gcc
make
```

This builds a full m68k-amigaos-{gcc,as,ld,objdump,...} toolchain
in `build/`. Add `build/bin` to your PATH and update the Makefile:

```diff
-ASM ?= vasmm68k_mot
+CC  ?= m68k-amigaos-gcc
+ASM ?= vasmm68k_mot
```

Then add the C source to the build:

```make
C_SRCS := $(SRCDIR)/cores/m6809.c $(SRCDIR)/cores/z80.c
C_OBJS := $(patsubst $(SRCDIR)/%.c,$(BUILDDIR)/%.o,$(C_SRCS))

$(BUILDDIR)/%.o: $(SRCDIR)/%.c
	$(CC) -m68000 -O2 -fomit-frame-pointer -I$(SRCDIR)/cores -c -o $@ $<
```

## Why not vasm-only?

`vasm` is an assembler, not a C compiler. The 6809 + Z80 cores are
~3500 + ~3300 lines of C respectively; re-implementing them in
hand-written 68k assembly is months of work and buys you nothing —
the C versions already run on 68k with -O2.

## Performance note

The spc476 6809 + C-Chads z80 cores are portable reference
interpreters, not cycle-accurate optimisations. They will be the
performance bottleneck. Once the basic port works, swap them out
for the MAME `m6809.cpp` / `z80.cpp` cores (which target
`m68000-amigaos` directly) or Karl Stenerud's Musashi if it's
been ported to 68k.

# Z80 arcade disassembler toolchain

Generic tooling to disassemble a Z80 arcade ROM into a MAME-style listing
that JotD's `z80268k.py` can transcode to 68k. Game-agnostic core; the
coverage step uses a per-machine runner (we have the Galaxian family).

## Pieces

- **`z80dasm.py`** — complete, self-contained Z80 disassembler (algorithmic
  x/y/z/p/q decode; all prefixes CB/ED/DD/FD/DDCB/FDCB). One instruction ->
  `(text, length, targets, stops)`. Output is lowercase MAME syntax with `$`
  hex. Run standalone to dump a region:
  `python3 tools/z80dasm.py rom.bin 0xad 0x110`

- **`z80disasm.py`** — driver. Recursive descent from the CPU entry/interrupt
  vectors (follows `targets`, respects `stops`) to separate code from data,
  optionally seeded with an execution trace. Emits the `AAAA: BB BB  mnemonic`
  format `z80268k.py` consumes; unreached bytes become `db`.
  ```
  python3 tools/z80disasm.py epr194,...,epr201 --trace trace.txt -o out.asm
  ```

- **`z80trace_host.c`** — execution-coverage tracer. Runs the game on the
  vendored Z80 core + machine layer (host build), logs every executed
  instruction address. Catches code reached only via computed jumps / jump
  tables that recursive descent can't follow.
  ```
  gcc -O2 -Isrc/cores -Isrc/hal -o /tmp/z80trace tools/z80trace_host.c \
      src/cores/z80.c src/hal/machine.c
  /tmp/z80trace games/mooncrst/roms 4000 > trace.txt
  ```

## Coverage is the hard part (per game)

Separating code from data in a raw ROM is undecidable in general; we combine:
1. **Recursive descent** (static) — follows all direct calls/jumps from the
   reset + interrupt vectors.
2. **Execution trace** (dynamic) — whatever the game actually runs. Only as
   complete as the states you exercise: attract alone is a small fraction.
   To cover gameplay the tracer must drive the *correct* inputs (coin/start/
   play) for that game -- the input bits in z80trace_host.c are Galaxian
   defaults and need tuning per title (see zarcade's input variant).
3. **Jump-table seeding** (manual) — Galaxian-family state machines dispatch
   through `jp (hl)` tables; those targets must be fed in as extra `--entry`
   / trace seeds.

## Full-speed transcode recipe (PROVEN on Moon Cresta -> 99% converted)

The native-68k path for 60fps (vs the ~10fps interpreter). Repeatable per game:

1. **Trace coverage** (needs the game's machine model for input bits):
   ```
   gcc -O2 -DZ80_TRACE_PC -Isrc/cores -Isrc/hal -o /tmp/z80trace \
       tools/z80trace_host.c src/cores/z80.c src/hal/machine.c
   /tmp/z80trace games/mooncrst/roms 6000 > trace.txt   # gameplay script inside
   ```
   z80.c built `-DZ80_TRACE_PC` calls `z80_trace_pc()` per instruction via the
   real `machine_run_frame` path. Moon Cresta: 73% of the ROM covered.
2. **Disassemble** (recursive descent + trace):
   `python3 tools/z80disasm.py <roms> --trace trace.txt -o dis.asm`
   (emits UPPERCASE bytes + `.db` data, both required by z80268k.)
3. **Transcode** with JotD's z80268k.py -- **use `-o mit`** (its `-o mot`
   macros are stale and crash, "MOT macros are not up to date"):
   ```
   python3 .../amiga68ktools/tools/z80268k.py -i mot -o mit \
       -c game.68k -I game.inc dis.asm
   ```
   Moon Cresta: 5810/5813 instructions, **only ~15 review/ERROR lines**
   (SP usage, `retn`, one `jp (hl)` jump table, flag-test/BCD edge cases).
4. **Hand-fix** the review lines + **wire the HAL macros** the transcode uses
   (`GET_ADDRESS` -> RAM/VRAM/IO routing, the I/O write hooks, flag macros in
   the .inc) -- galaxian500's `src/amiga/amiga.68k` is the reference.
5. **Assemble** game.68k (MIT/GNU syntax) with `m68k-amigaos-as`, link with the
   HAL + renderer (our mc_video/mc_render read the same VRAM), build the ADF.

Artifacts for Moon Cresta are checked in at `games/mooncrst/transcode/`.

## Host 68k debug harness (tools/run_native_host.py) -- the smart unblock

We can't boot the Amiga here, so to debug the NATIVE transcode without blind
ADF iteration, `run_native_host.py` runs it on the host via **machine68k**
(Musashi): link the transcode flat (`vlink -brawbin1 -T flat.ld ...`), load it
+ the ROM into a 64K Z80 space, run `cpu_init` + the entry/init + the NMI
handler, and use a per-instruction hook to (a) stop at a sentinel return and
(b) catch the first jump to a wild address, dumping the PC ring that led there.

Status: `cpu_init` + entry start correctly; **init crashes** with a `rts` to a
bad return address (~sentinel+4) = a 68k/Z80 **stack-width mismatch** (Z80
`push`=2 bytes, `call/ret`=4-byte bsr/rts; a `push addr; ret` jump idiom or
jump table then misaligns). That's the next fix -- now debuggable on the host.

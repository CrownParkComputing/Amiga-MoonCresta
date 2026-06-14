# Makefile -- Namco-Amiga multi-game build
# ============================================================
#
# Linux-first build for the Namco-arcade-to-Amiga anchored-emulation
# ports. Replaces the Windows-only jotd makefile.am.
#
# Universal commands:
#   make            build slave + main exe for the DEFAULT game
#   make list       list all games discovered from games/*/META.toml
#   make game-<n>   build slave + main exe for game <n>
#   make clean
#   make archive    build WHDLoad-installable directory for DEFAULT
#   make archive-<n>  build for game <n>
#   make test       run unit tests
#   make tools-...  invoke the python tooling
#
# DEFAULT game is pacland (priority); override with `make GAME=pacmania all`.
#
# ============================================================

PROJDIR   := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SRCDIR    := $(PROJDIR)/src
BUILDDIR  := $(PROJDIR)/build
TOOLSDIR  := $(PROJDIR)/tools
GAMESDIR  := $(PROJDIR)/games
GAME      ?= pacland
META      := $(GAMESDIR)/$(GAME)/META.toml
IOMAP     := $(GAMESDIR)/$(GAME)/io_map.json
GAMEBUILD := $(BUILDDIR)/$(GAME)
GAMESLAVE := $(BUILDDIR)/$(GAME).slave

# Bebbo's m68k-amigaos toolchain (built once, lives in $AMIGA_GCC_HOME or default).
# We use M68K_CC instead of CC because make's built-in CC defaults to host
# gcc and would clobber our cross-compiler.
AMIGA_GCC_HOME ?= /home/jon/amiga-amigaos
M68K_CC        ?= $(AMIGA_GCC_HOME)/bin/m68k-amigaos-gcc
# Target the A1200's 68020: better codegen + hardware 32-bit mul/div
# (the C interpreter is the hot path, and the A1200 is the deploy target).
M68K_CC_BASE   = -m68020 -noixemul -O2 -fomit-frame-pointer -I$(SRCDIR)/cores
CC_OBJS_DIR    = $(BUILDDIR)/c

# Toolchain
ASM       ?= vasmm68k_mot
ASMFLAGS  ?= -I$(SRCDIR) -I$(SRCDIR)/amiga -I$(SRCDIR)/hal -m68000 -phxass -nowarn=62
LINK      ?= vlink
LFLAGS    ?= -b amigahunk -Bstatic -Cexestack -mrel

# Sources
ASM_SRCS  := \
    $(SRCDIR)/slave.s          \
    $(SRCDIR)/amiga/amiga.s    \
    $(SRCDIR)/hal/hal_stubs.s  \
    $(SRCDIR)/hal/handlers.s   \
    $(SRCDIR)/hal/video.s      \
    $(SRCDIR)/hal/hal_sysvars.s \

C_SRCS    := \
    $(SRCDIR)/cores/m6809.c    \
    $(SRCDIR)/cores/z80.c      \
    $(SRCDIR)/hal/hal_io.c     \
    $(SRCDIR)/hal/video.c      \
    $(SRCDIR)/hal/machine.c    \

# Per-game frame hooks: Moon Cresta runs the Z80 + tilemap renderer;
# everything else uses the default (Pacland-style) hooks.
ifeq ($(GAME),mooncrst)
ifeq ($(DIAG),1)
# Diagnostic build: real display setup, but background colour reports
# whether the Z80 is running (green=alive, red=dead). No dos.library.
C_SRCS    += \
    $(SRCDIR)/hal/mc_video.c   \
    $(SRCDIR)/hal/mc_render.c  \
    $(SRCDIR)/hal/mc_diag.c    \
    $(SRCDIR)/hal/mc_romload.c \

else
C_SRCS    += \
    $(SRCDIR)/hal/mc_video.c   \
    $(SRCDIR)/hal/mc_render.c  \
    $(SRCDIR)/hal/mc_run.c     \
    $(SRCDIR)/hal/mc_audio.c   \
    $(SRCDIR)/hal/mc_font.c    \
    $(SRCDIR)/hal/mc_romload.c \

endif
else
C_SRCS    += $(SRCDIR)/hal/game_default.c
endif

# C files generated during the build (in $(BUILDDIR)/)
C_SRCS_BUILDDIR := \
    $(BUILDDIR)/c/$(GAME)_io_dispatch.c \

ASM_OBJS  := $(patsubst $(SRCDIR)/%.s,$(BUILDDIR)/%.o,$(ASM_SRCS))
# C source files can come from cores/, hal/, or the generated
# dispatch table. Each gets compiled to $(BUILDDIR)/c/<name>.o.
# Note: generated C files in $(BUILDDIR)/c/ skip the SRCDIR prefix.
C_OBJS    := $(patsubst $(SRCDIR)/%.c,$(CC_OBJS_DIR)/%.o,$(C_SRCS)) \
             $(patsubst $(BUILDDIR)/%.c,$(BUILDDIR)/%.o,$(C_SRCS_BUILDDIR))
ALL_OBJS  := $(ASM_OBJS) $(C_OBJS)

.PHONY: all list clean test dirs tools-version tools-games tools-archive tools-validate
.PHONY: archive game-$(GAME) archive-$(GAME)

# Auto-discover games from games/<name>/META.toml
LIST_GAMES = $(notdir $(wildcard $(GAMESDIR)/*/META.toml))

# ---- main targets -------------------------------------------------

all: dirs $(GAMEBUILD) $(GAMESLAVE)

list:
	@echo "Discovered games:"
	@for d in $(wildcard $(GAMESDIR)/*/); do \
	    test -f "$$d/META.toml" && echo "  $$(basename $$d)"; \
	done

dirs:
	@mkdir -p $(BUILDDIR)/amiga $(CC_OBJS_DIR)

$(BUILDDIR)/%.o: $(SRCDIR)/%.s
	@mkdir -p $(dir $@)
	$(ASM) $(ASMFLAGS) -Fhunk -o $@ $<

# Pattern rule for the C cores (built with m68k-amigaos-gcc).
# Two patterns: one for sources under $(SRCDIR)/, one for
# generated files under $(BUILDDIR)/.
$(CC_OBJS_DIR)/%.o: $(SRCDIR)/%.c
	@mkdir -p $(dir $@)
	$(M68K_CC) $(M68K_CC_BASE) -I$(SRCDIR)/hal -c -o $@ $<

$(BUILDDIR)/%.o: $(BUILDDIR)/%.c
	@mkdir -p $(dir $@)
	$(M68K_CC) $(M68K_CC_BASE) -I$(SRCDIR)/hal -I$(SRCDIR)/cores -c -o $@ $<

# Link the main executable: assembly + C cores.
# vlink takes both; vasm produces Hunk format objects that vlink
# can read natively, and the m68k-amigaos-gcc -c -o also produces
# Hunk format when given an Amiga hunk-friendly build.
$(GAMEBUILD): $(ALL_OBJS)
	$(LINK) $(LFLAGS) -o $@ $(ALL_OBJS)

# The dispatch C file is generated from io_map.json BEFORE
# compilation. The phony target forces it to regenerate every
# build (cheap: ~50ms).
.PHONY: $(BUILDDIR)/c/$(GAME)_io_dispatch.c
$(BUILDDIR)/c/$(GAME)_io_dispatch.c: $(GAMESDIR)/$(GAME)/io_map.json
	@mkdir -p $(BUILDDIR)/c
	cd $(PROJDIR) && PYTHONPATH=$(SRCDIR) python3 -m namco_amiga dispatch \
	    --project-root $(PROJDIR) --game $(GAME)

$(GAMESLAVE): $(BUILDDIR)/slave.o
	$(ASM) $(ASMFLAGS) -Fhunkexe -o $@ $<
	@echo "  SLAVE  $@"

# Per-game targets: `make game-pacmania` builds pacmania's binary + slave
define game_target_template
game-$(1): $(BUILDDIR)/$(1) $(BUILDDIR)/$(1).slave
archive-$(1): game-$(1)
	@$$(call do_archive,$(1))
endef

# Build the default pacland game target via the same template
game-$(GAME): $(GAMEBUILD) $(GAMESLAVE)
archive-$(GAME): $(GAMEBUILD) $(GAMESLAVE)
	@$(call do_archive,$(GAME))

# ---- archive (calls the python tool) -----------------------------

define do_archive
	@rm -rf $(BUILDDIR)/$(1)_HD
	@mkdir -p $(BUILDDIR)/$(1)_HD
	@cp $(BUILDDIR)/$(1)       $(BUILDDIR)/$(1).slave  $(BUILDDIR)/$(1)_HD/
	@cp $(PROJDIR)/README.md 2>/dev/null $(BUILDDIR)/$(1)_HD/ || true
	@echo "  ARCHIVE  $(BUILDDIR)/$(1)_HD"
endef

# ---- python tooling passthroughs --------------------------------

tools-version:
	cd $(PROJDIR) && PYTHONPATH=$(SRCDIR) python3 -m namco_amiga version

tools-games:
	cd $(PROJDIR) && PYTHONPATH=$(SRCDIR) python3 -m namco_amiga games \
	    --project-root $(PROJDIR)

tools-validate: all
	cd $(PROJDIR) && PYTHONPATH=$(SRCDIR) python3 -m namco_amiga validate \
	    --project-root $(PROJDIR) --game $(GAME)

tools-archive: all
	cd $(PROJDIR) && PYTHONPATH=$(SRCDIR) python3 -m namco_amiga archive \
	    --project-root $(PROJDIR) --game $(GAME)

test:
	cd $(PROJDIR) && PYTHONPATH=$(SRCDIR):$(PROJDIR)/tests python3 -m unittest discover -s tests -v

# alias for backward compat with the original Makefile
archive: archive-$(GAME)

# ---- bootable ADF (needs amitools' xdftool: pip install --user amitools) ----
XDFTOOL ?= xdftool
adf: $(GAMEBUILD)
	@printf 'SYS:$(GAME)\n' > $(BUILDDIR)/startup-sequence
	@rm -f $(BUILDDIR)/$(GAME).adf
	$(XDFTOOL) $(BUILDDIR)/$(GAME).adf format "$(GAME)" + boot install \
	    + write $(GAMEBUILD) $(GAME) \
	    + makedir s + write $(BUILDDIR)/startup-sequence s/startup-sequence
	@echo "  ADF  $(BUILDDIR)/$(GAME).adf"

clean:
	rm -rf $(BUILDDIR)

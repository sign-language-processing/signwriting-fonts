# SignWriting fonts — build recipe.
#
# Everything generated/downloaded lives under fonts/tmp/ (gitignored). The
# repo only tracks: this Makefile, the python sources, rules.json (the
# human-authored composition rules), and the final upstream-mirrored TTFs.
#
# Default target rebuilds the 1D symbol-explorer website end-to-end.

TMP := fonts/tmp
PKG := signwriting_fonts/font_1d

.PHONY: all serve watch clean
all: $(TMP)/site/index.html

clean:
	rm -rf $(TMP)

# =========================================================================
# Upstream-mirrored fonts (tracked) and downloads
# =========================================================================

fonts/SuttonSignWritingOneD.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingOneD.ttf

# Cubic-Bezier source SVGs from sutton-signwriting/font-db
# (iswa2010.db is a SQLite DB of every symbol's source SVG)
$(TMP)/iswa2010.db:
	mkdir -p $(dir $@)
	wget -O $@ https://unpkg.com/@sutton-signwriting/font-db/db/iswa2010.db

# Structural-marker SVGs (SW A/B/L/M/R + SW 250-749) from Slevinski's
# signwriting_2010_fonts repo. These aren't in iswa2010.db.
$(TMP)/1d/other_svg.zip:
	mkdir -p $(dir $@)
	wget -O $@ https://github.com/Slevinski/signwriting_2010_fonts/raw/master/source/other_svg.zip

$(TMP)/1d/markers/.extracted: $(TMP)/1d/other_svg.zip
	rm -rf $(TMP)/1d/markers
	unzip -o $(TMP)/1d/other_svg.zip -d $(TMP)/1d/
	mv $(TMP)/1d/other_svg $(TMP)/1d/markers
	touch $@

# Hero examples (tracked PNGs alongside the upstream TTFs).
assets/SuttonSignWritingOneD-example.png: fonts/SuttonSignWritingOneD.ttf
	hb-view fonts/SuttonSignWritingOneD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

assets/SuttonSignWritingTwoD-example.png: fonts/SuttonSignWritingTwoD.ttf
	hb-view fonts/SuttonSignWritingTwoD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

# =========================================================================
# 1D font — rebuilt from cubic source SVGs in font-db (issue #1)
# =========================================================================

# Extract per-symbol SVGs from iswa2010.db.
$(TMP)/1d/svg/.extracted: $(TMP)/iswa2010.db $(PKG)/extract.py
	python -m signwriting_fonts.font_1d.extract --db $(TMP)/iswa2010.db --out $(TMP)/1d/svg
	touch $@

# Fit ellipses to whole circular sub-paths and emit cleaner SVGs.
# Side outputs: ellipsed.json (per-symbol replacement counts) and
# circles.json (lenient circle-detection — drives the site's decoration).
$(TMP)/1d/svg-opt/.optimized $(TMP)/ellipsed.json $(TMP)/circles.json &: $(TMP)/1d/svg/.extracted $(PKG)/optimize.py
	python -m signwriting_fonts.font_1d.optimize \
		--in-dir $(TMP)/1d/svg --out-dir $(TMP)/1d/svg-opt \
		--report $(TMP)/ellipsed.json \
		--circles-report $(TMP)/circles.json
	touch $(TMP)/1d/svg-opt/.optimized

# Hand D4 + C8 rotation composites — emitted by formula from the symbol
# inventory in the extracted-SVG dir.
$(TMP)/duplicates.json: $(PKG)/tune_dedup.py $(TMP)/1d/svg/.extracted
	python -m signwriting_fonts.font_1d.tune_dedup \
		--svg-dir $(TMP)/1d/svg --output $@

# Multi-part rule compositions — resolved from rules.json against the
# extracted SVGs.
$(TMP)/compositions.json: $(PKG)/compositions.py $(PKG)/rules.json $(TMP)/1d/svg/.extracted
	python -m signwriting_fonts.font_1d.compositions \
		--svg-dir $(TMP)/1d/svg \
		--rules   $(PKG)/rules.json \
		--output  $@

# Base TTF from extracted SVGs via FontForge (cubic→quadratic happens in
# FontForge during .ttf export).
$(TMP)/SignWritingOneD-base.ttf: $(TMP)/1d/svg-opt/.optimized $(TMP)/1d/markers/.extracted $(PKG)/build_font.py $(TMP)/duplicates.json $(TMP)/compositions.json
	fontforge -lang=py -script $(PKG)/build_font.py \
		--svg-dir $(TMP)/1d/svg-opt --markers-dir $(TMP)/1d/markers \
		--duplicates   $(TMP)/duplicates.json \
		--compositions $(TMP)/compositions.json \
		--iou-threshold 0.9 --output $@

# No-dedup oracle TTF — same source SVGs, no duplicates/compositions.
# Used by the regression tests and the explorer's size-impact table.
$(TMP)/SignWritingOneD-unopt.ttf: $(TMP)/1d/svg/.extracted $(TMP)/1d/markers/.extracted $(PKG)/build_font.py
	fontforge -lang=py -script $(PKG)/build_font.py \
		--svg-dir $(TMP)/1d/svg --markers-dir $(TMP)/1d/markers \
		--output $@

# VTP positioning rules + the final 1D TTF (via volt2ttf).
$(TMP)/SignWritingOneD.vtp: $(TMP)/SignWritingOneD-base.ttf $(PKG)/generate_vtp.py
	python -m signwriting_fonts.font_1d.generate_vtp --ttf $(TMP)/SignWritingOneD-base.ttf > $@

fonts/SignWritingOneD.ttf: $(TMP)/SignWritingOneD.vtp $(TMP)/SignWritingOneD-base.ttf
	volt2ttf -t $(TMP)/SignWritingOneD.vtp $(TMP)/SignWritingOneD-base.ttf $@

# Symbol-explorer website. `make serve` runs an HTTP server with
# live-reload polling on version.txt; `make watch` rebuilds when the
# Python sources change.
$(TMP)/site/index.html: \
		$(TMP)/SignWritingOneD-base.ttf \
		$(TMP)/SignWritingOneD-unopt.ttf \
		fonts/SuttonSignWritingOneD.ttf \
		$(TMP)/duplicates.json \
		$(TMP)/compositions.json \
		$(TMP)/circles.json \
		$(PKG)/site.py
	python -m signwriting_fonts.font_1d.site \
		--new-ttf   $(TMP)/SignWritingOneD-base.ttf \
		--old-ttf   fonts/SuttonSignWritingOneD.ttf \
		--unopt-ttf $(TMP)/SignWritingOneD-unopt.ttf \
		--duplicates   $(TMP)/duplicates.json \
		--compositions $(TMP)/compositions.json \
		--circles      $(TMP)/circles.json \
		--out-dir      $(TMP)/site

serve: $(TMP)/site/index.html
	@echo "Serving http://localhost:8000/  (Ctrl-C to stop)"
	@cd $(TMP)/site && python -m http.server 8000

watch:
	@command -v fswatch >/dev/null || { \
	  echo "Install fswatch first:  brew install fswatch" >&2; exit 1; }
	@fswatch -o $(PKG) | \
	  while read -r _; do \
	    echo "[watch] rebuild…"; \
	    make $(TMP)/site/index.html 2>&1 | tail -3; \
	  done

# =========================================================================
# 2D font
# =========================================================================
# Built directly from the upstream OneD glyphs: TTX-round-trip to rebox /
# resize each symbol into a 2D grid cell, then attach an axis-decomposed
# GPOS that positions each symbol within its M-box from the SW{x} SW{y}
# markers that follow it. No volt2ttf, no VTP intermediate.

$(TMP)/SuttonSignWritingTwoTone.ttx: fonts/SuttonSignWritingOneD.ttf
	ttx -o $@ $<

$(TMP)/SuttonSignWritingTwoToneModified.ttx: $(TMP)/SuttonSignWritingTwoTone.ttx signwriting_fonts/font_2d/modify_ttx.py
	python -m signwriting_fonts.font_2d.modify_ttx --input $< --output $@

$(TMP)/SuttonSignWritingTwoToneModified.ttf: $(TMP)/SuttonSignWritingTwoToneModified.ttx
	ttx -o $@ $<

fonts/SuttonSignWritingTwoD.ttf: $(TMP)/SuttonSignWritingTwoToneModified.ttf signwriting_fonts/font_2d/generate_vtp.py
	python -m signwriting_fonts.font_2d.generate_vtp --input-ttf $< --output-ttf $@

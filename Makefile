# SignWriting fonts — build recipe.
#
# Everything generated/downloaded lives under fonts/tmp/ (gitignored). The
# repo only tracks: this Makefile, the python sources, rules.json (the
# human-authored composition rules), and the final upstream-mirrored TTFs.
#
# Default target rebuilds the 1D symbol-explorer website end-to-end.

TMP := fonts/tmp
PKG := signwriting_fonts/font_1d

.PHONY: all 1d-fonts serve watch clean
all: 1d-fonts $(TMP)/site/index.html

# Build the three 1D fonts (OneD, Line, Fill).
1d-fonts: fonts/SuttonSignWritingOneD.ttf fonts/SuttonSignWritingLine.ttf fonts/SuttonSignWritingFill.ttf

clean:
	rm -rf $(TMP)

# =========================================================================
# Upstream-mirrored fonts (tracked) and downloads
# =========================================================================

$(TMP)/SuttonSignWritingOneD.ttf:
	mkdir -p $(dir $@)
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingOneD.ttf

$(TMP)/SuttonSignWritingLine.ttf:
	mkdir -p $(dir $@)
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingLine.ttf

$(TMP)/SuttonSignWritingFill.ttf:
	mkdir -p $(dir $@)
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingFill.ttf

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
	hb-view $< "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

assets/SuttonSignWritingTwoD-example.png: fonts/SuttonSignWritingTwoD.ttf
	hb-view fonts/SuttonSignWritingTwoD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

# =========================================================================
# 1D fonts (OneD, Line, Fill) — rebuilt from cubic source SVGs in font-db
# =========================================================================
#
# Same pipeline for all three variants: extract per-symbol SVGs from
# iswa2010.db (keep sym-line for OneD/Line, sym-fill for Fill) →
# ellipse-fit circular sub-paths → detect hand-rotation composites →
# resolve multi-part rule compositions → emit TTF. OneD and Line share
# the same extracted/optimized SVG set and dedup/composition JSONs;
# Fill has its own because the fill paths are smaller polygons with
# different topology.

# --- extract --------------------------------------------------------------

$(TMP)/1d/svg-line/.extracted: $(TMP)/iswa2010.db $(PKG)/extract.py $(PKG)/variants.py
	python -m signwriting_fonts.font_1d.extract \
		--variant line --db $(TMP)/iswa2010.db --out $(TMP)/1d/svg-line
	touch $@

$(TMP)/1d/svg-fill/.extracted: $(TMP)/iswa2010.db $(PKG)/extract.py $(PKG)/variants.py
	python -m signwriting_fonts.font_1d.extract \
		--variant fill --db $(TMP)/iswa2010.db --out $(TMP)/1d/svg-fill
	touch $@

# --- optimize (circle "trick" — fit ellipses to circular sub-paths) ------
# Side outputs: ellipsed-*.json (per-symbol replacement counts) and
# circles-*.json (lenient circle-detection — drives the site's decoration).

$(TMP)/1d/svg-line-opt/.optimized $(TMP)/ellipsed-line.json $(TMP)/circles-line.json &: $(TMP)/1d/svg-line/.extracted $(PKG)/optimize.py
	python -m signwriting_fonts.font_1d.optimize \
		--in-dir $(TMP)/1d/svg-line --out-dir $(TMP)/1d/svg-line-opt \
		--report $(TMP)/ellipsed-line.json \
		--circles-report $(TMP)/circles-line.json
	touch $(TMP)/1d/svg-line-opt/.optimized

$(TMP)/1d/svg-fill-opt/.optimized $(TMP)/ellipsed-fill.json $(TMP)/circles-fill.json &: $(TMP)/1d/svg-fill/.extracted $(PKG)/optimize.py
	python -m signwriting_fonts.font_1d.optimize \
		--in-dir $(TMP)/1d/svg-fill --out-dir $(TMP)/1d/svg-fill-opt \
		--report $(TMP)/ellipsed-fill.json \
		--circles-report $(TMP)/circles-fill.json
	touch $(TMP)/1d/svg-fill-opt/.optimized

# --- duplicates (hand D4 + C8 rotations) ---------------------------------

$(TMP)/duplicates-line.json: $(PKG)/tune_dedup.py $(TMP)/1d/svg-line/.extracted
	python -m signwriting_fonts.font_1d.tune_dedup \
		--svg-dir $(TMP)/1d/svg-line --output $@

$(TMP)/duplicates-fill.json: $(PKG)/tune_dedup.py $(TMP)/1d/svg-fill/.extracted
	python -m signwriting_fonts.font_1d.tune_dedup \
		--svg-dir $(TMP)/1d/svg-fill --output $@

# --- multi-part rule compositions ----------------------------------------

$(TMP)/compositions-line.json: $(PKG)/compositions.py $(PKG)/rules.json $(TMP)/1d/svg-line/.extracted
	python -m signwriting_fonts.font_1d.compositions \
		--svg-dir $(TMP)/1d/svg-line \
		--rules   $(PKG)/rules.json \
		--output  $@

$(TMP)/compositions-fill.json: $(PKG)/compositions.py $(PKG)/rules.json $(TMP)/1d/svg-fill/.extracted
	python -m signwriting_fonts.font_1d.compositions \
		--svg-dir $(TMP)/1d/svg-fill \
		--rules   $(PKG)/rules.json \
		--output  $@

# --- final TTFs ----------------------------------------------------------
# Outline-level dedup (composite glyphs in the glyf table) is the entire
# size win; there are no GSUB/GPOS lookups, so build_font.py writes each
# shippable TTF directly. (cubic→quadratic happens inside FontForge during
# .ttf export.)

fonts/SuttonSignWritingOneD.ttf: $(TMP)/1d/svg-line-opt/.optimized $(TMP)/1d/markers/.extracted $(PKG)/build_font.py $(PKG)/variants.py $(TMP)/duplicates-line.json $(TMP)/compositions-line.json
	fontforge -lang=py -script $(PKG)/build_font.py \
		--variant oned \
		--svg-dir $(TMP)/1d/svg-line-opt --markers-dir $(TMP)/1d/markers \
		--duplicates   $(TMP)/duplicates-line.json \
		--compositions $(TMP)/compositions-line.json \
		--iou-threshold 0.9 --output $@

# Line and Fill skip multi-part rule compositions for now: the offsets in
# compositions-*.json are computed assuming OneD's centered-y placement,
# so they don't translate to the descender layout. (Per-glyph dedup via
# duplicates-*.json IS variant-safe — composites are rotated about the
# sibling glyph's own bbox center at apply-time.) Each symbol still has
# its own SVG so visuals are correct; we just lose ~301 multi-part
# composite-refs of size optimization. Revisit when needed.
fonts/SuttonSignWritingLine.ttf: $(TMP)/1d/svg-line-opt/.optimized $(PKG)/build_font.py $(PKG)/variants.py $(TMP)/duplicates-line.json
	fontforge -lang=py -script $(PKG)/build_font.py \
		--variant line \
		--svg-dir $(TMP)/1d/svg-line-opt \
		--duplicates   $(TMP)/duplicates-line.json \
		--iou-threshold 0.9 --output $@

fonts/SuttonSignWritingFill.ttf: $(TMP)/1d/svg-fill-opt/.optimized $(PKG)/build_font.py $(PKG)/variants.py $(TMP)/duplicates-fill.json
	fontforge -lang=py -script $(PKG)/build_font.py \
		--variant fill \
		--svg-dir $(TMP)/1d/svg-fill-opt \
		--duplicates   $(TMP)/duplicates-fill.json \
		--iou-threshold 0.9 --output $@

# No-dedup oracle TTF — same source SVGs, no duplicates/compositions.
# Used by the regression tests and the explorer's size-impact table.
$(TMP)/SignWritingOneD-unopt.ttf: $(TMP)/1d/svg-line/.extracted $(TMP)/1d/markers/.extracted $(PKG)/build_font.py $(PKG)/variants.py
	fontforge -lang=py -script $(PKG)/build_font.py \
		--variant oned \
		--svg-dir $(TMP)/1d/svg-line --markers-dir $(TMP)/1d/markers \
		--output $@

# Symbol-explorer website. `make serve` runs an HTTP server with
# live-reload polling on version.txt; `make watch` rebuilds when the
# Python sources change.
$(TMP)/site/index.html: \
		fonts/SuttonSignWritingOneD.ttf \
		$(TMP)/SignWritingOneD-unopt.ttf \
		$(TMP)/SuttonSignWritingOneD.ttf \
		$(TMP)/duplicates-line.json \
		$(TMP)/compositions-line.json \
		$(TMP)/circles-line.json \
		$(PKG)/site.py
	python -m signwriting_fonts.font_1d.site \
		--new-ttf   fonts/SuttonSignWritingOneD.ttf \
		--old-ttf   $(TMP)/SuttonSignWritingOneD.ttf \
		--unopt-ttf $(TMP)/SignWritingOneD-unopt.ttf \
		--duplicates   $(TMP)/duplicates-line.json \
		--compositions $(TMP)/compositions-line.json \
		--circles      $(TMP)/circles-line.json \
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

fonts/SuttonSignWritingTwoD.ttf: $(TMP)/SuttonSignWritingTwoToneModified.ttf signwriting_fonts/font_2d/add_gpos.py
	python -m signwriting_fonts.font_2d.add_gpos --input-ttf $< --output-ttf $@

# Default target — rebuild the symbol explorer website. The dependency
# chain pulls every upstream artifact in order:
#   site  ←  fonts/SignWritingOneD-base.ttf
#         ←  duplicates.json, compositions.json, circles.json
#         ←  build_font.py, tune_dedup.py, compositions.py,
#            optimize.py, site.py, rules.json
#         ←  fonts/1d/svg/.extracted, fonts/1d/svg-opt/.optimized
.PHONY: all
all: assets/regen/symbols/index.html

# Remote fonts
fonts/SuttonSignWritingOneD.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingOneD.ttf

fonts/SuttonSignWritingLine.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingLine.ttf

fonts/SuttonSignWritingFill.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/blob/master/src/font/SuttonSignWritingFill.ttf

# Cubic-Bezier source SVGs from sutton-signwriting/font-db
# (iswa2010.db is a SQLite DB of every symbol's source SVG)
fonts/iswa2010.db:
	wget -O $@ https://unpkg.com/@sutton-signwriting/font-db/db/iswa2010.db

# Structural-marker SVGs (SW A/B/L/M/R + SW 250-749) from Slevinski's
# signwriting_2010_fonts repo. These aren't in iswa2010.db.
fonts/1d/other_svg.zip:
	mkdir -p $(dir $@)
	wget -O $@ https://github.com/Slevinski/signwriting_2010_fonts/raw/master/source/other_svg.zip

fonts/1d/markers/.extracted: fonts/1d/other_svg.zip
	rm -rf fonts/1d/markers
	unzip -o fonts/1d/other_svg.zip -d fonts/1d/
	mv fonts/1d/other_svg fonts/1d/markers
	touch $@

# Examples
assets/SuttonSignWritingOneD-example.png: fonts/SuttonSignWritingOneD.ttf
	hb-view fonts/SuttonSignWritingOneD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

assets/SuttonSignWritingTwoD-example.png: fonts/SuttonSignWritingTwoD.ttf
	hb-view fonts/SuttonSignWritingTwoD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

# =========================================================================
# 1D font — rebuilt from cubic source SVGs in font-db (issue #1)
# =========================================================================

# Extract a subset of per-symbol SVGs from iswa2010.db
fonts/1d/svg/.extracted: fonts/iswa2010.db signwriting_fonts/font_1d/extract.py
	python -m signwriting_fonts.font_1d.extract --db fonts/iswa2010.db --out fonts/1d/svg
	touch $@

# Optionally fit ellipses to whole circular sub-paths and emit cleaner SVGs
fonts/1d/svg-opt/.optimized: fonts/1d/svg/.extracted signwriting_fonts/font_1d/optimize.py
	python -m signwriting_fonts.font_1d.optimize \
		--in-dir fonts/1d/svg --out-dir fonts/1d/svg-opt \
		--report signwriting_fonts/font_1d/ellipsed.json \
		--circles-report signwriting_fonts/font_1d/circles.json
	touch $@

# duplicates.json — generated offline by tune_dedup.py, checked into the
# repo. Drives the composite-glyph dedup at build time.
signwriting_fonts/font_1d/duplicates.json: signwriting_fonts/font_1d/tune_dedup.py fonts/1d/svg/.extracted
	python -m signwriting_fonts.font_1d.tune_dedup \
		--svg-dir fonts/1d/svg --output $@

# compositions.json — generated offline by compositions.py from manual
# composition rules in rules.json. Drives multi-part composite glyph
# emission at build time.
signwriting_fonts/font_1d/compositions.json: signwriting_fonts/font_1d/compositions.py signwriting_fonts/font_1d/rules.json fonts/1d/svg/.extracted
	python -m signwriting_fonts.font_1d.compositions \
		--svg-dir fonts/1d/svg \
		--rules   signwriting_fonts/font_1d/rules.json \
		--output  $@

# Build base TTF from the extracted SVGs via FontForge (cubic→quadratic happens inside FontForge)
fonts/SignWritingOneD-base.ttf: fonts/1d/svg-opt/.optimized fonts/1d/markers/.extracted signwriting_fonts/font_1d/build_font.py signwriting_fonts/font_1d/duplicates.json signwriting_fonts/font_1d/compositions.json
	fontforge -lang=py -script signwriting_fonts/font_1d/build_font.py \
		--svg-dir fonts/1d/svg-opt --markers-dir fonts/1d/markers \
		--duplicates  signwriting_fonts/font_1d/duplicates.json \
		--compositions signwriting_fonts/font_1d/compositions.json \
		--iou-threshold 0.9 --output $@

# Generate VTP positioning rules for the 1D font
fonts/SignWritingOneD.vtp: fonts/SignWritingOneD-base.ttf signwriting_fonts/font_1d/generate_vtp.py
	python -m signwriting_fonts.font_1d.generate_vtp --ttf fonts/SignWritingOneD-base.ttf > $@

# Apply VTP via volt2ttf to produce the final 1D font
fonts/SignWritingOneD.ttf: fonts/SignWritingOneD.vtp fonts/SignWritingOneD-base.ttf
	volt2ttf -t fonts/SignWritingOneD.vtp fonts/SignWritingOneD-base.ttf $@

# PDF report comparing the original OneD font with the regenerated variants
# (unoptimized + ellipse-optimized): file sizes, glyph counts, and visual
# spot-checks for each optimization currently implemented.
fonts/SignWritingOneD-unopt.ttf: fonts/1d/svg/.extracted fonts/1d/markers/.extracted signwriting_fonts/font_1d/build_font.py
	fontforge -lang=py -script signwriting_fonts/font_1d/build_font.py \
		--svg-dir fonts/1d/svg --markers-dir fonts/1d/markers \
		--output $@

assets/regen/report.pdf: fonts/SuttonSignWritingOneD.ttf fonts/SignWritingOneD-base.ttf fonts/SignWritingOneD-unopt.ttf signwriting_fonts/font_1d/report.py
	python -m signwriting_fonts.font_1d.report --output $@

# Live preview: serve the explorer over HTTP with an auto-reload script
# (the website polls `assets/regen/symbols/version.txt`; whenever it
# changes, the page reloads). Use `make watch` in another terminal to
# rebuild on source changes — when fswatch/entr is installed, the loop
# is automatic; otherwise rebuild manually with `make assets/regen/symbols/index.html`.
.PHONY: serve watch
serve: assets/regen/symbols/index.html
	@echo "Serving http://localhost:8000/  (Ctrl-C to stop)"
	@cd assets/regen/symbols && python -m http.server 8000

watch:
	@command -v fswatch >/dev/null || { \
	  echo "Install fswatch first:  brew install fswatch" >&2; exit 1; }
	@fswatch -o signwriting_fonts/font_1d | \
	  while read -r _; do \
	    echo "[watch] rebuild…"; \
	    make assets/regen/symbols/index.html 2>&1 | tail -3; \
	  done

# Symbol-explorer website with the new font, decorated by dedup category.
assets/regen/symbols/index.html: \
		fonts/SignWritingOneD-base.ttf fonts/SuttonSignWritingOneD.ttf \
		fonts/SignWritingOneD-unopt.ttf \
		signwriting_fonts/font_1d/duplicates.json \
		signwriting_fonts/font_1d/compositions.json \
		signwriting_fonts/font_1d/circles.json \
		signwriting_fonts/font_1d/site.py
	python -m signwriting_fonts.font_1d.site \
		--new-ttf   fonts/SignWritingOneD-base.ttf \
		--old-ttf   fonts/SuttonSignWritingOneD.ttf \
		--unopt-ttf fonts/SignWritingOneD-unopt.ttf \
		--duplicates  signwriting_fonts/font_1d/duplicates.json \
		--compositions signwriting_fonts/font_1d/compositions.json \
		--circles     signwriting_fonts/font_1d/circles.json \
		--out-dir     assets/regen/symbols

# =========================================================================
# 2D font (existing pipeline)
# =========================================================================

# Create a Two Tone font from the original fonts
fonts/SuttonSignWritingTwoTone.ttf: fonts/SuttonSignWritingLine.ttf fonts/SuttonSignWritingFill.ttf fonts/SuttonSignWritingOneD.ttf
	# TODO create a two tone font
	cp fonts/SuttonSignWritingOneD.ttf $@

# Turning the original ttf font file into a ttx file in order to change it
fonts/SuttonSignWritingTwoTone.ttx: fonts/SuttonSignWritingTwoTone.ttf
	ttx -o $@ fonts/SuttonSignWritingTwoTone.ttf

# Correcting and changing the ttx file, second argument is proportion
fonts/SuttonSignWritingTwoToneModified.ttx: fonts/SuttonSignWritingTwoTone.ttx signwriting_fonts/font_2d/modify_ttx.py
	python -m signwriting_fonts.font_2d.modify_ttx --input fonts/SuttonSignWritingTwoTone.ttx --output $@

# Turning the ttx file into a TTF file
fonts/SuttonSignWritingTwoToneModified.ttf: fonts/SuttonSignWritingTwoToneModified.ttx
	ttx -o $@ fonts/SuttonSignWritingTwoToneModified.ttx

# Generating a vtp file for the font
fonts/SuttonSignWritingTwoD.vtp: fonts/SuttonSignWritingTwoToneModified.ttx signwriting_fonts/font_2d/generate_vtp.py
	python -m signwriting_fonts.font_2d.generate_vtp --ttx fonts/SuttonSignWritingTwoToneModified.ttx > $@

# Add a VTP file instructions to a TTF File
fonts/SuttonSignWritingTwoD.ttf: fonts/SuttonSignWritingTwoD.vtp fonts/SuttonSignWritingTwoToneModified.ttf
	volt2ttf -t fonts/SuttonSignWritingTwoD.vtp fonts/SuttonSignWritingTwoToneModified.ttf $@
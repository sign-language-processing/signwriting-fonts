"""FontForge script: build a base SignWritingOneD TTF from per-symbol SVGs.

Runs inside FontForge's Python interpreter, not the project venv:

    fontforge -lang=py -script build_font.py --svg-dir <dir> --output <path>

Each SVG in --svg-dir must be named <symkey>.svg (e.g. S2ff00.svg). The script
maps each symbol key to the corresponding plane-4 SWU codepoint and imports the
SVG outline as the glyph. FontForge converts the cubic source paths to
quadratic Beziers automatically when emitting TrueType.
"""

import argparse
import os
import re
import sys

import fontforge
import psMat

# FontForge runs this script with the file's directory on sys.path but *not*
# the repository root, so an absolute `from signwriting_fonts.font_1d...`
# import fails. Add the repo root explicitly so we can share the symkey
# helper with `report.py`.
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))
from signwriting_fonts.font_1d._symkey import symkey_to_codepoint  # noqa: E402

# Sutton SignWriting OneD properties — match the original font's em-square so
# downstream tooling (hb-view, browser rendering) gets consistent sizing.
UNITS_PER_EM = 300
DESCENT = 205  # baseline-to-bottom in font units (from the upstream OneD font)

# Each symbol's SVG carries `width="N"` and `height="N"` attributes that
# describe its size in iswa2010.db's "natural" units. The upstream OneD font
# scales those by ~10× to land glyph bboxes in font-units roughly matching
# `width × 10`. We replicate that ratio so the relative sizes of glyphs
# (S2ff00 vs S17600 vs S21e00 vs hand glyphs) match the original.
TARGET_UNITS_PER_NATURAL = 10

# Glyph placement convention copied from the upstream OneD font (read off
# its glyf table). Every glyph is:
#   * left-padded by TARGET_LSB units (so xMin == TARGET_LSB),
#   * vertically centered around y == TARGET_Y_CENTER — that's how the
#     upstream font makes glyphs of very different heights (S21e00's 56
#     vs S2ff00's 349) share a visual baseline in single-line rendering,
#   * given an advance width of (target_width + 2 × TARGET_LSB) so the
#     right side-bearing equals the left.
TARGET_LSB = 20
TARGET_Y_CENTER = 166

_SVG_DIMS = re.compile(r'<svg[^>]*\bwidth="([0-9.]+)"[^>]*\bheight="([0-9.]+)"')

# Structural markers (plane-1 codepoints, 505 total).
# Convention copied from the upstream OneD font: each marker glyph is named
# "SW <token>" (with a space), where token is A/B/L/M/R or the 3-digit number,
# and sits with its bbox bottom at y == MARKER_Y_BOTTOM.
MARKER_Y_BOTTOM = 25         # baseline-to-bottom for markers (vs ~16 for hands)
MARKER_LSB_LETTER = 20       # left side-bearing for SW A/B/L/M/R
MARKER_LSB_NUMBER = 10       # left side-bearing for SW 250..749
_LETTER_CODEPOINTS = {"A": 0x1D800, "B": 0x1D801, "L": 0x1D802,
                      "M": 0x1D803, "R": 0x1D804}
_NUMBER_BASE_CODEPOINT = 0x1D80C   # SW 250 → 0x1D80C, SW 749 → 0x1D9FF


def _marker_filename_to_glyph(filename):
    """Map a structural-marker filename to (glyph_name, codepoint, lsb).

    Returns None for filenames that aren't named markers (null.svg,
    placeholder.svg, sw0..sw249 which the upstream font doesn't expose).
    """
    stem = os.path.splitext(filename)[0]
    if not stem.startswith("sw"):
        return None
    token = stem[2:]
    if token in _LETTER_CODEPOINTS:
        return ("SW %s" % token, _LETTER_CODEPOINTS[token], MARKER_LSB_LETTER)
    try:
        n = int(token)
    except ValueError:
        return None
    if 250 <= n <= 749:
        return ("SW %d" % n, _NUMBER_BASE_CODEPOINT + (n - 250),
                MARKER_LSB_NUMBER)
    return None


def _import_symbol(font, svg_dir, filename):
    """Import one font-db SignWriting symbol; apply the symbol layout rules."""
    symkey = os.path.splitext(filename)[0]
    try:
        codepoint = symkey_to_codepoint(symkey)
    except ValueError as exc:
        print("  ! skipping %s: %s" % (filename, exc))
        return False
    svg_path = os.path.join(svg_dir, filename)
    with open(svg_path) as fp:
        head = fp.read(400)
    m = _SVG_DIMS.search(head)
    if not m:
        print("  ! %s: no width/height in <svg>; skipping" % filename)
        return False
    nat_w = float(m.group(1))
    nat_h = float(m.group(2))

    glyph = font.createChar(codepoint, symkey)
    glyph.importOutlines(svg_path)
    bb = glyph.boundingBox()
    bb_w = bb[2] - bb[0]
    bb_h = bb[3] - bb[1]
    target_w = nat_w * TARGET_UNITS_PER_NATURAL
    target_h = nat_h * TARGET_UNITS_PER_NATURAL
    scale = min(target_w / bb_w if bb_w else 1.0,
                target_h / bb_h if bb_h else 1.0)
    if scale and scale != 1.0:
        glyph.transform(psMat.scale(scale))
    bb = glyph.boundingBox()
    dx = TARGET_LSB - bb[0]
    dy = TARGET_Y_CENTER - (bb[1] + bb[3]) / 2
    glyph.transform(psMat.translate(dx, dy))
    glyph.correctDirection()
    glyph.width = int(round(target_w + 2 * TARGET_LSB))
    return True


def _import_marker(font, markers_dir, filename):
    """Import one structural-marker SVG (SW A/B/L/M/R or SW 250..749)."""
    mapped = _marker_filename_to_glyph(filename)
    if mapped is None:
        return False
    glyph_name, codepoint, lsb = mapped

    svg_path = os.path.join(markers_dir, filename)
    with open(svg_path) as fp:
        head = fp.read(400)
    m = _SVG_DIMS.search(head)
    if not m:
        print("  ! %s: no width/height in <svg>; skipping" % filename)
        return False
    nat_w = float(m.group(1))   # marker SVGs already use font-units (1:1 scale)

    glyph = font.createChar(codepoint, glyph_name)
    glyph.importOutlines(svg_path)
    # 1:1 scale — markers ship at their target font-unit size already.
    bb = glyph.boundingBox()
    dx = lsb - bb[0]
    dy = MARKER_Y_BOTTOM - bb[1]
    glyph.transform(psMat.translate(dx, dy))
    glyph.correctDirection()
    glyph.width = int(round(nat_w + 2 * lsb))
    return True


def build_font(svg_dir, markers_dir, output_path):
    font = fontforge.font()
    font.encoding = "UnicodeFull"
    font.em = UNITS_PER_EM
    font.descent = DESCENT
    font.ascent = UNITS_PER_EM - DESCENT

    font.familyname = "SignWritingOneD"
    font.fontname = "SignWritingOneD"
    font.fullname = "SignWritingOneD"
    font.weight = "Medium"
    font.version = "0.1.0"
    font.copyright = (
        "Copyright (c) 1974-2018, Center for Sutton Movement Writing, inc. "
        "License: SIL OFL 1.1. "
        "Rebuilt from sutton-signwriting/font-db cubic source SVGs."
    )

    # Pass 1: per-symbol cubic SVGs from font-db.
    symbol_svgs = sorted(f for f in os.listdir(svg_dir) if f.endswith(".svg"))
    n_symbols = sum(1 for f in symbol_svgs if _import_symbol(font, svg_dir, f))

    # Pass 2: structural markers (SW A/B/L/M/R + SW 250-749) from the
    # signwriting_2010_fonts repo. These aren't in iswa2010.db so they get
    # imported from a separate directory of plain SVGs.
    n_markers = 0
    if markers_dir is not None:
        marker_svgs = sorted(f for f in os.listdir(markers_dir) if f.endswith(".svg"))
        n_markers = sum(1 for f in marker_svgs if _import_marker(font, markers_dir, f))

    print("Generating %s..." % output_path)
    font.generate(output_path)
    print("Done. %d symbol glyphs + %d marker glyphs." % (n_symbols, n_markers))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg-dir", required=True, help="directory of <symkey>.svg files")
    parser.add_argument("--markers-dir", default=None,
                        help="directory of structural-marker SVGs "
                             "(sw[A|B|L|M|R].svg + sw250..sw749.svg); optional")
    parser.add_argument("--output", required=True, help="output TTF path")
    args = parser.parse_args()
    build_font(args.svg_dir, args.markers_dir, args.output)


if __name__ == "__main__":
    main()

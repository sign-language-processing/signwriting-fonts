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

import fontforge
import psMat

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


def symkey_to_codepoint(symkey, plane=0x4):
    """Convert a FSW symbol key (e.g. "S2ff00") to its SWU plane-4 codepoint.

    Mirrors the formula in signwriting_2010_tools/tools/build.py:
        cp = (plane << 16) + (base - 0x100) * 96 + variant_hi * 16 + variant_lo + 1
    where the symkey is "S" + 3-hex base + 1-hex variant_hi + 1-hex variant_lo.
    """
    if len(symkey) != 6 or symkey[0] != "S":
        raise ValueError("expected symkey like S2ff00, got: %r" % symkey)
    base = int(symkey[1:4], 16)
    var_hi = int(symkey[4], 16)
    var_lo = int(symkey[5], 16)
    return (plane << 16) + (base - 0x100) * 96 + var_hi * 16 + var_lo + 1


def build_font(svg_dir, output_path):
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

    svgs = sorted(f for f in os.listdir(svg_dir) if f.endswith(".svg"))
    for filename in svgs:
        symkey = os.path.splitext(filename)[0]
        try:
            codepoint = symkey_to_codepoint(symkey)
        except ValueError as exc:
            print("  ! skipping %s: %s" % (filename, exc))
            continue

        svg_path = os.path.join(svg_dir, filename)
        with open(svg_path) as fp:
            head = fp.read(400)
        m = _SVG_DIMS.search(head)
        if not m:
            print("  ! %s: no width/height in <svg>; skipping" % filename)
            continue
        nat_w = float(m.group(1))
        nat_h = float(m.group(2))

        glyph = font.createChar(codepoint, symkey)
        glyph.importOutlines(svg_path)
        # FontForge ignores SVG width/height when sizing the import: every
        # glyph comes out filling roughly the em-square. To restore the
        # relative proportions seen in the upstream OneD font, scale each
        # imported glyph so its bbox width matches `nat_w × 10`.
        bb = glyph.boundingBox()  # (xMin, yMin, xMax, yMax)
        bb_w = bb[2] - bb[0]
        bb_h = bb[3] - bb[1]
        target_w = nat_w * TARGET_UNITS_PER_NATURAL
        target_h = nat_h * TARGET_UNITS_PER_NATURAL
        # Use a single uniform scale (the lesser of the two ratios) so glyphs
        # stay round; the original OneD doesn't squash either axis.
        scale = min(target_w / bb_w if bb_w else 1.0,
                    target_h / bb_h if bb_h else 1.0)
        if scale and scale != 1.0:
            glyph.transform(psMat.scale(scale))
        # Re-anchor: pad TARGET_LSB on the left and centre the glyph vertically
        # at y == TARGET_Y_CENTER, matching the upstream OneD layout convention
        # (all glyphs share a visual centreline regardless of height).
        bb = glyph.boundingBox()
        dx = TARGET_LSB - bb[0]
        dy = TARGET_Y_CENTER - (bb[1] + bb[3]) / 2
        glyph.transform(psMat.translate(dx, dy))
        # FontForge sometimes normalises sub-contour directions in surprising
        # ways when paths share fill rules ambiguously. correctDirection() puts
        # every contour into the canonical non-zero-winding orientation so a
        # ring (outer + inner sub-path) renders as a ring, not two filled discs.
        glyph.correctDirection()
        # Right side-bearing == left side-bearing.
        glyph.width = int(round(target_w + 2 * TARGET_LSB))
        print("  glyph %s -> U+%05X (svg %sx%s, bbox %.0fx%.0f, advance %d)"
              % (symkey, codepoint, m.group(1), m.group(2),
                 glyph.boundingBox()[2] - glyph.boundingBox()[0],
                 glyph.boundingBox()[3] - glyph.boundingBox()[1],
                 glyph.width))

    print("Generating %s..." % output_path)
    font.generate(output_path)
    print("Done. %d glyphs." % (len(svgs)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg-dir", required=True, help="directory of <symkey>.svg files")
    parser.add_argument("--output", required=True, help="output TTF path")
    args = parser.parse_args()
    build_font(args.svg_dir, args.output)


if __name__ == "__main__":
    main()

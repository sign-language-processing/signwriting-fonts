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

import fontforge

# Sutton SignWriting OneD properties — match the original font's em-square so
# downstream tooling (hb-view, browser rendering) gets consistent sizing.
UNITS_PER_EM = 300
DESCENT = 205  # baseline-to-bottom in font units (from the upstream OneD font)


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

        glyph = font.createChar(codepoint, symkey)
        glyph.importOutlines(os.path.join(svg_dir, filename))
        # FontForge sometimes normalises sub-contour directions in surprising
        # ways when paths share fill rules ambiguously. correctDirection() puts
        # every contour into the canonical non-zero-winding orientation so a
        # ring (outer + inner sub-path) renders as a ring, not two filled discs.
        glyph.correctDirection()
        glyph.width = int(glyph.boundingBox()[2] - glyph.boundingBox()[0]) or UNITS_PER_EM
        print("  glyph %s -> U+%05X (width %d)" % (symkey, codepoint, glyph.width))

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

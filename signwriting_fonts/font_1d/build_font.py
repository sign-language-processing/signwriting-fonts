"""FontForge script: build a base SignWritingOneD TTF from per-symbol SVGs.

Runs inside FontForge's Python interpreter, not the project venv:

    fontforge -lang=py -script build_font.py --svg-dir <dir> --output <path>

Each SVG in --svg-dir must be named <symkey>.svg (e.g. S2ff00.svg). The script
maps each symbol key to the corresponding plane-4 SWU codepoint and imports the
SVG outline as the glyph. FontForge converts the cubic source paths to
quadratic Beziers automatically when emitting TrueType.
"""

import argparse
import math
import os
import re
import subprocess
import sys
import textwrap

import fontforge
import psMat

# FontForge runs this script with the file's directory on sys.path but *not*
# the repository root, so an absolute `from signwriting_fonts.font_1d...`
# import fails. Add the repo root explicitly so we can share the symkey
# helper with `report.py`.
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))
from signwriting_fonts.font_1d._symkey import (  # noqa: E402
    symkey_to_codepoint,
)

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


# Dihedral-group transforms (the 8 rigid 2D operations) named the same way
# `tune_dedup.py` enumerates them. The psMat for each is the font-space
# equivalent of the image-space transform that the tune script applies:
# image-space "rotate θ CCW" becomes font-space "rotate -θ CCW" because
# rendering inverts the y axis. Mirrors don't touch y so they translate
# directly.
_TRANSFORM_MATRICES = {
    "I":     lambda: psMat.identity(),
    "R45":   lambda: psMat.rotate(math.radians(45)),
    "R90":   lambda: psMat.rotate(math.radians(90)),
    "R135":  lambda: psMat.rotate(math.radians(135)),
    "R180":  lambda: psMat.rotate(math.radians(180)),
    "R225":  lambda: psMat.rotate(math.radians(225)),
    "R270":  lambda: psMat.rotate(math.radians(270)),
    "R315":  lambda: psMat.rotate(math.radians(315)),
    "M":     lambda: psMat.scale(-1, 1),
    # Each MR? = mirror + the same rotation. Verified IOU 1.0 vs upstream
    # for cardinals and diagonals (see test_glyph_render tests).
    "MR90":  lambda: psMat.compose(psMat.scale(-1, 1), psMat.rotate(math.radians(90))),
    "MR180": lambda: psMat.compose(psMat.scale(-1, 1), psMat.rotate(math.radians(180))),
    "MR270": lambda: psMat.compose(psMat.scale(-1, 1), psMat.rotate(math.radians(270))),
}


def _composite_transform(base_glyph, sibling_glyph, transform_name):
    """Build a psMat that maps `base_glyph`'s outline into `sibling_glyph`'s
    bbox under the dihedral transform named `transform_name`.

    Sequence: centre base on origin → apply the named transform → translate
    back to the sibling's bbox centre.
    """
    op = _TRANSFORM_MATRICES[transform_name]()
    bb = base_glyph.boundingBox()
    sb = sibling_glyph.boundingBox()
    bcx = (bb[0] + bb[2]) / 2.0
    bcy = (bb[1] + bb[3]) / 2.0
    scx = (sb[0] + sb[2]) / 2.0
    scy = (sb[1] + sb[3]) / 2.0
    t = psMat.translate(-bcx, -bcy)
    t = psMat.compose(t, op)
    t = psMat.compose(t, psMat.translate(scx, scy))
    return t


def _glyph_for_symkey(font, symkey):
    """Look up the encoded glyph for a symkey, or None if it isn't
    mapped or the symkey is malformed."""
    try:
        cp = symkey_to_codepoint(symkey)
    except ValueError:
        return None
    try:
        return font[cp]
    except TypeError:
        return None


def _apply_duplicates(font, duplicates_path, iou_threshold):
    """For every entry in `duplicates.json`, rewrite the sibling glyph as
    a composite reference to its `duplicate_of` source + the recorded
    transform.

    Formula entries (source: "hand-formula", "c8-formula") have no
    fidelity metadata and are always accepted — the rotation pattern is
    part of the SignWriting spec, not an IOU heuristic. Search-based
    entries (if present) must clear `iou_threshold` and pass
    crossings/topology checks before being applied.
    """
    import json
    try:
        text = open(str(duplicates_path)).read()
    except FileNotFoundError:
        print("  ! %s not found; skipping duplicates pass" % duplicates_path)
        return 0, 0
    data = json.loads(text)

    n_replaced = n_skipped = 0
    formula_sources = {"hand-formula", "c8-formula"}
    for sib_sym, entry in data.items():
        if sib_sym.startswith("_"):
            continue
        if entry.get("source") not in formula_sources:
            iou = entry.get("iou", 0.0)
            if (iou < iou_threshold
                    or not entry.get("crossings_match", True)
                    or not entry.get("topology_match", True)):
                n_skipped += 1
                continue
        base_sym = entry["duplicate_of"]
        transform = entry["transform"]
        base_glyph = _glyph_for_symkey(font, base_sym)
        sibling = _glyph_for_symkey(font, sib_sym)
        if base_glyph is None or sibling is None:
            continue
        if transform not in _TRANSFORM_MATRICES:
            print("  ! unknown transform %r for %s" % (transform, sib_sym))
            continue
        t = _composite_transform(base_glyph, sibling, transform)
        old_width = sibling.width
        sibling.clear()
        sibling.addReference(base_glyph.glyphname, t)
        sibling.width = old_width
        n_replaced += 1
    print("Replaced %d glyphs with composites; %d kept as outlines."
          % (n_replaced, n_skipped))
    return n_replaced, n_skipped


def _apply_compositions(font, compositions_path):
    """Replace each composition target glyph with a multi-part TT
    composite reference, per the resolved `compositions.json`.

    Each part records `offset_font` — the font-unit translate to apply
    to the part's standalone outline so it appears at its intended
    position inside the target. Optional `transform: "M"` mirrors the
    part horizontally about its own bbox centre before placement.
    """
    import json as _json
    try:
        doc = _json.loads(open(str(compositions_path)).read())
    except FileNotFoundError:
        print("  ! %s not found; skipping compositions pass" % compositions_path)
        return 0
    if not doc:
        return 0

    n_composed = 0
    for target_sym, entry in doc.items():
        parts = entry.get("parts", [])
        if not parts:
            continue
        target = _glyph_for_symkey(font, target_sym)
        if target is None:
            continue

        refs = []
        any_missing = False
        for p in parts:
            ref_sym = p["ref"]
            part_glyph = _glyph_for_symkey(font, ref_sym)
            if part_glyph is None:
                print("  ! %s: missing part %s" % (target_sym, ref_sym))
                any_missing = True
                break
            tx, ty = p["offset_font"]
            t = psMat.translate(tx, ty)
            if p.get("transform") == "M":
                # Mirror the referenced glyph about its bbox centre,
                # then apply the placement translate.
                pb = part_glyph.boundingBox()
                pcx = (pb[0] + pb[2]) / 2.0
                pcy = (pb[1] + pb[3]) / 2.0
                mirror = psMat.translate(-pcx, -pcy)
                mirror = psMat.compose(mirror, psMat.scale(-1, 1))
                mirror = psMat.compose(mirror, psMat.translate(pcx, pcy))
                t = psMat.compose(mirror, t)
            refs.append((part_glyph.glyphname, t))

        if any_missing:
            continue

        old_width = target.width
        try:
            target.clear()
            for name, m in refs:
                target.addReference(name, m)
            target.width = old_width
            n_composed += 1
        except Exception as exc:
            print("  ! %s: composite failed: %s" % (target_sym, exc))

    print("Compositions: replaced %d glyphs with multi-part composites."
          % n_composed)
    return n_composed


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


def build_font(svg_dir, markers_dir, output_path,
               duplicates_path=None, rotation_dedup=True,
               iou_threshold=0.9, compositions_path=None):
    font = fontforge.font()
    font.encoding = "UnicodeFull"
    font.em = UNITS_PER_EM
    font.descent = DESCENT
    font.ascent = UNITS_PER_EM - DESCENT

    # Lock vertical metrics to the upstream OneD font's values so hb-view
    # (and browsers) compute the same line-height regardless of how far our
    # composite glyphs end up extending the head bbox. Without this override
    # FontForge derives ascent/descent from the actual glyph extents, which
    # are slightly larger here because rotated composites can push the bbox
    # negative — causing the same glyph to render in a TALLER canvas vs
    # upstream and look smaller side-by-side.
    font.os2_typoascent_add = False
    font.os2_typoascent = 300
    font.os2_typodescent_add = False
    font.os2_typodescent = 0
    font.os2_winascent_add = False
    font.os2_winascent = 535
    font.os2_windescent_add = False
    font.os2_windescent = 205
    font.hhea_ascent_add = False
    font.hhea_ascent = 535
    font.hhea_descent_add = False
    font.hhea_descent = -205
    font.hhea_linegap = 27

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
    print("Importing %d symbol SVGs…" % len(symbol_svgs)); sys.stdout.flush()
    n_symbols = sum(
        1 for f in symbol_svgs
        if _import_symbol(font, svg_dir, f)
    )
    print("  imported %d symbols" % n_symbols); sys.stdout.flush()

    # Pass 2: structural markers (SW A/B/L/M/R + SW 250-749) from the
    # signwriting_2010_fonts repo. These aren't in iswa2010.db so they get
    # imported from a separate directory of plain SVGs.
    n_markers = 0
    if markers_dir is not None:
        marker_svgs = sorted(f for f in os.listdir(markers_dir) if f.endswith(".svg"))
        n_markers = sum(1 for f in marker_svgs if _import_marker(font, markers_dir, f))

    # Pass 3: dedup via duplicates.json. Every entry maps a symkey to its
    # base symkey + a D4 transform + an IOU. Entries with IOU below the
    # build-time threshold are skipped (kept as outlines).
    n_composite = 0
    if rotation_dedup and duplicates_path is not None:
        n_composite, _ = _apply_duplicates(font, duplicates_path, iou_threshold)

    # Pass 4: manual rule-based compositions. Multi-part composite refs
    # for symbols where a JSON rule says "X = A + B + …" (e.g. eyebrow
    # families: head + eyebrows). Offsets are pre-resolved in
    # compositions.json by `compositions.py`.
    n_composed = 0
    if compositions_path is not None:
        n_composed = _apply_compositions(font, compositions_path)

    print("Generating %s..." % output_path)
    font.generate(output_path)
    _clamp_head_bbox_to_encoded_glyphs(output_path)
    print("Done. %d symbol glyphs + %d marker glyphs "
          "(%d D4 composites, %d rule compositions)."
          % (n_symbols, n_markers, n_composite, n_composed))


def _clamp_head_bbox_to_encoded_glyphs(path):
    """Rewrite `head.yMin/yMax` (and x bounds) so they describe only the
    bbox of encoded (text-renderable) glyphs.

    Some primitive `_prim_*` glyphs are intentionally taller than text
    line-height — they're internal building blocks for composites, never
    rendered on their own. FontForge auto-computes `head.yMax` from all
    glyphs including these, which inflates the font's bbox and causes
    hb-view / browser canvases to render text at a smaller relative
    scale. Cap to the encoded-glyph extents instead.

    Runs in a subprocess because fontTools isn't available in the
    FontForge-bundled Python that this script runs under.
    """
    script = textwrap.dedent('''
        from fontTools.ttLib import TTFont
        import sys
        path = sys.argv[1]
        f = TTFont(path, recalcBBoxes=False)
        cmap = f.getBestCmap()
        encoded = set(cmap.values())
        glyf = f["glyf"]
        xs_min, xs_max, ys_min, ys_max = [], [], [], []
        for name in encoded:
            g = glyf[name]
            if g.numberOfContours == 0:
                continue
            xs_min.append(g.xMin); xs_max.append(g.xMax)
            ys_min.append(g.yMin); ys_max.append(g.yMax)
        if not xs_min:
            sys.exit(0)
        head = f["head"]
        head.xMin, head.xMax = min(xs_min), max(xs_max)
        head.yMin, head.yMax = min(ys_min), max(ys_max)
        f.save(path)
        print(f"  clamped head bbox to encoded-glyphs: "
              f"y=[{head.yMin},{head.yMax}] x=[{head.xMin},{head.xMax}]")
    ''')
    subprocess.run(
        ["python3", "-c", script, str(path)],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg-dir", required=True, help="directory of <symkey>.svg files")
    parser.add_argument("--markers-dir", default=None,
                        help="directory of structural-marker SVGs "
                             "(sw[A|B|L|M|R].svg + sw250..sw749.svg); optional")
    parser.add_argument("--duplicates", default=None,
                        help="path to duplicates.json (from tune_dedup); "
                             "if omitted, no composite-dedup is performed")
    parser.add_argument("--iou-threshold", type=float, default=0.9,
                        help="minimum IOU to accept a composite (default 0.9); "
                             "entries in duplicates.json below this stay as "
                             "outlines")
    parser.add_argument("--no-rotation-dedup", action="store_true",
                        help="skip the composite-glyph dedup pass even if "
                             "--duplicates is provided (sizing comparison)")
    parser.add_argument("--compositions", default=None,
                        help="path to compositions.json (from compositions.py); "
                             "if provided, every listed target is rewritten as "
                             "a multi-part TT composite reference")
    parser.add_argument("--output", required=True, help="output TTF path")
    args = parser.parse_args()
    build_font(args.svg_dir, args.markers_dir, args.output,
               duplicates_path=args.duplicates,
               rotation_dedup=not args.no_rotation_dedup,
               iou_threshold=args.iou_threshold,
               compositions_path=args.compositions)


if __name__ == "__main__":
    main()

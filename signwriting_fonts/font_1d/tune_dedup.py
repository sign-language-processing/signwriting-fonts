"""Find duplicates among the font-db cubic source SVGs.

For every symbol whose outline is a rigid transform (rotation, reflection,
or a combination — the dihedral group D4) of some other symbol's outline,
record:

    duplicates[<symkey>] = {
        "duplicate_of": "<other_symkey>",
        "transform":    "I" | "R90" | "R180" | "R270"
                      | "M"  | "MR90" | "MR180" | "MR270",
        "iou":          <float>,
    }

The reference fonts to compare against come from `fonts/1d/svg/` — the
cubic-Bezier source SVGs extracted from sutton-signwriting/font-db. This
is closer to the canonical glyph shape than the upstream OneD TTF (which
has its own quadratic-approximation drift), so a duplicate detected here
is a duplicate by the SOURCE definition.

The build (`build_font.py`) reads this file and:
  - For glyphs in `duplicates.json`: emit a TrueType composite that
    references the duplicate's source + the recorded transform.
  - For glyphs not in `duplicates.json`: keep the imported outline.

Usage:
    python -m signwriting_fonts.font_1d.tune_dedup \\
        --svg-dir fonts/1d/svg \\
        --output  signwriting_fonts/font_1d/duplicates.json
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import numpy as np
import resvg_py
from PIL import Image

from signwriting_fonts.font_1d._symkey import symkey_to_codepoint


# D4 dihedral group — every rigid 2D transform up to translation.
TRANSFORM_NAMES = [
    "I",       # identity
    "R90",     # rotate 90° CCW (image space)
    "R180",    # rotate 180°
    "R270",    # rotate 270° CCW
    "M",       # mirror across vertical axis (left-right flip)
    "MR90",    # mirror, then rotate 90° CCW
    "MR180",   # vertical flip (mirror + 180°)
    "MR270",   # mirror, then rotate 270° CCW
]

# Pixels per SVG natural unit. font-db SVGs have width="N" / height="N"
# attributes where N is the symbol's "natural" pixel size; rendering at
# N*SCALE preserves glyph proportions across symbols of different sizes.
RENDER_SCALE = 10


def _render_svg(svg_path: Path) -> Image.Image | None:
    """Render an SVG to a PIL grayscale mask (True = ink)."""
    text = svg_path.read_text()
    # Parse natural width
    import re
    m = re.search(r'<svg[^>]*\bwidth="([0-9.]+)"[^>]*\bheight="([0-9.]+)"', text)
    if not m:
        return None
    w = int(float(m.group(1)) * RENDER_SCALE)
    h = int(float(m.group(2)) * RENDER_SCALE)
    if w <= 0 or h <= 0:
        return None
    png = bytes(resvg_py.svg_to_bytes(svg_string=text, width=w, height=h))
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    # font-db SVGs have transparent background + black ink. Flatten to L
    # with white background so a binary mask is straightforward.
    flat = Image.new("L", img.size, 255)
    flat.paste(img.convert("L"), (0, 0), img.split()[3])  # use alpha as mask
    return flat


def _apply_transform(img: Image.Image, name: str) -> Image.Image:
    """Apply one of the 8 dihedral-group transforms to a PIL image."""
    mirror = name.startswith("M")
    rot = name[1:] if mirror else name  # "MR90" → "R90"; "R90" → "R90"
    if mirror:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if rot == "R90":
        img = img.rotate(90, expand=True, fillcolor=255)
    elif rot == "R180":
        img = img.rotate(180, expand=True, fillcolor=255)
    elif rot == "R270":
        img = img.rotate(270, expand=True, fillcolor=255)
    return img


def _crop_ink(mask: np.ndarray) -> np.ndarray:
    rows = mask.any(axis=1)
    cols = mask.any(axis=0)
    if not rows.any():
        return mask[:0, :0]
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return mask[r0:r1 + 1, c0:c1 + 1]


def _aligned_iou(a_mask: np.ndarray, b_mask: np.ndarray) -> float:
    a = _crop_ink(a_mask)
    b = _crop_ink(b_mask)
    if a.size == 0 or b.size == 0:
        return 1.0 if a.shape == b.shape else 0.0
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])
    aa = np.zeros((h, w), bool)
    bb = np.zeros((h, w), bool)
    aa[(h - a.shape[0]) // 2: (h - a.shape[0]) // 2 + a.shape[0],
       (w - a.shape[1]) // 2: (w - a.shape[1]) // 2 + a.shape[1]] = a
    bb[(h - b.shape[0]) // 2: (h - b.shape[0]) // 2 + b.shape[0],
       (w - b.shape[1]) // 2: (w - b.shape[1]) // 2 + b.shape[1]] = b
    union = (aa | bb).sum()
    return float((aa & bb).sum() / union) if union else 1.0


def _best_transform(base_mask: np.ndarray, target_mask: np.ndarray
                    ) -> tuple[str, float]:
    """Try every D4 transform on `base_mask`; return (best_name, iou)."""
    base_img = Image.fromarray((base_mask * 255).astype(np.uint8), mode="L")
    best_name = "I"
    best_iou = 0.0
    for name in TRANSFORM_NAMES:
        candidate = _apply_transform(base_img, name)
        cand_mask = np.array(candidate) > 128  # ink = True for our masks
        # Original target_mask is "ink = True" too (built the same way)
        score = _aligned_iou(cand_mask, target_mask)
        if score > best_iou:
            best_name, best_iou = name, score
    return best_name, best_iou


def find_duplicates(svg_dir: Path, output_path: Path) -> dict:
    """Scan every (base, fill) family; for each non-base sibling find the
    best D4 transform that maps the family's base SVG onto the sibling
    SVG, and record (transform, iou) regardless of how good the match is.

    Threshold filtering is applied later, at build time — that way moving
    the cutoff doesn't require re-running this 7-minute scan.
    """
    svgs = {p.stem: p for p in svg_dir.glob("S*.svg")}
    print(f"Loaded {len(svgs)} source SVGs from {svg_dir}")

    # Pre-render every SVG to an ink mask, caching as we go.
    mask_cache: dict[str, np.ndarray] = {}

    def mask(sym: str) -> np.ndarray | None:
        if sym in mask_cache:
            return mask_cache[sym]
        p = svgs.get(sym)
        if p is None:
            return None
        img = _render_svg(p)
        if img is None:
            return None
        # Ink mask: dark pixels (RGB ~0) → True. We rendered the SVG into
        # a white-background grayscale, so dark = ink.
        m = np.array(img) < 128
        mask_cache[sym] = m
        return m

    out: dict = {"_meta": {
        "source": str(svg_dir),
        "transforms": TRANSFORM_NAMES,
        "note": ("every non-base sibling is recorded with its best D4 "
                 "transform and the resulting IOU. build_font.py applies "
                 "its own IOU threshold at build time."),
    }}
    n_total = n_recorded = 0

    for base_hex in range(0x100, 0x38c):
        for fill in range(16):
            for sibling_rot in range(0, 16):
                sib_sym = f"S{base_hex:03x}{fill:x}{sibling_rot:x}"
                if sib_sym not in svgs:
                    continue
                n_total += 1
                # Pick base: rot 0 for even, rot 1 for odd. Skip if sibling
                # *is* the base of its sub-family.
                base_rot = sibling_rot & 1
                if sibling_rot == base_rot:
                    continue
                base_sym = f"S{base_hex:03x}{fill:x}{base_rot:x}"
                if base_sym not in svgs:
                    continue
                base_mask = mask(base_sym)
                sib_mask = mask(sib_sym)
                if base_mask is None or sib_mask is None:
                    continue
                name, iou = _best_transform(base_mask, sib_mask)
                out[sib_sym] = {
                    "duplicate_of": base_sym,
                    "transform": name,
                    "iou": round(iou, 4),
                }
                n_recorded += 1
        if base_hex % 0x20 == 0:
            print(f"  scanned base 0x{base_hex:03x}  "
                  f"(recorded {n_recorded} / scanned {n_total})")

    out["_meta"]["counts"] = {
        "siblings_considered": n_total,
        "candidates_recorded": n_recorded,
    }
    output_path.write_text(json.dumps(out, indent=2))
    print()
    print(f"Wrote {output_path}")
    print(f"  siblings considered:  {n_total:>7}")
    print(f"  candidates recorded:  {n_recorded:>7}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg-dir", type=Path, required=True,
                        help="directory of font-db cubic source SVGs "
                             "(fonts/1d/svg/)")
    parser.add_argument("--output", type=Path, required=True,
                        help="destination duplicates.json")
    args = parser.parse_args()
    find_duplicates(args.svg_dir, args.output)


if __name__ == "__main__":
    main()

"""Regression tests for the regenerated SignWritingOneD font.

The oracle is `SignWritingOneD-unopt.ttf` — the no-op build straight from
font-db's cubic source SVGs, with no ellipse replacement, no dedup, no
primitives. The composed font (`SignWritingOneD-base.ttf`) is then
compared to it through the same FreeType rasterizer, so any IOU drop
attributes purely to a composition step rather than rasterizer noise.
The upstream Sutton OneD TTF is *not* used as an oracle — it has its own
quadratic drift we deliberately do not replicate.

The fonts are expected to exist (run `make fonts/SignWritingOneD-base.ttf`
before testing); tests skip if they aren't present.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from signwriting_fonts.font_1d._symkey import symkey_to_codepoint

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIG_TTF = REPO_ROOT / "fonts" / "SuttonSignWritingOneD.ttf"
NEW_TTF = REPO_ROOT / "fonts" / "SignWritingOneD-base.ttf"
ORACLE_TTF = REPO_ROOT / "fonts" / "SignWritingOneD-unopt.ttf"

# Spot-check thresholds against the oracle (unopt font). Both renders go
# through the same FreeType path, so the only source of IOU drop is the
# composition step (ellipse replacement, hand dedup, primitives) — there's
# no rasterizer noise to absorb. Targets are tight on purpose.
IOU_THRESHOLDS = {
    "S10000": 0.98,   # hand glyph — no composition applies, near-identical
    "S10001": 0.98,   # rotated hand base
    "S17600": 0.95,   # small ring — ellipse-replaced
    "S20310": 0.98,
    "S21e00": 0.95,   # two small dots — pixel-sensitive
    "S26b02": 0.97,
    "S2ff00": 0.95,   # big ring — ellipse-replaced
    "S33100": 0.97,
}


def _require(tools=("hb-view",), fonts=()):
    for t in tools:
        if shutil.which(t) is None:
            pytest.skip(f"required tool not on PATH: {t}")
    for f in fonts:
        if not f.exists():
            pytest.skip(f"required font not built: {f} — run `make` first")


def _hb_render(font: Path, codepoint: int, size: int = 192) -> np.ndarray:
    """Render a single codepoint via hb-view; return an ink mask (bool)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        out = Path(tf.name)
    try:
        subprocess.run(
            ["hb-view", str(font), chr(codepoint),
             "--output-file", str(out),
             "--font-size", str(size), "--margin", "8"],
            check=True, capture_output=True,
        )
        img = np.array(Image.open(out).convert("RGB")).mean(-1) < 128
    finally:
        out.unlink(missing_ok=True)
    return img


def _crop_to_content(mask: np.ndarray) -> np.ndarray:
    rows = mask.any(axis=1)
    cols = mask.any(axis=0)
    if not rows.any():
        return mask[:0, :0]
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return mask[r0:r1 + 1, c0:c1 + 1]


def _aligned_iou(a: np.ndarray, b: np.ndarray, target_h: int = 200) -> float:
    """IOU after cropping each mask to its ink bbox, resizing both to
    `target_h` rows (preserving aspect ratio), then centring on a shared
    canvas. The resize step makes the comparison scale-independent — needed
    when one input is a TTF render and the other a source-SVG render at a
    different pixel resolution but logically the same glyph."""
    a, b = _crop_to_content(a), _crop_to_content(b)
    if a.size == 0 or b.size == 0:
        return 1.0 if a.shape == b.shape else 0.0

    def resize(m: np.ndarray, h: int) -> np.ndarray:
        ratio = h / m.shape[0]
        w = max(1, int(round(m.shape[1] * ratio)))
        img = Image.fromarray((m * 255).astype("uint8")).resize(
            (w, h), Image.BILINEAR
        )
        return np.array(img) > 64

    a = resize(a, target_h)
    b = resize(b, target_h)
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])

    def pad(m: np.ndarray) -> np.ndarray:
        out = np.zeros((h, w), bool)
        oy = (h - m.shape[0]) // 2
        ox = (w - m.shape[1]) // 2
        out[oy:oy + m.shape[0], ox:ox + m.shape[1]] = m
        return out

    aa, bb = pad(a), pad(b)
    union = (aa | bb).sum()
    return float((aa & bb).sum() / union) if union else 1.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symkey", sorted(IOU_THRESHOLDS.keys()))
def test_glyph_matches_oracle(symkey: str):
    """Composed-font glyph must match the oracle (unopt) font's glyph
    within a tight IOU. Both rendered via hb-view/FreeType so any drop
    is purely from a composition step."""
    _require(fonts=(NEW_TTF, ORACLE_TTF))
    cp = symkey_to_codepoint(symkey)
    oracle = _hb_render(ORACLE_TTF, cp)
    new = _hb_render(NEW_TTF, cp)
    iou = _aligned_iou(new, oracle)
    threshold = IOU_THRESHOLDS[symkey]
    assert iou >= threshold, (
        f"{symkey}: IOU vs oracle {iou:.3f} below threshold {threshold:.3f}"
    )


@pytest.mark.parametrize("symkey", sorted(IOU_THRESHOLDS.keys()))
def test_glyph_is_mapped(symkey: str):
    """Every test symbol must be reachable via its SWU plane-4 codepoint."""
    _require(tools=(), fonts=(NEW_TTF,))
    from fontTools.ttLib import TTFont
    f = TTFont(NEW_TTF)
    cp = symkey_to_codepoint(symkey)
    cmap = f.getBestCmap()
    assert cp in cmap, f"{symkey} (U+{cp:05X}) not in cmap of new font"
    assert cmap[cp] == symkey, f"{symkey} maps to {cmap[cp]!r}, expected {symkey!r}"


def test_optimization_does_not_increase_size():
    """The ellipse-optimized font must not be larger than the unoptimized one."""
    _require(fonts=(NEW_TTF, ORACLE_TTF))
    opt = NEW_TTF.stat().st_size
    unopt = ORACLE_TTF.stat().st_size
    assert opt <= unopt, (
        f"optimized font ({opt:,} B) is larger than unoptimized ({unopt:,} B) — "
        f"the ellipse replacement should never inflate the path data"
    )


def test_new_font_smaller_than_original():
    """Stripping sym-fill paths and going straight to TTF should shrink the
    file vs the upstream OneD; if it doesn't, we've accidentally inflated
    something."""
    _require(fonts=(ORIG_TTF, NEW_TTF))
    orig = ORIG_TTF.stat().st_size
    new = NEW_TTF.stat().st_size
    assert new < orig, (
        f"new font ({new:,} B) is not smaller than original ({orig:,} B)"
    )


# ---------------------------------------------------------------------------
# Rotation dedup: cardinal siblings (rot 2/4/6/8/A/C/E) are stored as
# TrueType composite glyphs referencing the rot-0 base + a transform. The
# rendered result must still match the upstream OneD's hand-drawn version.
# ---------------------------------------------------------------------------

CARDINAL_DEDUP_SAMPLES = [
    # Cardinals: composites of rot 0
    "S10002",  # 90° rotation
    "S10004",  # 180°
    "S10006",  # 270°
    "S10008",  # mirror
    "S1000a",  # mirror + 90°
    "S1000c",  # mirror + 180°
    "S1000e",  # mirror + 270°
    "S20102",  # generalises to a different family
    # Diagonals: composites of rot 1
    "S10003",  # 90° rotation of S10001
    "S10005",  # 180°
    "S10007",  # 270°
    "S10009",  # mirror
    "S1000b",  # mirror + 90°
    "S1000d",  # mirror + 180°
    "S1000f",  # mirror + 270°
]


@pytest.mark.parametrize("symkey", CARDINAL_DEDUP_SAMPLES)
def test_cardinal_rotation_dedup_renders_correctly(symkey: str):
    """A rotation-composite glyph in the composed font must render close
    to its oracle (unopt) counterpart. The oracle has the rotation drawn
    by hand from font-db; the composed font reconstructs it via a
    transform on the rot-0 (or rot-1) base. If they disagree, either the
    transform matrix is wrong or font-db's hand-drawn rotation diverges
    from a pure rigid rotation."""
    _require(fonts=(NEW_TTF, ORACLE_TTF))
    cp = symkey_to_codepoint(symkey)
    oracle = _hb_render(ORACLE_TTF, cp)
    new = _hb_render(NEW_TTF, cp)
    iou = _aligned_iou(new, oracle)
    # Diagonals (rot 1, 3, 5, 7, 9, b, d, f) currently dedup against rot-1
    # via IOU search and land at ~0.93 against the oracle. Phase B (formula-
    # based hand dedup) is expected to tighten this; ratchet down then.
    assert iou >= 0.92, (
        f"{symkey}: rotation composite vs oracle IOU {iou:.3f} < 0.92"
    )


# ---------------------------------------------------------------------------
# End-to-end coverage: render every codepoint in both fonts and compare.
# ---------------------------------------------------------------------------
# Opt-in (sets `RUN_E2E=1`) because it iterates all ~38k glyphs and takes
# tens of seconds. The point is a single test that gives a release-readiness
# signal: every glyph in the new font should land near its upstream
# counterpart in scale, position, and shape.

def _pil_render(font, char):
    """Render `char` with PIL/FreeType; return a bool ink-mask (None if
    the glyph has no ink)."""
    from PIL import Image, ImageDraw
    bbox = font.getbbox(char)
    if bbox == (0, 0, 0, 0):
        return None
    w = bbox[2] - bbox[0] + 16
    h = bbox[3] - bbox[1] + 16
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    d.text((-bbox[0] + 8, -bbox[1] + 8), char, fill=255, font=font)
    return np.array(img) > 64


@pytest.mark.skipif(
    os.environ.get("RUN_E2E") != "1",
    reason="full-font e2e (~38k glyphs); set RUN_E2E=1 to enable",
)
def test_e2e_every_glyph_matches_oracle():
    """For every codepoint, render both the composed font and the oracle
    (unopt) font through FreeType and compare. Composition steps (ellipse
    replacement, hand-rotation dedup, primitives) should preserve shape
    very tightly — there is no rasterizer noise to absorb.

    Prints a per-percentile summary and the worst-IOU outliers so any
    regression points at the specific glyph that drifted.
    """
    from PIL import ImageFont
    from fontTools.ttLib import TTFont

    _require(fonts=(NEW_TTF, ORACLE_TTF))

    SIZE = 96
    new_ft = ImageFont.truetype(str(NEW_TTF), SIZE)
    oracle_ft = ImageFont.truetype(str(ORACLE_TTF), SIZE)
    common = (set(TTFont(NEW_TTF).getBestCmap())
              & set(TTFont(ORACLE_TTF).getBestCmap()))

    ious = []
    failures = []
    for cp in sorted(common):
        ch = chr(cp)
        a = _pil_render(new_ft, ch)
        b = _pil_render(oracle_ft, ch)
        if a is None or b is None:
            continue
        score = _aligned_iou(a, b)
        ious.append((cp, score))
        if score < 0.5:
            failures.append((cp, score))

    n = len(ious)
    assert n > 30000, f"expected ~38k glyphs in common, got {n}"
    sorted_scores = sorted(s for _, s in ious)

    def pct(p: float) -> float:
        return sorted_scores[max(0, int(n * p) - 1)]

    summary = (
        f"\n  e2e covered: {n} glyphs"
        f"\n    min:  {sorted_scores[0]:.3f}"
        f"\n    p1:   {pct(0.01):.3f}"
        f"\n    p5:   {pct(0.05):.3f}"
        f"\n    p25:  {pct(0.25):.3f}"
        f"\n    p50:  {pct(0.50):.3f}"
        f"\n    p95:  {pct(0.95):.3f}"
        f"\n    max:  {sorted_scores[-1]:.3f}"
        f"\n    below 0.5: {len(failures)}"
    )
    if failures:
        worst = sorted(failures, key=lambda x: x[1])[:10]
        summary += "\n  worst:\n" + "\n".join(
            f"    U+{cp:05X}  IOU={s:.3f}" for cp, s in worst
        )
    print(summary)

    # Baseline locked after Phase B (formula hand dedup): p50=1.000,
    # p5=0.891, p1=0.841, 2 below 0.5. Worst offenders are hand symbols
    # where font-db's hand-drawn rotation diverges from a pure D4 transform
    # — we deliberately follow the SignWriting spec (formula) rather than
    # reproduce font-db's drift. Phase C (primitives) should keep these
    # numbers stable or improve them.
    assert pct(0.01) >= 0.83, f"1st-percentile IOU {pct(0.01):.3f} < 0.83"
    assert pct(0.05) >= 0.88, f"5th-percentile IOU {pct(0.05):.3f} < 0.88"
    assert pct(0.50) >= 0.99, f"median IOU {pct(0.50):.3f} < 0.99"
    assert len(failures) <= 5, (
        f"{len(failures)} glyphs below 0.5 — baseline is 2"
    )


@pytest.mark.parametrize("symkey", CARDINAL_DEDUP_SAMPLES)
def test_cardinal_rotation_is_actually_a_composite(symkey: str):
    """Sanity-check: each cardinal-rotation sibling we report as dedup'd
    really is stored as a composite (refers to another glyph) rather than
    a standalone outline."""
    _require(fonts=(NEW_TTF,))
    from fontTools.ttLib import TTFont
    f = TTFont(NEW_TTF)
    cmap = f.getBestCmap()
    cp = symkey_to_codepoint(symkey)
    glyph_name = cmap.get(cp)
    assert glyph_name is not None, f"{symkey} not mapped"
    g = f["glyf"][glyph_name]
    assert g.isComposite(), (
        f"{symkey} is not a composite glyph — rotation dedup didn't run"
    )

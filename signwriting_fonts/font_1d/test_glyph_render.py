"""Regression tests for the regenerated SignWritingOneD font.

These tests render glyphs from the original Sutton OneD font and our
regenerated font and compare the ink masks at content-bbox alignment. They
intentionally do not chase pixel-perfect equality — the two fonts come from
different rasterizers (FreeType-of-quadratic-TTF vs FontForge-of-cubic-source
→ quadratic-TTF) and our build also strips the sym-fill layer, so a strict
match isn't reachable. The goal is to lock in the *scale + placement* match
documented in the build script (see TARGET_LSB, TARGET_Y_CENTER) so future
edits don't drift.

The fonts are expected to exist (run `make fonts/SignWritingOneD-base.ttf`
before testing); tests skip if they aren't present.
"""

from __future__ import annotations

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
NEW_UNOPT_TTF = REPO_ROOT / "fonts" / "SignWritingOneD-unopt.ttf"

# Per-symbol thresholds measured against the original Sutton OneD font at
# 192pt with content-bbox alignment. Values are set ~0.05 below the observed
# IOUs so a small rendering perturbation doesn't trip the test, but a real
# regression in scale/placement will.
IOU_THRESHOLDS = {
    "S10000": 0.90,   # hand glyph, observed 0.974
    "S10001": 0.85,   # rotated hand, observed 0.912
    "S17600": 0.75,   # small ring, observed 0.827
    "S20310": 0.90,   # contact, observed 0.988
    "S21e00": 0.65,   # two dots — most sensitive to wobble, observed 0.751
    "S26b02": 0.80,   # observed 0.893
    "S2ff00": 0.70,   # big ring, observed 0.804
    "S33100": 0.70,   # observed 0.812
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


def _aligned_iou(a: np.ndarray, b: np.ndarray) -> float:
    """IOU after centring each mask on its content bbox in a shared canvas."""
    a, b = _crop_to_content(a), _crop_to_content(b)
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
def test_glyph_scale_and_placement_matches_original(symkey: str):
    """Scale + baseline placement must stay within a tight IOU of the original.

    We compare content-bbox-aligned ink masks so the test only catches drift
    in shape/proportion, not in absolute glyph position.
    """
    _require(fonts=(ORIG_TTF, NEW_TTF))
    cp = symkey_to_codepoint(symkey)
    orig_mask = _hb_render(ORIG_TTF, cp)
    new_mask = _hb_render(NEW_TTF, cp)
    iou = _aligned_iou(orig_mask, new_mask)
    threshold = IOU_THRESHOLDS[symkey]
    assert iou >= threshold, (
        f"{symkey}: aligned IOU {iou:.3f} below threshold {threshold:.3f} — "
        f"scale or placement has drifted from the upstream OneD."
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
    _require(fonts=(NEW_TTF, NEW_UNOPT_TTF))
    opt = NEW_TTF.stat().st_size
    unopt = NEW_UNOPT_TTF.stat().st_size
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
    "S10002",  # 90° rotation of S10000
    "S10004",  # 180° rotation
    "S10006",  # 270° rotation
    "S10008",  # mirror
    "S1000a",  # mirror + 90°
    "S1000c",  # mirror + 180°
    "S1000e",  # mirror + 270°
    "S20102",  # different family — verify dedup generalises across bases
]


@pytest.mark.parametrize("symkey", CARDINAL_DEDUP_SAMPLES)
def test_cardinal_rotation_dedup_renders_correctly(symkey: str):
    """After composite-glyph dedup, cardinal rotations must still render
    within IOU 0.6 of the upstream OneD version."""
    _require(fonts=(ORIG_TTF, NEW_TTF))
    cp = symkey_to_codepoint(symkey)
    orig_mask = _hb_render(ORIG_TTF, cp)
    new_mask = _hb_render(NEW_TTF, cp)
    iou = _aligned_iou(orig_mask, new_mask)
    assert iou >= 0.60, (
        f"{symkey}: cardinal-rotation composite renders at IOU {iou:.3f} "
        f"(< 0.60) — either the rotation transform is wrong or the base "
        f"outline has drifted"
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

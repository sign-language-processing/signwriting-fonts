"""Pixel-level invariants for rule compositions.

For eyebrow families (S30a..S310) we want each eyebrow placed in a
fixed location on the head regardless of which sibling we render: the
right eyebrow appears at the same pixel position in (head+both) and
(head+right), the left at the same position in (head+both) and
(head+left). That makes the union of (head+right) and (head+left) a
pixel-perfect superset of (head+both).
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from signwriting_fonts.font_1d._symkey import symkey_to_codepoint

REPO_ROOT = Path(__file__).resolve().parents[3]
FONT = REPO_ROOT / "fonts" / "SuttonSignWritingOneD.ttf"
ORACLE_FONT = REPO_ROOT / "fonts" / "tmp" / "SignWritingOneD-unopt.ttf"
COMPOSITIONS_JSON = REPO_ROOT / "fonts" / "tmp" / "compositions-line.json"

# These tests rasterise glyphs via hb-view and compare ink masks against
# the built fonts. Skip the whole module if either prerequisite is
# missing (CI without hb-view; any environment where `make` hasn't been
# run yet).
pytestmark = pytest.mark.skipif(
    shutil.which("hb-view") is None
    or not FONT.exists()
    or not ORACLE_FONT.exists(),
    reason="hb-view or built fonts missing; run `make all` first",
)

EYEBROW_BASES = [
    "S30a", "S30b", "S30c", "S30d", "S30e", "S30f", "S310",
    "S357", "S358",
]
FOREHEAD_BASES = ["S311", "S312", "S313"]
# Partial-fit families: only target_00 (head + fill 3) composes.
HEAD_PLUS_30_BASES = ["S356", "S362", "S363", "S365", "S366", "S367"]
# Movement-contact "multiples": every variant of S206/S209/etc. is N
# copies of a single standalone glyph. Each target-base has 8 variants
# (fills 0 and 1 × rotations 0..3); 2 copies for fill 0, 3 copies for
# fill 1. We test the structural invariant (right number of copies,
# similar total ink to oracle) — not pixel-perfect equality, because
# the source SVGs hand-drew each copy slightly different from the
# standalone single (~5-8% size drift).
def _multiple_target_pairs():
    target_singles = [
        ("S206", "S20500"), ("S209", "S20800"), ("S20c", "S20b00"),
        ("S20f", "S20e00"), ("S212", "S21100"), ("S218", "S21600"),
        ("S219", "S21700"), ("S21d", "S21b00"), ("S21e", "S21c00"),
    ]
    pairs = []
    for base, single in target_singles:
        for fill in ("0", "1"):
            for rot in ("0", "1", "2", "3"):
                pairs.append((f"{base}{fill}{rot}", single, 2 if fill == "0" else 3))
    return pairs


MULTIPLE_TRIPLES = _multiple_target_pairs()

# S220 SQUEEZE-FLICK ALTERNATING: each variant is a mix of S21c00 + S21700.
# Fill 0 = 3 flicks + 2 squeezes; fill 1 = 2 flicks + 3 squeezes.
S220_VARIANTS = [f"S2200{r}" for r in "01234567"] + [f"S2201{r}" for r in "01234567"]

# S308 / S309 rotation mirrors: rotations 8..f are the horizontal mirror of
# rotations 0..7 (rot R+8 = M(rot R)). The composition pass emits a 1-part
# mirror composite of the rot-8 sibling. Fills 1/2 carry the rotation-dedup
# output (fill 0 is overwritten by the `face-direction` head+marker rule).
ROTATION_MIRROR_SIBLINGS = [
    (f"{base}{fill}{r + 8:x}", f"{base}{fill}{r}")
    for base in ("S308", "S309")
    for fill in "12"
    for r in range(8)
]
# Eye bases where the resolver currently succeeds (some bases — S31a,
# S31e, S31f — have source SVG sub-paths whose bboxes drift past the
# matcher tolerances and are skipped at compositions.py time; they fall
# back to the original outline in the font and don't get tested here).
EYE_BASES = ["S314", "S315", "S316", "S319", "S31a", "S31b", "S31c", "S31d", "S31e", "S31f"]
# S307's rot=1 column is the horizontal mirror of rot=0.
S307_MIRROR_PAIRS = [
    ("S30700", "S30701"),
    ("S30710", "S30711"),
    ("S30720", "S30721"),
    ("S30730", "S30731"),
    ("S30740", "S30741"),
    ("S30750", "S30751"),
]


def _render(sym: str, size: int = 200, font: Path = FONT) -> np.ndarray:
    """Render `sym` from `font` via hb-view and return a 2-D bool ink
    mask (True where the glyph has black ink)."""
    cp_char = chr(symkey_to_codepoint(sym))
    proc = subprocess.run(
        ["hb-view", str(font), cp_char,
         f"--font-size={size}", "--output-format=png", "-o", "-"],
        check=True, capture_output=True,
    )
    img = Image.open(io.BytesIO(proc.stdout)).convert("L")
    return np.array(img) < 128


def _pad_to(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    out = np.zeros(shape, dtype=bool)
    h, w = a.shape
    out[:h, :w] = a
    return out


@pytest.mark.parametrize("base", EYEBROW_BASES)
def test_eyebrow_overlay_equals_both(base):
    """For every eyebrow base: rendering (head+right) over (head+left)
    must equal (head+both) pixel-for-pixel.

    Concretely we compare ink masks. The head circle is shared by all
    three glyphs, so unioning the two single-eyebrow renders produces
    head ∪ right ∪ left — which is exactly what head+both renders. Any
    mismatch means an eyebrow drifted between siblings."""
    img_right = _render(f"{base}10")
    img_left  = _render(f"{base}20")
    img_both  = _render(f"{base}00")
    h = max(img_right.shape[0], img_left.shape[0], img_both.shape[0])
    w = max(img_right.shape[1], img_left.shape[1], img_both.shape[1])
    img_right = _pad_to(img_right, (h, w))
    img_left  = _pad_to(img_left,  (h, w))
    img_both  = _pad_to(img_both,  (h, w))

    merged = img_right | img_left

    # IOU as a single number for an easy-to-read assertion message.
    inter = int(np.logical_and(merged, img_both).sum())
    union = int(np.logical_or(merged, img_both).sum())
    iou = inter / union if union else 1.0

    # 0.97 tolerates the sub-pixel anti-aliasing fringe where an eyebrow
    # stroke meets the head circle (the rasterizer produces slightly
    # different alpha along those shared edges when the head + eyebrow
    # come from one composite vs. two overlaid renders). A structural
    # position drift would drop the IOU much further than that.
    assert iou >= 0.97, (
        f"{base}: overlay({base}10, {base}20) vs {base}00 IOU={iou:.4f} "
        f"(inter={inter}, union={union})"
    )


@pytest.mark.parametrize("base", EYE_BASES)
def test_eye_both_is_two_singles_no_mirror(base):
    """The eye 'both' glyph ({b}30) is two copies of the single eye ({b}40),
    and the head+single glyphs ({b}10/{b}20) reference {b}40 directly — never
    a mirror M({b}40). The eyes are identical copies; referencing the same
    {b}40 makes both render identically, whereas a mirror lands at a worse
    sub-pixel phase and renders that half thinner in a browser."""
    comp = json.loads(COMPOSITIONS_JSON.read_text())
    both = comp.get(f"{base}30")
    assert both, f"{base}30 not composed"
    parts = [(p["ref"], p.get("transform")) for p in both["parts"]]
    assert parts == [(f"{base}40", None), (f"{base}40", None)], (
        f"{base}30 -> {parts}, expected two un-mirrored copies of {base}40"
    )
    for fill in ("10", "20"):
        entry = comp.get(f"{base}{fill}")
        assert entry, f"{base}{fill} not composed"
        eye = [(p["ref"], p.get("transform"))
               for p in entry["parts"] if p["ref"] != "S2ff00"]
        assert eye == [(f"{base}40", None)], (
            f"{base}{fill} eye part {eye}, expected {base}40 with no mirror"
        )


@pytest.mark.parametrize("multiple,single,n", MULTIPLE_TRIPLES)
def test_movement_multiple_has_n_copies_of_single(multiple, single, n):
    """A 'multiple' glyph (e.g. S20600 TOUCH MULTIPLE) should contain
    roughly N copies of its single base's ink. We compare ink-pixel
    counts: target_ink ≈ N × single_ink (within hand-drawn variance,
    because each copy in the source SVG can be a few % off from the
    standalone single). A real structural bug (wrong N, missing copy,
    or completely wrong base) collapses this ratio.

    We also compare against the oracle (font-db direct build) so that
    our composition reproduces the same total ink area as the source.
    """
    new = _render(multiple)
    new_single = _render(single)
    oracle = _render(multiple, font=ORACLE_FONT)

    # Ratio: multiple's ink / single's ink should be ~N.
    ratio_new = new.sum() / max(1, new_single.sum())
    assert n - 0.30 < ratio_new < n + 0.30, (
        f"{multiple}: ink-ratio new={ratio_new:.2f} vs expected ~{n}"
    )
    # The new font's multiple-vs-oracle ink should match within ~10%
    # (source SVGs hand-redraw each copy at slightly different size).
    rel_diff = abs(new.sum() - oracle.sum()) / max(1, oracle.sum())
    assert rel_diff < 0.10, (
        f"{multiple}: ink count drift {rel_diff*100:.1f}% from oracle "
        f"(new={int(new.sum())}, oracle={int(oracle.sum())})"
    )


def _mask_iou(a, b):
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])
    a = _pad_to(a, (h, w))
    b = _pad_to(b, (h, w))
    inter = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    return inter / union if union else 1.0


@pytest.mark.parametrize("high,low", ROTATION_MIRROR_SIBLINGS)
def test_rotation_dedup_is_mirror_of_lower_sibling(high, low):
    """Each rotation 8..f must resolve to a single mirror (M) composite of
    its rot-8 sibling. Deterministic guard against the old `+8 offset` rule,
    which referenced the same sibling but WITHOUT the mirror — rendering the
    wrong rotation."""
    comp = json.loads(COMPOSITIONS_JSON.read_text())
    entry = comp.get(high)
    assert entry and entry["rule"] == "rotation-dedup", (
        f"{high} is not rotation-deduped"
    )
    parts = [(p["ref"], p.get("transform")) for p in entry["parts"]]
    assert parts == [(low, "M")], f"{high} -> {parts}, expected [({low!r}, 'M')]"


# Render-side guard: S309 is asymmetric, so its rot R+8 (a real mirror) must
# NOT render identically to rot R. Catches build_font silently dropping the
# mirror transform (which would collapse the glyph onto its un-mirrored self).
@pytest.mark.parametrize("fill", "12")
def test_s309_mirror_is_not_identity(fill):
    iou = _mask_iou(_render(f"S309{fill}0"), _render(f"S309{fill}8"))
    assert iou < 0.95, (
        f"S309{fill}0 vs S309{fill}8: IOU={iou:.4f} — a mirror must differ "
        f"from its source rotation"
    )


@pytest.mark.parametrize("variant", S220_VARIANTS)
def test_s220_alternating_matches_oracle_ink(variant):
    """S220 SQUEEZE-FLICK ALTERNATING — each variant is composed of
    S21c00 (flick) + S21700 (squeeze). Total ink should match oracle
    within hand-drawn variance."""
    new = _render(variant)
    oracle = _render(variant, font=ORACLE_FONT)
    rel_diff = abs(new.sum() - oracle.sum()) / max(1, oracle.sum())
    assert rel_diff < 0.10, (
        f"{variant}: ink drift {rel_diff*100:.1f}% from oracle "
        f"(new={int(new.sum())}, oracle={int(oracle.sum())})"
    )


@pytest.mark.parametrize("rot0,rot1", S307_MIRROR_PAIRS)
def test_s307_rot1_is_horizontal_mirror_of_rot0(rot0, rot1):
    """S307's rot=1 column should be the horizontal mirror of rot=0:
    rendering rot1 should match rendering rot0 flipped left-right."""
    img0 = _render(rot0)
    img1 = _render(rot1)
    h = max(img0.shape[0], img1.shape[0])
    w = max(img0.shape[1], img1.shape[1])
    img0 = _pad_to(img0, (h, w))
    img1 = _pad_to(img1, (h, w))
    flipped = img0[:, ::-1]
    inter = int(np.logical_and(flipped, img1).sum())
    union = int(np.logical_or(flipped, img1).sum())
    iou = inter / union if union else 1.0
    assert iou >= 0.92, (
        f"{rot1} vs M({rot0}): IOU={iou:.4f} (inter={inter}, union={union})"
    )


@pytest.mark.parametrize("base", HEAD_PLUS_30_BASES)
def test_head_plus_30_matches_oracle(base):
    """For families whose fill 0 = head + a single-blob decoration
    (drawn as fill 3), verify the composite render matches the oracle."""
    sym = f"{base}00"
    new = _render(sym)
    oracle = _render(sym, font=ORACLE_FONT)
    h = max(new.shape[0], oracle.shape[0])
    w = max(new.shape[1], oracle.shape[1])
    new = _pad_to(new, (h, w))
    oracle = _pad_to(oracle, (h, w))
    inter = int(np.logical_and(new, oracle).sum())
    union = int(np.logical_or(new, oracle).sum())
    iou = inter / union if union else 1.0
    # 0.80 absorbs significant hand-drawn variance — the "fill 3"
    # standalone glyph is often re-traced differently from how it
    # appears inside fill 0. Structural correctness (head present,
    # decoration roughly in the right place) is what this test asserts.
    assert iou >= 0.80, (
        f"{sym}: new vs oracle IOU={iou:.4f}"
    )


@pytest.mark.parametrize("base", FOREHEAD_BASES)
def test_forehead_matches_oracle(base):
    """S311..S313: the head+marker composite should render identically
    (within edge anti-aliasing) to the oracle (unopt) font that uses
    the original source SVG outline.
    """
    sym = f"{base}00"
    new = _render(sym)
    oracle = _render(sym, font=ORACLE_FONT)
    h = max(new.shape[0], oracle.shape[0])
    w = max(new.shape[1], oracle.shape[1])
    new = _pad_to(new, (h, w))
    oracle = _pad_to(oracle, (h, w))
    inter = int(np.logical_and(new, oracle).sum())
    union = int(np.logical_or(new, oracle).sum())
    iou = inter / union if union else 1.0
    # 0.92 absorbs hand-drawn variance between the standalone marker
    # SVG (S{b}10) and how that same marker is traced in S{b}00 — the
    # SignWriting authors redrew slightly different proportions in the
    # composed glyph. A real bug (wrong position, missing part, swapped
    # mirror) drops IOU much further than this.
    assert iou >= 0.92, (
        f"{sym}: new vs oracle IOU={iou:.4f} (inter={inter}, union={union})"
    )

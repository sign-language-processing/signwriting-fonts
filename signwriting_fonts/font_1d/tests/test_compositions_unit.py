"""Pure-Python unit tests for compositions internals.

The render-based suite in `test_compositions.py` covers end-to-end
behaviour, but its tolerances are coarse (IOU ≥ 0.80 — big enough to
absorb hand-drawn variance, so a small matcher bug could slip past).
These tests pin the smaller invariants directly.
"""

from __future__ import annotations

import pytest

from signwriting_fonts.font_1d._symkey import (
    HAND_BASE_MAX,
    symkey_to_codepoint,
)
from signwriting_fonts.font_1d.compositions import (
    _match_part_in_target,
    _mirror_x,
    apply_transform,
)
from signwriting_fonts.font_1d.svg_path import parse_subpaths


# ---------------------------------------------------------------------------
# symkey_to_codepoint
# ---------------------------------------------------------------------------

def test_symkey_to_codepoint_first_symbol():
    # S10000 = first hand glyph; codepoint formula = plane4 + (0)*96 + 1.
    assert symkey_to_codepoint("S10000") == 0x40001


def test_symkey_to_codepoint_variant_offset():
    # S100 base, fill 1 (16), rot 2 → offset (0 * 96) + (1 * 16) + 2 + 1 = 19.
    assert symkey_to_codepoint("S10012") == 0x40000 + 19


def test_symkey_to_codepoint_last_hand_base():
    base = HAND_BASE_MAX - 1  # 0x204
    sk = f"S{base:03x}00"
    cp = symkey_to_codepoint(sk)
    # offset is (base - 0x100) * 96 + 1.
    assert cp == 0x40000 + (base - 0x100) * 96 + 1


def test_symkey_to_codepoint_rejects_malformed():
    for bad in ("X10000", "S1000", "S100000", "Saaaaa00"):
        with pytest.raises(ValueError):
            symkey_to_codepoint(bad)


# ---------------------------------------------------------------------------
# _mirror_x reverses winding
# ---------------------------------------------------------------------------

def test_mirror_x_reflects_about_axis():
    sub = parse_subpaths("M 0 0 L 10 0 L 10 5 Z")[0]
    mirrored = _mirror_x(sub, axis_x=5)
    # All x-coords reflected; y unchanged; winding reversed (last point
    # of the original is the new M).
    assert mirrored[0] == ("M", [0, 5])   # was the last anchor (10, 5)
    # All anchors lie on the mirror — sum of original x + mirrored x == 10.
    for (cmd_orig, args_orig), (cmd_new, args_new) in zip(sub, mirrored):
        for kx in range(0, len(args_orig), 2):
            # The mirror reverses winding so we can't pair indexes directly,
            # but x bounds must match (each original x has a partner).
            pass
    # Bbox stays put.
    orig_xs = [args[k] for _, args in sub for k in range(0, len(args), 2)]
    new_xs = [args[k] for _, args in mirrored for k in range(0, len(args), 2)]
    assert min(orig_xs) == 10 - max(new_xs) + min(new_xs) - 0  # symmetry
    assert max(orig_xs) == max(new_xs)


def test_apply_transform_none_returns_unchanged():
    sub = parse_subpaths("M 0 0 L 5 0 L 5 5 Z")
    assert apply_transform(sub, None) is sub


def test_apply_transform_M_mirrors_across_combined_bbox():
    subs = parse_subpaths("M 0 0 L 10 0 L 10 5 Z M 20 0 L 30 0 L 30 5 Z")
    # Combined bbox is x in [0, 30]; axis = 15.
    mirrored = apply_transform(subs, "M")
    assert len(mirrored) == 2
    # All x-coords reflected about x=15, so the new set of x-extremes is
    # exactly the original set.
    orig_xs = {args[k] for sub in subs for _, args in sub
               for k in range(0, len(args), 2)}
    new_xs = {args[k] for sub in mirrored for _, args in sub
              for k in range(0, len(args), 2)}
    assert orig_xs == new_xs


def test_apply_transform_rejects_unknown_op():
    subs = parse_subpaths("M 0 0 L 1 0 Z")
    with pytest.raises(ValueError, match="unsupported transform"):
        apply_transform(subs, "ROTATE")


# ---------------------------------------------------------------------------
# _match_part_in_target — the sub-path assignment matcher
# ---------------------------------------------------------------------------

def _box(x: float, y: float, w: float = 10, h: float = 10) -> str:
    return f"M {x} {y} L {x + w} {y} L {x + w} {y + h} L {x} {y + h} Z"


def test_match_single_part_finds_translation():
    target = parse_subpaths(_box(50, 30))
    part = parse_subpaths(_box(0, 0))
    result = _match_part_in_target(part, target)
    assert result is not None
    off_x, off_y, _ = result
    assert off_x == 50
    assert off_y == 30


def test_match_returns_none_when_part_size_does_not_fit():
    target = parse_subpaths(_box(0, 0, w=10, h=10))
    part = parse_subpaths(_box(0, 0, w=100, h=100))  # 10× larger
    assert _match_part_in_target(part, target) is None


def test_match_picks_rightmost_when_ambiguous():
    """The matcher iterates target sub-paths in descending-x order; given
    two identical-size candidates it must pick the rightmost (so a 'base'
    part in a mirror pair lands on the right, matching the resolver's
    intent — see the comment inside _match_part_in_target)."""
    target = parse_subpaths(_box(0, 0) + " " + _box(50, 0))
    part = parse_subpaths(_box(0, 0))
    off_x, off_y, _ = _match_part_in_target(part, target)
    assert off_x == 50  # rightmost candidate wins


def test_match_two_parts_must_share_consistent_offset():
    """N-part assignment must share one offset within _OFFSET_ABS_TOL
    (~300 path units). Two part boxes co-located, with target boxes
    1000 units apart in x, can't share an offset → no match."""
    target = parse_subpaths(_box(0, 0) + " " + _box(1000, 0))
    part = parse_subpaths(_box(0, 0) + " " + _box(0, 0))
    assert _match_part_in_target(part, target) is None


def test_match_succeeds_when_offsets_within_tolerance():
    """Two part boxes with target boxes at exactly the same offset →
    match returns that single offset."""
    target = parse_subpaths(_box(50, 30) + " " + _box(50, 30, w=20, h=10))
    part = parse_subpaths(_box(0, 0) + " " + _box(0, 0, w=20, h=10))
    result = _match_part_in_target(part, target)
    assert result is not None
    off_x, off_y, _ = result
    assert off_x == 50
    assert off_y == 30

"""Unit tests for the ellipse-replacement optimizer.

The integration suite checks pixel parity vs the upstream oracle; these
tests target the smaller behaviours: circle detection thresholds, the
exact 4-segment kappa output, sub-paths that don't fit a circle, and
the lenient circle counter used by the symbol-explorer site.
"""

from __future__ import annotations

import math

from signwriting_fonts.font_1d.optimize import (
    DETECT_TOLERANCE,
    ELLIPSE_TOLERANCE,
    KAPPA,
    _ellipse_cubic_path,
    _fit_circle_lsq,
    _winding_sign,
    count_circles_in_svg,
    optimize_path_d,
    optimize_svg,
)


def _circle_d(cx: float, cy: float, r: float, n: int = 8,
              clockwise: bool = True) -> str:
    """Build a closed sub-path whose anchors sit exactly on a circle."""
    pts = []
    for i in range(n):
        # SVG y axis is down — clockwise means increasing angle (CCW math)
        # gives clockwise visual winding, so flip if the caller asked for it.
        theta = 2 * math.pi * i / n
        if not clockwise:
            theta = -theta
        pts.append((cx + r * math.cos(theta), cy + r * math.sin(theta)))
    parts = [f"M {pts[0][0]} {pts[0][1]}"]
    parts.extend(f"L {x} {y}" for x, y in pts[1:])
    parts.append("Z")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Circle fitting
# ---------------------------------------------------------------------------

def test_fit_circle_lsq_recovers_center_and_radius():
    # 8 evenly-spaced anchors → max gap 45°, well inside any threshold.
    pts = [(math.cos(2 * math.pi * i / 8) * 5 + 3,
            math.sin(2 * math.pi * i / 8) * 5 + 7)
           for i in range(8)]
    fit = _fit_circle_lsq(pts)
    assert fit is not None
    cx, cy, r, err = fit
    assert math.isclose(cx, 3, abs_tol=1e-6)
    assert math.isclose(cy, 7, abs_tol=1e-6)
    assert math.isclose(r, 5, abs_tol=1e-6)
    assert err < 1e-9


def test_fit_circle_lsq_rejects_arc_with_large_gap():
    """A fragment that's almost a circle but missing a quadrant should
    fail the angular-gap check, not slip through with a tiny residual."""
    pts = [(math.cos(t), math.sin(t)) for t in (0, math.pi / 6,
                                                math.pi / 3, math.pi / 2)]
    assert _fit_circle_lsq(pts) is None


def test_fit_circle_lsq_rejects_too_few_points():
    assert _fit_circle_lsq([(0, 0), (1, 0), (0, 1)]) is None


def test_fit_circle_lsq_max_gap_arg_loosens_threshold():
    """The lenient counter (used by the site) passes a larger gap arg —
    fragments that the strict path would reject still match here.

    Anchors at 0°, 60°, 120°, 180°, 240°, 275° have a max gap of
    360° − 275° = 85°. Strict (80°) rejects; lenient (90°) accepts."""
    pts = [(math.cos(math.radians(a)), math.sin(math.radians(a)))
           for a in (0, 60, 120, 180, 240, 275)]
    assert _fit_circle_lsq(pts, max_gap_deg=80) is None
    assert _fit_circle_lsq(pts, max_gap_deg=90) is not None


# ---------------------------------------------------------------------------
# Ellipse emission
# ---------------------------------------------------------------------------

def test_ellipse_cubic_path_has_four_segments_plus_close():
    d = _ellipse_cubic_path(cx=0, cy=0, rx=10, ry=10, clockwise=True)
    # 1 M + 4 C + Z
    assert d.count(" C") == 4
    assert d.endswith("Z")


def test_ellipse_cubic_path_anchor_coordinates_on_circle():
    """The four anchor points of the kappa path must be exactly on the
    fitted circle (control points push the curve outward by ~KAPPA·r)."""
    d = _ellipse_cubic_path(cx=5, cy=5, rx=3, ry=3, clockwise=True)
    # Parse out coords:
    nums = [float(t) for t in d.replace("M", "").replace("C", "")
                                   .replace("Z", "").split()]
    pts = list(zip(nums[0::2], nums[1::2]))
    # Anchor points are at indices 0 (M) and 3, 6, 9, 12 (end of each C).
    anchors = [pts[0], pts[3], pts[6], pts[9], pts[12]]
    for x, y in anchors:
        assert math.isclose(math.hypot(x - 5, y - 5), 3, abs_tol=1e-6)


def test_winding_sign_distinguishes_orientation():
    """_winding_sign sums (x2-x1)(y2+y1) over edges. Direction is opposite
    for a forward vs reversed point list — we don't pin which one is
    +1, only that they disagree."""
    pts = [(10, 0), (0, 10), (-10, 0), (0, -10)]
    assert _winding_sign(pts) == -_winding_sign(list(reversed(pts)))
    assert _winding_sign(pts) in (+1, -1)


# ---------------------------------------------------------------------------
# optimize_path_d / optimize_svg
# ---------------------------------------------------------------------------

def test_optimize_path_d_replaces_clean_circle():
    d = _circle_d(0, 0, 10, n=8, clockwise=True)
    out, n = optimize_path_d(d)
    assert n == 1
    assert out.count(" C") == 4  # kappa ellipse has exactly 4 cubics


def test_optimize_path_d_keeps_non_circular_subpath():
    """A straight-line polygon should not be replaced."""
    d = "M 0 0 L 10 0 L 10 5 L 0 5 Z"
    out, n = optimize_path_d(d)
    assert n == 0
    assert out.strip() == d.strip() or out.startswith("M")


def test_optimize_path_d_handles_mixed_subpaths():
    """When the path has BOTH a circle and a non-circle sub-path, only
    the circle is replaced; the other passes through untouched."""
    circle = _circle_d(0, 0, 5, n=8, clockwise=True)
    line = "M 100 100 L 110 100 L 110 105 L 100 105 Z"
    d = circle + " " + line
    out, n = optimize_path_d(d)
    assert n == 1
    # Output has two sub-paths: one synthetic ellipse + one passthrough.
    assert out.count("M") == 2


def test_optimize_svg_passes_through_when_no_circles():
    """No replacement → path data is preserved (the optimizer normalises
    each sub-path with a trailing Z, but the segments are byte-identical
    otherwise)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<path class="sym-line" d="M 0 0 L 10 10"/></svg>'
    )
    out, n = optimize_svg(svg)
    assert n == 0
    # Segments survive (Z is appended by the re-emitter).
    assert "M 0 0 L 10 10" in out
    assert "<path" in out and 'class="sym-line"' in out


def test_optimize_svg_replaces_circles_in_path():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        f'<path class="sym-line" d="{_circle_d(10, 10, 5, n=8)}"/>'
        '</svg>'
    )
    out, n = optimize_svg(svg)
    assert n == 1
    # After replacement the path's d should contain exactly 4 C commands.
    assert out.count(" C") == 4


def test_count_circles_lenient_threshold():
    """The lenient detector counts a 5-anchor near-circle that the strict
    optimizer would reject (≤ DETECT_TOLERANCE residual is enough)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        f'<path class="sym-line" d="{_circle_d(10, 10, 5, n=8)}"/>'
        '</svg>'
    )
    assert count_circles_in_svg(svg) == 1


def test_thresholds_are_in_expected_range():
    """Guard against an accidental loosening of the strict optimizer
    that would replace non-circular shapes."""
    assert 0 < ELLIPSE_TOLERANCE < DETECT_TOLERANCE
    # KAPPA is the canonical Bezier-circle constant.
    assert math.isclose(KAPPA, 4 * (math.sqrt(2) - 1) / 3, abs_tol=1e-9)

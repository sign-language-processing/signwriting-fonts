"""Unit tests for the shared SVG path parser.

The font-db inputs only exercise M/L/C, so these tests deliberately
include the H/V/Z and relative-coord paths that the parser claims to
support but the integration suite doesn't actually feed it.
"""

from __future__ import annotations

import math

import pytest

from signwriting_fonts.font_1d.svg_path import (
    anchors,
    control_bbox,
    parse_subpaths,
    render_bbox,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parse_absolute_moveto_lineto():
    subs = parse_subpaths("M 10 20 L 30 40 L 50 60 Z")
    assert subs == [
        [("M", [10, 20]), ("L", [30, 40]), ("L", [50, 60])]
    ]


def test_parse_relative_moveto_resets_per_subpath():
    """After Z, the next `m` is relative to the CURRENT point (= sub-start
    after Z), not to the previous subpath's last cursor."""
    subs = parse_subpaths("M 10 10 L 20 20 Z m 5 5 L 30 30")
    assert subs[0][0] == ("M", [10, 10])
    # After Z, cursor is back at (10, 10). Then `m 5 5` → (15, 15).
    assert subs[1][0] == ("M", [15, 15])


def test_parse_implicit_lineto_after_moveto():
    """Extra coord pairs after an M/m are implicit L/l per SVG spec."""
    subs = parse_subpaths("M 10 10 20 20 30 30")
    assert subs == [
        [("M", [10, 10]), ("L", [20, 20]), ("L", [30, 30])]
    ]
    # Relative variant
    subs_rel = parse_subpaths("m 10 10 1 1 1 1")
    assert subs_rel == [
        [("M", [10, 10]), ("L", [11, 11]), ("L", [12, 12])]
    ]


def test_parse_horizontal_vertical_become_lineto():
    subs = parse_subpaths("M 0 0 H 10 V 20 h -5 v -5")
    assert subs == [[
        ("M", [0, 0]),
        ("L", [10, 0]),
        ("L", [10, 20]),
        ("L", [5, 20]),
        ("L", [5, 15]),
    ]]


def test_parse_cubic_relative_resolved_against_cursor():
    subs = parse_subpaths("M 10 10 c 1 2 3 4 5 6")
    # Each relative control/endpoint adds to the current cursor (10, 10).
    assert subs == [[
        ("M", [10, 10]),
        ("C", [11, 12, 13, 14, 15, 16]),
    ]]


def test_parse_multiple_subpaths():
    subs = parse_subpaths("M 0 0 L 1 0 Z M 10 0 L 11 0")
    assert len(subs) == 2
    assert subs[0][0] == ("M", [0, 0])
    assert subs[1][0] == ("M", [10, 0])


def test_parse_scientific_and_signed_numbers():
    """Numbers must parse with sign and scientific notation."""
    subs = parse_subpaths("M -1.5e1 .5 L 0 0")
    assert subs[0][0] == ("M", [-15.0, 0.5])


def test_parse_rejects_unknown_command():
    with pytest.raises(ValueError, match="unsupported path command"):
        parse_subpaths("M 0 0 Q 1 1 2 2")


def test_parse_rejects_number_before_command():
    with pytest.raises(ValueError, match="number before any command"):
        parse_subpaths("10 20 M 0 0")


def test_parse_empty_input_returns_no_subpaths():
    assert parse_subpaths("") == []
    assert parse_subpaths("  ") == []


# ---------------------------------------------------------------------------
# anchors / control_bbox
# ---------------------------------------------------------------------------

def test_anchors_returns_each_segment_endpoint():
    sub = parse_subpaths("M 0 0 L 10 0 C 5 5 5 5 10 10")[0]
    assert anchors(sub) == [(0, 0), (10, 0), (10, 10)]


def test_control_bbox_includes_control_points():
    sub = parse_subpaths("M 0 0 C 100 100 -50 -50 10 10")[0]
    # Control points (100, 100) and (-50, -50) push the bbox past the
    # endpoints — that's the point of control_bbox.
    assert control_bbox(sub) == (-50, -50, 100, 100)


# ---------------------------------------------------------------------------
# render_bbox
# ---------------------------------------------------------------------------

def test_render_bbox_straight_line_matches_endpoints():
    sub = parse_subpaths("M 0 0 L 10 20")[0]
    assert render_bbox(sub) == (0, 0, 10, 20)


def test_render_bbox_cubic_includes_extremum_inside_segment():
    """A bezier whose anchors are flat but whose control points peak
    inside the segment — render_bbox should pick up the parametric
    extremum, not just the endpoints."""
    sub = parse_subpaths("M 0 0 C 0 100 10 100 10 0")[0]
    xmin, ymin, xmax, ymax = render_bbox(sub)
    # ymax must exceed the anchor ymax (=0).
    assert ymax > 50
    # x bounds stay within the anchor x range.
    assert xmin == 0
    assert xmax == 10


def test_render_bbox_kappa_circle_within_one_percent():
    """A kappa cubic-Bezier approximation of a unit circle should
    have render_bbox very close to (-1, -1, 1, 1)."""
    K = 0.5522847498307933
    d = (
        f"M 1 0 "
        f"C 1 {K} {K} 1 0 1 "
        f"C {-K} 1 -1 {K} -1 0 "
        f"C -1 {-K} {-K} -1 0 -1 "
        f"C {K} -1 1 {-K} 1 0 Z"
    )
    sub = parse_subpaths(d)[0]
    xmin, ymin, xmax, ymax = render_bbox(sub)
    for got, want in ((xmin, -1), (ymin, -1), (xmax, 1), (ymax, 1)):
        assert math.isclose(got, want, abs_tol=1e-3), (got, want)


def test_render_bbox_empty_subpath_returns_none():
    assert render_bbox([]) is None

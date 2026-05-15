"""Detect ellipse-like sub-paths in source SVGs and replace with clean ellipse curves.

For the first iteration this script only handles the most common case: a closed
sub-path whose anchor points lie close to a best-fit ellipse. Such a path is
replaced with a synthetic 4-segment cubic-Bezier ellipse (kappa approximation,
~0.027 % radius error). This:

  - reduces font size (fewer control points), and
  - removes hand-traced wobble (true ellipses instead of approximate ones).

Paths that don't fit an ellipse are passed through untouched.
"""

import argparse
import math
import re
import shutil
from pathlib import Path

# Cubic-Bezier-of-a-circle constant.
KAPPA = 0.5522847498307933

# A sub-path qualifies as an ellipse if the max deviation of its anchor points
# from the fitted ellipse is below this fraction of the ellipse's mean radius.
# The source SVGs from font-db often include one extra "stitch" anchor where
# the path's start/end joins; we drop the worst single outlier before checking.
# Kept tight: looser thresholds catch sub-arcs of non-circular shapes (e.g.
# the outer outline of a comb) and replace them with synthetic discs.
ELLIPSE_TOLERANCE = 0.025
OUTLIER_DROP = 1

# Cubic Bezier reproduces ≤90° arcs cleanly via kappa. Anchor gaps above
# this threshold can't trace a true circle arc, no matter how well the
# overall LSQ fit looks.
MAX_ANGULAR_GAP_DEG = 80  # strict optimizer: only replace clean rings


# ---------------------------------------------------------------------------
# Path parsing — enough of an SVG path subset to handle font-db's outputs.
# font-db emits only M, m, L, l, C, c, Z, z (plus whitespace/commas).
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[MmLlCcZz]|-?\d+\.?\d*")


def _split_subpaths(d: str):
    """Yield each sub-path of `d` as a list of absolute (x0, y0, segments).

    SVG path semantics:
      - relative `m` after a previous sub-path starts at the *current point*
        (where the prior sub-path ended), not at (0, 0);
      - `Z`/`z` returns the current point to the sub-path's start point.
    We track the cursor across sub-paths and emit each sub-path with absolute
    segment commands so callers don't need to chase the cursor themselves.
    """
    tokens = _TOKEN.findall(d)
    i = 0
    cur_x = cur_y = 0.0       # global cursor across all sub-paths
    sub_start_x = sub_start_y = 0.0
    current = []               # list of (cmd_uppercase, abs_args)
    while i < len(tokens):
        t = tokens[i]
        if t in "Zz":
            if current:
                yield (sub_start_x, sub_start_y, current)
                current = []
            cur_x, cur_y = sub_start_x, sub_start_y
            i += 1
            continue
        if t in "MmLlCc":
            cmd = t
            if cmd in ("M", "m") and current:
                yield (sub_start_x, sub_start_y, current)
                current = []
            n = {"M": 2, "m": 2, "L": 2, "l": 2, "C": 6, "c": 6}[cmd]
            i += 1
            first_in_run = True
            while i + n <= len(tokens) and tokens[i] not in "MmLlCcZz":
                raw = [float(tokens[i + k]) for k in range(n)]
                rel = cmd.islower()
                abs_args = []
                if cmd.upper() == "M":
                    # MoveTo
                    if rel:
                        cur_x += raw[0]; cur_y += raw[1]
                    else:
                        cur_x, cur_y = raw[0], raw[1]
                    if first_in_run:
                        sub_start_x, sub_start_y = cur_x, cur_y
                    abs_args = [cur_x, cur_y]
                    current.append(("M", abs_args))
                    # Implicit follow-on coords become L/l
                    if cmd == "M":
                        cmd = "L"
                    elif cmd == "m":
                        cmd = "l"
                elif cmd.upper() == "L":
                    if rel:
                        cur_x += raw[0]; cur_y += raw[1]
                    else:
                        cur_x, cur_y = raw[0], raw[1]
                    abs_args = [cur_x, cur_y]
                    current.append(("L", abs_args))
                elif cmd.upper() == "C":
                    if rel:
                        x1, y1 = cur_x + raw[0], cur_y + raw[1]
                        x2, y2 = cur_x + raw[2], cur_y + raw[3]
                        x3, y3 = cur_x + raw[4], cur_y + raw[5]
                    else:
                        x1, y1, x2, y2, x3, y3 = raw
                    cur_x, cur_y = x3, y3
                    abs_args = [x1, y1, x2, y2, x3, y3]
                    current.append(("C", abs_args))
                first_in_run = False
                i += n
        else:
            i += 1
    if current:
        yield (sub_start_x, sub_start_y, current)


def _anchors(segments):
    """Return absolute (x, y) anchor points (endpoint of each segment, including M)."""
    pts = []
    for cmd, args in segments:
        # M/L: args = [x, y]; C: args = [x1, y1, x2, y2, x3, y3] (endpoint last)
        pts.append((args[-2], args[-1]))
    return pts


def _subpath_bbox(segments):
    """Return (xmin, ymin, xmax, ymax) of the rendered sub-path.

    For cubic Beziers we evaluate the parametric extremes (derivative
    zeros) in addition to the endpoints — that gives an exact bbox of
    the rendered curve, not just the control polygon. This matters for
    circle replacement: the source's curve bulges past its anchors, and
    sizing the synthetic ellipse to the anchor circle alone shrinks the
    glyph ~2.5%.
    """
    xs, ys = [], []
    cur_x, cur_y = None, None
    for cmd, args in segments:
        if cmd == "M" or cmd == "L":
            x, y = args
            xs.append(x); ys.append(y)
            cur_x, cur_y = x, y
            continue
        # Cubic: (x1, y1, x2, y2, x3, y3) with start = (cur_x, cur_y)
        x1, y1, x2, y2, x3, y3 = args
        # Endpoints always contribute.
        xs.append(cur_x); ys.append(cur_y)
        xs.append(x3); ys.append(y3)
        # B(t) = (1-t)³ P0 + 3(1-t)²t P1 + 3(1-t)t² P2 + t³ P3
        # B'(t) = 3 [(1-t)² (P1-P0) + 2(1-t)t (P2-P1) + t² (P3-P2)]
        #       = 3 [A t² + B t + C]   with A = (P3 - 3 P2 + 3 P1 - P0),
        #                                   B = 2(P2 - 2 P1 + P0),
        #                                   C = (P1 - P0)
        for axis_p0, axis_p1, axis_p2, axis_p3, sink in (
            (cur_x, x1, x2, x3, xs),
            (cur_y, y1, y2, y3, ys),
        ):
            A = axis_p3 - 3 * axis_p2 + 3 * axis_p1 - axis_p0
            B = 2 * (axis_p2 - 2 * axis_p1 + axis_p0)
            C = axis_p1 - axis_p0
            roots = []
            if abs(A) < 1e-12:
                if abs(B) > 1e-12:
                    roots.append(-C / B)
            else:
                disc = B * B - 4 * A * C
                if disc >= 0:
                    sd = disc ** 0.5
                    roots.append((-B + sd) / (2 * A))
                    roots.append((-B - sd) / (2 * A))
            for t in roots:
                if 0.0 < t < 1.0:
                    omt = 1 - t
                    val = (omt ** 3 * axis_p0
                           + 3 * omt * omt * t * axis_p1
                           + 3 * omt * t * t * axis_p2
                           + t ** 3 * axis_p3)
                    sink.append(val)
        cur_x, cur_y = x3, y3
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Ellipse fitting (axis-aligned only — sufficient for the SignWriting glyphs)
# ---------------------------------------------------------------------------

def _fit_circle_lsq(points):
    """Algebraic LSQ fit of (x-cx)² + (y-cy)² = R² to `points`.

    Rejects (returns None) when the anchors don't span at least
    `MIN_ANGULAR_COVERAGE_DEG` around the fitted centre — that filters out
    arc fragments that happen to lie close to a circle locally but aren't
    actually closed rings (e.g. the outer outline of a comb shape).

    Returns (cx, cy, R, max_relative_error). The bezier anchors of a
    SignWriting "circle" sit ON the true circle (with control points pushed
    outward to bulge each segment), so LSQ fit gives a clean center+radius and
    very small residuals when the shape really is a circle.
    """
    import numpy as np
    if len(points) < 4:
        return None
    pts = np.array(points, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = sol
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = float(np.sqrt(r2))
    # Max anchor gap: an open arc has one big gap (e.g. comb-fragment
    # ~270°), a closed ring has gaps all ≤ ~60° depending on sampling.
    # Cubic Bezier reproduces ≤90° arcs cleanly via kappa, so the strict
    # threshold sits a bit below that.
    angles = np.sort(np.degrees(np.arctan2(y - cy, x - cx)) % 360)
    gaps = np.append(np.diff(angles), 360 - angles[-1] + angles[0])
    max_gap = float(np.max(gaps))
    if max_gap > MAX_ANGULAR_GAP_DEG:
        return None
    dists = np.hypot(x - cx, y - cy)
    max_err = float(np.max(np.abs(dists - r))) / r
    return float(cx), float(cy), r, max_err


def _fit_axis_aligned_ellipse(points):
    """Fit a circle (or ellipse-via-circle) to anchors.

    For now we only detect circles via LSQ. Returns
    (cx, cy, rx, ry, max_relative_error) with rx == ry for circles, or None.
    """
    if len(points) < 5:
        return None
    fit = _fit_circle_lsq(points)
    if fit is None:
        return None
    cx, cy, r, err = fit
    return cx, cy, r, r, err


def _ellipse_cubic_path(cx, cy, rx, ry, clockwise):
    """Emit a 4-segment cubic-Bezier path approximating an ellipse."""
    kx = KAPPA * rx
    ky = KAPPA * ry
    if clockwise:
        # right → bottom → left → top → right
        return (
            f"M{cx + rx} {cy} "
            f"C{cx + rx} {cy + ky} {cx + kx} {cy + ry} {cx} {cy + ry} "
            f"C{cx - kx} {cy + ry} {cx - rx} {cy + ky} {cx - rx} {cy} "
            f"C{cx - rx} {cy - ky} {cx - kx} {cy - ry} {cx} {cy - ry} "
            f"C{cx + kx} {cy - ry} {cx + rx} {cy - ky} {cx + rx} {cy} "
            f"Z"
        )
    else:
        return (
            f"M{cx + rx} {cy} "
            f"C{cx + rx} {cy - ky} {cx + kx} {cy - ry} {cx} {cy - ry} "
            f"C{cx - kx} {cy - ry} {cx - rx} {cy - ky} {cx - rx} {cy} "
            f"C{cx - rx} {cy + ky} {cx - kx} {cy + ry} {cx} {cy + ry} "
            f"C{cx + kx} {cy + ry} {cx + rx} {cy + ky} {cx + rx} {cy} "
            f"Z"
        )


def _winding_sign(points):
    """Return +1 if anchors trace clockwise (in SVG's y-down system), else -1."""
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += (x2 - x1) * (y2 + y1)
    return 1 if s > 0 else -1


def optimize_path_d(d: str):
    """Rewrite a path's `d` attribute, replacing ellipse-like sub-paths."""
    out_subpaths = []
    n_replaced = 0
    for sub_start_x, sub_start_y, segments in _split_subpaths(d):
        anchors = _anchors(segments)
        fit = _fit_axis_aligned_ellipse(anchors)
        if fit is not None:
            _cx, _cy, _rx, _ry, rel_err = fit
            if rel_err < ELLIPSE_TOLERANCE:
                # Detection uses the anchor LSQ (passes when the shape is
                # truly a circle). For emission, size the synthetic ellipse
                # to the source sub-path's actual bbox — SignWriting source
                # control points bulge past their anchors, so an anchor-
                # radius ellipse renders ~2.5% smaller than the original.
                bbox = _subpath_bbox(segments)
                if bbox is not None:
                    xmin, ymin, xmax, ymax = bbox
                    cx = (xmin + xmax) / 2
                    cy = (ymin + ymax) / 2
                    rx = (xmax - xmin) / 2
                    ry = (ymax - ymin) / 2
                    clockwise = _winding_sign(anchors) > 0
                    out_subpaths.append(
                        _ellipse_cubic_path(cx, cy, rx, ry, clockwise)
                    )
                    n_replaced += 1
                    continue
        out_subpaths.append(_segments_to_string(segments))
    return " ".join(out_subpaths), n_replaced


def _segments_to_string(segments):
    out = []
    for cmd, args in segments:
        out.append(cmd + " " + " ".join(_fmt(a) for a in args))
    out.append("Z")
    return " ".join(out)


def _fmt(n):
    """Format a float compactly (drops trailing .0)."""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:g}"


# ---------------------------------------------------------------------------
# SVG-level processing
# ---------------------------------------------------------------------------

_PATH_D = re.compile(r'(<path[^>]*\bd=")([^"]+)(")')


def optimize_svg(text: str):
    total_replaced = 0
    def repl(m):
        nonlocal total_replaced
        new_d, n = optimize_path_d(m.group(2))
        total_replaced += n
        return m.group(1) + new_d + m.group(3)
    new_text = _PATH_D.sub(repl, text)
    return new_text, total_replaced


# Looser thresholds used only for VISUALIZATION (the website's green-border
# decoration). At these settings we accept "circle-shaped" sub-paths that
# the strict optimizer rejects — clearly-circular rings with sparse anchor
# spacing (S21600: 6 anchors at 90° max-gap) or slight wobble (S2ff10: ~6%
# residual). We still reject anchors with gaps > 90° (those produce lumpy
# arcs no matter how well the fit looks — see _prim_08301's 97° gap).
DETECT_TOLERANCE = 0.07
DETECT_MAX_ANGULAR_GAP_DEG = 90


def _fit_circle_for_detection(points):
    """Lenient version of `_fit_circle_lsq` for the visualization pass."""
    import numpy as np
    if len(points) < 4:
        return None
    pts = np.array(points, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = sol
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = float(np.sqrt(r2))
    angles = np.sort(np.degrees(np.arctan2(y - cy, x - cx)) % 360)
    gaps = np.append(np.diff(angles), 360 - angles[-1] + angles[0])
    if float(np.max(gaps)) > DETECT_MAX_ANGULAR_GAP_DEG:
        return None
    max_err = float(np.max(np.abs(np.hypot(x - cx, y - cy) - r))) / r
    if max_err > DETECT_TOLERANCE:
        return None
    return max_err


def count_circles_in_svg(svg_text: str) -> int:
    """Return the number of approximately-circular sub-paths in `svg_text`
    (using the lenient detection thresholds)."""
    n = 0
    for m in _PATH_D.finditer(svg_text):
        for _x0, _y0, segments in _split_subpaths(m.group(2)):
            anchors = _anchors(segments)
            if _fit_circle_for_detection(anchors) is not None:
                n += 1
    return n


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--report", type=Path, default=None,
                        help="optional JSON output: {symkey: n_subpaths_replaced} "
                             "for every symbol whose render was modified")
    parser.add_argument("--circles-report", type=Path, default=None,
                        help="optional JSON output: {symkey: n_circle_subpaths} "
                             "for every symbol containing ≥1 approximately-"
                             "circular sub-path (lenient detection — does "
                             "NOT correspond to what gets replaced)")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(args.in_dir.glob("*.svg"))
    total = 0
    per_symbol = {}
    circle_symbol = {}
    for src in files:
        text = src.read_text()
        new_text, replaced = optimize_svg(text)
        (args.out_dir / src.name).write_text(new_text)
        if replaced:
            print(f"  {src.name}: replaced {replaced} sub-path(s) with synthetic ellipses")
            total += replaced
            per_symbol[src.stem] = replaced
        else:
            print(f"  {src.name}: passthrough")
        if args.circles_report is not None:
            n_circles = count_circles_in_svg(text)
            if n_circles:
                circle_symbol[src.stem] = n_circles
    print(f"Optimized {len(files)} SVG(s); replaced {total} sub-path(s) total.")
    if args.report is not None:
        args.report.write_text(json.dumps(per_symbol, indent=2, sort_keys=True))
        print(f"Wrote ellipse-replacement report: {args.report}")
    if args.circles_report is not None:
        args.circles_report.write_text(
            json.dumps(circle_symbol, indent=2, sort_keys=True)
        )
        print(f"Wrote circle-detection report: {args.circles_report} "
              f"({len(circle_symbol):,} symbols contain ≥1 circular sub-path)")


if __name__ == "__main__":
    main()

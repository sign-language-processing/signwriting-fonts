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
# Tightened from 0.05 to 0.025: at 0.05 some glyphs that *contain* a roughly
# circular sub-arc (e.g. the outer outline of S15401's comb shape) qualify
# and get replaced with a synthetic ellipse, turning the comb into a disc.
# All the legitimate ring outlines we want to optimize have err well under
# 0.02 in practice.
ELLIPSE_TOLERANCE = 0.025
OUTLIER_DROP = 1

# A closed ellipse path traces a full revolution around its centre. An arc
# fragment that only happens to fit a circle locally won't, so we reject
# sub-paths whose anchors don't span at least ~300° around the fitted centre.
MIN_ANGULAR_COVERAGE_DEG = 300


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
    # Angular coverage: bin the anchors' angles around the centre into 30°
    # buckets and require that they touch at least MIN_ANGULAR_COVERAGE_DEG
    # worth of buckets. An arc covering 90° (typical comb-outline fragment)
    # touches 3 buckets ≈ 90°; a full ring touches all 12 ≈ 360°.
    angles = np.degrees(np.arctan2(y - cy, x - cx)) % 360
    buckets = set((angles // 30).astype(int))
    coverage = len(buckets) * 30
    if coverage < MIN_ANGULAR_COVERAGE_DEG:
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
            cx, cy, rx, ry, rel_err = fit
            if rel_err < ELLIPSE_TOLERANCE:
                clockwise = _winding_sign(anchors) > 0
                out_subpaths.append(_ellipse_cubic_path(cx, cy, rx, ry, clockwise))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(args.in_dir.glob("*.svg"))
    total = 0
    for src in files:
        text = src.read_text()
        new_text, replaced = optimize_svg(text)
        (args.out_dir / src.name).write_text(new_text)
        if replaced:
            print(f"  {src.name}: replaced {replaced} sub-path(s) with synthetic ellipses")
            total += replaced
        else:
            print(f"  {src.name}: passthrough")
    print(f"Optimized {len(files)} SVG(s); replaced {total} sub-path(s) total.")


if __name__ == "__main__":
    main()

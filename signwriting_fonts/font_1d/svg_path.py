"""Shared SVG path parsing for the 1D pipeline.

font-db only emits a small subset of SVG path commands (M/L/C/Z, plus
implicit-lineto after M, plus the relative variants and the occasional
H/V). One parser keeps optimize.py and compositions.py in sync — changes
to handling (e.g., a new command) flow through both.

`parse_subpaths` returns each sub-path as a list of (CMD, abs_args)
tuples where CMD ∈ {M, L, C}; H/V are normalised to L; relative
variants are resolved against the running cursor.
"""

from __future__ import annotations

import re

# Match one path-data atom: either a command letter or a number
# (optionally signed, optionally fractional, optionally scientific).
_TOKEN_RE = re.compile(r'[A-DF-Za-df-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?')


def _tokens(d: str):
    for m in _TOKEN_RE.finditer(d):
        t = m.group()
        yield t if t[0].isalpha() else float(t)


def parse_subpaths(d: str) -> list[list[tuple[str, list[float]]]]:
    """Parse `d` into a list of sub-paths.

    Each sub-path is a list of (CMD, abs_args). H/V are emitted as L.
    Unsupported commands (S/Q/T/A) raise ValueError so a silent fallthrough
    can't mask a font-db change.
    """
    tokens = list(_tokens(d))
    sub_paths: list[list[tuple[str, list[float]]]] = []
    current: list[tuple[str, list[float]]] = []
    cur_x = cur_y = 0.0
    sub_start_x = sub_start_y = 0.0
    cmd: str | None = None

    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        if isinstance(t, str):
            cmd = t
            i += 1
            if cmd in 'Zz':
                cur_x, cur_y = sub_start_x, sub_start_y
                cmd = None
            continue
        if cmd is None:
            raise ValueError(f"number before any command in d={d[:60]!r}…")
        cu = cmd.upper()
        rel = (cmd != cu)
        if cu == 'M':
            x, y = tokens[i], tokens[i + 1]
            i += 2
            if rel:
                x += cur_x
                y += cur_y
            cur_x, cur_y = x, y
            sub_start_x, sub_start_y = x, y
            if current:
                sub_paths.append(current)
            current = [('M', [x, y])]
            # Implicit line-tos follow an explicit moveto, per the SVG spec.
            cmd = 'l' if rel else 'L'
        elif cu == 'L':
            x, y = tokens[i], tokens[i + 1]
            i += 2
            if rel:
                x += cur_x
                y += cur_y
            cur_x, cur_y = x, y
            current.append(('L', [x, y]))
        elif cu == 'H':
            x = tokens[i]
            i += 1
            if rel:
                x += cur_x
            cur_x = x
            current.append(('L', [x, cur_y]))
        elif cu == 'V':
            y = tokens[i]
            i += 1
            if rel:
                y += cur_y
            cur_y = y
            current.append(('L', [cur_x, y]))
        elif cu == 'C':
            x1, y1 = tokens[i],     tokens[i + 1]
            x2, y2 = tokens[i + 2], tokens[i + 3]
            x3, y3 = tokens[i + 4], tokens[i + 5]
            i += 6
            if rel:
                x1 += cur_x
                x2 += cur_x
                x3 += cur_x
                y1 += cur_y
                y2 += cur_y
                y3 += cur_y
            cur_x, cur_y = x3, y3
            current.append(('C', [x1, y1, x2, y2, x3, y3]))
        else:
            raise ValueError(f"unsupported path command {cmd!r} in d={d[:60]!r}…")
    if current:
        sub_paths.append(current)
    return sub_paths


def anchors(sub: list[tuple[str, list[float]]]) -> list[tuple[float, float]]:
    """Endpoint of each segment in a sub-path (M's args, then each L/C
    endpoint)."""
    return [(args[-2], args[-1]) for _, args in sub]


def control_bbox(sub: list[tuple[str, list[float]]]
                 ) -> tuple[float, float, float, float]:
    """Axis-aligned bbox over every coord in the sub-path (anchors AND
    cubic control points). Good enough for canonical-form matching; NOT
    the same as the rendered-curve bbox (see `render_bbox`)."""
    xs: list[float] = []
    ys: list[float] = []
    for _, args in sub:
        for k in range(0, len(args), 2):
            xs.append(args[k])
            ys.append(args[k + 1])
    return min(xs), min(ys), max(xs), max(ys)


def render_bbox(sub: list[tuple[str, list[float]]]
                ) -> tuple[float, float, float, float] | None:
    """Bbox of the rendered curve, evaluating cubic Bezier derivative
    zeros so the bulge between anchors is included. Required for circle
    replacement — fitting to the anchor bbox alone shrinks the synthetic
    ring ~2.5% relative to the source.

    Returns None for an empty sub-path.
    """
    xs: list[float] = []
    ys: list[float] = []
    cur_x = cur_y = None
    for cmd, args in sub:
        if cmd in ('M', 'L'):
            x, y = args
            xs.append(x)
            ys.append(y)
            cur_x, cur_y = x, y
            continue
        x1, y1, x2, y2, x3, y3 = args
        xs.append(cur_x)
        xs.append(x3)
        ys.append(cur_y)
        ys.append(y3)
        # B(t) = (1-t)³ P0 + 3(1-t)²t P1 + 3(1-t)t² P2 + t³ P3
        # B'(t)/3 = A t² + B t + C  with  A = P3 - 3 P2 + 3 P1 - P0,
        #                                 B = 2(P2 - 2 P1 + P0),
        #                                 C = P1 - P0
        for p0, p1, p2, p3, sink in (
            (cur_x, x1, x2, x3, xs),
            (cur_y, y1, y2, y3, ys),
        ):
            A = p3 - 3 * p2 + 3 * p1 - p0
            B = 2 * (p2 - 2 * p1 + p0)
            C = p1 - p0
            roots: list[float] = []
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
                    sink.append(
                        omt ** 3 * p0
                        + 3 * omt * omt * t * p1
                        + 3 * omt * t * t * p2
                        + t ** 3 * p3
                    )
        cur_x, cur_y = x3, y3
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)

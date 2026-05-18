"""Resolve manual composition rules into per-symbol composite specs.

Reads `rules.json` (human-authored composition patterns templated by
base) and the source SVG directory, then for each composition derives
each part's offset within its target by canonical sub-path matching.
Writes `compositions.json`: a flat map { target_symkey: { parts: [...] } }
that `build_font.py` consumes to emit TT composite glyph references.

Algorithm:
  - Parse target's `d` attribute into ordered sub-paths in absolute
    path coords.
  - For each part: parse its standalone `d`, apply any declared
    transform (currently "M" = horizontal mirror about bbox centre,
    with contour winding reversed).
  - Canonical-match the part's sub-paths against target's sub-paths
    (translation-only: subtract bbox-min of each sub-path and compare).
  - All sub-paths of a single part must share one consistent
    translation. Record that translation as the part's offset in target.

Usage:
    python -m signwriting_fonts.font_1d.compositions \\
        --svg-dir fonts/1d/svg \\
        --rules   signwriting_fonts/font_1d/rules.json \\
        --output  signwriting_fonts/font_1d/compositions.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from signwriting_fonts.font_1d.svg_path import (
    control_bbox as subpath_bbox,
    parse_subpaths,
)

# Layout constants — must match `build_font.py`. Each glyph is positioned
# with its bbox-min-x at TARGET_LSB and its bbox-mid-y at TARGET_Y_CENTER
# in font units.
TARGET_UNITS_PER_NATURAL = 10
TARGET_LSB = 20
TARGET_Y_CENTER = 166


# ---------------------------------------------------------------------------
# SVG metadata + path-to-font simulation
# ---------------------------------------------------------------------------

_G_TRANSFORM_RE = re.compile(
    r'<g\s+transform="translate\(\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)\s*\)'
    r'\s*scale\(\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)\s*\)"'
)
_SVG_DIMS_RE = re.compile(r'<svg[^>]*\bwidth="([0-9.]+)"\s+height="([0-9.]+)"')


def _read_svg_info(svg_path: Path) -> dict | None:
    """Return everything we need to simulate a glyph's path→font
    conversion: the raw `d` attribute, the SVG's natural width/height
    (from <svg width=… height=…>), and the `<g transform>` translate +
    scale values (per-glyph, not constant).

    Returns ``None`` if the SVG has no path data — this happens for Fill
    variants of symbols whose source has only ``sym-line`` (e.g. S20500
    contact glyphs). Callers skip those symbols rather than failing the
    whole build.
    """
    text = svg_path.read_text()
    dattr = re.search(r'd="([^"]+)"', text)
    if not dattr:
        return None
    dims = _SVG_DIMS_RE.search(text)
    gtransform = _G_TRANSFORM_RE.search(text)
    if not (dims and gtransform):
        raise ValueError(f"SVG {svg_path.name}: missing width/height or g "
                         f"transform")
    return {
        "d": dattr.group(1),
        "nat_w": float(dims.group(1)),
        "nat_h": float(dims.group(2)),
        "tx": float(gtransform.group(1)),
        "ty": float(gtransform.group(2)),
        "sx": float(gtransform.group(3)),
        "sy": float(gtransform.group(4)),
    }


def _path_to_natural(xy, info):
    """Apply the SVG's `<g transform>` to a single path point.
    Returns (natural_x, natural_y) in the SVG natural (viewBox) frame
    — y-DOWN convention, as in SVG."""
    x, y = xy
    return (x * info["sx"] + info["tx"], y * info["sy"] + info["ty"])


def _glyph_font_pipeline(info, subs):
    """Pre-compute the per-glyph parameters used by `_path_to_font`:
    natural-bbox, scale factor, layout offsets.

    FontForge stores glyphs in y-UP convention but SVG natural coords
    are y-DOWN. On import FontForge flips y around the viewBox height,
    i.e. font_y = nat_h_attr - natural_y. We replicate that here so the
    pipeline produces the same font positions FontForge ends up with."""
    nat_xs, nat_ys = [], []
    for sub in subs:
        for cmd, args in sub:
            for k in range(0, len(args), 2):
                nx, ny = _path_to_natural((args[k], args[k + 1]), info)
                nat_xs.append(nx)
                nat_ys.append(ny)
    nat_xmin, nat_xmax = min(nat_xs), max(nat_xs)
    nat_ymin, nat_ymax = min(nat_ys), max(nat_ys)
    nat_w = nat_xmax - nat_xmin
    nat_h = nat_ymax - nat_ymin
    target_w = info["nat_w"] * TARGET_UNITS_PER_NATURAL
    target_h = info["nat_h"] * TARGET_UNITS_PER_NATURAL
    sx_font = target_w / nat_w if nat_w else 1.0
    sy_font = target_h / nat_h if nat_h else 1.0
    scale = min(sx_font, sy_font)
    # Post-scale (pre-layout) font-space bbox. Flip y around nat_h_attr
    # before scaling so natural-y-DOWN becomes font-y-UP.
    nat_h_attr = info["nat_h"]
    f_xmin = nat_xmin * scale
    f_ymin = (nat_h_attr - nat_ymax) * scale
    f_ymax = (nat_h_attr - nat_ymin) * scale
    layout_dx = TARGET_LSB - f_xmin
    layout_dy = TARGET_Y_CENTER - (f_ymin + f_ymax) / 2.0
    return {"scale": scale, "dx": layout_dx, "dy": layout_dy, "info": info}


def _path_to_font(path_xy, pipeline):
    """Map a path point to its position in the glyph's final font space
    (g transform → y-flip around nat_h_attr → scale → layout). Result is
    in FontForge's y-UP font convention."""
    nat = _path_to_natural(path_xy, pipeline["info"])
    nat_h_attr = pipeline["info"]["nat_h"]
    flipped_y = nat_h_attr - nat[1]
    return (nat[0] * pipeline["scale"] + pipeline["dx"],
            flipped_y * pipeline["scale"] + pipeline["dy"])


# ---------------------------------------------------------------------------
# Transforms applied to a part's sub-paths before matching
# ---------------------------------------------------------------------------

def _mirror_x(sub, axis_x):
    """Reflect a sub-path across the vertical line x = axis_x. Reverses
    the contour winding (so fill direction stays consistent)."""
    reflected = []
    for cmd, args in sub:
        new = []
        for k in range(0, len(args), 2):
            new.append(2 * axis_x - args[k])
            new.append(args[k + 1])
        reflected.append((cmd, new))
    # Reverse winding: walk segments back, swapping C control points so
    # the curve direction inverts.
    if not reflected:
        return reflected
    # Collect anchor points and segment commands
    pts = [(reflected[0][1][0], reflected[0][1][1])]  # M start
    segs = []
    for cmd, args in reflected[1:]:
        if cmd == 'L':
            pts.append((args[0], args[1]))
            segs.append(('L', [], (args[0], args[1])))
        elif cmd == 'C':
            pts.append((args[4], args[5]))
            segs.append(('C', [args[0], args[1], args[2], args[3]],
                         (args[4], args[5])))
    # Reverse: new start = last point; for each prior segment, emit reversed
    out = [('M', [pts[-1][0], pts[-1][1]])]
    for i in range(len(segs) - 1, -1, -1):
        kind, ctrl, _end = segs[i]
        new_end = pts[i]
        if kind == 'L':
            out.append(('L', [new_end[0], new_end[1]]))
        elif kind == 'C':
            # Reversed cubic: swap control points and flip endpoints
            out.append(('C', [ctrl[2], ctrl[3], ctrl[0], ctrl[1],
                              new_end[0], new_end[1]]))
    return out


def apply_transform(sub_paths, transform: str | None):
    """Apply a declared transform to all sub-paths of a part. Currently
    supports None (identity) and "M" (horizontal mirror across the
    combined bbox centre)."""
    if transform is None:
        return sub_paths
    if transform == "M":
        # Combined bbox of all sub-paths (the "part as a whole")
        xs = []
        for sub in sub_paths:
            for cmd, args in sub:
                for k in range(0, len(args), 2):
                    xs.append(args[k])
        axis = (min(xs) + max(xs)) / 2
        return [_mirror_x(s, axis) for s in sub_paths]
    raise ValueError(f"unsupported transform {transform!r}")


# ---------------------------------------------------------------------------
# Rule expansion + composition resolution
# ---------------------------------------------------------------------------

def _glyph_info(svg_dir: Path, symkey: str, cache: dict | None = None) -> dict | None:
    """Return everything needed to map this glyph's path coords to its
    final font position: SVG metadata + parsed sub-paths + import pipeline.
    Cached because the same glyph (e.g. S2ff00) is referenced by many
    compositions.
    """
    if cache is not None and symkey in cache:
        return cache[symkey]
    p = svg_dir / f"{symkey}.svg"
    if not p.exists():
        return None
    info = _read_svg_info(p)
    if info is None:
        if cache is not None:
            cache[symkey] = None
        return None
    info["symkey"] = symkey
    info["subs"] = parse_subpaths(info["d"])
    info["pipeline"] = _glyph_font_pipeline(info, info["subs"])
    if cache is not None:
        cache[symkey] = info
    return info


def _expand(template: str, base: str) -> str:
    """Substitute {b} (the base prefix) in a template; templates without
    {b} are absolute symkeys and pass through."""
    return template.replace("{b}", base)


def _font_translate(part_info, parent_info, part_subs_for_anchor,
                    off_path_x, off_path_y) -> tuple[float, float]:
    """Translate that maps the part's standalone outline into the parent.

    Anchor: the bbox-min of `part_subs_for_anchor[0]` (typically the
    transform-applied sub-paths, so mirror-applied parts use the
    mirrored anchor). That point sits at font position F_part in the
    standalone glyph and at F_parent inside the target — the composite
    translate is F_parent − F_part.
    """
    first_bb = subpath_bbox(part_subs_for_anchor[0])
    f_part = _path_to_font((first_bb[0], first_bb[1]), part_info["pipeline"])
    f_parent = _path_to_font(
        (first_bb[0] + off_path_x, first_bb[1] + off_path_y),
        parent_info["pipeline"],
    )
    return f_parent[0] - f_part[0], f_parent[1] - f_part[1]


def _font_bbox_of_subs(subs, pipeline):
    xs, ys = [], []
    for sub in subs:
        for cmd, args in sub:
            for k in range(0, len(args), 2):
                fx, fy = _path_to_font((args[k], args[k + 1]), pipeline)
                xs.append(fx)
                ys.append(fy)
    return min(xs), min(ys), max(xs), max(ys)


def _composed_font_bbox(symkey, glyph_cache, compositions):
    """Font-space bbox of `symkey` assuming any composition rule already
    resolved for it has been applied. If `symkey` has a composition entry
    in `compositions`, compute the union of each part's standalone font
    bbox shifted by the part's `offset_font` (matching how build_font
    will render the final composite). Otherwise fall back to the
    standalone glyph's natural font bbox.

    This matters for `center: "x"`: when the part is itself a composite
    of an exact mirror pair (e.g. S31a30 = S31a40 + M(S31a40)), the
    composed bbox is perfectly symmetric while the source-SVG bbox of
    the part can drift a few path units due to hand-drawn asymmetry."""
    entry = compositions.get(symkey)
    info = glyph_cache.get(symkey)
    if info is None:
        return None
    if entry is None:
        return _font_bbox_of_subs(info["subs"], info["pipeline"])
    xs_min, ys_min, xs_max, ys_max = [], [], [], []
    for p in entry["parts"]:
        sub_info = glyph_cache.get(p["ref"])
        if sub_info is None:
            return _font_bbox_of_subs(info["subs"], info["pipeline"])
        sub_subs = apply_transform(sub_info["subs"], p.get("transform"))
        bb = _font_bbox_of_subs(sub_subs, sub_info["pipeline"])
        tx, ty = p["offset_font"]
        xs_min.append(bb[0] + tx)
        xs_max.append(bb[2] + tx)
        ys_min.append(bb[1] + ty)
        ys_max.append(bb[3] + ty)
    return min(xs_min), min(ys_min), max(xs_max), max(ys_max)


def _center_axis_font(parent_info, part_info, axis: str,
                      compositions=None, glyph_cache=None) -> float:
    """Font-space translation along `axis` such that the part's bbox is
    centred on the parent's bbox in font coordinates. Uses the part's
    *composed* font bbox when a prior composition rule already resolved
    it (so symmetric pair-composites stay truly centred); otherwise
    falls back to the part's standalone bbox."""
    parent_bb = _font_bbox_of_subs(parent_info["subs"], parent_info["pipeline"])
    if compositions is not None and glyph_cache is not None:
        part_bb = _composed_font_bbox(part_info["symkey"], glyph_cache,
                                       compositions)
    else:
        part_bb = _font_bbox_of_subs(part_info["subs"], part_info["pipeline"])
    if part_bb is None:
        part_bb = _font_bbox_of_subs(part_info["subs"], part_info["pipeline"])
    if axis == "x":
        return (parent_bb[0] + parent_bb[2]) / 2 - (part_bb[0] + part_bb[2]) / 2
    if axis == "y":
        return (parent_bb[1] + parent_bb[3]) / 2 - (part_bb[1] + part_bb[3]) / 2
    raise ValueError(f"unknown center axis {axis!r}")


def _resolve_position_from(chain, base, compositions):
    """Sum the part offsets across a `position_from` chain. Each chain
    entry is either:
      - `[target, ref]` — find the first part with this ref, or
      - `[target, ref, transform]` — disambiguate when the same ref
        appears multiple times under different transforms (e.g. eye
        families where both the base and its mirror reference the same
        `{b}40`).
    """
    off_x = off_y = 0.0
    for link in chain:
        if len(link) == 2:
            target_t, part_t = link
            transform_filter = ...  # sentinel: match any transform
        elif len(link) == 3:
            target_t, part_t, transform_filter = link
        else:
            raise ValueError(f"position_from link must be length 2 or 3: {link!r}")
        target = _expand(target_t, base)
        part = _expand(part_t, base)
        entry = compositions.get(target)
        if entry is None:
            raise KeyError(f"target {target} not yet resolved")
        for p in entry["parts"]:
            if p["ref"] != part:
                continue
            if transform_filter is not ... and p.get("transform") != transform_filter:
                continue
            off_x += p["offset_font"][0]
            off_y += p["offset_font"][1]
            break
        else:
            raise KeyError(
                f"part {part} (transform={transform_filter}) not found in {target}"
            )
    return off_x, off_y


# Sub-paths in different SignWriting source SVGs are sometimes hand-redrawn
# with quite different proportions and positions (~5-30% size drift, ~50-200
# path-unit position drift, against a typical ~3000-wide glyph). Tolerances
# are generous to absorb that authoring jitter — the composite glyph will
# render at the "best single placement" of the part within the target, not
# pixel-faithful to the target's original outline.
_BBOX_SIZE_REL_TOL = 0.35  # 35% relative size tolerance
_OFFSET_ABS_TOL    = 300   # path units


def _match_part_in_target(part_subs, target_subs):
    """Find an assignment of every sub-path in `part_subs` to a distinct
    target sub-path such that:
      - the matched bbox sizes agree within `_BBOX_SIZE_REL_TOL`, and
      - all assignments share one common (xmin → xmin) translation
        within `_OFFSET_ABS_TOL`.

    Returns (offset_x, offset_y, [target_index_per_part_subpath]) or None.

    Why bbox instead of exact canonical: SignWriting source SVGs are
    hand-drawn — the same visual eyebrow is sometimes traced with cubic
    Beziers in one symbol and straight-line segments in another, so
    canonical-equality misses cases that are visually identical.
    """
    part_boxes = [subpath_bbox(s) for s in part_subs]
    target_boxes = [subpath_bbox(s) for s in target_subs]

    def _size_match(pi, ti):
        pw = part_boxes[pi][2] - part_boxes[pi][0]
        ph = part_boxes[pi][3] - part_boxes[pi][1]
        tw = target_boxes[ti][2] - target_boxes[ti][0]
        th = target_boxes[ti][3] - target_boxes[ti][1]
        if max(pw, 1) and abs(tw - pw) > _BBOX_SIZE_REL_TOL * max(pw, 1):
            return False
        if max(ph, 1) and abs(th - ph) > _BBOX_SIZE_REL_TOL * max(ph, 1):
            return False
        return True

    def _consistent_offset(pi, ti, offset):
        ox = target_boxes[ti][0] - part_boxes[pi][0]
        oy = target_boxes[ti][1] - part_boxes[pi][1]
        if offset is None:
            return (ox, oy)
        if (abs(ox - offset[0]) <= _OFFSET_ABS_TOL and
                abs(oy - offset[1]) <= _OFFSET_ABS_TOL):
            return offset
        return None

    n = len(part_subs)
    # Try target sub-paths in DESCENDING X order. Many SignWriting
    # source families draw the "base" (non-mirrored) variant on the
    # left half of the side-by-side composite (S30d, S30e, …), even
    # though others (S30a, S30b, …) draw it on the right. Without this
    # bias the matcher picks the first valid assignment — which is the
    # leftmost candidate — and the rule treats the base as the LEFT
    # eyebrow, swapping it with its mirror across the family. Iterating
    # right-to-left makes the matcher consistently pick the RIGHTMOST
    # valid placement for the base part, matching the rule's intent.
    target_order = sorted(
        range(len(target_subs)),
        key=lambda ti: -target_boxes[ti][0],
    )

    def search(idx, used, offset):
        if idx == n:
            return [used[i] for i in range(n)]
        for ti in target_order:
            if ti in used.values():
                continue
            if not _size_match(idx, ti):
                continue
            new_offset = _consistent_offset(idx, ti, offset)
            if new_offset is None:
                continue
            used[idx] = ti
            result = search(idx + 1, used, new_offset)
            if result is not None:
                return result
            del used[idx]
        return None

    assignments = search(0, {}, None)
    if assignments is None:
        return None
    off_x = target_boxes[assignments[0]][0] - part_boxes[0][0]
    off_y = target_boxes[assignments[0]][1] - part_boxes[0][1]
    return off_x, off_y, assignments


def _expand_rotation_dedup(rules_doc: dict, svg_dir: Path) -> list[dict]:
    """Expand "rotation_dedup" entries — each (fill, rot) with rot >=
    rot_offset becomes a 1-part composite ref to the (fill, rot -
    rot_offset) variant of the same base. SignWriting source has many
    face-direction symbols where the upper-half rotations exactly
    duplicate the lower-half."""
    entries = rules_doc.get("rotation_dedup", [])
    if not entries:
        return []
    synth_rule = {
        "name": "rotation-dedup",
        "comment": "Auto-generated identity duplicates: rot R+N = rot R "
                   "for some base prefix.",
        "bases": [""],
        "compositions": [],
    }
    for spec in entries:
        target_base = spec["target_base"]
        rot_offset = spec["rot_offset"]
        for tp in sorted(svg_dir.glob(f"{target_base}*.svg")):
            if len(tp.stem) != len(target_base) + 2:
                continue
            fill = tp.stem[-2]
            rot_hex = tp.stem[-1]
            rot = int(rot_hex, 16)
            if rot < rot_offset:
                continue
            source_rot = rot - rot_offset
            source = f"{target_base}{fill}{source_rot:x}"
            if not (svg_dir / f"{source}.svg").exists():
                continue
            synth_rule["compositions"].append({
                "target": tp.stem,
                "parts": [{"ref": source}],
            })
    return [synth_rule] if synth_rule["compositions"] else []


def _expand_multiples(rules_doc: dict, svg_dir: Path,
                      glyph_cache: dict) -> list[dict]:
    """Expand "multiples" entries — each variant of `target_base` becomes
    N copies of the fixed `single` glyph, with N auto-detected from the
    ratio of target / single sub-path counts.

    Older schema (`single_base` + `copies`) is still accepted: it matches
    same-suffix singles and uses an explicit copy count.
    """
    entries = rules_doc.get("multiples", [])
    if not entries:
        return []
    synth_rule = {
        "name": "multiples-auto",
        "comment": "Auto-generated: target = N copies of a single base. "
                   "N is target_sub_paths / single_sub_paths. The matcher "
                   "finds each copy's offset by claiming target sub-paths.",
        "bases": [""],
        "compositions": [],
    }
    for spec in entries:
        target_base = spec["target_base"]
        suffix_len = spec.get("suffix_len", 2)
        # Mixed schema: `mix` is a list of {single, copies}. Each variant
        # of target_base becomes the concatenation of `copies` copies of
        # each single. The matcher claims sub-paths in order.
        mix = spec.get("mix")
        if mix is not None:
            for tp in sorted(svg_dir.glob(f"{target_base}*.svg")):
                if len(tp.stem) != len(target_base) + suffix_len:
                    continue
                parts: list = []
                for m in mix:
                    parts.extend([{"ref": m["single"]}] * m["copies"])
                synth_rule["compositions"].append({
                    "target": tp.stem,
                    "parts": parts,
                })
            continue
        # New schema: `single` is the full standalone symkey (S20500),
        # auto-detect N per target variant.
        single = spec.get("single")
        if single is not None:
            single_info = _glyph_info(svg_dir, single, glyph_cache)
            if single_info is None:
                continue
            single_n_subs = len(single_info["subs"])
            for tp in sorted(svg_dir.glob(f"{target_base}*.svg")):
                if len(tp.stem) != len(target_base) + 2:
                    continue
                tgt_info = _glyph_info(svg_dir, tp.stem, glyph_cache)
                if tgt_info is None:
                    continue
                n = round(len(tgt_info["subs"]) / max(1, single_n_subs))
                if n < 1:
                    continue
                synth_rule["compositions"].append({
                    "target": tp.stem,
                    "parts": [{"ref": single}] * n,
                })
            continue
        # Legacy schema: `single_base` + explicit `copies`. Matches on
        # same-suffix singles.
        single_base = spec["single_base"]
        copies = spec["copies"]
        targets = {p.stem[len(target_base):]
                   for p in svg_dir.glob(f"{target_base}*.svg")
                   if len(p.stem) == len(target_base) + 2}
        singles = {p.stem[len(single_base):]
                   for p in svg_dir.glob(f"{single_base}*.svg")
                   if len(p.stem) == len(single_base) + 2}
        for suffix in sorted(targets & singles):
            synth_rule["compositions"].append({
                "target": target_base + suffix,
                "parts": [{"ref": single_base + suffix}] * copies,
            })
    return [synth_rule] if synth_rule["compositions"] else []


def resolve_rules(svg_dir: Path, rules_path: Path) -> dict:
    """Expand the rules file into a flat compositions dict.

    Output schema (offsets are font-unit translations applied to the
    part's standalone outline to place it inside the target):
      {
        symkey: {
          "rule": "<rule name>",
          "parts": [
            {"ref": "S2ff00", "transform": None, "offset_font": [tx, ty]},
            {"ref": "S30a40", "transform": "M",  "offset_font": [tx, ty]},
            ...
          ]
        },
        ...
      }
    """
    rules_doc = json.loads(rules_path.read_text())
    out: dict = {}
    n_skipped = 0
    glyph_cache: dict = {}
    # Expand any `multiples` shorthand into a synthetic rule first so its
    # compositions go through the normal matcher + offset pipeline.
    all_rules = (
        _expand_multiples(rules_doc, svg_dir, glyph_cache)
        + _expand_rotation_dedup(rules_doc, svg_dir)
        + rules_doc.get("rules", [])
    )
    for rule in all_rules:
        name = rule["name"]
        bases = rule["bases"]
        for base in bases:
            for comp in rule["compositions"]:
                target = _expand(comp["target"], base)
                target_info = _glyph_info(svg_dir, target, glyph_cache)
                if target_info is None:
                    print(f"  ! {target}: no source SVG; skipping",
                          file=sys.stderr)
                    n_skipped += 1
                    continue
                target_subs = target_info["subs"]
                resolved_parts = []
                claimed: set[int] = set()
                fail = None
                for part in comp["parts"]:
                    ref = _expand(part["ref"], base)
                    transform = part.get("transform")
                    part_info = _glyph_info(svg_dir, ref, glyph_cache)
                    if part_info is None:
                        fail = f"missing part SVG {ref}"
                        break
                    part_subs_for_match = apply_transform(
                        part_info["subs"], transform
                    )
                    unclaimed_subs = [s for i, s in enumerate(target_subs)
                                      if i not in claimed]
                    unclaimed_map = [i for i in range(len(target_subs))
                                     if i not in claimed]
                    match = _match_part_in_target(part_subs_for_match,
                                                   unclaimed_subs)
                    if match is None:
                        fail = (f"part {ref}{' (M)' if transform else ''} "
                                f"did not match in target")
                        break
                    off_path_x, off_path_y, local_assignments = match
                    for local_idx in local_assignments:
                        claimed.add(unclaimed_map[local_idx])
                    # Convert the path-coord match into a font-space
                    # translate by simulating both glyphs' import
                    # pipelines (per-glyph SVG g transforms differ ~1%
                    # so uniform pc_to_font is not accurate).
                    tx, ty = _font_translate(
                        part_info, target_info, part_subs_for_match,
                        off_path_x, off_path_y,
                    )
                    resolved_parts.append({
                        "ref":         ref,
                        "transform":   transform,
                        "offset_font": [round(tx, 2), round(ty, 2)],
                    })
                if fail is not None:
                    print(f"  ! {target}: {fail}", file=sys.stderr)
                    n_skipped += 1
                    continue
                if len(claimed) != len(target_subs):
                    print(f"  ! {target}: {len(target_subs) - len(claimed)} "
                          f"unclaimed sub-paths; skipping", file=sys.stderr)
                    n_skipped += 1
                    continue
                # `center: "x"|"y"|"xy"` — override the auto-derived
                # offset with a geometric centring of the part on the
                # target in FONT space (consistent with build-time
                # bboxes).
                for spec, resolved in zip(comp["parts"], resolved_parts):
                    axes = spec.get("center")
                    if not axes:
                        continue
                    part_info = glyph_cache[resolved["ref"]]
                    tx, ty = resolved["offset_font"]
                    if "x" in axes:
                        tx = _center_axis_font(target_info, part_info, "x",
                                                compositions=out,
                                                glyph_cache=glyph_cache)
                    if "y" in axes:
                        ty = _center_axis_font(target_info, part_info, "y",
                                                compositions=out,
                                                glyph_cache=glyph_cache)
                    resolved["offset_font"] = [round(tx, 2), round(ty, 2)]
                # `position_from` — replace the auto-derived offset
                # with a chain of summed translates from earlier-
                # resolved compositions. Keeps a sub-symbol's location
                # identical across every parent that references it.
                for spec, resolved in zip(comp["parts"], resolved_parts):
                    chain = spec.get("position_from")
                    if not chain:
                        continue
                    try:
                        new_off = _resolve_position_from(chain, base, out)
                    except KeyError as exc:
                        print(f"  ! {target}: position_from override "
                              f"failed for {resolved['ref']}: {exc}",
                              file=sys.stderr)
                        continue
                    resolved["offset_font"] = [
                        round(new_off[0], 2), round(new_off[1], 2)
                    ]
                out[target] = {"rule": name, "parts": resolved_parts}
    if n_skipped:
        print(f"  (skipped {n_skipped} compositions due to failures)",
              file=sys.stderr)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--svg-dir", type=Path, required=True)
    p.add_argument("--rules",   type=Path, required=True)
    p.add_argument("--output",  type=Path, required=True)
    args = p.parse_args()

    compositions = resolve_rules(args.svg_dir, args.rules)
    args.output.write_text(json.dumps(compositions, indent=2, sort_keys=True))
    print(f"Wrote {len(compositions)} compositions to {args.output}")


if __name__ == "__main__":
    main()

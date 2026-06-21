"""Emit rotation/reflection composites by formula.

Two families share the same `duplicates.json` schema:

1. Hand symbols (S100..S204) follow a D4 pattern indexed by the rot
   digit: even rotations derive from rot 0, odd from rot 1, with
   transforms cycling through {R90, R180, R270, M, MR270, MR180, MR90}.
   Rot 0 and rot 1 are stored as separate outline bases — the rot-1
   "diagonal" variant is drawn independently by the SignWriting authors
   (not a clean rotation of rot 0).

2. C8 (8-fold pure-rotation) families like S37f have 8 rotation
   variants per fill, where rot i is a 45°·i rotation of rot 0.

Non-hand, non-C8 symbols are deduped via the sub-path primitive
detector (see primitives.py) instead — earlier search-based D4 dedup
across other families was unreliable.

Usage:
    python -m signwriting_fonts.font_1d.tune_dedup \\
        --svg-dir fonts/1d/svg \\
        --output  signwriting_fonts/font_1d/duplicates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from signwriting_fonts.font_1d._symkey import HAND_BASE_MAX

HAND_BASE_MIN = 0x100

# Indexed by rot digit (0..15). None means "this rotation is itself a base".
_HAND_TRANSFORMS: list[str | None] = [
    None,    None,    "R90",   "R90",
    "R180",  "R180",  "R270",  "R270",
    "M",     "M",     "MR270", "MR270",
    "MR180", "MR180", "MR90",  "MR90",
]

# C8 (8-fold pure-rotation) symbol families. Each family has 8 rotations
# per fill, rot 0 is the base and rot i is a 45°·i rotation of rot 0.
# The (base, fills) tuple lists which fill digits are members of the family.
_C8_FAMILIES: list[tuple[str, tuple[int, ...]]] = [
    ("S37f", (0, 1, 2, 3)),
    ("S380", (0, 1, 2, 3)),
]

_C8_TRANSFORMS: list[str | None] = [
    None, "R45", "R90", "R135", "R180", "R225", "R270", "R315",
]


def build_hand_composites(svg_dir: Path) -> dict:
    """Return a duplicates.json-shaped dict mapping every non-base hand
    sibling that has a font-db SVG to (base, transform). Bases (rot 0 and
    rot 1) are not included since they're stored as outlines.
    """
    svgs = {p.stem for p in svg_dir.glob("S*.svg")}
    entries: dict = {}

    for base_hex in range(HAND_BASE_MIN, HAND_BASE_MAX):
        for fill in range(16):
            for rot in range(16):
                transform = _HAND_TRANSFORMS[rot]
                if transform is None:
                    continue
                sib = f"S{base_hex:03x}{fill:x}{rot:x}"
                if sib not in svgs:
                    continue
                base_rot = rot & 1  # even→0, odd→1
                base = f"S{base_hex:03x}{fill:x}{base_rot:x}"
                if base not in svgs:
                    continue
                entries[sib] = {
                    "duplicate_of": base,
                    "transform": transform,
                    "source": "hand-formula",
                }
    return entries


# D4 rotation families that aren't hand glyphs, indexed by the rot digit via
# `_HAND_TRANSFORMS`: rot 2/3 = R90, 4/5 = R180, 6/7 = R270 of rot 0 (even) /
# rot 1 (odd); with 16 rotations the upper half 8..f adds the mirror set
# (M, MR270, MR180, MR90). Each entry is (base, fills, n_rots) — the member
# fill digits and how many rotations that family has (8 = no mirror half, 16 =
# full). Only the single-marker fills are listed; the "double" and "head+…"
# fills are built by composition rules (rules.json), and other fills (e.g. the
# arrow fills 0/1) are kept as their own hand-drawn outlines.
# Only families whose rotations are genuinely rigid R90/R180/R270 (and, for
# 16-rotation families, mirror) transforms of rot 0/1 — verified against the
# hand-drawn source. S323, S326, S328, S329 are excluded: their rotations are
# drawn independently (the transform reproduces the source at only ~0.1-0.5
# IOU), so they keep their own outlines.
_ROTATION_FAMILIES: list[tuple[str, tuple[int, ...], int]] = [
    ("S321", (2, 3), 8),
    ("S322", (2, 3), 8),
    ("S324", (2, 3), 8),
    ("S325", (2, 3), 8),
    ("S327", (2,), 16),
]


def build_rotation_composites(svg_dir: Path) -> dict:
    """Return duplicates.json entries for the D4 rotation families. For each
    listed (base, fill), rot 2..n_rots-1 is the `_HAND_TRANSFORMS[rot]`
    rotation/reflection of rot 0 (even rots) or rot 1 (odd rots)."""
    svgs = {p.stem for p in svg_dir.glob("S*.svg")}
    entries: dict = {}
    for base, fills, n_rots in _ROTATION_FAMILIES:
        for fill in fills:
            for rot in range(n_rots):
                transform = _HAND_TRANSFORMS[rot]
                if transform is None:
                    continue
                sib = f"{base}{fill:x}{rot:x}"
                if sib not in svgs:
                    continue
                base_sym = f"{base}{fill:x}{rot & 1:x}"
                if base_sym not in svgs:
                    continue
                entries[sib] = {
                    "duplicate_of": base_sym,
                    "transform": transform,
                    "source": "rotation-formula",
                }
    return entries


def build_c8_composites(svg_dir: Path) -> dict:
    """Return duplicates.json entries for C8 (8-fold rotation) families.
    For each (base, fill) pair, rot 1..7 are 45°·i rotations of rot 0.
    """
    svgs = {p.stem for p in svg_dir.glob("S*.svg")}
    entries: dict = {}
    for base, fills in _C8_FAMILIES:
        for fill in fills:
            base_sym = f"{base}{fill:x}0"
            if base_sym not in svgs:
                continue
            for rot, transform in enumerate(_C8_TRANSFORMS):
                if transform is None:
                    continue
                sib = f"{base}{fill:x}{rot:x}"
                if sib not in svgs:
                    continue
                entries[sib] = {
                    "duplicate_of": base_sym,
                    "transform": transform,
                    "source": "c8-formula",
                }
    return entries


def _outline_d(path: Path) -> str | None:
    m = re.search(r'd="([^"]+)"', path.read_text())
    return m.group(1) if m else None


def build_exact_copy_composites(svg_dir: Path, exclude: set[str]) -> dict:
    """Byte-identical-outline dedup. Group every symbol that doesn't already
    have a rule (`exclude` = the formula duplicates above + the rule
    compositions) by its raw `d` attribute; within each group of >1, every
    member except the lowest-index one becomes an identity ("I") copy of that
    lowest member. These are exact copies, so the copy is certain."""
    groups: dict[str, list[str]] = defaultdict(list)
    for p in sorted(svg_dir.glob("S*.svg")):
        if p.stem in exclude:
            continue
        d = _outline_d(p)
        if d is None:
            continue
        groups[hashlib.md5(d.encode()).hexdigest()].append(p.stem)
    entries: dict = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort()
        rep = members[0]
        for sib in members[1:]:
            entries[sib] = {
                "duplicate_of": rep,
                "transform": "I",
                "source": "exact-copy",
            }
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compositions", type=Path, default=None,
                        help="compositions.json — its targets are excluded "
                             "from exact-copy dedup (they already have a rule)")
    args = parser.parse_args()

    hand = build_hand_composites(args.svg_dir)
    c8 = build_c8_composites(args.svg_dir)
    rot = build_rotation_composites(args.svg_dir)
    exclude = set(hand) | set(c8) | set(rot)
    if args.compositions and args.compositions.exists():
        comp = json.loads(args.compositions.read_text())
        exclude |= {k for k in comp if not k.startswith("_")}
    exact = build_exact_copy_composites(args.svg_dir, exclude)
    entries = {**hand, **c8, **rot, **exact}
    out = {
        "_meta": {
            "source": str(args.svg_dir),
            "method": "hand + c8 + rotation + exact-copy",
            "hand_base_range": [f"S{HAND_BASE_MIN:03x}", f"S{HAND_BASE_MAX:03x}"],
            "c8_families": [base for base, _ in _C8_FAMILIES],
            "rotation_families": [base for base, _, _ in _ROTATION_FAMILIES],
            "count": len(entries),
            "hand_count": len(hand),
            "c8_count": len(c8),
            "rotation_count": len(rot),
            "exact_copy_count": len(exact),
        },
        **entries,
    }
    args.output.write_text(json.dumps(out, indent=2))
    print(
        f"Wrote {args.output}: {len(hand):,} hand + {len(c8):,} c8 + "
        f"{len(rot):,} rotation + {len(exact):,} exact-copy "
        f"= {len(entries):,} composites"
    )


if __name__ == "__main__":
    main()

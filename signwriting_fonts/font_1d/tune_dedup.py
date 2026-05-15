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
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    hand = build_hand_composites(args.svg_dir)
    c8 = build_c8_composites(args.svg_dir)
    entries = {**hand, **c8}
    out = {
        "_meta": {
            "source": str(args.svg_dir),
            "method": "hand-formula + c8-formula",
            "hand_base_range": [f"S{HAND_BASE_MIN:03x}", f"S{HAND_BASE_MAX:03x}"],
            "c8_families": [base for base, _ in _C8_FAMILIES],
            "count": len(entries),
            "hand_count": len(hand),
            "c8_count": len(c8),
        },
        **entries,
    }
    args.output.write_text(json.dumps(out, indent=2))
    print(
        f"Wrote {args.output}: "
        f"{len(hand):,} hand + {len(c8):,} c8 = {len(entries):,} composites"
    )


if __name__ == "__main__":
    main()

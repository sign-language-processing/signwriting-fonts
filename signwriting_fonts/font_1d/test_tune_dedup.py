"""Unit tests for the rotation-formula expander.

`tune_dedup` walks a directory of `<symkey>.svg` files and emits
duplicate entries for hand glyphs (D4 pattern) and C8 rotation families.
We don't need real SVG content — the script keys on filenames only —
so each test prepares the SVG directory with `touch` semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from signwriting_fonts.font_1d.tune_dedup import (
    _C8_TRANSFORMS,
    _HAND_TRANSFORMS,
    build_c8_composites,
    build_hand_composites,
)


@pytest.fixture
def svg_dir(tmp_path: Path) -> Path:
    return tmp_path


def _touch(svg_dir: Path, *symkeys: str) -> None:
    for sk in symkeys:
        (svg_dir / f"{sk}.svg").write_text("<svg/>")


# ---------------------------------------------------------------------------
# Hand D4 pattern
# ---------------------------------------------------------------------------

def test_hand_rot0_and_rot1_are_bases_not_emitted(svg_dir):
    _touch(svg_dir, "S10000", "S10001", "S10002")
    entries = build_hand_composites(svg_dir)
    assert "S10000" not in entries
    assert "S10001" not in entries
    assert "S10002" in entries  # rot 2 derives from rot 0


def test_hand_even_rotations_derive_from_rot0(svg_dir):
    _touch(svg_dir, "S10000",
           "S10002", "S10004", "S10006", "S10008",
           "S1000a", "S1000c", "S1000e")
    entries = build_hand_composites(svg_dir)
    for rot in (2, 4, 6, 8, 0xa, 0xc, 0xe):
        sib = f"S1000{rot:x}"
        assert entries[sib]["duplicate_of"] == "S10000"
        assert entries[sib]["transform"] == _HAND_TRANSFORMS[rot]
        assert entries[sib]["source"] == "hand-formula"


def test_hand_odd_rotations_derive_from_rot1(svg_dir):
    _touch(svg_dir, "S10001",
           "S10003", "S10005", "S10007", "S10009",
           "S1000b", "S1000d", "S1000f")
    entries = build_hand_composites(svg_dir)
    for rot in (3, 5, 7, 9, 0xb, 0xd, 0xf):
        sib = f"S1000{rot:x}"
        assert entries[sib]["duplicate_of"] == "S10001"
        assert entries[sib]["transform"] == _HAND_TRANSFORMS[rot]


def test_hand_skips_when_base_missing(svg_dir):
    """If rot 0 isn't on disk, the even-rot siblings can't be deduped
    (no outline to reference)."""
    _touch(svg_dir, "S10002")     # rot 0 (S10000) is missing
    entries = build_hand_composites(svg_dir)
    assert entries == {}


def test_hand_skips_outside_hand_base_range(svg_dir):
    """Bases ≥ S205 aren't hand glyphs and must not get D4 entries."""
    _touch(svg_dir, "S20500", "S20502")
    entries = build_hand_composites(svg_dir)
    assert entries == {}


# ---------------------------------------------------------------------------
# C8 (8-fold pure rotation) families
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("base", ["S37f", "S380"])
def test_c8_emits_seven_rotations_per_fill(svg_dir, base):
    for fill in range(4):
        for rot in range(8):
            _touch(svg_dir, f"{base}{fill:x}{rot:x}")
    entries = build_c8_composites(svg_dir)
    for fill in range(4):
        base_sym = f"{base}{fill:x}0"
        assert base_sym not in entries  # rot 0 is the outline base
        for rot in range(1, 8):
            sib = f"{base}{fill:x}{rot:x}"
            assert entries[sib]["duplicate_of"] == base_sym
            assert entries[sib]["transform"] == _C8_TRANSFORMS[rot]
            assert entries[sib]["source"] == "c8-formula"


def test_c8_skips_unknown_family(svg_dir):
    """A family that isn't S37f/S380 doesn't get emitted even if all
    its rot variants exist on disk."""
    for rot in range(8):
        _touch(svg_dir, f"S30000{rot:x}")
    assert build_c8_composites(svg_dir) == {}


def test_c8_skips_fill_when_rot0_missing(svg_dir):
    """For S37f fill 2: if rot 0 is absent, none of rot 1..7 get emitted
    (no base to reference)."""
    for rot in range(1, 8):
        _touch(svg_dir, f"S37f2{rot:x}")   # rot 0 missing
    entries = build_c8_composites(svg_dir)
    # Other fills with rot 0 absent are also skipped — nothing emitted.
    assert all(not k.startswith("S37f2") for k in entries)

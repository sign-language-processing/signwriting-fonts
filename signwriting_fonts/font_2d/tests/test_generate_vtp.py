import shutil
import subprocess
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from signwriting_fonts.font_2d.generate_vtp import (
    ORIGIN,
    SYMBOL_PARTITIONS,
    build_axis_gpos,
    parse_coords,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
BUILT_FONT = REPO_ROOT / "fonts" / "SuttonSignWritingTwoD.ttf"

# Codepoints for the integration-test clusters.
SWM_CODEPOINT = 0x1D803
S10000_CODEPOINT = 0x40001
SW_CODEPOINT_BASE = 0x1D8F4 - 482  # SW482 = U+1D8F4; SW{n} = SW_CODEPOINT_BASE + n.


def _fake_glyph_order():
    """A minimal glyph order that matches the partition + marker ranges.

    Just one glyph per partition boundary plus the SW250-SW749 marker
    range. The compiler only cares about the glyph names existing in
    order; coverage tables are built from sliced ranges.
    """
    order = [".notdef", ".null", "nonmarkingreturn"]
    for start, end in SYMBOL_PARTITIONS:
        order.extend([start, end])
    order.extend([f"SW{i}" for i in range(250, 750)])
    return order


def _fake_font():
    font = TTFont()
    font.setGlyphOrder(_fake_glyph_order())
    return font


def test_parse_coords_ranges_and_singles():
    assert parse_coords("500") == [500]
    assert parse_coords("482,483,500") == [482, 483, 500]
    assert parse_coords("498-502") == [498, 499, 500, 501, 502]
    assert parse_coords("482, 500-502 , 510") == [482, 500, 501, 502, 510]


def test_parse_coords_dedup_and_sort():
    assert parse_coords("500,495-500,498") == [495, 496, 497, 498, 499, 500]


def test_parse_coords_rejects_out_of_range():
    with pytest.raises(ValueError, match=r"\[250, 749\]"):
        parse_coords("100,500")
    with pytest.raises(ValueError, match=r"\[250, 749\]"):
        parse_coords("750")  # ORIGIN is no-shift; rules for it are meaningless
    with pytest.raises(ValueError, match=r"\[250, 749\]"):
        parse_coords("245-260")


def test_build_axis_gpos_emits_expected_structure():
    font = _fake_font()
    coords = [482, 483]
    build_axis_gpos(font, coords)
    gpos = font["GPOS"].table

    # Script DFLT with one default langsys pointing at the mark feature.
    assert [sr.ScriptTag for sr in gpos.ScriptList.ScriptRecord] == ["DFLT"]
    langsys = gpos.ScriptList.ScriptRecord[0].Script.DefaultLangSys
    assert langsys.FeatureIndex == [0]

    # The mark feature references one outer lookup per (axis, coord, partition).
    feature = gpos.FeatureList.FeatureRecord[0]
    assert feature.FeatureTag == "mark"
    expected_outers = 2 * len(coords) * len(SYMBOL_PARTITIONS)
    assert feature.Feature.LookupCount == expected_outers

    # Total lookups = inner + outer for each combination, then wrapped in
    # an extension lookup each.
    assert len(gpos.LookupList.Lookup) == 2 * expected_outers
    for lk in gpos.LookupList.Lookup:
        assert lk.LookupType == 9  # GPOS Extension


def test_outer_lookup_invokes_inner_with_correct_shift():
    font = _fake_font()
    coord = 482
    build_axis_gpos(font, [coord])
    gpos = font["GPOS"].table

    # First outer in the feature list is the X-axis lookup for the first
    # partition: input=g1, lookahead=[SW482, any-marker], -> inner with
    # XPlacement = coord - ORIGIN.
    first_outer_idx = gpos.FeatureList.FeatureRecord[0].Feature.LookupListIndex[0]
    outer_ext = gpos.LookupList.Lookup[first_outer_idx].SubTable[0]
    assert outer_ext.ExtensionLookupType == 8
    chain = outer_ext.ExtSubTable
    assert chain.LookAheadCoverage[0].glyphs == [f"SW{coord}"]
    inner_idx = chain.PosLookupRecord[0].LookupListIndex
    inner_ext = gpos.LookupList.Lookup[inner_idx].SubTable[0]
    assert inner_ext.ExtensionLookupType == 1
    inner = inner_ext.ExtSubTable
    assert inner.Format == 2
    # Every value record carries the same XPlacement.
    expected_dx = coord - ORIGIN
    assert all(
        getattr(v, "XPlacement", 0) == expected_dx and getattr(v, "YPlacement", 0) == 0
        for v in inner.Value
    )


def test_y_axis_lookup_shifts_only_y():
    font = _fake_font()
    coord = 510
    build_axis_gpos(font, [coord])
    gpos = font["GPOS"].table
    # Y-axis outers come after the X-axis ones for this coord — pick the
    # one whose second lookahead matches SW{coord}.
    for outer_idx in gpos.FeatureList.FeatureRecord[0].Feature.LookupListIndex:
        chain = gpos.LookupList.Lookup[outer_idx].SubTable[0].ExtSubTable
        if chain.LookAheadCoverage[1].glyphs == [f"SW{coord}"]:
            inner_idx = chain.PosLookupRecord[0].LookupListIndex
            inner = gpos.LookupList.Lookup[inner_idx].SubTable[0].ExtSubTable
            expected_dy = ORIGIN - coord
            v0 = inner.Value[0]
            assert getattr(v0, "XPlacement", 0) == 0
            assert getattr(v0, "YPlacement", 0) == expected_dy
            return
    pytest.fail("no Y-axis outer found")


@pytest.mark.skipif(
    shutil.which("hb-shape") is None or not BUILT_FONT.exists(),
    reason="hb-shape or built 2D font missing; run `make fonts/SuttonSignWritingTwoD.ttf` first",
)
def test_built_font_positions_known_clusters():
    """End-to-end check: the shipped font shifts symbols by the expected
    additive (x-750, 750-y) for a few clusters in the default coord
    window. Skipped on CI where the built font isn't available.
    """
    cases = [
        ((482, 483), "@-268,267"),
        ((500, 500), "@-250,250"),
        ((506, 500), "@-244,250"),
        ((503, 520), "@-247,230"),
    ]
    for (x, y), expected in cases:
        codepoints = (SWM_CODEPOINT, S10000_CODEPOINT,
                      SW_CODEPOINT_BASE + x, SW_CODEPOINT_BASE + y)
        text = "".join(chr(c) for c in codepoints)
        result = subprocess.run(
            ["hb-shape", str(BUILT_FONT), text],
            capture_output=True,
            text=True,
            check=True,
        )
        assert expected in result.stdout, (
            f"cluster ({x},{y}) missing {expected}: {result.stdout.strip()}"
        )

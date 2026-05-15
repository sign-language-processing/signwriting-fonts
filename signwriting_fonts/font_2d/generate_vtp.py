"""Build the 2D SignWriting GPOS table directly via fontTools.

Replaces the older `generate_vtp.py` → `volt2ttf` round-trip with a
single Python step. The positioning is axis-decomposed: instead of one
lookup per (x, y) pair (500 × 500 = 250k pairs — multiplicative), we
emit one lookup per X coordinate and one per Y coordinate, which then
stack via standard GPOS accumulation. The total rule count is
2 × (coords) × 3 (partitions) — linear in the coord range, not
quadratic.
"""
import argparse

from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot


# SignWriting plane-4 layout encodes a positioned symbol as a 3-codepoint
# cluster: <symbol Sxxxxx> <x-position SW{x}> <y-position SW{y}>, with
# x, y in [250, 749]. SW750 is the origin (no offset). The mapping to
# font units is dx = x - 750, dy = 750 - y.
ORIGIN = 750

# Default coord window: 150 values centered on the M-box anchor. Covers
# every position used by typical SignWriting text — the few outliers
# fall back to no positioning rather than blowing the LookupList past
# what fontTools' offset-overflow recovery can pack.
DEFAULT_COORDS = "425-574"

# Glyph-name partitions of the full symbol set (S10000-S38b07). The
# range is split because a single context lookup whose input coverage
# exceeds ~32k glyphs is silently dropped by harfbuzz; each partition
# stays well under the limit while still covering every symbol.
SYMBOL_PARTITIONS = [
    ("S10000", "S1a045"),
    ("S1a046", "S2862c"),
    ("S2862d", "S38b07"),
]
MARKER_RANGE = ("SW250", "SW749")


def parse_coords(spec):
    out = set()
    for piece in spec.split(','):
        piece = piece.strip()
        if not piece:
            continue
        if '-' in piece:
            lo, hi = piece.split('-', 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(piece))
    return sorted(out)


def _range_glyphs(glyph_order, start, end):
    return glyph_order[glyph_order.index(start): glyph_order.index(end) + 1]


def _coverage(glyphs):
    cov = ot.Coverage()
    cov.glyphs = list(glyphs)
    return cov


def _single_pos_lookup(coverage, dx, dy):
    # SinglePos Format 2 (per-glyph ValueRecord) rather than Format 1 (one
    # shared value). With Format 1 inside a large chained-context lookup,
    # harfbuzz silently drops the GPOS — every value is identical here, so
    # Format 2 just costs more bytes for the same effect, but it actually
    # gets applied. The ValueRecord is shared across all glyph slots:
    # fontTools sees the same Python object and emits one record's worth
    # of bytes per slot rather than allocating millions of distinct
    # ValueRecord instances, which Python object-creation can't keep up
    # with at full scale.
    fmt = 0
    if dx:
        fmt |= 1
    if dy:
        fmt |= 2
    if not fmt:
        fmt = 1  # ValueFormat must be non-zero
    shared = ot.ValueRecord()
    if dx:
        shared.XPlacement = dx
    if dy:
        shared.YPlacement = dy

    st = ot.SinglePos()
    st.Format = 2
    st.Coverage = coverage
    st.ValueFormat = fmt
    st.Value = [shared] * len(coverage.glyphs)
    st.ValueCount = len(coverage.glyphs)

    lk = ot.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _chained_ctx_lookup(input_cov, lookahead_covs, inner_lookup_idx):
    st = ot.ChainContextPos()
    st.Format = 3
    st.BacktrackGlyphCount = 0
    st.BacktrackCoverage = []
    st.InputGlyphCount = 1
    st.InputCoverage = [input_cov]
    st.LookAheadGlyphCount = len(lookahead_covs)
    st.LookAheadCoverage = list(lookahead_covs)

    plr = ot.PosLookupRecord()
    plr.SequenceIndex = 0
    plr.LookupListIndex = inner_lookup_idx
    st.PosCount = 1
    st.PosLookupRecord = [plr]

    lk = ot.Lookup()
    lk.LookupType = 8
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _wrap_extension_pos(lookup):
    """Re-emit a GPOS lookup as a LookupType-9 extension wrapper.

    Extension subtables hold a 32-bit offset to the actual data, so the
    LookupList itself stays small (each lookup body is ~8 bytes) and we
    can fit thousands of lookups without the uint16 LookupList offsets
    overflowing.
    """
    ext_subtables = []
    for st in lookup.SubTable:
        ext = ot.ExtensionPos()
        ext.Format = 1
        ext.ExtensionLookupType = lookup.LookupType
        ext.ExtSubTable = st
        ext_subtables.append(ext)
    out = ot.Lookup()
    out.LookupType = 9
    out.LookupFlag = lookup.LookupFlag
    out.SubTable = ext_subtables
    out.SubTableCount = len(ext_subtables)
    return out


def _axis_lookups(partition_glyphs, marker_glyphs, coords):
    """Build the inner/outer lookup pairs for X and Y axes.

    Returns (lookups, outer_indices) where outer_indices identifies which
    entries in `lookups` are the chained-context outers that the feature
    should reference (inners are addressed only via PosLookupRecord).
    """
    lookups = []
    outer_indices = []
    for axis in ('x', 'y'):
        for coord in coords:
            for part in partition_glyphs:
                if axis == 'x':
                    dx, dy = coord - ORIGIN, 0
                    lookahead = [_coverage([f"SW{coord}"]), _coverage(marker_glyphs)]
                else:
                    dx, dy = 0, ORIGIN - coord
                    lookahead = [_coverage(marker_glyphs), _coverage([f"SW{coord}"])]

                inner_idx = len(lookups)
                lookups.append(_single_pos_lookup(_coverage(part), dx, dy))
                outer_indices.append(len(lookups))
                lookups.append(_chained_ctx_lookup(_coverage(part), lookahead, inner_idx))
    return lookups, outer_indices


def _assemble_gpos(lookups, outer_indices, feature_tag="mark", script_tag="DFLT"):
    """Wire up Script→Feature→Lookup pointers into a complete GPOS table."""
    feature = ot.Feature()
    feature.FeatureParams = None
    feature.LookupCount = len(outer_indices)
    feature.LookupListIndex = outer_indices

    feature_record = ot.FeatureRecord()
    feature_record.FeatureTag = feature_tag
    feature_record.Feature = feature

    feature_list = ot.FeatureList()
    feature_list.FeatureCount = 1
    feature_list.FeatureRecord = [feature_record]

    langsys = ot.DefaultLangSys()
    langsys.LookupOrder = None
    langsys.ReqFeatureIndex = 0xFFFF
    langsys.FeatureCount = 1
    langsys.FeatureIndex = [0]

    script = ot.Script()
    script.DefaultLangSys = langsys
    script.LangSysRecord = []
    script.LangSysCount = 0

    script_record = ot.ScriptRecord()
    script_record.ScriptTag = script_tag
    script_record.Script = script

    script_list = ot.ScriptList()
    script_list.ScriptCount = 1
    script_list.ScriptRecord = [script_record]

    lookup_list = ot.LookupList()
    lookup_list.LookupCount = len(lookups)
    lookup_list.Lookup = lookups

    gpos = ot.GPOS()
    gpos.Version = 0x00010000
    gpos.ScriptList = script_list
    gpos.FeatureList = feature_list
    gpos.LookupList = lookup_list
    return gpos


def build_axis_gpos(font, coords):
    """Construct the GPOS table for axis-decomposed SignWriting positioning.

    Emits, for each coord and each glyph partition, one outer chained-context
    lookup matching <symbol> <SW{coord}> <any-marker> (X axis) or
    <symbol> <any-marker> <SW{coord}> (Y axis), invoking an inner SinglePos
    that shifts the symbol by (coord-750, 0) or (0, 750-coord). The X and Y
    lookups stack via standard GPOS accumulation, so a cluster carrying
    SW{x} SW{y} ends up shifted by (x-750, 750-y) without any per-(x,y)
    rule. Every lookup is then wrapped in a LookupType-9 extension so the
    LookupList stays addressable by uint16 offsets.
    """
    glyph_order = font.getGlyphOrder()
    partition_glyphs = [
        _range_glyphs(glyph_order, start, end) for start, end in SYMBOL_PARTITIONS
    ]
    marker_glyphs = _range_glyphs(glyph_order, *MARKER_RANGE)

    lookups, outer_indices = _axis_lookups(partition_glyphs, marker_glyphs, coords)
    lookups = [_wrap_extension_pos(lk) for lk in lookups]
    gpos = _assemble_gpos(lookups, outer_indices)

    gpos_table = newTable("GPOS")
    gpos_table.table = gpos
    font["GPOS"] = gpos_table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-ttf", required=True,
                        help="Path to base TTF (without GPOS)")
    parser.add_argument("--output-ttf", required=True,
                        help="Path to write final TTF (with GPOS)")
    parser.add_argument("--coords", default=DEFAULT_COORDS,
                        help=f'SW coords, e.g. "482,500-510" (default "{DEFAULT_COORDS}")')
    args = parser.parse_args()

    coords = parse_coords(args.coords)
    font = TTFont(args.input_ttf)
    build_axis_gpos(font, coords)
    font.save(args.output_ttf)


if __name__ == '__main__':
    main()

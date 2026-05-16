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
MIN_COORD = 250
MAX_COORD = 749
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
    bad = [c for c in out if not MIN_COORD <= c <= MAX_COORD]
    if bad:
        raise ValueError(
            f"coords must lie in [{MIN_COORD}, {MAX_COORD}]; got {sorted(bad)}"
        )
    return sorted(out)


def _range_glyphs(glyph_order, start, end):
    return glyph_order[glyph_order.index(start): glyph_order.index(end) + 1]


def _coverage(glyphs):
    cov = ot.Coverage()
    cov.glyphs = list(glyphs)
    return cov


def _lookup(lookup_type, subtables, flag=0):
    lk = ot.Lookup()
    lk.LookupType = lookup_type
    lk.LookupFlag = flag
    lk.SubTable = list(subtables)
    return lk


def _single_pos_lookup(coverage, dx, dy):
    # SinglePos Format 2 (per-glyph ValueRecord) rather than Format 1 (one
    # shared value). With Format 1 inside a large chained-context lookup,
    # harfbuzz silently drops the GPOS; Format 2 costs more output bytes
    # for the same effect (N identical records instead of one) but
    # actually gets applied. To keep Python heap sane at full scale, the
    # same ValueRecord *object* is referenced from every slot — fontTools
    # still writes N copies on the wire, but we don't allocate N copies
    # in memory while building.
    assert dx or dy, "_single_pos_lookup expects a non-trivial shift"
    shared = ot.ValueRecord()
    if dx:
        shared.XPlacement = dx
    if dy:
        shared.YPlacement = dy

    st = ot.SinglePos()
    st.Format = 2
    st.Coverage = coverage
    st.ValueFormat = (1 if dx else 0) | (2 if dy else 0)
    st.Value = [shared] * len(coverage.glyphs)
    return _lookup(1, [st])


def _chained_ctx_lookup(input_cov, lookahead_covs, inner_lookup_idx):
    plr = ot.PosLookupRecord()
    plr.SequenceIndex = 0
    plr.LookupListIndex = inner_lookup_idx

    st = ot.ChainContextPos()
    st.Format = 3
    st.BacktrackCoverage = []
    st.InputCoverage = [input_cov]
    st.LookAheadCoverage = list(lookahead_covs)
    st.PosLookupRecord = [plr]
    return _lookup(8, [st])


def _wrap_extension_pos(lookup):
    """Re-emit a GPOS lookup as a LookupType-9 extension wrapper.

    Extension subtables hold a 32-bit offset to the actual data, so the
    LookupList itself stays small (each lookup body is ~8 bytes) and we
    can fit thousands of lookups without the uint16 LookupList offsets
    overflowing.
    """
    def wrap(st):
        ext = ot.ExtensionPos()
        ext.Format = 1
        ext.ExtensionLookupType = lookup.LookupType
        ext.ExtSubTable = st
        return ext
    return _lookup(9, [wrap(st) for st in lookup.SubTable], flag=lookup.LookupFlag)


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
    feature.LookupListIndex = list(outer_indices)

    feature_record = ot.FeatureRecord()
    feature_record.FeatureTag = feature_tag
    feature_record.Feature = feature

    feature_list = ot.FeatureList()
    feature_list.FeatureRecord = [feature_record]

    langsys = ot.DefaultLangSys()
    langsys.LookupOrder = None
    langsys.ReqFeatureIndex = 0xFFFF
    langsys.FeatureIndex = [0]

    script = ot.Script()
    script.DefaultLangSys = langsys
    script.LangSysRecord = []

    script_record = ot.ScriptRecord()
    script_record.ScriptTag = script_tag
    script_record.Script = script

    script_list = ot.ScriptList()
    script_list.ScriptRecord = [script_record]

    lookup_list = ot.LookupList()
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

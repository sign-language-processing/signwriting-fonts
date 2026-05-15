"""Emit a minimal VTP (VOLT project) file for the 1D font.

For the first iteration this generates only the glyph definitions and CMAP
clauses — no positioning lookups, since 1D text doesn't need symbol
repositioning the way the 2D grid does. Once the build pipeline stabilizes
this can grow per-symbol substitution lookups (e.g. for rotation dedup).
"""

import argparse
from fontTools.ttLib import TTFont


def emit_vtp(ttf_path: str) -> None:
    font = TTFont(ttf_path)
    cmap = font.getBestCmap()
    # Stable id ordering: by codepoint
    print('DEF_GLYPH ".notdef" ID 0 TYPE BASE END_GLYPH')
    next_id = 1
    glyph_to_id = {".notdef": 0}
    for cp in sorted(cmap):
        name = cmap[cp]
        if name in glyph_to_id:
            continue
        print(f'DEF_GLYPH "{name}" ID {next_id} UNICODE {cp} TYPE BASE END_GLYPH')
        glyph_to_id[name] = next_id
        next_id += 1

    # No lookups yet; minimal script/feature scaffolding for volt2ttf sanity.
    print()
    print('DEF_SCRIPT NAME "Default" TAG "DFLT"')
    print('DEF_LANGSYS NAME "Default" TAG "dflt"')
    print('END_LANGSYS')
    print('END_SCRIPT')

    # Standard CMAP table set
    print()
    print('CMAP_FORMAT 0 3 4')
    print('CMAP_FORMAT 0 4 12')
    print('CMAP_FORMAT 1 0 0')
    print('CMAP_FORMAT 3 1 4')
    print('CMAP_FORMAT 3 10 12 END')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ttf", required=True, help="Base 1D TTF (without VOLT lookups)")
    args = parser.parse_args()
    emit_vtp(args.ttf)


if __name__ == "__main__":
    main()

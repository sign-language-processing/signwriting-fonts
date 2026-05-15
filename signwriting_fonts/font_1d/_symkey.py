"""Symbol-key helpers shared across scripts (no FontForge dependency)."""


# Hand-symbol bases occupy S100..S204 in the FSW spec (everything from
# S205 onward is movement/contact/face/etc). Imported by tune_dedup,
# primitives, and build_font so the cutoff is defined exactly once.
HAND_BASE_MAX = 0x205


def symkey_to_codepoint(symkey: str, plane: int = 0x4) -> int:
    """Convert a FSW symbol key (e.g. "S2ff00") to its SWU plane-4 codepoint.

    Mirrors the formula in signwriting_2010_tools/tools/build.py:
        cp = (plane << 16) + (base - 0x100) * 96 + variant_hi * 16 + variant_lo + 1
    where the symkey is "S" + 3-hex base + 1-hex variant_hi + 1-hex variant_lo.
    """
    if len(symkey) != 6 or symkey[0] != "S":
        raise ValueError(f"expected symkey like S2ff00, got: {symkey!r}")
    base = int(symkey[1:4], 16)
    var_hi = int(symkey[4], 16)
    var_lo = int(symkey[5], 16)
    return (plane << 16) + (base - 0x100) * 96 + var_hi * 16 + var_lo + 1

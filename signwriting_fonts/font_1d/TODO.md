# Composition-rule TODO

Pending requests + investigations across S300–S36c. Each item is a user note from the iteration log; check off as resolved.

## Rules to add

- [ ] **S300–S306** — head movement/direction (rotations 0..7). No standalone "head-movement arrow" base symbol in source to compose from. Each S300 has 3 sub-paths (likely head 2 + arrow 1), S301 has 5 (head 2 + arrow 3), etc. — but the arrow itself isn't a separately-stored glyph. Would need to extract/recognize the arrow shape automatically.
- [x] **S308, S309** — 48 variants each. Done in two passes:
  1. Fill-0 row = head + corresponding fill-2 variant per rotation (16 entries each).
  2. New `rotation_dedup` schema: rot R+8 = rot R (identity duplicate) — emits 24 entries per base via 1-part composite refs. **S308 has 32 compositions, S309 has 32.**
  Confirmed via hash: S308 has 24 byte-exact duplicate pairs; S309 has the same conceptual layout but with slight hand-drawn variance between rot R and rot R+8.
- [x] **S307** — done (rot 0 column = head + marker, rot 1 column = mirror of rot 0). One column (rot=1) is the horizontal mirror of the other (rot=0). Within rot=0: `S30700 = S2ff00 + S30730`, `S30710 = S2ff00 + S30740`, presumably `S30720 = S2ff00 + S30750`. Rot=1 column = M of corresponding rot=0 glyph. Bases (outlines kept): S30730, S30740, S30750.
- [x] **Movement contact multiples** — every variant of a target_base = N copies of a fixed single standalone glyph. N is auto-detected per variant from the sub-path ratio (2 for fill 0, 3 for fill 1 in this family). All 8 variants of each target_base (4 fills × 4 rotations) compose. Done for: S206 ← S20500, S209 ← S20800, S20c ← S20b00, S20f ← S20e00, S212 ← S21100, S218 ← S21600, S219 ← S21700, S21d ← S21b00, S21e ← S21c00. **72 compositions added.**
- [x] **S231 ← S22a paired rotation** — `S2310i = S22a0i + S22a0(i+4 mod 8)` for i in 0..7 (paired with the 180°-opposite-direction sibling). Implemented as explicit `movement-paired-rotation` rule. The remaining S23110+ variants (fills 1,2 × all rotations) need similar but aren't covered yet.
- [x] **S220** (SQUEEZE FLICK ALTERNATING) — implemented via new `mix` schema in multiples: fill 0 = 3×S21c00 + 2×S21700, fill 1 = 2×S21c00 + 3×S21700. All 16 variants compose. **+16 compositions.**
- [ ] **S22f, S234 ← S22a** — sub-path count = 1 (same as S22a), so probably a transform variant (rotation/scale), not an N-copy. Out of scope for the current N-copy multiples mechanism.
- [x] **Tests**: regression tests added for each rule family.
- [ ] **S308, S309** — face direction with full 16-rotation cycle, 3 fills.
- [ ] **S321–S329** — eyegaze. Investigated S321 fill 2: turned out to be arrow + 2 small eye-ticks, NOT head + arrow (no head ring in these glyphs). Each fill has a specific count of eye-indicator ticks but no head ring. Would need a "EyeGaze base" abstraction we don't have.
- [ ] **S337, S338** — air-rotation symbols (8 rotations).
- [ ] **S339, S33a** — breath inhale/exhale: same shape at different sizes across fills (scale-only variation).
- [ ] **S335, S336** — air blow/suck. Many sub-paths (air-flow lines + head). Not paired-marker.
- [ ] **S356–S358** — mouth corners/wrinkles: different marker variant per fill rather than left/right halves.
- [x] **S357, S358** mouth wrinkles single/double — added to eyebrow rule (full 6-fill pattern).
- [x] **S335, S336** air blow/suck — added to eyebrow rule. Only fill 3 and 5 compose; fills 0/1/2 fail because the head ring in S335/S336 source is drawn as partial arcs (segmented by air-flow openings), not the standard 2-ring S2ff00. **+4 compositions.**
- [x] **S356, S362, S363, S365, S366, S367** mouth corners + teeth simple — partial-fit "head + fill 3" rule (no decomposition of fill 3). **+6 compositions.** Hand-drawn variance keeps IOU around 0.80-0.91.
- [ ] **S35f, S360** — tongue centre families.
- [ ] **S359–S35e** — tongue (with rotations).
- [ ] **S361–S367** — teeth families: multiple variant markers per family.
- [ ] **S368, S369** — jaw movement (rotations).
- [ ] **S36a** — neck.
- [ ] **S36b, S36c** — hair, excitement (4-fill pattern, structure TBD).
- [x] **S320** eyelashes fluttering — added to eye rule, 4/4 compose.
- [ ] **S32a–S32c cheeks** — head ring is drawn MODIFIED (with cheek-bump shapes built-in), not as a base S2ff00 + separate cheek sub-paths. Can't decompose without scaling/transforming the head ring itself. Skip.
- [ ] **S32d–S32f tense cheeks, S330 ears** — similar modified-head problem. Skip.
- [ ] **S31a, S31e, S31f** — eye variants where source has high bbox-size variance.
- [ ] **S317, S318** — eye blink families: source draws (arc + V) as different topology in fill-4 vs fill-3.
- [ ] **S33100** specifically — fails resolver despite S332/S333/S334 working.
- [ ] **S33c, S34c** — mouth simple bases that fail resolver.

## Fixes / improvements

- [x] `_center_axis_font` uses **composed** bbox of the part when the part is itself already-resolved, so symmetric mirror-pairs stay perfectly centred even when the source SVG has a hand-drawn asymmetry.
- [ ] Verify S31a00 eyes are now centred (delta to head-cx ≤ 1 px) after the composed-bbox fix.
- [ ] Survey **all** eye groups for centred-ness — currently only S31a was flagged.

## C8 rotation families (tune_dedup.py)

- [x] S37f (4 fills, 8 rotations each)
- [x] S380 (4 fills, 8 rotations each) — added.
- [ ] Audit whether any other base outside this pair is a clean 8-fold rotation family.

## Tests

- [x] eyebrow overlay-equality (S30a–S310)
- [x] forehead vs oracle (S311–S313)
- [x] eye overlay-equality (S314, S315, S316, S319, S31b, S31c, S31d)
- [ ] eye overlay-equality for S31a after centering fix
- [ ] S307 mirror-column invariant once that rule is added

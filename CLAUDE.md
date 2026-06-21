# SignWriting Fonts

The goal of this repository is to build the fonts for SignWriting — both 1D
(OneD/Line/Fill) and 2D — and to deliver them as both `.woff2` (web) and `.ttf`
(harfbuzz/freetype/downstream) targets.

`.ttf` is canonical: harfbuzz and freetype (`hb-view`, downstream rendering)
can't decode `.woff2`, only browsers can. `.woff2` is an additive,
Brotli-compressed web-delivery variant built from the `.ttf` (`make woff2`).

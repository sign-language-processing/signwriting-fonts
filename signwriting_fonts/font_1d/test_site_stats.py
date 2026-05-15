"""Site-build invariants.

Right now: assert that the About page's "file size impact" table shows
numbers that match the current TTF files on disk. If the user rebuilds
the font but forgets to regenerate the site, this test fails — so the
public-facing reduction claim can't silently drift away from reality.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ABOUT_HTML = REPO_ROOT / "assets" / "regen" / "symbols" / "about.html"
UPSTREAM_TTF = REPO_ROOT / "fonts" / "SuttonSignWritingOneD.ttf"
UNOPT_TTF = REPO_ROOT / "fonts" / "SignWritingOneD-unopt.ttf"
COMPOSED_TTF = REPO_ROOT / "fonts" / "SignWritingOneD-base.ttf"


def _kb(b: int) -> str:
    """Mirror the formatting in site.py: '{b/1024:,.0f} KB'."""
    return f"{b/1024:,.0f} KB"


def test_about_size_table_matches_current_ttfs():
    """about.html must list the live byte counts of every TTF we ship.
    Catches the 'rebuilt the font but didn't regen the site' regression."""
    for f in (ABOUT_HTML, UPSTREAM_TTF, UNOPT_TTF, COMPOSED_TTF):
        if not f.exists():
            pytest.skip(f"required artifact missing: {f}")

    html = ABOUT_HTML.read_text()
    expected = {
        "upstream": _kb(UPSTREAM_TTF.stat().st_size),
        "unopt":    _kb(UNOPT_TTF.stat().st_size),
        "composed": _kb(COMPOSED_TTF.stat().st_size),
    }
    missing = {k: v for k, v in expected.items() if v not in html}
    if missing:
        # Surface every stale entry at once so a regen reveals all drift.
        msg = "\n".join(
            f"  {k}: expected '{v}' in about.html, not found" for k, v in missing.items()
        )
        pytest.fail(
            "About-page file-size table is stale:\n" + msg +
            "\n  → run `make assets/regen/symbols/index.html` to refresh."
        )

    # Bonus: pin the inline reduction percentage too, so a font shrink
    # that doesn't propagate to the headline number is caught.
    upstream_b = UPSTREAM_TTF.stat().st_size
    composed_b = COMPOSED_TTF.stat().st_size
    pct = round((1 - composed_b / upstream_b) * 100)
    assert re.search(rf"−{pct}%", html), (
        f"expected −{pct}% reduction figure in about.html"
    )

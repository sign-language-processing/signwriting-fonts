"""Unit tests for the per-symbol SVG extractor.

Build a tiny SQLite DB in-process that mimics font-db's `symbol` table,
then exercise the strip-sym-fill regex + SVG wrapping. The integration
suite covers the full 37k-symbol extract; these tests guard the
edge-case parsing without needing the real DB.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from signwriting_fonts.font_1d.extract import _SYM_FILL_PATH, extract


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fake.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE symbol (symkey TEXT, width INT, height INT, svg TEXT)"
    )
    rows = [
        # Plain sym-line plus a sym-fill that must be stripped.
        ("S10000", 30, 30,
         '<g transform="translate(0,30) scale(1,-1)">'
         '<path class="sym-line" d="M 0 0 L 10 10"/>'
         '<path class="sym-fill" d="M 0 0 L 5 5"/>'
         '</g>'),
        # No sym-fill at all — pass-through (just the line path remains).
        ("S10001", 20, 20,
         '<g transform="translate(0,20) scale(1,-1)">'
         '<path class="sym-line" d="M 1 1 L 2 2"/>'
         '</g>'),
        # sym-fill with attribute order swapped — the regex must still find it.
        ("S17600", 40, 40,
         '<g transform="translate(0,40) scale(1,-1)">'
         '<path d="M 0 0" class="sym-fill"/>'
         '<path class="sym-line" d="M 3 3 L 4 4"/>'
         '</g>'),
    ]
    conn.executemany(
        "INSERT INTO symbol VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


def test_extract_writes_one_svg_per_row(tmp_db: Path, tmp_path: Path):
    out = tmp_path / "out"
    n = extract(tmp_db, out, symbols=None)
    assert n == 3
    assert {p.name for p in out.glob("*.svg")} == {
        "S10000.svg", "S10001.svg", "S17600.svg",
    }


def test_extract_strips_sym_fill_path(tmp_db: Path, tmp_path: Path):
    out = tmp_path / "out"
    extract(tmp_db, out, symbols=["S10000"])
    text = (out / "S10000.svg").read_text()
    assert 'class="sym-fill"' not in text
    # sym-line must survive.
    assert 'class="sym-line"' in text
    assert 'd="M 0 0 L 10 10"' in text


def test_extract_strips_sym_fill_when_attrs_reordered(tmp_db: Path,
                                                      tmp_path: Path):
    out = tmp_path / "out"
    extract(tmp_db, out, symbols=["S17600"])
    text = (out / "S17600.svg").read_text()
    assert 'class="sym-fill"' not in text
    # The companion sym-line path is preserved.
    assert 'class="sym-line"' in text


def test_extract_passthrough_when_no_sym_fill(tmp_db: Path, tmp_path: Path):
    out = tmp_path / "out"
    extract(tmp_db, out, symbols=["S10001"])
    text = (out / "S10001.svg").read_text()
    # No sym-fill to strip — sym-line stays put.
    assert text.count("<path") == 1
    assert 'd="M 1 1 L 2 2"' in text


def test_extract_emits_well_formed_svg_header(tmp_db: Path, tmp_path: Path):
    out = tmp_path / "out"
    extract(tmp_db, out, symbols=["S10000"])
    text = (out / "S10000.svg").read_text()
    assert text.startswith(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="30" height="30" viewBox="0 0 30 30">'
    )
    assert text.rstrip().endswith("</svg>")


def test_extract_filters_to_requested_symbols(tmp_db: Path, tmp_path: Path):
    out = tmp_path / "out"
    n = extract(tmp_db, out, symbols=["S10000", "S10001"])
    assert n == 2
    assert not (out / "S17600.svg").exists()


def test_sym_fill_regex_does_not_eat_neighbouring_elements():
    """Adjacent <path .../> elements must each be matched individually,
    not collapsed into a single greedy match across both."""
    body = (
        '<path class="sym-fill" d="A"/>'
        '<path class="sym-line" d="B"/>'
    )
    stripped = _SYM_FILL_PATH.sub("", body)
    assert stripped == '<path class="sym-line" d="B"/>'


def test_sym_fill_regex_keeps_non_matching_paths():
    """Paths with other class values stay untouched."""
    body = '<path class="something-else" d="A"/>'
    assert _SYM_FILL_PATH.sub("", body) == body


def test_sym_fill_regex_is_compiled_pattern():
    """Sanity: the module exposes a real compiled regex (not a string)."""
    assert isinstance(_SYM_FILL_PATH, re.Pattern)

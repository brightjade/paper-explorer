from pathlib import Path

import pytest

from ppr.readme_table import add_year, format_years, parse_years, selection_cell, update_readme

README = """# Title

| Field | Venue | ID | Years | Tracks |
|---|---|---|---|---|
| ML | ICLR | `iclr` | 2013–2026 | oral, spotlight, poster, main |
| | NeurIPS | `neurips` | 2013–2025 | oral, spotlight, poster, main, datasets |
| CV | ICCV | `iccv` | 2013–2025 (odd years) | main |
| Robotics | CoRL | `corl` | 2017–2025 | oral, poster, main |

NeurIPS also includes datasets tracks.
"""


class TestSelectionCell:
    def test_orders_by_vocabulary(self):
        assert selection_cell(["poster", "main", "oral", "spotlight"]) == "oral, spotlight, poster, main"

    def test_drops_prefixed_extra_tracks(self):
        assert selection_cell(["oral", "datasets_oral", "poster"]) == "oral, poster"

    def test_unknown_names_follow_alphabetically(self):
        assert selection_cell(["main", "zeta", "alpha"]) == "main, alpha, zeta"


class TestYears:
    @pytest.mark.parametrize("cell, years", [
        ("2013–2026", set(range(2013, 2027))),
        ("2013, 2015–2017", {2013, 2015, 2016, 2017}),
        ("2014–2024 (even years)", set(range(2014, 2025, 2))),
        ("2013-2015", {2013, 2014, 2015}),
        ("", set()),
    ])
    def test_parse(self, cell, years):
        assert parse_years(cell) == years

    def test_unparseable_cell_raises(self):
        with pytest.raises(ValueError):
            parse_years("since 2013")

    @pytest.mark.parametrize("years, cell", [
        (range(2013, 2027), "2013–2026"),
        ([2013, 2015, 2016, 2017], "2013, 2015–2017"),
        ([2013, 2015, 2017], "2013–2017 (odd years)"),
        ([2014, 2016], "2014, 2016"),
        ([2014, 2016, 2018, 2024, 2025], "2014, 2016, 2018, 2024–2025"),
        ([2025], "2025"),
    ])
    def test_format(self, years, cell):
        assert format_years(years) == cell


class TestAddYear:
    def test_extends_the_range(self):
        out = add_year(README, "NeurIPS", 2026, "oral, poster")
        assert "| | NeurIPS | `neurips` | 2013–2026 | oral, spotlight, poster, main, datasets |" in out

    def test_new_track_joins_in_vocabulary_order(self):
        out = add_year(README, "CoRL", 2026, "spotlight, poster")
        assert "| Robotics | CoRL | `corl` | 2017–2026 | oral, spotlight, poster, main |" in out

    def test_biennial_venue_keeps_its_stride(self):
        out = add_year(README, "ICCV", 2027, "main")
        assert "| CV | ICCV | `iccv` | 2013–2027 (odd years) | main |" in out

    def test_a_gap_is_written_out(self):
        out = add_year(README, "CoRL", 2027, "main")
        assert "| 2017–2025, 2027 |" in out

    def test_known_year_is_idempotent(self):
        assert add_year(README, "ICLR", 2026, "oral, poster") == README

    def test_untouched_rows_keep_their_exact_text(self):
        out = add_year(README, "NeurIPS", 2026, "oral")
        assert "| ML | ICLR | `iclr` | 2013–2026 | oral, spotlight, poster, main |" in out
        assert "| CV | ICCV | `iccv` | 2013–2025 (odd years) | main |" in out

    def test_unknown_venue_returns_none(self):
        assert add_year(README, "SIGGRAPH", 2026, "main") is None

    def test_prose_around_the_table_survives(self):
        out = add_year(README, "CoRL", 2026, "main")
        assert "NeurIPS also includes datasets tracks." in out
        assert out.startswith("# Title\n")


class TestUpdateReadme:
    def test_writes_and_reports(self, tmp_path):
        p = tmp_path / "README.md"
        p.write_text(README)
        assert update_readme(p, "NeurIPS", 2026, "oral") is True
        assert "| NeurIPS | `neurips` | 2013–2026 |" in p.read_text()

    def test_missing_row_leaves_file_alone(self, tmp_path):
        p = tmp_path / "README.md"
        p.write_text(README)
        assert update_readme(p, "SIGGRAPH", 2026, "main") is False
        assert p.read_text() == README


def test_every_years_cell_in_the_readme_round_trips():
    """Autoregister rewrites a row's Years cell from parse_years; a hand edit
    that does not read back the same would be rewritten on the next
    registration, or hold it."""
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    lines = readme.split("\n")
    header = next(i for i, l in enumerate(lines)
                  if l.startswith("|") and "| Years |" in l and "| Tracks |" in l)
    col = [c.strip() for c in lines[header].strip().strip("|").split("|")].index("Years")
    rows = []
    for line in lines[header + 2:]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")][col])
    assert len(rows) >= 25
    for cell in rows:
        assert format_years(parse_years(cell)) == cell

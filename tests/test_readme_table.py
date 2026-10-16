from ppr.readme_table import selection_cell, set_cell, update_readme

README = """# Title

### ML

| Conference | 2026 | 2025 |
|---|---|---|
| ICLR | oral, poster | oral, spotlight, poster |
| NeurIPS | | oral, spotlight, poster |

NeurIPS also includes datasets tracks.

### Robotics

| Conference | 2025 | 2024 |
|---|---|---|
| CoRL | oral, poster | main |
| ICRA | main | main |
"""


class TestSelectionCell:
    def test_orders_by_vocabulary(self):
        assert selection_cell(["poster", "main", "oral", "spotlight"]) == "oral, spotlight, poster, main"

    def test_drops_prefixed_extra_tracks(self):
        assert selection_cell(["oral", "datasets_oral", "poster"]) == "oral, poster"

    def test_unknown_names_follow_alphabetically(self):
        assert selection_cell(["main", "zeta", "alpha"]) == "main, alpha, zeta"


class TestSetCell:
    def test_fills_an_empty_cell(self):
        out = set_cell(README, "NeurIPS", 2026, "oral, poster")
        assert "| NeurIPS | oral, poster | oral, spotlight, poster |" in out

    def test_untouched_rows_keep_their_exact_text(self):
        out = set_cell(README, "NeurIPS", 2026, "oral")
        assert "| ICLR | oral, poster | oral, spotlight, poster |" in out
        assert "| ICRA | main | main |" in out

    def test_missing_year_column_is_inserted_in_descending_order(self):
        out = set_cell(README, "CoRL", 2026, "main")
        assert "| Conference | 2026 | 2025 | 2024 |" in out
        assert "|---|---|---|---|" in out
        assert "| CoRL | main | oral, poster | main |" in out
        assert "| ICRA | | main | main |" in out

    def test_other_tables_are_not_widened(self):
        out = set_cell(README, "CoRL", 2026, "main")
        assert "| ICLR | oral, poster | oral, spotlight, poster |" in out
        assert out.count("| Conference | 2026 | 2025 |") == 2  # ML unchanged + Robotics widened

    def test_unknown_venue_returns_none(self):
        assert set_cell(README, "SIGGRAPH", 2026, "main") is None

    def test_prose_around_tables_survives(self):
        out = set_cell(README, "CoRL", 2026, "main")
        assert "NeurIPS also includes datasets tracks." in out
        assert out.startswith("# Title\n")


class TestUpdateReadme:
    def test_writes_and_reports(self, tmp_path):
        p = tmp_path / "README.md"
        p.write_text(README)
        assert update_readme(p, "NeurIPS", 2026, "oral") is True
        assert "| NeurIPS | oral |" in p.read_text()

    def test_missing_row_leaves_file_alone(self, tmp_path):
        p = tmp_path / "README.md"
        p.write_text(README)
        assert update_readme(p, "SIGGRAPH", 2026, "main") is False
        assert p.read_text() == README


from pathlib import Path


def test_autoregister_never_edits_the_backfill_table():
    """The 2013-2022 table is static. Its header starts `| Venue |`, not
    `| Conference |`, so set_cell never treats it as a year grid."""
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    section = lambda text: text.split("### 2013–2022", 1)[1].split("\n## ", 1)[0]
    updated = set_cell(readme, "ICLR", 2027, "oral")
    assert updated is not None
    assert section(updated) == section(readme)

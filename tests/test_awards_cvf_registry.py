"""thecvf.com's awards registry, shaped like the live page of 2026-10-15."""

from unittest.mock import MagicMock

import pytest

from ppr.awards import cvf_registry
from ppr.awards.cvf_registry import REGISTRY_URL, parse_registry
from ppr.awards.labels import UnknownAwardLabel


def _section(name, *rows):
    trs = "".join(f"<tr><td>{year}</td><td>{title}</td><td>{authors}</td></tr>" for year, title, authors in rows)
    return f"<h1>{name}</h1><table><tbody>{trs}</tbody></table>"


PAGE = "<html><body><h1>Computer Vision Awards</h1>" + "".join([
    _section("PAMI Young Researcher Award", ("2024", "A. Person", "")),
    _section("Longuet-Higgins Prize",
             ("2026", "“Paper ResNet”", "K. He"),
             ("2026", "“Paper YOLO”", "J. Redmon")),
    _section("Helmholtz Prize", ("2025", "“Paper Fast R-CNN”", "R. Girshick")),
    _section("CVPR Best Paper Award",
             ("2025", "“Paper A”", "J. Wang"),
             ("2024", "“Paper B”", "Y. Liang")),
    _section("CVPR Best Paper Honorable Mention Award",
             ("2024", "“Paper C” (Student Paper)", "B. Yu"),
             ("2024", "“Paper D”", "D. Charatan")),
    _section("ICCV Best Paper Award (Marr Prize)", ("2025", "“Paper E”", "A. Pun")),
    _section("ECCV Best Paper Award", ("2024", "“Paper F”", "J. Klotz")),
]) + "</body></html>"


def _labels(out, conf_id):
    return [(a.label, a.kind, a.title) for a in out[conf_id]]


class TestParseRegistry:
    def test_groups_rows_by_venue_and_year(self):
        out = parse_registry(PAGE, REGISTRY_URL)
        assert sorted(out) == ["cvpr_2024", "cvpr_2025", "cvpr_2026", "eccv_2024", "iccv_2025"]
        assert _labels(out, "cvpr_2025") == [("Best Paper", "award", "Paper A")]
        assert _labels(out, "iccv_2025") == [("Helmholtz Prize", "test_of_time", "Paper Fast R-CNN"),
                                             ("Best Paper (Marr Prize)", "award", "Paper E")]

    def test_student_honorable_mentions_are_labelled_as_such(self):
        out = parse_registry(PAGE, REGISTRY_URL)
        assert _labels(out, "cvpr_2024") == [
            ("Best Paper", "award", "Paper B"),
            ("Best Student Paper Honorable Mention", "honorable", "Paper C"),
            ("Best Paper Honorable Mention", "honorable", "Paper D"),
        ]

    def test_test_of_time_prizes_go_to_the_venue_that_gives_them(self):
        out = parse_registry(PAGE, REGISTRY_URL)
        assert _labels(out, "cvpr_2026") == [("Longuet-Higgins Prize", "test_of_time", "Paper ResNet"),
                                             ("Longuet-Higgins Prize", "test_of_time", "Paper YOLO")]
        assert {a.via for a in out["cvpr_2026"]} == {"cvf_registry"}

    def test_a_new_section_for_one_of_our_venues_raises(self):
        page = PAGE.replace("</body>", _section("CVPR Best Demo Award", ("2026", "“X”", "Y")) + "</body>")
        with pytest.raises(UnknownAwardLabel):
            parse_registry(page, REGISTRY_URL)

    def test_a_page_without_known_sections_raises(self):
        with pytest.raises(ValueError):
            parse_registry("<html><body><h1>Maintenance</h1></body></html>", REGISTRY_URL)

    def test_a_section_without_its_own_table_takes_no_rows(self):
        page = ("<html><body><h1>ECCV Best Paper Honorable Mention Award</h1>"
                + _section("ECCV Best Paper Award", ("2024", "“Paper F”", "J. Klotz")) + "</body></html>")
        assert _labels(parse_registry(page, REGISTRY_URL), "eccv_2024") == [("Best Paper", "award", "Paper F")]


class TestSource:
    def test_one_fetch_serves_every_venue(self, monkeypatch):
        monkeypatch.setattr(cvf_registry, "_cache", {})
        get = MagicMock(return_value=MagicMock(status_code=200, text=PAGE))
        monkeypatch.setattr(cvf_registry.fetch, "get", get)
        assert [a.title for a in cvf_registry.cvf_registry("cvpr_2025", 2025, [])] == ["Paper A"]
        assert [a.title for a in cvf_registry.cvf_registry("eccv_2024", 2024, [])] == ["Paper F"]
        assert cvf_registry.cvf_registry("iccv_2023", 2023, []) == []
        get.assert_called_once_with(REGISTRY_URL)

"""SE awards: researchr badges and the SIGSOFT distinguished-paper list."""

from unittest.mock import MagicMock

import pytest

from ppr.awards import researchr_badges, sigsoft
from ppr.awards.model import Award
from ppr.awards.researchr_badges import badge_awards
from ppr.awards.sigsoft import LABEL, SIGSOFT_URL, parse_sigsoft
from tests.test_researchr import _page, _row

TRACK_URL = "https://conf.researchr.org/track/icse-2025/icse-2025-research-track"


class TestBadgeAwards:
    def test_keeps_award_badges_and_drops_the_rest(self):
        rows = [
            {"title": "Won", "badges": ["Award Winner", "Artifact-Available"]},
            {"title": "Artifact", "badges": ["Award Winner Best Artifact"]},
            {"title": "Topic", "badges": ["Security", "SE for AI"]},
            {"title": "Plain", "badges": []},
        ]
        out = badge_awards(rows, "icse", TRACK_URL)
        assert [(a.label, a.kind, a.title, a.via) for a in out] == [
            ("Award Winner", "award", "Won", "researchr"),
            ("Award Winner Best Artifact", "artifact", "Artifact", "researchr"),
        ]

    def test_source_reads_the_registered_track_page(self, monkeypatch):
        html = _page([_row("e1", "Won", badges=("Distinguished Paper Award",)), _row("e2", "Plain")],
                     conf="ICSE 2025")
        get = MagicMock(return_value=MagicMock(status_code=200, text=html))
        monkeypatch.setattr(researchr_badges.fetch, "get", get)
        out = researchr_badges.researchr_badges("icse_2025", 2025, [])
        assert [(a.label, a.title) for a in out] == [("Distinguished Paper Award", "Won")]
        get.assert_called_once_with(TRACK_URL)

    def test_source_refuses_a_page_for_another_track(self, monkeypatch):
        html = _page([_row("e1", "Won", track="Journal-first Papers")], track="Journal-first Papers")
        monkeypatch.setattr(researchr_badges.fetch, "get", MagicMock(return_value=MagicMock(status_code=200, text=html)))
        with pytest.raises(ValueError):
            researchr_badges.researchr_badges("icse_2025", 2025, [])

    def test_unregistered_conference_has_nothing(self):
        assert researchr_badges.researchr_badges("icse_2031", 2031, []) == []


SIGSOFT_PAGE = (
    '<html><body><div id="post-content"><h2 id="winners">Winners</h2>'
    '<h3 id="ase-2025">The IEEE/ACM International Conference on Automated Software Engineering (ASE 2025)</h3>'
    '<p>Nov 2025</p><ul><li>A Author, B Author: Paper One</li></ul>'
    '<h3>The ACM International Conference on the Foundations of Software Engineering (FSE 2025)</h3>'
    '<p>Mon 23 - Fri 27 June, 2025, Trondheim, Norway</p><ul>'
    '<li>Bruno Kreyssig, Alexandre Bartel: Gleipner - A Benchmark for Gadget Chain Detection in Java '
    'Deserialization Vulnerabilities</li>'
    '<li>Susheng Wu, Xin Peng: Mystique: Automated Vulnerability Patch Porting with Semantic and '
    'Syntactic-Enhanced LLM</li></ul>'
    '<h3>ACM SIGSOFT International Symposium on Software Testing and Analysis (ISSTA 2025)</h3><p>June 2025</p>'
    '<h3>32nd ACM Joint European Software Engineering Conference and Symposium on the Foundations of '
    'Software Engineering (ESEC/FSE 2023)</h3><p>Dec 2023</p><ul><li>X Y: Old Paper</li></ul>'
    '<h3>ACM / IEEE 27th International Conference on Model Driven Engineering Languages and Systems '
    '(MODELS 2024)</h3><ul><li>Q R: Not Tracked</li></ul>'
    '</div></body></html>'
)


class TestSigsoft:
    def test_splits_at_the_first_colon_only(self):
        out = parse_sigsoft(SIGSOFT_PAGE, SIGSOFT_URL)
        assert [a.title for a in out["fse_2025"]] == [
            "Gleipner - A Benchmark for Gadget Chain Detection in Java Deserialization Vulnerabilities",
            "Mystique: Automated Vulnerability Patch Porting with Semantic and Syntactic-Enhanced LLM",
        ]
        assert {(a.label, a.kind, a.via) for a in out["fse_2025"]} == {(LABEL, "award", "sigsoft")}

    def test_venues_and_years_from_the_heading(self):
        out = parse_sigsoft(SIGSOFT_PAGE, SIGSOFT_URL)
        assert sorted(out) == ["ase_2025", "fse_2023", "fse_2025"]  # MODELS ignored

    def test_a_section_without_a_list_does_not_take_the_next_one(self):
        assert "issta_2025" not in parse_sigsoft(SIGSOFT_PAGE, SIGSOFT_URL)

    def test_a_page_without_winners_raises(self):
        with pytest.raises(ValueError):
            parse_sigsoft("<html><body><h2>Nominations</h2></body></html>", SIGSOFT_URL)

    def test_backfill_is_skipped_when_an_earlier_source_has_winners(self, monkeypatch):
        get = MagicMock()
        monkeypatch.setattr(sigsoft.fetch, "get", get)
        earlier = [Award("Distinguished Paper Award", "award", "P", "researchr", TRACK_URL)]
        assert sigsoft.sigsoft_backfill("fse_2024", 2024, earlier) is None
        get.assert_not_called()

    def test_backfill_runs_when_no_earlier_source_has_winners(self, monkeypatch):
        monkeypatch.setattr(sigsoft, "_cache", {})
        get = MagicMock(return_value=MagicMock(status_code=200, text=SIGSOFT_PAGE))
        monkeypatch.setattr(sigsoft.fetch, "get", get)
        artifact_only = [Award("Best Artifact Award", "artifact", "Q", "manual", "https://x.test")]
        assert len(sigsoft.sigsoft_backfill("fse_2025", 2025, artifact_only)) == 2
        assert sigsoft.sigsoft_backfill("issta_2026", 2026, []) == []
        get.assert_called_once_with(SIGSOFT_URL)

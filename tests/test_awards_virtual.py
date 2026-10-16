"""awards_detail and AwardCandidates pages, shaped like the live pages of 2026-10-15."""

from unittest.mock import MagicMock

import pytest
import requests

from ppr.awards import virtual
from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.virtual import awards_detail, cvpr_candidates, parse_award_candidates, parse_awards_detail

URL = "https://neurips.cc/virtual/2024/awards_detail"


def _classic(event, title, path="poster", abstract=""):
    """A card in the markup NeurIPS 2023-24, ICML 2023-25 and ICLR 2023-24 use."""
    details = f"<details><summary>Abstract</summary><div>{abstract}</div></details>" if abstract else ""
    return (f'<div class="displaycards touchup-date" id="event-{event}"><div class="virtual-card">'
            f'<a class="small-title text-underline-hover" href="/virtual/2024/{path}/{event}">{title}</a></div>'
            f'<div class="type_display_name_virtual_card">Poster</div>'
            f'<div class="author-str">A One · B Two</div><div class="author-str higher"></div>{details}</div>')


def _redesigned(event, title, path="poster", abstract=""):
    """A card in the 2025 redesign: inline styles, no classes (NeurIPS 2025, ICML 2026, CVPR 2026)."""
    details = (f'<details style="margin-top: 12px;"><summary>Abstract</summary>'
               f'<div style="margin-top: 8px;">{abstract}</div></details>') if abstract else ""
    return (f'<div class="displaycards touchup-date" id="event-{event}"><div style="margin-bottom: 8px;">'
            f'<a href="/virtual/2025/{path}/{event}" style="font-weight: 600;">{title}</a></div>'
            f'<div style="color: #666;"> Poster </div><div style="color: #555;"> A One ⋅ B Two </div>'
            f'{details}</div>')


def _row(label, *cards):
    return f"<tr><td><div>{label}</div></td><td>{''.join(cards)}</td></tr>"


def _page(*rows):
    cookie = ('<table class="gdpr-statement"><tr><td>NeurIPS uses cookies for essential functions only.'
              '</td><td><button>Accept</button></td></tr></table>')
    return f"<html><body><table>{''.join(rows)}</table>{cookie}</body></html>"


class TestParseAwardsDetail:
    def test_reads_label_and_title_per_card(self):
        html = _page(_row("Best Paper", _classic(1, "Paper One"), _classic(2, "Paper Two")),
                     _row("Datasets and Benchmarks Best Paper", _classic(3, "Paper Three")))
        out = parse_awards_detail(html, URL, "neurips")
        assert [(a.label, a.kind, a.title) for a in out] == [
            ("Best Paper", "award", "Paper One"),
            ("Best Paper", "award", "Paper Two"),
            ("Datasets and Benchmarks Best Paper", "award", "Paper Three"),
        ]
        assert {a.via for a in out} == {"virtual"}
        assert {a.source for a in out} == {URL}

    def test_both_card_markups_on_one_page(self):
        html = _page(_row("Best Paper", _redesigned(1, "New Markup")),
                     _row("Best Paper Runner-up", _classic(2, "Old Markup")))
        assert [a.title for a in parse_awards_detail(html, URL, "neurips")] == ["New Markup", "Old Markup"]

    def test_title_whitespace_is_collapsed(self):
        html = _page(_row("Best Paper", _redesigned(1, "Why Diffusion Models Don’t Memorize:  The Role")))
        [a] = parse_awards_detail(html, URL, "neurips")
        assert a.title == "Why Diffusion Models Don’t Memorize: The Role"

    def test_cookie_banner_and_an_empty_page_yield_nothing(self):
        # ICLR 2025 and 2026: a 200 page whose only table is the cookie banner.
        assert parse_awards_detail(_page(), URL, "iclr") == []

    def test_non_award_rows_are_skipped(self):
        assert parse_awards_detail(_page(_row("Highlight", _classic(1, "P"))), URL, "cvpr") == []

    def test_unknown_label_raises(self):
        with pytest.raises(UnknownAwardLabel):
            parse_awards_detail(_page(_row("Community Choice", _classic(1, "P"))), URL, "neurips")

    def test_paper_cards_carry_no_url(self):
        [a] = parse_awards_detail(_page(_row("Best Paper", _classic(1, "P"))), URL, "neurips")
        assert a.url == ""

    def test_test_of_time_talk_prefix_is_dropped_and_the_event_page_linked(self):
        html = _page(_row("Test of Time Award", _classic(
            83333, "Test of Time Award Talk:Distributed Representations of Words and Phrases and their "
                   "Compositionality", path="test-of-time")))
        [a] = parse_awards_detail(html, "https://neurips.cc/virtual/2023/awards_detail", "neurips")
        assert a.kind == "test_of_time"
        assert a.title == "Distributed Representations of Words and Phrases and their Compositionality"
        assert a.url == "https://neurips.cc/virtual/2024/test-of-time/83333"

    def test_generic_test_of_time_card_takes_the_paper_from_its_abstract(self):
        # NeurIPS 2025: the card is titled just "Test of Time Award".
        abstract = ("[Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks "
                    "(Test of Time Award)](https://papers.neurips.cc/paper_files/paper/2015/hash/14bf-Abstract.html)"
                    " *Shaoqing Ren, Kaiming He* &lt;strong&gt;Paper Abstract&lt;/strong&gt;: State-of-the-art")
        html = _page(_row("Test of Time Award", _redesigned(128328, "Test of Time Award",
                                                             path="test-of-time", abstract=abstract)))
        [a] = parse_awards_detail(html, "https://neurips.cc/virtual/2025/awards_detail", "neurips")
        assert a.title == "Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks"
        assert a.url == "https://papers.neurips.cc/paper_files/paper/2015/hash/14bf-Abstract.html"


class TestParseAwardCandidates:
    def test_reads_every_event_card(self):
        card = ('<div class="event-card touchup-date" data-event-type="Poster" id="event-{i}">'
                '<span class="event-type-badge">Poster</span><h3 class="event-title">'
                '<a href="/virtual/2026/poster/{i}">Candidate {i}</a></h3>'
                '<div class="event-speakers"> A ⋅ B </div></div>')
        html = "<html><body>" + "".join(card.format(i=i) for i in (1, 2)) + "</body></html>"
        out = parse_award_candidates(html, "https://cvpr.thecvf.com/virtual/2026/events/AwardCandidates2026")
        assert [(a.label, a.kind, a.title, a.via) for a in out] == [
            ("Award Candidate", "candidate", "Candidate 1", "virtual"),
            ("Award Candidate", "candidate", "Candidate 2", "virtual"),
        ]


def _respond(monkeypatch, status=200, text=""):
    response = MagicMock(status_code=status, text=text)
    get = MagicMock(return_value=response)
    monkeypatch.setattr(virtual.fetch, "get", get)
    return get


class TestSources:
    def test_awards_detail_url_per_venue(self, monkeypatch):
        get = _respond(monkeypatch, text=_page(_row("Best Paper", _classic(1, "P"))))
        assert [a.title for a in awards_detail("eccv_2024", 2024, [])] == ["P"]
        get.assert_called_once_with("https://eccv.ecva.net/virtual/2024/awards_detail")

    def test_a_missing_page_is_nothing_yet(self, monkeypatch):
        _respond(monkeypatch, status=404)
        assert awards_detail("neurips_2026", 2026, []) == []

    def test_other_http_errors_raise(self, monkeypatch):
        response = MagicMock(status_code=503)
        response.raise_for_status.side_effect = requests.HTTPError("503")
        monkeypatch.setattr(virtual.fetch, "get", MagicMock(return_value=response))
        with pytest.raises(requests.HTTPError):
            awards_detail("icml_2026", 2026, [])

    def test_cvpr_candidates_url_and_missing_years(self, monkeypatch):
        get = _respond(monkeypatch, status=404)
        assert cvpr_candidates("cvpr_2024", 2024, []) == []
        get.assert_called_once_with("https://cvpr.thecvf.com/virtual/2024/events/AwardCandidates2024")

"""USENIX Security technical-sessions pages, shaped like the live 2023-2026 pages."""

from unittest.mock import MagicMock

import pytest

from ppr.awards import usenix_notes
from ppr.awards.usenix_notes import note_awards, split_note
from ppr.scrapers import usenix
from ppr.scrapers.usenix import parse_sessions, sessions_url


def _article(title, *paragraphs, href="/conference/usenixsecurity23/presentation/x"):
    ps = "".join(paragraphs)
    return (f'<article class="node-paper"><h2> <a href="{href}">{title}</a> </h2>'
            f'<div class="field field-name-field-paper-people-text"><div class="field-items">'
            f'<div class="field-item odd">{ps}</div></div></div></article>')


AWARD_P = '<p style="font-weight: 600; font-style: italic;">{}</p>'
BOTSCREEN = _article(
    "BotScreen: Trust Everybody, but Cut the Aimbots Yourself",
    "<p>Minyeop Choi, <em>KAIST;</em> Gihyuk Ko, <em>Cyber Security Research Center at KAIST and Carnegie "
    "Mellon University;</em> Sang Kil Cha, <em>KAIST and Cyber Security Research Center at KAIST</em></p> ",
    AWARD_P.format("Distinguished Paper Award Winner"),
    href="/conference/usenixsecurity23/presentation/choi",
)


def _page(*articles):
    return f"<html><body>{''.join(articles)}</body></html>"


class TestParseSessions:
    def test_award_note_is_not_an_author(self):
        [row] = parse_sessions(_page(BOTSCREEN))
        assert row["title"] == "BotScreen: Trust Everybody, but Cut the Aimbots Yourself"
        assert row["link"] == "https://www.usenix.org/conference/usenixsecurity23/presentation/choi"
        assert row["authors"] == ["Minyeop Choi", "Gihyuk Ko", "Sang Kil Cha"]
        assert row["notes"] == ["Distinguished Paper Award Winner"]

    def test_shared_affiliation_keeps_every_author(self):
        [row] = parse_sessions(_page(_article(
            "T", "<p>Claudio Anliker, Giovanni Camurati, and Srdjan Čapkun, <em>ETH Zurich</em></p>")))
        assert row["authors"] == ["Claudio Anliker", "Giovanni Camurati", "Srdjan Čapkun"]

    def test_and_joins_names_without_splitting_names_that_contain_it(self):
        [row] = parse_sessions(_page(_article(
            "T", "<p>Ang Li and Alexandra Ferdinand, <em>Arizona State University;</em> Dianqi Han, "
                 "<em>University of Texas at Arlington</em></p>")))
        assert row["authors"] == ["Ang Li", "Alexandra Ferdinand", "Dianqi Han"]

    def test_semicolon_separated_affiliations_are_not_authors(self):
        [row] = parse_sessions(_page(_article(
            "T", "<p>Peihua Zhang, <em>University of Chinese Academy of Sciences; Zhongguancun Laboratory;</em> "
                 "Chenggang Wu, <em>Zhongguancun Laboratory</em></p>")))
        assert row["authors"] == ["Peihua Zhang", "Chenggang Wu"]

    def test_article_without_affiliations_has_no_authors(self):
        # The 2026 Test-of-Time panel is an article.node-paper too.
        [row] = parse_sessions(_page(_article(
            "Some 2016 Paper", "<p>Originally presented at USENIX Security '16.</p>", "<p>Read the paper</p>")))
        assert row["authors"] == []
        assert row["notes"] == ["Read the paper"]

    def test_scraper_builds_papers_from_the_parse(self, monkeypatch):
        response = MagicMock(status_code=200, content=_page(BOTSCREEN).encode())
        get = MagicMock(return_value=response)
        monkeypatch.setattr(usenix.requests, "get", get)
        [paper] = usenix.SCRAPERS["usenix_security_2023"]()
        assert paper.authors == ["Minyeop Choi", "Gihyuk Ko", "Sang Kil Cha"]
        assert paper.selection == "main"
        assert get.call_args.args[0] == sessions_url("usenix_security_2023")
        assert get.call_args.kwargs["headers"] == usenix.HEADERS


class TestAwardNotes:
    @pytest.mark.parametrize("note,labels", [
        ("Distinguished Paper Award Winner", ["Distinguished Paper Award Winner"]),
        ("Distinguished Paper Award Winner and Co-Winner of the 2023 Internet Defense Prize",
         ["Distinguished Paper Award Winner", "Co-Winner of the 2023 Internet Defense Prize"]),
        ("Distinguished Paper Award Winner and Runner-Up Winner of the 2023 Internet Defense Prize",
         ["Distinguished Paper Award Winner", "Runner-Up Winner of the 2023 Internet Defense Prize"]),
        ("Distinguished Paper Award Winner and Winner of the 2024 Internet Defense Prize",
         ["Distinguished Paper Award Winner", "Winner of the 2024 Internet Defense Prize"]),
    ])
    def test_split_note(self, note, labels):
        assert split_note(note) == labels

    def test_note_awards_kinds(self):
        rows = [{"title": "P", "notes": [
            "Distinguished Paper Award Winner and Runner-Up Winner of the 2023 Internet Defense Prize"]},
                {"title": "Q", "notes": ["Distinguished Artifact Award Winner"]}]
        out = note_awards(rows, "https://www.usenix.org/x")
        assert [(a.label, a.kind, a.title, a.via) for a in out] == [
            ("Distinguished Paper Award Winner", "award", "P", "usenix"),
            ("Runner-Up Winner of the 2023 Internet Defense Prize", "honorable", "P", "usenix"),
            ("Distinguished Artifact Award Winner", "artifact", "Q", "usenix"),
        ]

    def test_non_award_notes_are_ignored(self):
        rows = [{"title": "P", "notes": ["Read the paper", "Speaker bio: she received the X award in 2019"]}]
        assert note_awards(rows, "https://www.usenix.org/x") == []

    def test_source_reads_the_sessions_page(self, monkeypatch):
        get = MagicMock(return_value=MagicMock(status_code=200, content=_page(BOTSCREEN).encode()))
        monkeypatch.setattr(usenix_notes.fetch, "get", get)
        out = usenix_notes.usenix_awards("usenix_security_2023", 2023, [])
        assert [(a.label, a.title) for a in out] == [
            ("Distinguished Paper Award Winner", "BotScreen: Trust Everybody, but Cut the Aimbots Yourself")]
        get.assert_called_once_with(sessions_url("usenix_security_2023"))

    def test_a_page_without_papers_raises(self, monkeypatch):
        monkeypatch.setattr(usenix_notes.fetch, "get",
                            MagicMock(return_value=MagicMock(status_code=200, content=b"<html></html>")))
        with pytest.raises(ValueError):
            usenix_notes.usenix_awards("usenix_security_2023", 2023, [])


def _teaser(title, people, href="/conference/usenixsecurity13/technical-sessions/presentation/zhang"):
    """A 2013-16 paper: a div teaser, the award inline in the author <p>."""
    return (f'<div class="node node-paper view-mode-teaser node-teaser clearfix"><h2><a href="{href}">{title}</a>'
            f'</h2><div class="content"><div class="field field-name-field-paper-people-text"><div class="field-items">'
            f'<div class="field-item odd">{people}</div></div></div></div></div>')


TEASER_2013 = _teaser(
    "Control Flow Integrity for COTS Binaries",
    "<p>Mingwei Zhang and R. Sekar, <em>Stony Brook University<br/></em>"
    "<strong><em>Awarded Best Paper! </em></strong></p>")
INLINE_2017 = _article(
    "Detecting Credential Spearphishing in Enterprise Settings",
    "<p>Grant Ho, <em>UC Berkeley;</em> David Wagner, <em>UC Berkeley</em><br/>\n"
    "<strong><em>Distinguished Paper Award Winner and winner of the 2017 Internet Defense Prize!</em></strong></p>",
    href="/conference/usenixsecurity17/technical-sessions/presentation/ho")


class TestOldMarkups:
    def test_2013_teasers_are_papers_and_the_inline_award_is_a_note(self):
        [row] = parse_sessions(_page(TEASER_2013))
        assert row["title"] == "Control Flow Integrity for COTS Binaries"
        assert row["authors"] == ["Mingwei Zhang", "R. Sekar"]
        assert row["notes"] == ["Awarded Best Paper!"]

    def test_2017_inline_award_is_a_note_and_not_an_author(self):
        [row] = parse_sessions(_page(INLINE_2017))
        assert row["authors"] == ["Grant Ho", "David Wagner"]
        assert row["notes"] == ["Distinguished Paper Award Winner and winner of the 2017 Internet Defense Prize!"]

    def test_a_titleless_teaser_is_not_a_paper(self):
        assert parse_sessions(_page(_teaser("", "<p>Program Co-Chairs</p>"))) == []

    def test_old_years_awards(self):
        rows = parse_sessions(_page(TEASER_2013, INLINE_2017))
        out = note_awards(rows, "https://www.usenix.org/x")
        assert [(a.label, a.kind) for a in out] == [
            ("Awarded Best Paper", "award"),
            ("Distinguished Paper Award Winner", "award"),
            ("Winner of the 2017 Internet Defense Prize", "award"),
        ]


class TestNoteRules:
    @pytest.mark.parametrize("note,labels", [
        ("Distinguished Paper Award Winner and First Prize winner of the 2020 Internet Defense Prize",
         ["Distinguished Paper Award Winner", "First Prize winner of the 2020 Internet Defense Prize"]),
        ("Distinguished Paper Award Winner and Second Prize Winner (tie) of the 2022 Internet Defense Prize",
         ["Distinguished Paper Award Winner", "Second Prize Winner (tie) of the 2022 Internet Defense Prize"]),
        ("Awarded Best Student Paper!", ["Awarded Best Student Paper"]),
        ("Facebook Internet Defense Prize Winner!", ["Facebook Internet Defense Prize Winner"]),
        ("2018 Internet Defense Prize First Runner Up", ["2018 Internet Defense Prize First Runner Up"]),
    ])
    def test_split_note(self, note, labels):
        assert split_note(note) == labels

    def test_a_note_line_is_never_an_award(self):
        rows = [{"title": "P", "notes": [
            "Distinguished Paper Award Winner and Third Prize winner of the 2020 Internet Defense Prize",
            "Note: Co-authors Greenstadt and McCoy have declined the Internet Defense Prize."]}]
        assert [a.label for a in note_awards(rows, "https://www.usenix.org/x")] == [
            "Distinguished Paper Award Winner", "Third Prize winner of the 2020 Internet Defense Prize"]

    def test_the_url_is_built_from_the_year(self, monkeypatch):
        get = MagicMock(return_value=MagicMock(status_code=200, content=_page(TEASER_2013).encode()))
        monkeypatch.setattr(usenix_notes.fetch, "get", get)
        usenix_notes.usenix_awards("usenix_security_2013", 2013, [])
        get.assert_called_once_with("https://www.usenix.org/conference/usenixsecurity13/technical-sessions")
        assert usenix_notes.sessions_url(2023) == sessions_url("usenix_security_2023")

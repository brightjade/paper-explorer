import json
from unittest.mock import MagicMock

import pytest

from ppr.api_client import OpenReviewAPIClient
from ppr.config import CrawlConfig
from ppr.models import Paper


def make_config():
    return CrawlConfig(
        name="ICLR", year=2025,
        venue_id="ICLR.cc/2025/Conference",
        selections={
            "oral": "ICLR 2025 Oral",
            "poster": "ICLR 2025 Poster",
        },
        conference_id="iclr_2025",
    )


def make_mock_note(forum_id="abc123", title="Test Paper", authors=None,
                   keywords=None, abstract="An abstract.",
                   venue="ICLR 2025 Oral"):
    note = MagicMock()
    note.forum = forum_id
    note.content = {
        "title": {"value": title},
        "authors": {"value": authors or ["Alice", "Bob"]},
        "keywords": {"value": keywords or ["ML"]},
        "abstract": {"value": abstract},
        "venueid": {"value": "ICLR.cc/2025/Conference"},
        "venue": {"value": venue},
    }
    return note


class TestOpenReviewAPIClient:
    def test_fetch_papers(self):
        mock_client = MagicMock()
        mock_client.get_all_notes.return_value = [
            make_mock_note("id1", "Paper One", venue="ICLR 2025 Oral"),
            make_mock_note("id2", "Paper Two", venue="ICLR 2025 Oral"),
            make_mock_note("id3", "Poster Paper", venue="ICLR 2025 Poster"),
        ]

        config = make_config()
        client = OpenReviewAPIClient(config, mock_client)
        papers = client.fetch_papers()

        assert len(papers) == 3
        orals = [p for p in papers if p.selection == "oral"]
        posters = [p for p in papers if p.selection == "poster"]
        assert len(orals) == 2
        assert len(posters) == 1
        assert orals[0].title == "Paper One"
        assert orals[0].forum_id == "id1"
        assert orals[0].link == "https://openreview.net/pdf?id=id1"
        assert orals[0].authors == ["Alice", "Bob"]
        assert orals[0].selection == "oral"

    def test_fetch_papers_filters_unknown_venues(self):
        mock_client = MagicMock()
        mock_client.get_all_notes.return_value = [
            make_mock_note("id1", "Oral", venue="ICLR 2025 Oral"),
            make_mock_note("id2", "Unknown", venue="ICLR 2025 Workshop"),
        ]

        config = make_config()
        client = OpenReviewAPIClient(config, mock_client)
        papers = client.fetch_papers()

        assert len(papers) == 1
        assert papers[0].selection == "oral"

    def test_save_papers(self, tmp_path):
        config = CrawlConfig(
            name="ICLR", year=2025, venue_id="X",
            selections={"oral": "X"},
            conference_id="iclr_2025",
        )
        save_path = tmp_path / "2025.jsonl"
        config.get_save_path = lambda: save_path

        client = OpenReviewAPIClient(config, MagicMock())
        papers = [
            Paper(title="P1", link="L1", authors=["A"], selection="oral", forum_id="id1"),
            Paper(title="P2", link="L2", authors=["B"], selection="poster", forum_id="id2"),
        ]
        client.save_papers(papers)

        assert save_path.exists()
        lines = save_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["title"] == "P1"
        assert json.loads(lines[0])["selection"] == "oral"

    def test_save_papers_write_mode_no_duplicates(self, tmp_path):
        config = CrawlConfig(
            name="ICLR", year=2025, venue_id="X",
            selections={"oral": "X"},
            conference_id="iclr_2025",
        )
        save_path = tmp_path / "2025.jsonl"
        config.get_save_path = lambda: save_path

        client = OpenReviewAPIClient(config, MagicMock())
        papers = [Paper(title="P1", link="L1", authors=["A"], selection="oral")]

        client.save_papers(papers)
        client.save_papers(papers)

        lines = save_path.read_text().strip().split("\n")
        assert len(lines) == 1


import pytest

from ppr.api_client import EmptyCrawlError, OpenReviewAPIClient
from ppr.store import ShrinkError


class TestEmptyCrawlGuard:
    def _client(self, venue_values, selections):
        from unittest.mock import MagicMock

        notes = []
        for v in venue_values:
            n = MagicMock()
            n.content = {"venue": {"value": v}, "title": {"value": "T"},
                         "authors": {"value": ["A"]}}
            n.forum = "f"
            notes.append(n)
        or_client = MagicMock()
        or_client.get_all_notes.return_value = notes

        config = MagicMock()
        config.venue_id = "X/2026/Conference"
        config.api_version = 2
        config.year_from_pdate = False
        config.selections = selections
        config.extra_venue_ids = []
        return OpenReviewAPIClient(config, or_client)

    def test_raises_when_every_note_is_filtered_away(self):
        """CoRL 2024: 264 notes, selections matching none of them."""
        client = self._client(["CoRL 2024"] * 264,
                              {"oral": "CoRL 2024 Oral", "poster": "CoRL 2024 Poster"})
        with pytest.raises(EmptyCrawlError) as exc:
            client.fetch_papers()
        assert "264" in str(exc.value)
        assert "CoRL 2024" in str(exc.value)  # names the venue strings actually seen

    def test_succeeds_when_selections_match(self):
        client = self._client(["CoRL 2024"] * 3, {"main": "CoRL 2024"})
        assert len(client.fetch_papers()) == 3

    def test_no_notes_at_all_is_not_an_error(self):
        client = self._client([], {"main": "X"})
        assert client.fetch_papers() == []


class TestSaveGuard:
    def _client(self, tmp_path):
        config = CrawlConfig(
            name="CoRL", year=2024, venue_id="X",
            selections={"poster": "X"},
            conference_id="corl_2024",
        )
        save_path = tmp_path / "2025.jsonl"
        config.get_save_path = lambda: save_path
        return OpenReviewAPIClient(config, MagicMock()), save_path

    def test_refuses_to_erase_an_existing_crawl(self, tmp_path):
        """`fetch_papers` returns `[]` on an OpenReviewException, so the save
        path is the second door onto the CoRL 2024 failure -- an empty file
        written over a good one while the log says "Saved 0 papers"."""
        client, save_path = self._client(tmp_path)
        client.save_papers([Paper(title="P1", link="L1", authors=["A"], selection="poster")])
        before = save_path.read_bytes()

        with pytest.raises(ShrinkError):
            client.save_papers([])

        assert save_path.read_bytes() == before

    def test_first_crawl_of_an_empty_venue_still_writes(self, tmp_path):
        client, save_path = self._client(tmp_path)
        client.save_papers([])
        assert save_path.exists() and save_path.read_text() == ""


from ppr.api_client import DuplicateConflictError, EmptyCrawlError, collapse_duplicates


def v1_note(forum, title="T", venue=None, authors=None, tcdate=1, details=None):
    note = MagicMock()
    note.forum = forum
    note.tcdate = tcdate
    note.content = {"title": title, "authors": authors or ["A"], "abstract": "abs",
                    "keywords": ["k"]}
    if venue is not None:
        note.content["venue"] = venue
    note.details = details
    return note


def v1_config(**kw):
    base = dict(name="ICLR", year=2019, venue_id="ICLR.cc/2019/Conference",
                selections={"oral": "Accept (Oral)", "poster": "Accept (Poster)"},
                conference_id="iclr_2019", api_version=1)
    base.update(kw)
    return CrawlConfig(**base)


class TestV1Backfill:
    def test_submission_invitation_override(self):
        client = MagicMock()
        client.get_all_notes.return_value = [v1_note("f1", venue="ICLR 2017 Oral")]
        cfg = v1_config(selections={"oral": "ICLR 2017 Oral"},
                        submission_invitation="ICLR.cc/2017/conference/-/submission")
        papers = OpenReviewAPIClient(cfg, client).fetch_papers()
        client.get_all_notes.assert_called_once_with(invitation="ICLR.cc/2017/conference/-/submission")
        assert [p.selection for p in papers] == ["oral"]

    def test_decisions_from_their_own_invitation(self):
        """ICLR 2018: one Acceptance_Decision note per forum."""
        subs = [v1_note("f1", "One"), v1_note("f2", "Two"), v1_note("f3", "Three")]
        decisions = [MagicMock(forum="f1", content={"decision": "Accept (Oral)"}),
                     MagicMock(forum="f2", content={"decision": "Accept (Poster)"}),
                     MagicMock(forum="f3", content={"decision": "Reject"})]
        client = MagicMock()
        client.get_all_notes.side_effect = lambda invitation, **kw: (
            decisions if invitation.endswith("Acceptance_Decision") else subs)
        cfg = v1_config(decisions={"invitation": "ICLR.cc/2018/Conference/-/Acceptance_Decision",
                                   "field": "decision"})
        papers = OpenReviewAPIClient(cfg, client).fetch_papers()
        assert [(p.title, p.selection) for p in papers] == [("One", "oral"), ("Two", "poster")]

    def test_decisions_from_direct_replies(self):
        """ICLR 2019: the meta-review reply carries the recommendation."""
        replies = lambda rec: {"directReplies": [
            {"invitation": "ICLR.cc/2019/Conference/-/Paper1/Official_Review", "content": {"rating": "8"}},
            {"invitation": "ICLR.cc/2019/Conference/-/Paper1/Meta_Review", "content": {"recommendation": rec}},
        ]}
        subs = [v1_note("f1", "One", details=replies("Accept (Oral)")),
                v1_note("f2", "Two", details=replies("Reject")),
                v1_note("f3", "Three", details={"directReplies": []})]
        client = MagicMock()
        client.get_all_notes.return_value = subs
        cfg = v1_config(decisions={"reply_suffix": "Meta_Review", "field": "recommendation"})
        papers = OpenReviewAPIClient(cfg, client).fetch_papers()
        client.get_all_notes.assert_called_once_with(
            invitation="ICLR.cc/2019/Conference/-/Blind_Submission", details="directReplies")
        assert [(p.title, p.selection) for p in papers] == [("One", "oral")]

    def test_extra_venues_on_v1_with_a_multi_string_selection(self):
        main = [v1_note("m1", "Main", venue="NeurIPS 2021 Poster")]
        r1 = [v1_note("d1", "DB One", venue="NeurIPS 2021 Datasets and Benchmarks Track (Round 1)")]
        r2 = [v1_note("d2", "DB Two", venue="NeurIPS 2021 Datasets and Benchmarks Track (Round 2)")]
        by_inv = {
            "NeurIPS.cc/2021/Conference/-/Blind_Submission": main,
            "NeurIPS.cc/2021/Track/Datasets_and_Benchmarks/Round1/-/Submission": r1,
            "NeurIPS.cc/2021/Track/Datasets_and_Benchmarks/Round2/-/Submission": r2,
        }
        client = MagicMock()
        client.get_all_notes.side_effect = lambda invitation, **kw: list(by_inv[invitation])
        cfg = v1_config(
            name="NeurIPS", year=2021, venue_id="NeurIPS.cc/2021/Conference", conference_id="neurips_2021",
            extra_venue_ids=["NeurIPS.cc/2021/Track/Datasets_and_Benchmarks/Round1",
                             "NeurIPS.cc/2021/Track/Datasets_and_Benchmarks/Round2"],
            selections={"poster": "NeurIPS 2021 Poster",
                        "datasets": ["NeurIPS 2021 Datasets and Benchmarks Track (Round 1)",
                                     "NeurIPS 2021 Datasets and Benchmarks Track (Round 2)"]})
        papers = OpenReviewAPIClient(cfg, client).fetch_papers()
        assert sorted((p.title, p.selection) for p in papers) == [
            ("DB One", "datasets"), ("DB Two", "datasets"), ("Main", "poster")]

    def test_duplicate_notes_collapse_to_the_earliest(self):
        client = MagicMock()
        client.get_all_notes.return_value = [
            v1_note("late", "Same Paper", venue="NeurIPS 2021 Poster", authors=["A", "B"], tcdate=20),
            v1_note("early", "Same  paper", venue="NeurIPS 2021 Poster", authors=["A", "B"], tcdate=10),
            v1_note("other", "Same Paper", venue="NeurIPS 2021 Poster", authors=["C"], tcdate=5),
        ]
        cfg = v1_config(selections={"poster": "NeurIPS 2021 Poster"})
        papers = OpenReviewAPIClient(cfg, client).fetch_papers()
        assert sorted(p.forum_id for p in papers) == ["early", "other"]

    def test_duplicates_with_different_labels_raise(self):
        a = (Paper(title="X", link="l", authors=["A"], selection="oral"), 1)
        b = (Paper(title="X", link="l", authors=["A"], selection="poster"), 2)
        with pytest.raises(DuplicateConflictError):
            collapse_duplicates([a, b])

    def test_collapse_reports_how_many(self):
        a = (Paper(title="X", link="l", authors=["A"], selection="oral"), 2)
        b = (Paper(title="X", link="l2", authors=["A"], selection="oral"), 1)
        papers, collapsed = collapse_duplicates([a, b])
        assert (len(papers), collapsed, papers[0].link) == (1, 1, "l2")

    def test_empty_crawl_message_survives_list_selections(self):
        client = MagicMock()
        client.get_all_notes.return_value = [v1_note("f1", venue="Something Else")]
        cfg = v1_config(selections={"datasets": ["R1", "R2"]})
        with pytest.raises(EmptyCrawlError, match="Something Else"):
            OpenReviewAPIClient(cfg, client).fetch_papers()


# --- publication-date split (one venueid shared by every year) ---

from datetime import date, datetime, timezone

from ppr.api_client import note_pdate


def _ms(iso):  # "2025-12-31T23:30:00" read as UTC
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def tmlr_config():
    return CrawlConfig(name="TMLR", year=2025, venue_id="TMLR",
                       selections={"main": "Accepted by TMLR"},
                       conference_id="tmlr_2025", year_from_pdate=True)


def test_note_pdate_is_utc():
    note = make_mock_note()
    note.pdate = _ms("2025-12-31T23:30:00")
    assert note_pdate(note) == date(2025, 12, 31)


def test_note_pdate_is_none_without_an_int():
    note = make_mock_note()
    note.pdate = None
    assert note_pdate(note) is None
    assert note_pdate(make_mock_note()) is None  # MagicMock attribute, not an int


def test_year_from_pdate_keeps_that_year_and_records_venue_date():
    notes = []
    for fid, iso in [("a", "2024-06-01T00:00:00"), ("b", "2025-02-03T10:00:00"),
                     ("c", "2025-12-31T23:30:00"), ("d", None)]:
        n = make_mock_note(fid, venue="Accepted by TMLR")
        n.pdate = _ms(iso) if iso else None
        notes.append(n)
    mock = MagicMock()
    mock.get_all_notes.return_value = notes
    papers = OpenReviewAPIClient(tmlr_config(), mock).fetch_papers()
    assert [(p.forum_id, p.venue_date, p.selection) for p in papers] == [
        ("b", "2025-02-03", "main"), ("c", "2025-12-31", "main")]
    mock.get_all_notes.assert_called_once_with(invitation="TMLR/-/Submission",
                                               content={"venueid": "TMLR"})


def test_without_year_from_pdate_venue_date_stays_empty():
    note = make_mock_note("x", venue="ICLR 2025 Oral")
    note.pdate = _ms("2025-04-01T00:00:00")
    mock = MagicMock()
    mock.get_all_notes.return_value = [note]
    (paper,) = OpenReviewAPIClient(make_config(), mock).fetch_papers()
    assert paper.venue_date == ""

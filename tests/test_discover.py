from ppr.discover import known_conference_ids, missing_years


class TestMissingYears:
    def test_proposes_the_next_year(self):
        assert missing_years("icse", "annual", {"icse_2023", "icse_2024", "icse_2025"}, 2026) == [2026, 2027]

    def test_fills_a_gap_in_the_middle(self):
        assert missing_years("acl", "annual", {"acl_2023", "acl_2025"}, 2025) == [2024, 2026]

    def test_up_to_date_venue_still_looks_ahead(self):
        assert missing_years("wacv", "annual", {"wacv_2025", "wacv_2026"}, 2026) == [2027]

    def test_biennial_odd_never_proposes_an_even_year(self):
        out = missing_years("iccv", "biennial-odd", {"iccv_2023", "iccv_2025"}, 2026)
        assert out == [2027]
        assert all(y % 2 == 1 for y in out)

    def test_biennial_even_never_proposes_an_odd_year(self):
        out = missing_years("eccv", "biennial-even", {"eccv_2024"}, 2026)
        assert out == [2026]
        assert all(y % 2 == 0 for y in out)

    def test_ignores_other_venues(self):
        assert missing_years("icse", "annual", {"acl_2023", "acl_2024"}, 2024) == []

    def test_no_known_years_yields_nothing(self):
        assert missing_years("icse", "annual", set(), 2026) == []

    def test_result_is_sorted_ascending(self):
        out = missing_years("acl", "annual", {"acl_2020", "acl_2023"}, 2024)
        assert out == sorted(out)


class TestKnownConferenceIds:
    def test_derives_from_committed_sources_not_data(self):
        """CI has no data/ directory, so this must not depend on one."""
        ids = known_conference_ids()
        assert "iclr_2026" in ids       # from configs/
        assert "usenix_security_2025" in ids  # from SCRAPERS
        assert "venues" not in ids      # the registry file is not a conference

    def test_covers_every_committed_source(self):
        """A lower bound, not an exact count -- later tasks register more."""
        from pathlib import Path

        from ppr.scrapers import SCRAPERS

        configs = Path(__file__).resolve().parent.parent / "configs"
        expected = {p.stem for p in configs.glob("*.yaml") if p.stem != "venues"}
        expected |= set(SCRAPERS.keys())
        assert known_conference_ids() == expected
        assert len(expected) >= 69


from unittest.mock import MagicMock, patch

import pytest
import requests

from ppr.dblp_client import DblpUnavailable
from ppr.discover import (
    MIN_LIVE_PAPERS,
    ProbeResult,
    probe,
)
from ppr.venues import Venue


def _venue(**kw) -> Venue:
    base = dict(
        prefix="cvpr", name="CVPR", source="cvf", cadence="annual",
        announce_month=2, probe={"url": "https://x.test/CVPR{year}"},
    )
    base.update(kw)
    return Venue(**base)


def _response(status=200, text="", headers=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.content = text.encode()
    # A real dict, not an auto-vivified MagicMock attribute: `.get(...)` on an
    # unconfigured MagicMock returns another MagicMock rather than `None`,
    # which would make Retry-After parsing see a bogus non-None value.
    r.headers = headers or {}
    return r


CVF_PAPER = '<dt class="ptitle"><a href="/p.html">A Paper</a></dt>'
USENIX_PAPER = '<article class="node-paper"><h2>A Paper</h2></article>'


class TestLiveFloor:
    def test_floor_is_fifty(self):
        """Pinned to a literal on purpose. Both floor tests below are written in
        terms of the constant, so lowering it would keep them green while making
        CVPR 2026's 9-link stub page read as `live` -- the false positive the
        floor exists to prevent."""
        assert MIN_LIVE_PAPERS == 50


class TestCvfProbe:
    def test_populated_page_is_live(self):
        with patch("ppr.discover.requests.get", return_value=_response(200, CVF_PAPER * 60)):
            r = probe(_venue(), 2025)
        assert r.status == "live"
        assert r.count == 60
        assert r.conf_id == "cvpr_2025"

    def test_stub_page_is_empty_not_live(self):
        """CVPR 2026 really returns 200 with a 3KB stub and zero papers."""
        with patch("ppr.discover.requests.get", return_value=_response(200, "<html>CVPR 2026 open access</html>")):
            r = probe(_venue(), 2026)
        assert r.status == "empty"
        assert r.count == 0

    def test_just_below_the_floor_is_empty(self):
        html = CVF_PAPER * (MIN_LIVE_PAPERS - 1)
        with patch("ppr.discover.requests.get", return_value=_response(200, html)):
            assert probe(_venue(), 2026).status == "empty"

    def test_exactly_at_the_floor_is_live(self):
        html = CVF_PAPER * MIN_LIVE_PAPERS
        with patch("ppr.discover.requests.get", return_value=_response(200, html)):
            assert probe(_venue(), 2026).status == "live"

    def test_404_with_a_large_body_is_not_yet(self):
        """WACV 2027 really returns 404 with a 29KB custom error page."""
        with patch("ppr.discover.requests.get", return_value=_response(404, "x" * 29000)):
            r = probe(_venue(), 2027)
        assert r.status == "not-yet"
        assert r.count == 0

    def test_network_failure_is_unreachable(self):
        with patch("ppr.discover.requests.get", side_effect=requests.RequestException("boom")):
            assert probe(_venue(), 2026).status == "unreachable"

    def test_ecva_marker_absent_is_not_yet(self):
        v = _venue(prefix="eccv", name="ECCV", cadence="biennial-even",
                   probe={"url": "https://ecva.test/papers.php", "marker": "ECCV {year}"})
        with patch("ppr.discover.requests.get", return_value=_response(200, "ECCV 2024 papers")):
            assert probe(v, 2026).status == "not-yet"

    def test_ecva_count_is_scoped_to_the_requested_year(self):
        """The ECVA page lists every ECCV year's papers on one page; the count
        must come from the requested year's accordion section, not the whole page."""
        html = (
            '<button class="accordion">ECCV 2024</button>'
            '<div class="accordion-content">' + CVF_PAPER * 40 + "</div>"
            '<button class="accordion">ECCV 2026</button>'
            '<div class="accordion-content">' + CVF_PAPER * 5 + "</div>"
        )
        v = _venue(prefix="eccv", name="ECCV", cadence="biennial-even",
                   probe={"url": "https://ecva.test/papers.php", "marker": "ECCV {year}"})
        with patch("ppr.discover.requests.get", return_value=_response(200, html)):
            r = probe(v, 2026)
        assert r.count == 5
        assert r.status == "empty"  # below MIN_LIVE_PAPERS, unlike the 40 in 2024's section

    def test_ecva_marker_present_but_no_matching_section_is_empty_not_not_yet(self):
        """The marker proves the year is on the page; a missing accordion section
        is a redesign the selector didn't survive, not an unpublished conference."""
        v = _venue(prefix="eccv", name="ECCV", cadence="biennial-even",
                   probe={"url": "https://ecva.test/papers.php", "marker": "ECCV {year}"})
        html = "<html>ECCV 2026 papers are up, but the accordion markup changed.</html>"
        with patch("ppr.discover.requests.get", return_value=_response(200, html)):
            r = probe(v, 2026)
        assert r.status == "empty"
        assert r.count == 0
        assert "did not parse" in r.note


class TestUsenixProbe:
    def test_populated_page_is_live(self):
        v = _venue(prefix="usenix_security", name="USENIX Security", source="usenix",
                   probe={"slug": "usenixsecurity{yy}"})
        with patch("ppr.discover.requests.get", return_value=_response(200, USENIX_PAPER * 381)) as g:
            r = probe(v, 2026)
        assert (r.status, r.count) == ("live", 381)
        assert "usenixsecurity26" in g.call_args[0][0]


def _rr_page(n, track="Research Track", conf="ICSE 2026"):
    rows = "".join(
        f'<tr><td><a href="#" data-event-modal="e{i}">Paper {i}</a>'
        f'<div class="prog-track">{track}</div><div class="performers">A</div></td></tr>'
        for i in range(n)
    )
    return (f"<html><head><title>{conf} - {track} - {conf}</title></head><body>"
            f'<div id="event-overview"><table>{rows}</table></div></body></html>')


class TestResearchrProbe:
    @pytest.fixture(autouse=True)
    def no_researchr_sleep(self, monkeypatch):
        monkeypatch.setattr("ppr.scrapers.researchr.time.sleep", lambda *_: None)

    def _venue(self):
        return _venue(prefix="icse", name="ICSE", source="researchr", announce_month=1,
                      probe={"conf": "icse", "track_slugs": ["research-track", "technical-track"]})

    def test_the_first_existing_slug_with_papers_is_live(self):
        with patch("ppr.scrapers.researchr.requests.get", return_value=_response(200, _rr_page(321))) as g:
            r = probe(self._venue(), 2026)
        assert (r.status, r.count) == ("live", 321)
        assert g.call_args.args[0] == "https://conf.researchr.org/track/icse-2026/icse-2026-research-track"

    def test_a_404_slug_falls_through_to_the_next(self):
        with patch("ppr.scrapers.researchr.requests.get",
                   side_effect=[_response(404), _response(200, _rr_page(207, "Technical Track"))]):
            r = probe(self._venue(), 2023)
        assert (r.status, r.count) == ("live", 207)
        assert r.url.endswith("icse-2023-technical-track")

    def test_every_slug_404_is_not_yet(self):
        with patch("ppr.scrapers.researchr.requests.get", return_value=_response(404)) as g:
            assert probe(self._venue(), 2028).status == "not-yet"
        assert g.call_count == 2

    def test_a_call_for_papers_page_is_empty_not_not_yet(self):
        """ICSE 2027's research-track page answers 200 in October 2026 with no
        accepted list. The page that exists decides; later slugs are not tried."""
        cfp = "<html><head><title>ICSE 2027 - Research Track - ICSE 2027</title></head><body>CFP</body></html>"
        with patch("ppr.scrapers.researchr.requests.get", return_value=_response(200, cfp)) as g:
            r = probe(self._venue(), 2027)
        assert (r.status, r.count) == ("empty", 0)
        assert g.call_count == 1

    def test_below_the_floor_is_empty(self):
        with patch("ppr.scrapers.researchr.requests.get",
                   return_value=_response(200, _rr_page(MIN_LIVE_PAPERS - 1))):
            assert probe(self._venue(), 2026).status == "empty"

    def test_a_server_error_is_unreachable(self):
        with patch("ppr.scrapers.researchr.requests.get", return_value=_response(503)):
            r = probe(self._venue(), 2026)
        assert r.status == "unreachable"
        assert "503" in r.note

    def test_network_failure_is_unreachable(self):
        with patch("ppr.scrapers.researchr.requests.get", side_effect=requests.ConnectionError()):
            assert probe(self._venue(), 2026).status == "unreachable"


class TestDblpProbe:
    """Candidate traversal and status mapping. Transport, retries and pacing
    belong to ppr/dblp_client.py and are tested there."""

    FSE = dict(prefix="fse", name="FSE", source="dblp", probe={"toc": [
        "db/conf/sigsoft/fse{year}.bht",
        {"key": "db/journals/pacmse/pacmse{pacmse_vol}.bht", "number": "FSE"},
    ]})

    def _icse(self):
        return _venue(prefix="icse", name="ICSE", source="dblp",
                      probe={"toc": "db/conf/icse/icse{year}.bht"})

    def test_hits_means_live(self):
        with patch("ppr.discover.dblp_client.toc_count", return_value=245) as c:
            out = probe(self._icse(), 2026)
        assert (out.status, out.count) == ("live", 245)
        assert c.call_args.args[0] == ["db/conf/icse/icse2026.bht"]

    def test_zero_hits_is_not_yet(self):
        with patch("ppr.discover.dblp_client.toc_count", return_value=0):
            assert probe(self._icse(), 2026).status == "not-yet"

    def test_falls_through_toc_candidates_until_one_has_hits(self):
        """FSE moved to shared PACMSE volumes; the old conf key is dead for 2024+."""
        with patch("ppr.discover.dblp_client.toc_count", side_effect=[0, 132]) as c:
            out = probe(_venue(**self.FSE), 2026)
        assert (out.status, out.count) == ("live", 132)
        # pacmse1 is 2024, so 2026 must resolve to volume 3 -- not the year.
        assert c.call_args_list[1].args[0] == ["db/journals/pacmse/pacmse3.bht"]
        assert c.call_args_list[1].kwargs["number"] == "FSE"

    def test_stops_at_the_first_candidate_with_hits(self):
        with patch("ppr.discover.dblp_client.toc_count", return_value=206) as c:
            out = probe(_venue(**self.FSE), 2023)
        assert out.count == 206
        assert c.call_count == 1

    def test_all_candidates_empty_is_not_yet(self):
        with patch("ppr.discover.dblp_client.toc_count", return_value=0):
            assert probe(_venue(**self.FSE), 2027).status == "not-yet"

    def test_unavailable_is_unreachable_with_the_reason(self):
        with patch("ppr.discover.dblp_client.toc_count",
                   side_effect=DblpUnavailable("bot challenge (HTTP 202)")):
            out = probe(self._icse(), 2026)
        assert out.status == "unreachable"
        assert "bot challenge" in out.note

    def test_unreachable_first_candidate_is_not_papered_over_by_second_candidate(self):
        """Falling through to a second candidate's `not-yet` would turn an
        unanswered DBLP into a false "nothing new"."""
        with patch("ppr.discover.dblp_client.toc_count",
                   side_effect=DblpUnavailable("HTTP 429 after 5 attempts")) as c:
            out = probe(_venue(**self.FSE), 2026)
        assert out.status == "unreachable"
        assert c.call_count == 1


class TestOpenreviewProbe:
    def _venue(self):
        return _venue(prefix="iclr", name="ICLR", source="openreview",
                      probe={"venue_id": "ICLR.cc/{year}/Conference"})

    def test_notes_means_live(self):
        client = MagicMock()
        client.get_all_notes.return_value = [MagicMock()] * 5340
        out = probe(self._venue(), 2026, openreview_client=client)
        assert (out.status, out.count) == ("live", 5340)
        client.get_all_notes.assert_called_once_with(
            content={"venueid": "ICLR.cc/2026/Conference"}
        )

    def test_no_notes_is_not_yet(self):
        client = MagicMock()
        client.get_all_notes.return_value = []
        assert probe(self._venue(), 2027, openreview_client=client).status == "not-yet"

    def test_missing_client_is_unreachable_with_a_credentials_note(self):
        """No secret in CI must degrade coverage, not read as 'nothing new'."""
        out = probe(self._venue(), 2026, openreview_client=None)
        assert out.status == "unreachable"
        assert "credential" in out.note.lower()

    def test_api_error_is_unreachable(self):
        client = MagicMock()
        client.get_all_notes.side_effect = Exception("ChallengeRequiredError")
        assert probe(self._venue(), 2026, openreview_client=client).status == "unreachable"


class TestManualSources:
    @pytest.mark.parametrize("source", ["acl", "aaai", "bespoke"])
    def test_always_needs_manual_never_live(self, source):
        v = _venue(prefix="acl", name="ACL", source=source,
                   probe={"url": "https://{year}.aclweb.org/"})
        with patch("ppr.discover.requests.get", return_value=_response(200, CVF_PAPER * 500)):
            out = probe(v, 2026)
        assert out.status == "needs-manual"
        assert out.url == "https://2026.aclweb.org/"

    def test_makes_no_request_at_all(self):
        v = _venue(prefix="aaai", name="AAAI", source="aaai", probe={"url": "https://x.test/"})
        with patch("ppr.discover.requests.get") as g:
            probe(v, 2027)
        assert g.call_count == 0


import json as _json

from ppr.discover import (
    discover,
    format_discover_table,
    results_to_json,
    stale_empty,
)


def _pr(conf_id, status, count=0, prefix=None, year=2026, note=""):
    return ProbeResult(
        conf_id=conf_id, prefix=prefix or conf_id.rsplit("_", 1)[0],
        year=year, status=status, count=count, url="https://x.test", note=note,
    )


class TestDiscoverSweep:
    def test_probes_every_missing_year_of_every_venue(self):
        reg = {
            "icse": Venue("icse", "ICSE", "dblp", "annual", {"toc": "t{year}"}, 12),
            "acl": Venue("acl", "ACL", "acl", "annual", {"url": "u{year}"}, 5),
        }
        known = {"icse_2025", "acl_2025"}
        with patch("ppr.discover.probe", side_effect=lambda v, y, **k: _pr(f"{v.prefix}_{y}", "not-yet")) as p:
            out = discover(reg, known, 2026)
        assert {c.args[1] for c in p.call_args_list} == {2026, 2027}
        assert len(out) == 4

    def test_venue_with_nothing_registered_is_skipped(self):
        reg = {"new": Venue("new", "New", "dblp", "annual", {"toc": "t{year}"}, 1)}
        with patch("ppr.discover.probe") as p:
            assert discover(reg, set(), 2026) == []
        assert p.call_count == 0

    def test_openreview_client_is_forwarded(self):
        reg = {"iclr": Venue("iclr", "ICLR", "openreview", "annual", {"venue_id": "v{year}"}, 1)}
        client = MagicMock()
        with patch("ppr.discover.probe", return_value=_pr("iclr_2027", "not-yet")) as p:
            discover(reg, {"iclr_2026"}, 2026, openreview_client=client)
        assert p.call_args.kwargs["openreview_client"] is client

    def test_missing_credentials_do_not_abort_the_sweep(self):
        """No OpenReview secret in CI must degrade coverage, not end the run."""
        reg = {
            "iclr": Venue("iclr", "ICLR", "openreview", "annual", {"venue_id": "v{year}"}, 1),
            "icse": Venue("icse", "ICSE", "dblp", "annual", {"toc": "t{year}"}, 12),
        }
        with patch("ppr.discover._probe_dblp", return_value=_pr("icse_2026", "live", 245)):
            out = discover(reg, {"iclr_2025", "icse_2025"}, 2025, openreview_client=None)
        by_status = {r.prefix: r.status for r in out}
        assert by_status["iclr"] == "unreachable"
        assert by_status["icse"] == "live"


class TestStaleEmpty:
    def test_flags_empty_past_the_announce_month(self):
        reg = {"cvpr": Venue("cvpr", "CVPR", "cvf", "annual", {"url": "u"}, 2)}
        out = stale_empty([_pr("cvpr_2026", "empty")], reg, today_month=7, today_year=2026)
        assert [r.conf_id for r in out] == ["cvpr_2026"]

    def test_ignores_empty_before_the_announce_month(self):
        reg = {"wacv": Venue("wacv", "WACV", "cvf", "annual", {"url": "u"}, 10)}
        out = stale_empty([_pr("wacv_2026", "empty")], reg, today_month=7, today_year=2026)
        assert out == []

    def test_ignores_non_empty_statuses(self):
        reg = {"cvpr": Venue("cvpr", "CVPR", "cvf", "annual", {"url": "u"}, 2)}
        results = [_pr("cvpr_2026", "not-yet"), _pr("cvpr_2026", "live", 2000)]
        assert stale_empty(results, reg, today_month=12, today_year=2026) == []

    def test_ignores_a_candidate_from_a_future_year(self):
        """`missing_years` always proposes next year, and a stub page for a
        conference that has not happened yet is the ordinary pre-publication
        state -- never evidence of a selector the site outgrew. Comparing only
        months would flag every next-year candidate from March onward."""
        reg = {"cvpr": Venue("cvpr", "CVPR", "cvf", "annual", {"url": "u"}, 2)}
        results = [_pr("cvpr_2027", "empty", year=2027)]
        assert stale_empty(results, reg, today_month=12, today_year=2026) == []

    def test_still_flags_the_current_year_late_in_it(self):
        """The guard against next-year candidates must not silence the signal
        it exists to carry: this year's venue, months past its announce month."""
        reg = {"cvpr": Venue("cvpr", "CVPR", "cvf", "annual", {"url": "u"}, 2)}
        results = [_pr("cvpr_2026", "empty", year=2026)]
        out = stale_empty(results, reg, today_month=12, today_year=2026)
        assert [r.conf_id for r in out] == ["cvpr_2026"]


class TestOutputFormats:
    def test_table_shows_every_status_and_count(self):
        out = format_discover_table([
            _pr("usenix_security_2026", "live", 381),
            _pr("cvpr_2026", "empty"),
            _pr("acl_2026", "needs-manual"),
        ])
        assert "usenix_security_2026" in out and "381" in out
        assert "live" in out and "empty" in out and "needs-manual" in out

    def test_table_reports_when_nothing_is_live(self):
        assert "no new" in format_discover_table([_pr("cvpr_2026", "not-yet")]).lower()

    def test_json_round_trips_every_field(self):
        payload = _json.loads(results_to_json([_pr("usenix_security_2026", "live", 381, note="n")]))
        row = payload["results"][0]
        assert row == {
            "conf_id": "usenix_security_2026", "prefix": "usenix_security",
            "year": 2026, "status": "live", "count": 381,
            "url": "https://x.test", "note": "n", "registration": {},
        }
        assert payload["live_count"] == 1

    def test_json_is_valid_when_empty(self):
        payload = _json.loads(results_to_json([]))
        assert payload["results"] == []
        assert payload["live_count"] == 0
        assert payload["stale_empty"] == []

    def test_json_carries_stale_empty_for_the_workflow(self):
        """The workflow is JS and cannot recompute this -- it must arrive in the JSON."""
        stale = [_pr("cvpr_2026", "empty")]
        payload = _json.loads(results_to_json([_pr("cvpr_2026", "empty")], stale=stale))
        assert payload["stale_empty"] == ["cvpr_2026"]


class TestVenueFilter:
    def _args(self, venues):
        import argparse

        return argparse.Namespace(venue=venues, json=False, username=None, password=None)

    def test_unknown_prefix_raises_instead_of_sweeping_nothing(self):
        """A typo'd --venue used to filter the registry down to {}, probe
        nothing, and print "no new lists ready to register" -- one character
        producing the exact false negative the status taxonomy exists to
        prevent. It must fail loudly instead."""
        from ppr.cli import cmd_discover

        with patch("ppr.discover.discover") as swept:
            with pytest.raises(SystemExit) as exc:
                cmd_discover(self._args(["cvrp"]))
        assert "cvrp" in str(exc.value)
        assert swept.call_count == 0

    def test_names_every_unknown_prefix_not_just_the_first(self):
        from ppr.cli import cmd_discover

        with patch("ppr.discover.discover", return_value=[]):
            with pytest.raises(SystemExit) as exc:
                cmd_discover(self._args(["cvrp", "cvpr", "nuerips"]))
        assert "cvrp" in str(exc.value) and "nuerips" in str(exc.value)

    def test_known_prefix_still_narrows_the_sweep(self):
        from ppr.cli import cmd_discover

        with patch("ppr.discover.discover", return_value=[]) as swept:
            cmd_discover(self._args(["cvpr"]))
        assert swept.call_count == 1
        assert set(swept.call_args.args[0]) == {"cvpr"}


class TestCliWiring:
    def test_discover_subcommand_exists(self):
        from ppr.cli import build_parser
        args = build_parser().parse_args(["discover"])
        assert args.command == "discover"
        assert args.json is False
        assert args.venue == []

    def test_json_and_venue_flags(self):
        from ppr.cli import build_parser
        args = build_parser().parse_args(["discover", "--json", "--venue", "cvpr", "--venue", "iclr"])
        assert args.json is True
        assert args.venue == ["cvpr", "iclr"]


class TestProbeRegistration:
    """Each probe records what it matched, so autoregister never reconstructs it."""

    def test_cvf_openaccess(self):
        with patch("ppr.discover.requests.get", return_value=_response(200, CVF_PAPER * 60)):
            r = probe(_venue(), 2027)
        assert r.registration == {"url": "https://x.test/CVPR2027", "parser": "openaccess"}

    def test_ecva_carries_parser_and_year(self):
        v = _venue(prefix="eccv", name="ECCV", cadence="biennial-even",
                   probe={"url": "https://www.ecva.net/papers.php", "marker": "ECCV {year}"})
        html = (
            'ECCV 2026<button class="accordion">ECCV 2026 Papers</button>'
            '<div class="accordion-content">' + CVF_PAPER * 60 + "</div>"
        )
        with patch("ppr.discover.requests.get", return_value=_response(200, html)):
            r = probe(v, 2026)
        assert r.status == "live"
        assert r.registration == {
            "url": "https://www.ecva.net/papers.php", "parser": "ecva", "year": 2026,
        }

    def test_usenix_slug(self):
        v = _venue(prefix="usenix_security", name="USENIX Security", source="usenix",
                   probe={"slug": "usenixsecurity{yy}"})
        with patch("ppr.discover.requests.get", return_value=_response(200, USENIX_PAPER * 381)):
            r = probe(v, 2027)
        assert r.registration == {"slug": "usenixsecurity27"}

    def test_dblp_plain_key(self):
        v = _venue(prefix="icse", name="ICSE", source="dblp",
                   probe={"toc": "db/conf/icse/icse{year}.bht"})
        with patch("ppr.discover.dblp_client.toc_count", return_value=245):
            r = probe(v, 2026)
        assert r.registration == {"key": "db/conf/icse/icse2026.bht"}

    def test_dblp_pacmse_key_carries_number(self):
        v = _venue(prefix="fse", name="FSE", source="dblp", probe={"toc": [
            {"key": "db/journals/pacmse/pacmse{pacmse_vol}.bht", "number": "FSE"},
        ]})
        with patch("ppr.discover.dblp_client.toc_count", return_value=2):
            r = probe(v, 2026)
        assert r.registration == {"key": "db/journals/pacmse/pacmse3.bht", "number": "FSE"}

    def test_openreview_venue_id(self):
        v = _venue(prefix="colm", name="COLM", source="openreview",
                   probe={"venue_id": "colmweb.org/COLM/{year}/Conference"})
        client = MagicMock()
        client.get_all_notes.return_value = [MagicMock()] * 856
        r = probe(v, 2026, openreview_client=client)
        assert r.registration == {"venue_id": "colmweb.org/COLM/2026/Conference"}

    def test_unreachable_has_no_registration(self):
        with patch("ppr.discover.requests.get", side_effect=requests.ConnectionError()):
            r = probe(_venue(), 2027)
        assert r.registration == {}

    def test_researchr_url_and_track(self, monkeypatch):
        monkeypatch.setattr("ppr.scrapers.researchr.time.sleep", lambda *_: None)
        v = _venue(prefix="ase", name="ASE", source="researchr",
                   probe={"conf": "ase", "track_slugs": ["research-track"]})
        with patch("ppr.scrapers.researchr.requests.get",
                   return_value=_response(200, _rr_page(263, "Research Papers", "ASE 2026"))):
            r = probe(v, 2026)
        assert r.registration == {
            "url": "https://conf.researchr.org/track/ase-2026/ase-2026-research-track",
            "track": "Research Papers",
        }

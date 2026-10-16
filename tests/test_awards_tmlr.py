"""TMLR certifications read from OpenReview notes (no network: notes are built here)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ppr.awards import tmlr_certifications as mod
from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.tmlr_certifications import SOURCE_URL, certification_awards, tmlr_certifications


def _note(forum, iso, certs=None, title=None):
    pdate = int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    content = {"title": {"value": title or f"Paper {forum}"}}
    if certs is not None:
        content["certifications"] = {"value": certs}
    return SimpleNamespace(forum=forum, pdate=pdate, content=content)


def test_certification_awards_by_year():
    notes = [_note("A", "2025-03-01", ["Featured Certification"]),
             _note("B", "2025-04-01", ["Outstanding Certification", "Featured Certification"]),
             _note("C", "2025-05-01", ["J2C Certification"]),
             _note("D", "2024-05-01", ["Featured Certification"]),
             _note("E", "2025-06-01")]
    awards = certification_awards(notes, 2025)
    assert [(a.forum_id, a.kind, a.label) for a in awards] == [
        ("A", "honorable", "Featured Certification"), ("B", "award", "Outstanding Certification")]
    assert all(a.via == "tmlr" and a.source == SOURCE_URL and a.title for a in awards)


def test_an_unknown_certification_raises():
    with pytest.raises(UnknownAwardLabel):
        certification_awards([_note("X", "2025-01-01", ["Spotlight Certification"])], 2025)


def test_no_accepted_papers_is_an_error_not_an_empty_year(monkeypatch):
    client = SimpleNamespace(get_all_notes=lambda **kw: [])
    monkeypatch.setattr(mod, "create_openreview_client", lambda: client)
    mod._accepted_notes.cache_clear()
    try:
        with pytest.raises(ValueError):
            tmlr_certifications("tmlr_2025", 2025, [])
    finally:
        mod._accepted_notes.cache_clear()


def test_tmlr_certifications_reads_the_cached_fetch(monkeypatch):
    monkeypatch.setattr(mod, "_accepted_notes", lambda: [_note("A", "2025-03-01", ["Outstanding Certification"])])
    assert [a.forum_id for a in tmlr_certifications("tmlr_2025", 2025, [])] == ["A"]

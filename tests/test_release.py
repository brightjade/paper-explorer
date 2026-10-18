import json
import zipfile

import pytest

from ppr.release import (
    KEEP,
    ReleaseAborted,
    data_releases,
    make_zip,
    next_tag,
    publish,
    render_notes,
)


class FakeGh:
    def __init__(self, releases, fail_on=()):
        self.releases = releases  # list of (tag, publishedAt[, isDraft])
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, cmd):
        self.calls.append(cmd)
        if any(cmd[:3] == list(f) for f in self.fail_on):
            raise RuntimeError("gh failed")
        if cmd[:3] == ["gh", "release", "list"]:
            return json.dumps([{"tagName": r[0], "publishedAt": r[1], "isDraft": len(r) > 2 and r[2]}
                                    for r in self.releases])
        return ""

    def verbs(self):
        return [(c[2], c[3]) for c in self.calls if c[:2] == ["gh", "release"] and c[2] != "list"]


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "iclr_2025").mkdir(parents=True)
    (d / "iclr_2025" / "papers.jsonl").write_text("{}\n")
    (d / "iclr_2025" / ".papers_enriched.tmp.jsonl").write_text("{}\n")
    (d / "citation_updated.txt").write_text("2026-11-03\n")
    return d


RELEASES = [("data-2026-10-03", "2026-10-03T00:00:00Z"),
            ("v1.0", "2026-10-05T00:00:00Z"),
            ("data-2026-09-03", "2026-09-03T00:00:00Z"),
            ("data-2026-08-05", "2026-08-05T00:00:00Z")]


class TestDataReleases:
    def test_ignores_other_tags_and_sorts_by_publication(self):
        gh = FakeGh(list(reversed(RELEASES)))  # listed oldest first on purpose
        assert data_releases(gh) == ["data-2026-10-03", "data-2026-09-03", "data-2026-08-05"]
        [list_call] = gh.calls
        assert "publishedAt" in list_call[list_call.index("--json") + 1]

    @pytest.mark.parametrize("order", [1, -1])
    def test_releases_made_from_one_commit_are_ordered_by_publication(self, order):
        # GitHub's createdAt is the tagged commit's date, so two releases made from
        # one commit tie on it (data-2026-10-17-2 and -3, which aborted run
        # 39038452486's release); publishedAt does not.
        rows = [{"tagName": "data-2026-10-17-2", "createdAt": "2026-10-16T12:06:30Z",
                 "publishedAt": "2026-10-17T07:41:27Z", "isDraft": False},
                {"tagName": "data-2026-10-17-3", "createdAt": "2026-10-16T12:06:30Z",
                 "publishedAt": "2026-10-17T11:38:45Z", "isDraft": False}][::order]
        assert data_releases(lambda cmd: json.dumps(rows))[0] == "data-2026-10-17-3"


class TestDrafts:
    def test_draft_data_release_is_ignored(self):
        gh = FakeGh([*RELEASES, ("data-2026-10-20", "2026-10-20T00:00:00Z", True)])
        assert data_releases(gh)[0] == "data-2026-10-03"

    def test_draft_newer_than_base_does_not_abort_publish(self, data_dir, tmp_path):
        gh = FakeGh([*RELEASES, ("data-2026-10-20", "2026-10-20T00:00:00Z", True)])
        tag = publish(data_dir, "data-2026-10-03", "n", "2026-11-03", gh, zip_path=tmp_path / "d.zip")
        assert tag == "data-2026-11-03"


class TestNextTag:
    def test_plain(self):
        assert next_tag("2026-11-03", {"data-2026-10-03"}) == "data-2026-11-03"

    def test_suffixes_on_collision(self):
        assert next_tag("2026-11-03", {"data-2026-11-03", "data-2026-11-03-2"}) == "data-2026-11-03-3"


class TestMakeZip:
    def test_paths_are_rooted_at_data_and_checkpoints_are_excluded(self, data_dir, tmp_path):
        z = tmp_path / "data.zip"
        make_zip(data_dir, z)
        names = set(zipfile.ZipFile(z).namelist())
        assert "data/iclr_2025/papers.jsonl" in names
        assert "data/citation_updated.txt" in names
        assert not any(n.endswith(".tmp.jsonl") for n in names)


class TestPublish:
    def test_aborts_when_someone_released_during_the_run(self, data_dir, tmp_path):
        gh = FakeGh(RELEASES)
        with pytest.raises(ReleaseAborted, match="data-2026-10-03"):
            publish(data_dir, "data-2026-09-03", "n", "2026-11-03", gh, zip_path=tmp_path / "d.zip")
        assert gh.verbs() == []

    def test_aborts_when_there_is_no_data_release(self, data_dir, tmp_path):
        with pytest.raises(ReleaseAborted):
            publish(data_dir, "data-2026-10-03", "n", "2026-11-03", FakeGh([]), zip_path=tmp_path / "d.zip")

    def test_creates_before_pruning_and_keeps_three(self, data_dir, tmp_path):
        gh = FakeGh(RELEASES)
        tag = publish(data_dir, "data-2026-10-03", "n", "2026-11-03", gh, zip_path=tmp_path / "d.zip")
        assert tag == "data-2026-11-03"
        assert gh.verbs() == [("create", "data-2026-11-03"), ("delete", "data-2026-08-05")]
        create = next(c for c in gh.calls if c[2] == "create")
        assert "--latest" in create
        assert KEEP == 3

    def test_failed_create_deletes_nothing(self, data_dir, tmp_path):
        gh = FakeGh(RELEASES, fail_on=[("gh", "release", "create")])
        with pytest.raises(RuntimeError):
            publish(data_dir, "data-2026-10-03", "n", "2026-11-03", gh, zip_path=tmp_path / "d.zip")
        assert [v for v, _ in gh.verbs()] == ["create"]

    def test_failed_prune_is_not_fatal(self, data_dir, tmp_path):
        gh = FakeGh(RELEASES, fail_on=[("gh", "release", "delete")])
        assert publish(data_dir, "data-2026-10-03", "n", "2026-11-03", gh,
                       zip_path=tmp_path / "d.zip") == "data-2026-11-03"

    def test_dry_run_touches_nothing(self, data_dir, tmp_path):
        gh = FakeGh(RELEASES)
        publish(data_dir, "data-2026-10-03", "n", "2026-11-03", gh,
                zip_path=tmp_path / "d.zip", dry_run=True)
        assert gh.verbs() == []
        assert not (tmp_path / "d.zip").exists()


class TestRenderNotes:
    def test_lists_additions_holds_and_match_counts(self, data_dir):
        (data_dir / "iclr_2025" / "papers_enriched.jsonl").write_text(
            json.dumps({"title": "A", "link": "L", "authors": [], "match_status": "matched"}) + "\n"
            + json.dumps({"title": "B", "link": "L", "authors": [], "match_status": "not_found"}) + "\n"
        )
        notes = render_notes(
            "data-2026-10-03",
            {"outcomes": [{"conf_id": "colm_2026", "status": "registered", "count": 856},
                          {"conf_id": "x_2027", "status": "held", "reason": "r"}]},
            {"results": [{"conf_id": "iclr_2025", "status": "enriched", "deferred": 4}]},
            data_dir, "https://run",
        )
        assert "colm_2026 (856 papers)" in notes
        assert "x_2027" in notes
        assert "matched 1" in notes and "not_found 1" in notes and "deferred 4" in notes
        assert "data-2026-10-03" in notes and "https://run" in notes

import json
import zipfile

import pytest

from scripts.sync_data import STATE_FILE, SyncRefused, newest_data_tag, sync


def make_release_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


class FakeGitHub:
    """Stands in for the two network calls: the newest tag and its data.zip."""

    def __init__(self, tmp_path, tag, files):
        self.tmp_path = tmp_path
        self.tag = tag
        self.files = files
        self.downloads = 0

    def latest_tag(self):
        return self.tag

    def download(self, tag, dest):
        assert tag == self.tag
        self.downloads += 1
        make_release_zip(dest, self.files)


RELEASE_A = {
    "data/iclr_2025/papers.jsonl": "{}\n",
    "data/iclr_2025/papers_enriched.jsonl": "{}\n",
    "data/old_2023/papers.jsonl": "{}\n",
    "data/citation_updated.txt": "2026-10-14\n",
}
RELEASE_B = {
    "data/iclr_2025/papers.jsonl": "{}\n",
    "data/iclr_2025/papers_enriched.jsonl": '{"citation_count": 3}\n',
    "data/icse_2026/papers.jsonl": "{}\n",
    "data/citation_updated.txt": "2026-11-03\n",
}


def installed(root, gh_a):
    sync(root, gh_a.latest_tag, gh_a.download)
    return root


def tree(root):
    data = root / "data"
    return {p.relative_to(root).as_posix(): p.read_text() for p in data.rglob("*") if p.is_file()}


class TestNewestDataTag:
    def test_picks_newest_non_draft_data_release(self):
        releases = [
            {"tag_name": "data-2026-10-14", "published_at": "2026-10-14T11:20:30Z", "draft": False},
            {"tag_name": "v1.0", "published_at": "2026-12-01T00:00:00Z", "draft": False},
            {"tag_name": "data-2026-11-03", "published_at": None, "draft": True},
            {"tag_name": "data-2026-10-15", "published_at": "2026-10-15T06:30:40Z", "draft": False},
        ]
        assert newest_data_tag(releases) == "data-2026-10-15"

    def test_no_data_release_is_an_error(self):
        with pytest.raises(RuntimeError):
            newest_data_tag([{"tag_name": "v1.0", "published_at": "2026-01-01T00:00:00Z", "draft": False}])

    @pytest.mark.parametrize("order", [1, -1])
    def test_releases_made_from_one_commit_are_ordered_by_publication(self, order):
        # GitHub's created_at is the tagged commit's date, so two releases made
        # from one commit tie on it (data-2026-10-17-2 and -3); published_at does not.
        releases = [
            {"tag_name": "data-2026-10-17-2", "created_at": "2026-10-16T12:06:30Z",
             "published_at": "2026-10-17T07:41:27Z", "draft": False},
            {"tag_name": "data-2026-10-17-3", "created_at": "2026-10-16T12:06:30Z",
             "published_at": "2026-10-17T11:38:45Z", "draft": False},
        ][::order]
        assert newest_data_tag(releases) == "data-2026-10-17-3"


class TestSync:
    def test_installs_into_an_absent_data_dir(self, tmp_path):
        gh = FakeGitHub(tmp_path, "data-2026-10-14", RELEASE_A)
        assert sync(tmp_path, gh.latest_tag, gh.download) == ("updated", None, "data-2026-10-14")
        assert tree(tmp_path) == RELEASE_A
        assert json.loads((tmp_path / STATE_FILE).read_text())["tag"] == "data-2026-10-14"

    def test_same_tag_does_not_download(self, tmp_path):
        gh = FakeGitHub(tmp_path, "data-2026-10-14", RELEASE_A)
        installed(tmp_path, gh)
        assert sync(tmp_path, gh.latest_tag, gh.download) == ("current", "data-2026-10-14", "data-2026-10-14")
        assert gh.downloads == 1

    def test_new_release_replaces_data_exactly(self, tmp_path):
        installed(tmp_path, FakeGitHub(tmp_path, "data-2026-10-14", RELEASE_A))
        gh = FakeGitHub(tmp_path, "data-2026-11-03", RELEASE_B)
        assert sync(tmp_path, gh.latest_tag, gh.download) == ("updated", "data-2026-10-14", "data-2026-11-03")
        # old_2023 is gone: data/ mirrors the release, it does not accumulate
        assert tree(tmp_path) == RELEASE_B
        assert not any(p.name.startswith(".data-sync") for p in tmp_path.iterdir())

    @pytest.mark.parametrize("edit", ["change", "add", "delete"])
    def test_local_edits_are_never_overwritten(self, tmp_path, edit):
        installed(tmp_path, FakeGitHub(tmp_path, "data-2026-10-14", RELEASE_A))
        data = tmp_path / "data"
        if edit == "change":
            (data / "iclr_2025" / "papers_enriched.jsonl").write_text('{"local": 1}\n')
        elif edit == "add":
            (data / "iclr_2025" / "papers_enriched.tmp.jsonl").write_text("{}\n")
        else:
            (data / "old_2023" / "papers.jsonl").unlink()
        before = tree(tmp_path)
        gh = FakeGitHub(tmp_path, "data-2026-11-03", RELEASE_B)
        with pytest.raises(SyncRefused):
            sync(tmp_path, gh.latest_tag, gh.download)
        assert tree(tmp_path) == before
        assert gh.downloads == 0

    def test_data_not_installed_by_sync_needs_force(self, tmp_path):
        (tmp_path / "data" / "x_2025").mkdir(parents=True)
        (tmp_path / "data" / "x_2025" / "papers.jsonl").write_text("mine\n")
        gh = FakeGitHub(tmp_path, "data-2026-10-14", RELEASE_A)
        with pytest.raises(SyncRefused):
            sync(tmp_path, gh.latest_tag, gh.download)
        assert sync(tmp_path, gh.latest_tag, gh.download, force=True)[0] == "updated"
        assert tree(tmp_path) == RELEASE_A

    @pytest.mark.parametrize("files", [
        {"data/a_2025/papers.jsonl": "{}\n", "../escape.txt": "x"},
        {"data/a_2025/papers.jsonl": "{}\n", "README.md": "x"},
        {"data/citation_updated.txt": "2026-10-14\n"},  # no conference data at all
    ])
    def test_a_bad_zip_leaves_data_untouched(self, tmp_path, files):
        installed(tmp_path, FakeGitHub(tmp_path, "data-2026-10-14", RELEASE_A))
        gh = FakeGitHub(tmp_path, "data-2026-11-03", files)
        with pytest.raises(RuntimeError):
            sync(tmp_path, gh.latest_tag, gh.download)
        assert tree(tmp_path) == RELEASE_A
        assert json.loads((tmp_path / STATE_FILE).read_text())["tag"] == "data-2026-10-14"
        assert not (tmp_path / "escape.txt").exists()

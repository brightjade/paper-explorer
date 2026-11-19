import multiprocessing
import shutil
import time
import urllib.error
from pathlib import Path

import pytest

from ppr import data_home, layout
from ppr.data_sync import sync
from tests.release_helpers import FakeGitHub, make_release_zip

REL_A = {"data/iclr/2025.jsonl": "{}\n"}
REL_B = {"data/iclr/2025.jsonl": '{"citation_count": 3}\n', "data/icml/2026.jsonl": "{}\n"}
DAY = data_home.CHECK_INTERVAL


def boom(*args, **kwargs):
    raise AssertionError("the network was touched")


def raising(exc):
    def fail(*args, **kwargs):
        raise exc
    return fail


def seed(root, tag, files=REL_A, checked_at=None):
    gh = FakeGitHub(root, tag, files)
    sync(root, gh.latest_tag, gh.download)
    if checked_at is not None:
        (root / data_home.CHECK_FILE).write_text(str(checked_at))
    return root


def ensure(root, said, *, latest_tag, download, now, auto_update=True):
    data_home.ensure_data(root, auto_update=auto_update, say=said.append, latest_tag=latest_tag,
                          download=download, now=lambda: now)


def test_no_data_downloads_and_says_so(tmp_path):
    gh, said = FakeGitHub(tmp_path, "data-2026-11-03", REL_A), []
    ensure(tmp_path / "h", said, latest_tag=gh.latest_tag, download=gh.download, now=1000.0)
    assert data_home.has_data(tmp_path / "h") and gh.downloads == 1
    assert any("downloading data release data-2026-11-03" in s for s in said)
    assert data_home.installed_tag(tmp_path / "h") == "data-2026-11-03"


def test_no_data_and_auto_update_off_is_unavailable(tmp_path):
    with pytest.raises(data_home.DataUnavailable, match="ppr data update"):
        ensure(tmp_path, [], latest_tag=boom, download=boom, now=1000.0, auto_update=False)


def test_no_data_and_no_network_is_unavailable(tmp_path):
    with pytest.raises(data_home.DataUnavailable, match="could not download"):
        ensure(tmp_path, [], latest_tag=raising(urllib.error.URLError("offline")), download=boom, now=1000.0)


def test_fresh_check_makes_no_network_call(tmp_path):
    seed(tmp_path, "data-2026-10-19", checked_at=1000.0 - 10)
    ensure(tmp_path, [], latest_tag=boom, download=boom, now=1000.0)


def test_auto_update_off_with_data_makes_no_network_call(tmp_path):
    seed(tmp_path, "data-2026-10-19", checked_at=0.0)
    ensure(tmp_path, [], latest_tag=boom, download=boom, now=10 * DAY, auto_update=False)


def test_stale_check_same_tag_records_time(tmp_path):
    seed(tmp_path, "data-2026-10-19", checked_at=0.0)
    gh, said = FakeGitHub(tmp_path, "data-2026-10-19", REL_A), []
    ensure(tmp_path, said, latest_tag=gh.latest_tag, download=gh.download, now=2 * DAY)
    assert gh.downloads == 0 and said == []
    assert data_home.check_due(tmp_path, 2 * DAY + 60) is False


def test_missing_check_file_is_due(tmp_path):
    seed(tmp_path, "data-2026-10-19")
    assert data_home.check_due(tmp_path, 1000.0)


def test_stale_check_newer_tag_updates(tmp_path):
    seed(tmp_path, "data-2026-10-19", checked_at=0.0)
    gh, said = FakeGitHub(tmp_path, "data-2026-11-03", REL_B), []
    ensure(tmp_path, said, latest_tag=gh.latest_tag, download=gh.download, now=2 * DAY)
    assert data_home.installed_tag(tmp_path) == "data-2026-11-03"
    assert (tmp_path / "data" / "icml" / "2026.jsonl").exists()
    assert "data updated: data-2026-10-19 -> data-2026-11-03" in said


def test_check_failure_warns_keeps_data_and_waits_a_day(tmp_path):
    seed(tmp_path, "data-2026-10-19", checked_at=0.0)
    said = []
    err = urllib.error.HTTPError("https://api.github.com", 403, "rate limited", {}, None)
    ensure(tmp_path, said, latest_tag=raising(err), download=boom, now=2 * DAY)
    assert said[-1].startswith("warning: could not update the data")
    assert "searching data-2026-10-19" in said[-1]
    assert data_home.check_due(tmp_path, 2 * DAY + 60) is False


def test_refused_zip_keeps_old_data_and_hints_upgrade(tmp_path):
    seed(tmp_path, "data-2026-10-19", checked_at=0.0)
    gh, said = FakeGitHub(tmp_path, "data-2026-11-03", {"data/readme.txt": "new layout\n"}), []
    ensure(tmp_path, said, latest_tag=gh.latest_tag, download=gh.download, now=2 * DAY)
    assert (tmp_path / "data" / "iclr" / "2025.jsonl").read_text() == "{}\n"
    assert data_home.installed_tag(tmp_path) == "data-2026-10-19"
    assert "uv tool upgrade ppr" in said[-1]


def test_interrupted_first_download_leaves_nothing_and_retries(tmp_path):
    def dies(tag, dest):
        dest.write_bytes(b"PK partial")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ensure(tmp_path, [], latest_tag=lambda: "data-2026-11-03", download=dies, now=1000.0)
    assert not data_home.has_data(tmp_path) and not (tmp_path / "data").exists()
    assert not list(tmp_path.glob(".data-sync-*"))
    gh = FakeGitHub(tmp_path, "data-2026-11-03", REL_A)
    ensure(tmp_path, [], latest_tag=gh.latest_tag, download=gh.download, now=1000.0)
    assert gh.downloads == 1 and data_home.has_data(tmp_path)


def _parallel_worker(home, log, zip_src, tag, out):
    def download(t, dest):
        with open(log, "a") as f:
            f.write(t + "\n")
        time.sleep(0.5)
        shutil.copy(zip_src, dest)

    with data_home.home_lock(Path(home), say=lambda s: None):
        data_home.ensure_data(Path(home), auto_update=True, say=lambda s: None, latest_tag=lambda: tag,
                              download=download, now=lambda: 1000.0)
    Path(out).write_text(str(data_home.has_data(Path(home))))


def test_parallel_first_run_downloads_once(tmp_path):
    zip_src, log, home = tmp_path / "rel.zip", tmp_path / "downloads.log", tmp_path / "h"
    make_release_zip(zip_src, REL_A)
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_parallel_worker,
                         args=(str(home), str(log), str(zip_src), "data-2026-11-03", str(tmp_path / f"out{i}")))
             for i in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    assert [p.exitcode for p in procs] == [0, 0, 0]
    assert log.read_text().splitlines() == ["data-2026-11-03"]
    assert [(tmp_path / f"out{i}").read_text() for i in range(3)] == ["True"] * 3


def test_busy_lock_says_it_is_waiting(tmp_path):
    said = []
    ctx = multiprocessing.get_context("spawn")
    ready = tmp_path / "ready"
    holder = ctx.Process(target=_hold_lock, args=(str(tmp_path), str(ready)))
    holder.start()
    deadline = time.time() + 30
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.05)
    with data_home.home_lock(tmp_path, say=said.append):
        pass
    holder.join(30)
    assert said and "waiting for another ppr process" in said[0]


def _hold_lock(root, ready):
    with data_home.home_lock(Path(root), say=lambda s: None):
        Path(ready).write_text("1")
        time.sleep(0.5)


def test_status_lists_venues_and_unknown(tmp_path):
    files = {f"data/iclr/{y}.jsonl": "{}\n" for y in (2023, 2024, 2025)} | {"data/zzz/2026.jsonl": "{}\n"}
    seed(tmp_path, "data-2026-11-03", files)
    st = data_home.status(layout.Home(tmp_path, True), "installed")
    assert st["tag"] == "data-2026-11-03" and st["venues"]["iclr"] == "2023–2025"
    assert st["unknown_venues"] == ["zzz"] and st["mode"] == "installed"
    assert st["last_check"] is None and st["disk_bytes"] > 0 and st["managed"] is True
    text = data_home.format_status(st)
    assert "data-2026-11-03" in text and "2023–2025" in text and "zzz" in text

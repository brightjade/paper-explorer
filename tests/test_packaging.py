"""What `uv tool install git+…` gets: the search side alone, with the venue registry, and no data."""

import re
import shutil
import subprocess
import tomllib
import zipfile

import pytest

from ppr.layout import ROOT

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")


def _names(requirements):
    return {re.split(r"[<>=\[ ;]", r)[0] for r in requirements}


def test_core_dependencies_are_the_search_side_only():
    assert _names(PYPROJECT["project"]["dependencies"]) == {"httpx", "pyyaml", "python-dotenv"}


def test_pipeline_group_is_installed_by_default_in_the_repo():
    group = _names(PYPROJECT["dependency-groups"]["pipeline"])
    assert group == {"openreview-py", "beautifulsoup4", "requests", "tqdm"}
    assert PYPROJECT["tool"]["uv"]["default-groups"] == ["dev", "pipeline"]


def test_console_script_is_the_entry_router():
    assert PYPROJECT["project"]["scripts"] == {"ppr": "ppr.entry:main"}


@needs_uv
def test_lock_is_current():
    assert subprocess.run(["uv", "lock", "--check"], cwd=ROOT, capture_output=True).returncode == 0


@needs_uv
def test_lean_environment_runs_the_client(tmp_path):
    def run(*args):
        return subprocess.run(["uv", "run", "--isolated", "--no-default-groups", "--project", str(ROOT), *args],
                              cwd=tmp_path, capture_output=True, text=True, timeout=600)

    assert run("python", "-c", "import openreview").returncode != 0
    probe = run("python", "-c", "import ppr.entry, ppr.client_cli, ppr.data_home, ppr.data_sync, "
                "ppr.search.find, ppr.search.lookup, ppr.search.cites, ppr.search.batch, "
                "ppr.search.verdicts, ppr.search.index")
    assert probe.returncode == 0, probe.stderr
    assert run("ppr", "search", "find", "--help").returncode == 0
    crawl = run("ppr", "crawl", "iclr_2025")
    assert crawl.returncode != 0 and "needs the repository environment" in crawl.stderr


@needs_uv
def test_wheel_carries_the_registry_and_no_data(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=ROOT, check=True,
                   capture_output=True)
    names = zipfile.ZipFile(next(tmp_path.glob("*.whl"))).namelist()
    assert "ppr/_venues.yaml" in names
    assert not [n for n in names if n.startswith(("data/", "configs/", "tests/", "web/", "scripts/"))]

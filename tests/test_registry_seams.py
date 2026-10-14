"""Registry seams: every place autoregister writes must leave the suite green.

Autoregister edits scraper dicts, configs and the README on the monthly run,
then step 4 runs the whole suite. A hand-maintained mirror of any of those
registries turns the first automatic registration into a failed run that
repeats every month. This test does what the writers do, in a scratch copy of
the checkout, and runs the registry-consistency tests there.
"""

import os
import shlex
import re
import subprocess
import sys
from pathlib import Path

import yaml

from ppr.cli import build_parser
from ppr.register import (
    register_cvf,
    register_dblp,
    register_usenix,
    render_openreview_config,
)
from ppr.readme_table import update_readme

ROOT = Path(__file__).resolve().parent.parent

CONSISTENCY_TESTS = [
    "tests/test_validate.py", "tests/test_dblp.py", "tests/test_cvf.py",
    "tests/test_discover.py", "tests/test_venues.py", "tests/test_register.py",
]


def _copy_checkout(dest: Path) -> None:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.split("\0")
    for rel in filter(None, files):
        if rel.startswith(("data/", "tests/workflow/")) or rel == "tests/test_registry_seams.py":
            continue
        src = ROOT / rel
        if not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())


def test_registering_one_venue_per_source_keeps_the_suite_green(tmp_path):
    _copy_checkout(tmp_path)
    scrapers = tmp_path / "ppr" / "scrapers"
    register_dblp("icse_2099", "db/conf/icse/icse2099.bht", scrapers / "dblp.py")
    register_cvf("cvpr_2099", "https://openaccess.thecvf.com/CVPR2099?day=all",
                 "openaccess", scrapers / "cvf.py")
    register_usenix("usenix_security_2099", "usenixsecurity99", scrapers / "usenix.py")
    (tmp_path / "configs" / "colm_2099.yaml").write_text(render_openreview_config(
        "COLM", 2099, "colmweb.org/COLM/2099/Conference", {"main": "COLM 2099"}))
    update_readme(tmp_path / "README.md", "ICSE", 2099, "main")

    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    existing = [t for t in CONSISTENCY_TESTS if (tmp_path / t).exists()]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *existing],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _ppr_commands(text: str) -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", text)
    return [m.group(0).strip() for m in re.finditer(r"uv run ppr [^\n]*", joined)]


def test_every_ppr_command_in_monthly_workflow_parses():
    text = (ROOT / ".github/workflows/monthly.yml").read_text()
    commands = _ppr_commands(text)
    assert len(commands) >= 6, commands
    for cmd in commands:
        cmd = cmd.replace('"${extra[@]}"', "")
        cmd = re.sub(r"\$\{\{[^}]*\}\}", "PLACEHOLDER", cmd)
        cmd = re.sub(r'"\$[A-Z_]+"', "PLACEHOLDER", cmd)
        cmd = cmd.split(">")[0] if "> " in cmd else cmd  # drop shell redirection
        argv = shlex.split(cmd)
        assert argv[:3] == ["uv", "run", "ppr"], cmd
        build_parser().parse_args(argv[3:])

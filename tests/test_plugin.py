"""The Claude Code plugin this repository serves: its marketplace, and the two skills an installed ppr backs."""

import json
import shutil
import subprocess

import pytest

from ppr.layout import ROOT

SKILLS = ROOT / "plugin" / "skills"


def test_marketplace_points_at_the_plugin():
    m = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert m["name"] == "paper-explorer"
    [p] = m["plugins"]
    assert p["name"] == "paper-explorer"
    assert (ROOT / p["source"] / ".claude-plugin" / "plugin.json").is_file()
    assert json.loads((ROOT / p["source"] / ".claude-plugin" / "plugin.json").read_text())["name"] == "paper-explorer"


@pytest.mark.parametrize("skill", ["survey", "venue-check"])
def test_skill_has_frontmatter_and_uses_the_installed_command(skill):
    text = (SKILLS / skill / "SKILL.md").read_text()
    front = text.split("---")[1]
    assert f"name: {skill}" in front and "description:" in front
    assert "uv run ppr" not in text and "repository root" not in text
    assert "uv tool upgrade ppr" in text
    assert "uv tool install git+https://github.com/brightjade/paper-explorer" in text


def test_survey_moved_and_uses_surveys_folder():
    assert not (ROOT / ".claude" / "skills" / "survey").exists()
    text = (SKILLS / "survey" / "SKILL.md").read_text()
    assert "surveys/<slug>_" in text and "outputs/" not in text
    assert (SKILLS / "survey" / "judging.md").is_file()
    assert "ppr data status" in text and ".data-release.json" not in text


def test_venue_check_grounds_through_lookup_and_status():
    text = (SKILLS / "venue-check" / "SKILL.md").read_text()
    assert "ppr search lookup --file" in text and "ppr data status --json" in text
    assert "Agent" not in text


@pytest.mark.parametrize("skill", ["survey", "venue-check"])
def test_skill_runs_downloads_under_a_long_timeout(skill):
    text = (SKILLS / skill / "SKILL.md").read_text()
    assert "ppr data status --json" in text and "ppr data update" in text and "600000" in text


def test_survey_leaves_venue_grounding_to_venue_check():
    front = (SKILLS / "survey" / "SKILL.md").read_text().split("---")[1]
    assert "venue-check" in front
    assert "to ground or complete" not in front and "this repository" not in front


def test_survey_outputs_are_ignored():
    assert "surveys/" in (ROOT / ".gitignore").read_text().splitlines()


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH")
@pytest.mark.parametrize("path", [".", "plugin"])
def test_claude_validates(path):
    proc = subprocess.run(["claude", "plugin", "validate", str(ROOT / path)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr

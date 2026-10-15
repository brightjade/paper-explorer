"""Structure of the monthly workflow's re-crawl path.

The input exists so a source migration ships through the pipeline that owns
the data release. Its guarantees are ordering and fail-closed wiring, which a
YAML edit can break without any test noticing, so they are pinned here.
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "monthly.yml"


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return wf.get("on", wf.get(True))


def _steps(wf: dict) -> list[dict]:
    return wf["jobs"]["pipeline"]["steps"]


def _named(name: str) -> dict:
    return next(s for s in _steps(_wf()) if s.get("name") == name)


def test_dispatch_takes_a_recrawl_list_that_defaults_to_nothing():
    recrawl = _triggers(_wf())["workflow_dispatch"]["inputs"]["recrawl"]
    assert recrawl["type"] == "string"
    assert recrawl["default"] == ""


def test_recrawl_reaches_every_step_as_an_env_var():
    """Empty on schedule: `inputs` is null there, and `|| ''` keeps it a string."""
    assert _wf()["env"]["RECRAWL"] == "${{ inputs.recrawl || '' }}"


def test_recrawl_runs_after_autoregister_and_before_tests_and_enrich():
    names = [s.get("name") for s in _steps(_wf())]
    assert names.index("Autoregister") < names.index("Recrawl") < names.index("Tests") < names.index("Enrich")


def test_recrawl_is_skipped_when_nothing_was_asked():
    step = _named("Recrawl")
    assert step["if"] == "env.RECRAWL != ''"
    assert 'uv run ppr crawl "${ids[@]}"' in step["run"]


def test_enrich_requires_every_recrawled_conference():
    run = _named("Enrich")["run"]
    assert "--require" in run
    assert "$RECRAWL" in run

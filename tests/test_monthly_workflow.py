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


def test_awards_run_after_tests_and_before_enrich():
    names = [s.get("name") for s in _steps(_wf())]
    assert names.index("Tests") < names.index("Awards") < names.index("Enrich")


def test_awards_collect_everything_and_write_a_report():
    assert _named("Awards")["run"] == "uv run ppr awards --all --report awards.json"


def test_the_awards_report_is_uploaded_even_after_a_failure():
    upload = next(s for s in _steps(_wf()) if s.get("with", {}).get("name") == "report-awards")
    assert upload["with"]["path"] == "awards.json"
    assert "!cancelled()" in upload["if"]


def test_notify_reads_the_awards_report():
    decide = next(s for s in _wf()["jobs"]["notify"]["steps"] if s.get("name") == "Decide the issue action")
    assert "--awards reports/awards.json" in decide["run"]


def test_rolling_recrawl_runs_after_autoregister_and_before_tests_and_enrich():
    names = [s.get("name") for s in _steps(_wf())]
    assert names.index("Autoregister") < names.index("Rolling recrawl") < names.index("Tests") < names.index("Enrich")


def test_rolling_recrawl_writes_a_report_that_is_uploaded():
    assert _named("Rolling recrawl")["run"] == "uv run ppr rolling --report rolling.json"
    upload = next(s for s in _steps(_wf()) if s.get("with", {}).get("name") == "report-rolling")
    assert upload["with"]["path"] == "rolling.json" and "!cancelled()" in upload["if"]


def test_notify_reads_the_rolling_report():
    decide = next(s for s in _wf()["jobs"]["notify"]["steps"] if s.get("name") == "Decide the issue action")
    assert "--rolling reports/rolling.json" in decide["run"]

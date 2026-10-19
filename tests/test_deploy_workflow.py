"""The deploy refuses a release zip in the wrong layout before it builds the site."""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy.yml"


def test_download_step_fails_closed_on_the_wrong_layout():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["build"]["steps"]
                if s.get("name") == "Download data from latest release")
    run = step["run"]
    check = 'compgen -G "data/*/[0-9][0-9][0-9][0-9].jsonl"'
    assert check in run
    assert run.index("unzip") < run.index(check)

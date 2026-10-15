"""Register, crawl and check newly published venues without a human.

Every judgment the check-new-conferences skill used to ask a person for is a
rule here, and a venue the rules cannot settle is *held*: its edits are
reverted and the reason is reported, so it comes back next month as the same
unregistered `live` venue. Nothing is guessed.
"""

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ppr.readme_table import selection_cell, update_readme
from ppr.register import (
    TRACK_VOCABULARY,
    RegistrationError,
    register_cvf,
    register_dblp,
    register_researchr,
    register_usenix,
    render_openreview_config,
    selections_from_notes,
)
from ppr.venues import Venue

logger = logging.getLogger(__name__)

MECHANICAL_SOURCES = {"openreview", "dblp", "cvf", "usenix", "researchr"}

# Crawled vs probed paper count. The probe and the crawler read the same
# source, so a wider gap means the crawler and the page disagree about what a
# paper is -- the signature of a selector or a venue-string mismatch.
COUNT_TOLERANCE = 0.10


class Hold(Exception):
    """This venue cannot be registered by rule; a human has to look."""


@dataclass
class Outcome:
    conf_id: str
    status: str  # "registered" | "held"
    count: int = 0
    expected: int = 0
    reason: str = ""
    url: str = ""
    notes: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class Workspace:
    root: Path

    @property
    def configs_dir(self) -> Path:
        return self.root / "configs"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def readme(self) -> Path:
        return self.root / "README.md"

    @property
    def dblp_module(self) -> Path:
        return self.root / "ppr" / "scrapers" / "dblp.py"

    @property
    def cvf_module(self) -> Path:
        return self.root / "ppr" / "scrapers" / "cvf.py"

    @property
    def usenix_module(self) -> Path:
        return self.root / "ppr" / "scrapers" / "usenix.py"

    @property
    def researchr_module(self) -> Path:
        return self.root / "ppr" / "scrapers" / "researchr.py"


Crawl = Callable[[str, Venue, Workspace], int]


class _Snapshot:
    """Everything one venue's attempt touched, so a hold can put it all back."""

    def __init__(self) -> None:
        self._files: dict[Path, str | None] = {}
        self._dirs: dict[Path, Path | None] = {}
        self._tmp = Path(tempfile.mkdtemp(prefix="autoregister-"))

    def file(self, path: Path) -> Path:
        if path not in self._files:
            self._files[path] = path.read_text(encoding="utf-8") if path.exists() else None
        return path

    def dir(self, path: Path) -> Path:
        if path not in self._dirs:
            if path.exists():
                backup = self._tmp / path.name
                shutil.copytree(path, backup)
                self._dirs[path] = backup
            else:
                self._dirs[path] = None
        return path

    def changed_files(self) -> list[Path]:
        return list(self._files)

    def restore(self) -> None:
        for path, text in self._files.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text, encoding="utf-8")
        for path, backup in self._dirs.items():
            shutil.rmtree(path, ignore_errors=True)
            if backup is not None:
                shutil.copytree(backup, path)
        self.discard()

    def discard(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


def check_count(crawled: int, expected: int) -> None:
    if expected <= 0 or abs(crawled - expected) > COUNT_TOLERANCE * expected:
        raise Hold(
            f"crawled {crawled} papers but the probe counted {expected} "
            f"(more than {COUNT_TOLERANCE:.0%} apart)"
        )


def _checked_selections(notes: list, venue_id: str) -> dict[str, str]:
    selections = selections_from_notes(notes, venue_id)
    for key, value in selections.items():
        if key not in TRACK_VOCABULARY:
            raise Hold(f'unknown track name "{value}" -- name it by hand')
    return selections


def _register_openreview(row: dict, venue: Venue, ws: Workspace, snap: _Snapshot,
                         openreview: Callable[[], object]) -> int:
    client = openreview()
    venue_id = row["registration"]["venue_id"]
    selections = _checked_selections(client.get_all_notes(content={"venueid": venue_id}), venue_id)
    expected = row["count"]
    extra_ids: list[str] = []
    for track in venue.extra_tracks:
        track_id = track["venue_id"].format(year=row["year"])
        notes = client.get_all_notes(content={"venueid": track_id})
        if not notes:
            continue
        for key, value in _checked_selections(notes, track_id).items():
            selections[f"{track['prefix']}_{key}"] = value
        extra_ids.append(track_id)
        expected += len(notes)

    path = snap.file(ws.configs_dir / f"{row['conf_id']}.yaml")
    path.write_text(
        render_openreview_config(venue.name, row["year"], venue_id, selections,
                                 extra_venue_ids=extra_ids),
        encoding="utf-8",
    )
    return expected


def _register(row: dict, venue: Venue, ws: Workspace, snap: _Snapshot,
              openreview: Callable[[], object]) -> int:
    """Write the registry entry. Returns the paper count the crawl must match."""
    reg = row.get("registration") or {}
    if not reg:
        raise Hold("the probe carried no registration payload -- re-run discover")
    conf_id = row["conf_id"]
    if venue.source == "openreview":
        return _register_openreview(row, venue, ws, snap, openreview)
    if venue.source == "dblp":
        register_dblp(conf_id, reg["key"], snap.file(ws.dblp_module), number=reg.get("number"))
    elif venue.source == "cvf":
        register_cvf(conf_id, reg["url"], reg["parser"], snap.file(ws.cvf_module),
                     year=reg.get("year"))
    elif venue.source == "usenix":
        register_usenix(conf_id, reg["slug"], snap.file(ws.usenix_module))
    elif venue.source == "researchr":
        register_researchr(conf_id, reg["url"], reg["track"], snap.file(ws.researchr_module))
    else:
        raise Hold(f"no registration writer for source {venue.source!r}")
    return row["count"]


def _selections_in(path: Path) -> set[str]:
    with open(path, encoding="utf-8") as f:
        return {json.loads(line).get("selection", "") for line in f if line.strip()}


def register_one(row: dict, venue: Venue, ws: Workspace, *, crawl: Crawl,
                 validate: Callable[[str], str],
                 commit: Callable[[list[Path], str], None],
                 openreview: Callable[[], object]) -> Outcome:
    conf_id = row["conf_id"]
    snap = _Snapshot()
    try:
        expected = _register(row, venue, ws, snap, openreview)
        snap.dir(ws.data_dir / conf_id)
        count = crawl(conf_id, venue, ws)
        check_count(count, expected)
        if venue.source != "dblp":
            status = validate(conf_id)
            if status == "FAIL":
                raise Hold("paper count disagrees with DBLP (ppr validate: FAIL)")

        notes = []
        value = selection_cell(_selections_in(ws.data_dir / conf_id / "papers.jsonl"))
        if not update_readme(snap.file(ws.readme), venue.name, row["year"], value):
            notes.append(f"README has no row named {venue.name!r}; cell not filled")

        files = snap.changed_files()
        commit(files, f"feat(registry): register {conf_id} ({count} papers)")
    except (Hold, RegistrationError) as exc:
        snap.restore()
        logger.warning("Held %s: %s", conf_id, exc)
        return Outcome(conf_id, "held", expected=row.get("count", 0), reason=str(exc), url=row["url"])
    except Exception as exc:  # one venue's crash must not cost the others their run
        snap.restore()
        logger.exception("Held %s after an error", conf_id)
        return Outcome(conf_id, "held", expected=row.get("count", 0),
                       reason=f"{type(exc).__name__}: {exc}", url=row["url"])
    snap.discard()
    logger.info("Registered %s (%d papers)", conf_id, count)
    return Outcome(conf_id, "registered", count=count, expected=expected, url=row["url"],
                   notes=notes, files=[str(f.relative_to(ws.root)) for f in files])


def autoregister(rows: list[dict], registry: dict[str, Venue], ws: Workspace, *,
                 crawl: Crawl, validate: Callable[[str], str],
                 commit: Callable[[list[Path], str], None],
                 openreview: Callable[[], object]) -> list[Outcome]:
    outcomes = []
    for row in rows:
        venue = registry.get(row["prefix"])
        if row["status"] != "live" or venue is None or venue.source not in MECHANICAL_SOURCES:
            continue
        outcomes.append(register_one(row, venue, ws, crawl=crawl, validate=validate,
                                     commit=commit, openreview=openreview))
    return outcomes


def outcomes_to_json(outcomes: list[Outcome]) -> str:
    return json.dumps({"outcomes": [asdict(o) for o in outcomes]}, indent=2)


# --- Real collaborators, wired by the CLI -----------------------------------

def default_crawl(openreview: Callable[[], object]) -> Crawl:
    """Crawl with the real sources.

    OpenReview runs in-process on the shared client because login is limited
    to 3/min. Scrapers run in a fresh process because the registry module was
    just edited on disk and this process imported the old one.
    """
    def crawl(conf_id: str, venue: Venue, ws: Workspace) -> int:
        out = ws.data_dir / conf_id / "papers.jsonl"
        if venue.source == "openreview":
            from ppr.api_client import OpenReviewAPIClient
            from ppr.config import CrawlConfig
            from ppr.models import write_papers

            config = CrawlConfig.from_yaml(ws.configs_dir / f"{conf_id}.yaml")
            papers = OpenReviewAPIClient(config, openreview()).fetch_papers()
            write_papers(papers, out)
            return len(papers)
        subprocess.run([sys.executable, "-m", "ppr.cli", "crawl", conf_id],
                       cwd=ws.root, check=True)
        with open(out, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    return crawl


def git_commit(root: Path) -> Callable[[list[Path], str], None]:
    def commit(files: list[Path], message: str) -> None:
        paths = [str(f) for f in files]
        try:
            subprocess.run(["git", "add", "--", *paths], cwd=root, check=True)
            # Scoped to our paths so anything else staged is never swept in.
            subprocess.run(
                ["git", "commit", "-m", message, "--", *paths],
                cwd=root, check=True,
            )
        except subprocess.CalledProcessError:
            # The caller reverts the working tree; the index must follow.
            subprocess.run(["git", "reset", "-q", "--", *paths], cwd=root, check=False)
            raise
    return commit


def no_commit(files: list[Path], message: str) -> None:
    logger.info("Would commit %s: %s", [str(f) for f in files], message)

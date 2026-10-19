---
name: check-new-conferences
description: Handle the venues the monthly pipeline hands back (held, needs-manual, stale_empty), and check whether tracked conferences have published new accepted-paper lists. Use when the user asks to "check for new conferences", "any new papers", "update conferences", mentions a discover issue, or asks whether a specific venue is out yet.
---

# Check New Conferences

Finds conference-years whose accepted-paper list is up but not yet in this repo, registers the ones whose source is mechanical, and runs the pipeline.

## When to use this now

The monthly workflow (`.github/workflows/monthly.yml`) registers mechanical-source venues on its own. Use this skill for what it hands back:

- venues it **held** (the tracking issue names the reason),
- `needs-manual` venues (ACL-family, AAAI),
- `stale_empty` venues (probable broken selector).

Before any manual crawl or enrich, bring `data/` to the newest data release with `uv run python -m scripts.sync_data` -- the release is the source of truth, and the tag it records is what `release-data` later builds on. If it refuses, `data/` holds local work: find out what it is before passing `--force`, which discards it.

A held venue whose cause is fixed (a scraper repaired, a registry entry corrected) can go back through the same rules locally: `uv run ppr discover --json > discover.json && uv run ppr autoregister discover.json --report register.json`. Without `--commit` it writes the registration, crawl and README cell to the working tree and commits nothing.

## Phase 1 — Detect, then stop

```bash
uv run ppr discover
```

Present the table. **Stop here and ask which venues to add.** Do not register or crawl anything yet.

Reading the output:

- `live` — ready to register. The count is real, parsed papers.
- `needs-manual` — ACL-family or AAAI. Registration needs a hand-written scraper; report the URL and stop.
- `empty` — the page responded but yielded too few papers. Normal before publication. **If the venue's `announce_month` has passed, suspect a broken selector** and say so.
- `not-yet` — nothing published.
- `unreachable` — network trouble or missing OpenReview credentials. Never report these as "nothing new".

## Phase 2 — Register and crawl the approved venues

Only for `live` venues. One venue at a time.

**DBLP** — add the toc key:

```python
from pathlib import Path
from ppr.register import register_dblp
register_dblp("ijcai_2027", "db/conf/ijcai/ijcai2027.bht", Path("ppr/scrapers/dblp.py"))
```

**CVF** — `parser` is `openaccess` for `openaccess.thecvf.com`, `accepted` for a conference AcceptedPapers page, `ecva` for ECCV (pass `year=`).

```python
from ppr.register import register_cvf
register_cvf("cvpr_2026", "https://openaccess.thecvf.com/CVPR2026?day=all", "openaccess", Path("ppr/scrapers/cvf.py"))
```

The writers insert each entry into its venue's group and use the module's host constants, so the diff needs reviewing, not hand-moving.

**USENIX** — the slug is `usenixsecurity` plus the two-digit year:

```python
from ppr.register import register_usenix
register_usenix("usenix_security_2026", "usenixsecurity26", Path("ppr/scrapers/usenix.py"))
```

**researchr** (ICSE/FSE/ASE/ISSTA) — use the `url` and `track` from the probe's `registration`; never guess a slug:

```python
from ppr.register import register_researchr
register_researchr("icse_2027", "https://conf.researchr.org/track/icse-2027/icse-2027-research-track", "Research Track", Path("ppr/scrapers/researchr.py"))
```

A researchr entry has no DOIs until DBLP indexes the year. Once DBLP has a toc for a registered researchr year, add it to the entry as `"dblp": {"key": "db/conf/<conf>/<conf><year>.bht"}` (a PACMSE volume also takes `"number": "FSE"` or `"ISSTA"`), then re-crawl the venue with the monthly workflow's `recrawl` input, which backfills the DOIs. That re-crawl fails if fewer than 80% of the research-track papers match DBLP.

**Crossref** (ICRA/IROS):

```python
from ppr.register import register_crossref
register_crossref("iros_2026", "10.1109", "2026 IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)", Path("ppr/scrapers/crossref.py"))
```

**roboticsproceedings** (RSS) — the volume is the year minus 2004:

```python
from ppr.register import register_roboticsproceedings
register_roboticsproceedings("rss_2027", 23, Path("ppr/scrapers/roboticsproceedings.py"))
```

**OpenReview** — never write `selections` by following another year's pattern. Read them from the API. Load `.env` first: only `ppr/cli.py` calls `load_dotenv()`, so a standalone script otherwise dies with "No OpenReview credentials provided".

```python
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()  # required — api_client does not load it itself

from ppr.api_client import create_openreview_client
from ppr.register import openreview_selections, render_openreview_config
client = create_openreview_client()
sel = openreview_selections(client, "ICLR.cc/2027/Conference")
print(sel)  # review before writing
Path("configs/iclr/2027.yaml").write_text(render_openreview_config("ICLR", 2027, "ICLR.cc/2027/Conference", sel))
```

`configs/corl/2024.yaml` followed the 2023/2025 pattern, matched nothing, and wrote an empty file that went unnoticed for months. ICML 2026 proved the point again: it tags papers `"ICML 2026 regular"` / `"ICML 2026 spotlight"` where 2025 used `oral` / `spotlightposter` / `poster`.

**Review the generated selection names before crawling.** `openreview_selections` derives a key from each venue string: a single venue string becomes `main`, a track word (`oral`, `spotlight`, `poster`, `findings`, `industry`) names its track, and `regular` maps to `main` (ICML 2026's base track). Anything else falls back to a slug of the whole venue string, such as `iclr_2027_highlight`; autoregister holds those venues for exactly this reason. That name would land on every paper and show up in the web app's track breakdown, so rename it to the project's vocabulary (`TRACK_VOCABULARY` in `ppr/register.py`): `main` for a base track (61k papers already use it), then `oral`, `poster`, `spotlight`, `findings`, `industry`.

Then crawl and check:

```bash
uv run ppr crawl <conf_id>
wc -l data/<venue>/<year>.jsonl
uv run ppr validate <conf_id>   # only if a DBLP key exists for it
```

The crawled count should be close to the probe's count. If it is far off, stop and report — do not proceed to Phase 3 with a suspect crawl.

One exception: a venue with extra track venue IDs (`extra_venue_ids` in its config, e.g. NeurIPS Datasets & Benchmarks) is crawled across several venue IDs while the probe queries only one, so the crawl legitimately comes back *higher*. Check the extra tracks' counts add up rather than treating the gap as a fault.

A **held rolling venue** (TMLR; the issue's rolling section, reason "N paper(s) on disk missing from the crawl (crawl returned M): <forum ids>") means a recrawl lost papers already on disk, so its file was kept. Open the named forum ids on OpenReview. If they were retracted or moved, run `uv run ppr crawl tmlr_<year>`, which deliberately bypasses the guard, then enrich and release as for any manual fix. If the crawl returned 0 papers (the whole year "missing"), it was an outage: do nothing, next month's run retries on its own.

Also fill the conference's cell in `README.md` (`ppr.readme_table.update_readme(Path("README.md"), "ICLR", 2027, "oral, poster")` does what autoregister does), and run `uv run pytest tests/`. A new ID needs no test edit: the per-scraper `test_expected_conference_ids` tests check a subset, and `tests/test_registry_seams.py` checks that a registration in every source keeps the suite green.

## Phase 2b — Decide whether to enrich now or later

A conference published days ago is usually absent from Semantic Scholar, and enriching it then costs hours for almost nothing. **Check before committing to it:**

```python
import os, httpx
from dotenv import load_dotenv
load_dotenv()
h = {"x-api-key": os.environ["SEMANTIC_SCHOLAR_API_KEY"]}
r = httpx.get("https://api.semanticscholar.org/graph/v1/paper/search/bulk",
              params={"venue": "<S2 venue string from ppr/enrich.py's S2_VENUE_NAMES>",
                      "year": "<year>", "fields": "title"},
              headers=h, timeout=60.0)
print(r.json().get("total"))  # compare against the crawled count
```

Measured on 2026-07-30, the day after both published: **CVPR 2026 → 0 indexed, ICML 2026 → 17**, against 4068 and 6341 crawled. Their 2025 editions sat at 67% and 83%, so the venue strings were fine — it is pure indexing lag. USENIX Security 2026 took **3h09m for 381 papers** under that condition and matched only 40%, all arXiv preprints.

So: if coverage is near zero, **crawl now and enrich later**. The papers reach the site immediately without citation counts, and a run once Semantic Scholar has caught up covers 70-80% by bulk prefetch instead of grinding every paper through title matching. Waiting is worth roughly two orders of magnitude here.

If you skip enrichment, say so plainly and stop before Phase 3 — a partial dataset should not be silently released.

## Phase 3 — Full pipeline

Run only after Phase 2 is verified, **and in this order**:

```bash
uv run ppr enrich --all
date +%Y-%m-%d > data/citation_updated.txt
./build.sh
```

Read the `ppr enrich --all` summary, do not just check its exit code: a conference skipped by a data-loss guard exits 0 by design. Any `skipped` or `failed` row must be reported before continuing. Report the `Unbound` column too — it counts bindings that verification severed. A handful per conference is the system working; a conference unbinding a large share of its papers means the venue's Semantic Scholar records moved and needs a look.

Then invoke the `release-data` skill (which runs `ppr release`), and only afterwards `git push`.

**The order is load-bearing.** `.github/workflows/deploy.yml` builds the site from the *latest release's* `data.zip` when `main` is pushed. Pushing before releasing deploys the new code against stale data.

## Never

- Report `unreachable` venues as "nothing new" — that hides both outages and missing credentials.
- Write OpenReview `selections` from a pattern.
- Push before releasing data.

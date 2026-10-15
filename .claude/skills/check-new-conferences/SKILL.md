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

Before any manual crawl or enrich, start from the newest data release (`./setup.sh`), not from any existing `data/` copy -- the release is the source of truth.

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
Path("configs/iclr_2027.yaml").write_text(render_openreview_config("ICLR", 2027, "ICLR.cc/2027/Conference", sel))
```

`configs/corl_2024.yaml` followed the 2023/2025 pattern, matched nothing, and wrote an empty file that went unnoticed for months. ICML 2026 proved the point again: it tags papers `"ICML 2026 regular"` / `"ICML 2026 spotlight"` where 2025 used `oral` / `spotlightposter` / `poster`.

**Review the generated selection names before crawling.** `openreview_selections` derives a key from each venue string, falling back to a slug when no track word matches — ICML 2026's "regular" became `icml_2026_regular`. That name lands on every paper and shows up in the web app's track breakdown, so rename it to the project's vocabulary: `main` for a base track (61k papers already use it), then `oral`, `poster`, `spotlight`, `findings`, `industry`.

Then crawl and check:

```bash
uv run ppr crawl <conf_id>
wc -l data/<conf_id>/papers.jsonl
uv run ppr validate <conf_id>   # only if a DBLP key exists for it
```

The crawled count should be close to the probe's count. If it is far off, stop and report — do not proceed to Phase 3 with a suspect crawl.

One exception: a venue with extra track venue IDs (`extra_venue_ids` in its config, e.g. NeurIPS Datasets & Benchmarks) is crawled across several venue IDs while the probe queries only one, so the crawl legitimately comes back *higher*. Check the extra tracks' counts add up rather than treating the gap as a fault.

Also update the conference table in `README.md`, and run `uv run pytest tests/` — several scraper tests pin the exact set of registered conference IDs (`tests/test_cvf.py::TestCvfScrapersDict::test_expected_conference_ids` is one), so they fail by design when you add a venue. Add the new ID to the expected set; a failure there is the test doing its job, not a regression.

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

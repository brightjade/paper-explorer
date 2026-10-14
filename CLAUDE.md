# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                        # Install dependencies
uv run ppr discover                            # Check tracked venues for new accepted-paper lists
uv run ppr crawl iclr_2025                     # Crawl one conference
uv run ppr crawl iclr_2025 neurips_2025        # Crawl multiple (one OpenReview login)
uv run ppr enrich iclr_2025 neurips_2025        # Enrich with Semantic Scholar metadata
uv run ppr enrich --all                        # Refresh citations for every conference
uv run ppr validate iclr_2025                  # Validate paper count against DBLP
./build.sh                                     # Build static JSON for web app
uv run ppr autoregister discover.json --report register.json   # Register live venues by rule (--commit commits each venue)
uv run ppr enrich --all --time-budget 4h --report enrich.json  # Enrich within a time budget
uv run ppr release --base-tag data-YYYY-MM-DD --dry-run         # Plan a data release
uv run pytest tests/                           # Run all tests
uv run pytest tests/test_models.py::TestPaper::test_to_dict_full  # Single test
```

## Convention

Conference ID = config filename without `.yaml` (for OpenReview) or key in `SCRAPERS` dict (for ACL-family / AAAI / USENIX / DBLP). Everything derives from it:

- Config: `configs/<id>.yaml` (OpenReview only)
- Scraper: `ppr.scrapers.SCRAPERS[<id>]` (ACL-family / AAAI / USENIX / DBLP)
- Output: `data/<id>/papers.jsonl`
- Enriched: `data/<id>/papers_enriched.jsonl` (sorted by citation count, with abstracts)

## Architecture

Multiple data sources, one output format:

- **OpenReview conferences** (ICLR, NeurIPS, ICML, COLM, CoRL): conference ID -> YAML config -> `OpenReviewAPIClient` -> API (`get_all_notes` with invitation + venueid) -> filter by `venue` field -> `Paper` with `selection` tag
- **ACL-family conferences** (EMNLP, ACL, NAACL, EACL, COLING): conference ID -> `ppr.scrapers.acl.SCRAPERS` -> scrape `<li><strong>Title</strong><em>Authors</em></li>` from conference website -> `Paper` with `selection` tag
- **AAAI**: conference ID -> `ppr.scrapers.aaai.SCRAPERS` -> scrape OJS issue pages from `ojs.aaai.org` -> `Paper` with `selection` tag
- **USENIX Security**: conference ID -> `ppr.scrapers.usenix.SCRAPERS` -> scrape `article.node-paper` from `technical-sessions` page -> `Paper` with `selection` tag. Requires browser User-Agent header.
- **CV conferences** (CVPR, ICCV, ECCV, WACV): conference ID -> `ppr.scrapers.cvf.SCRAPERS` -> CVF Open Access / ECVA for ECCV -> `Paper` with `selection` tag
- **Robotics conferences** (ICRA, IROS): conference ID -> `ppr.scrapers.dblp.SCRAPERS` -> DBLP JSON API. RSS 2025 uses dedicated `ppr.scrapers.rss` scraper; RSS 2023-2024 use DBLP.
- **SE conferences** (ICSE, FSE, ASE, ISSTA): conference ID -> `ppr.scrapers.dblp.SCRAPERS` -> DBLP JSON search API (`toc:` query) -> `Paper` with `selection` tag. No auth needed. FSE 2024+ and ISSTA 2025+ use PACMSE journal keys with `number` field filtering.
- **IJCAI**: 2023-2025 -> `ppr.scrapers.dblp.SCRAPERS` -> DBLP JSON API. 2026 -> `ppr.scrapers.ijcai.SCRAPERS` -> conference website (not yet on DBLP).

All produce JSONL. Enrichment (citations + abstracts via Semantic Scholar) works the same for all sources. OpenReview abstracts are preserved; Semantic Scholar abstracts fill in papers that lack them.

### Key modules

All source code lives in the `ppr/` package:

- `ppr/cli.py` -- Entry point (`ppr`) with subcommands: `crawl`, `enrich`, `validate`. `crawl` accepts multiple conference IDs, logs into OpenReview once, scrapes ACL-family conferences without auth.
- `ppr/api_client.py` -- `create_openreview_client()` logs in once, `OpenReviewAPIClient` takes the client + config. Fetches all accepted papers in one API call, filters by `venue` string client-side.
- `ppr/scrapers/` -- Web scrapers for conferences not on OpenReview. Each module exports a `SCRAPERS` dict mapping conference IDs to scraper functions. `ppr/scrapers/__init__.py` aggregates all scrapers.
  - `acl.py` -- ACL-family (EMNLP, ACL, NAACL). Handles both separate-page and single-page layouts. Skips entries without authors (filters footer noise).
  - `aaai.py` -- AAAI proceedings from `ojs.aaai.org`. Scrapes multiple OJS issue pages per year (technical tracks + special tracks).
  - `usenix.py` -- USENIX Security. Scrapes `technical-sessions` page. Parses `Name1 and Name2,Affiliation;Name3,Affiliation` author format. Needs browser UA to avoid 403.
  - `dblp.py` -- SE conferences (ICSE, FSE, ASE, ISSTA), robotics (ICRA, IROS, RSS 2023-2024), and IJCAI via DBLP JSON API. Config dict maps conference IDs to `toc:` keys. Handles PACMSE journal volumes (shared by FSE/ISSTA) via `number` field filtering. Strips DBLP author disambiguation suffixes and HTML entities.
  - `cvf.py` -- CV conferences (CVPR, ICCV, WACV) from CVF Open Access, ECCV from ECVA. Parses paper lists with author metadata.
  - `rss.py` -- RSS 2025 from the RSS website (earlier years use DBLP).
  - `ijcai.py` -- IJCAI 2026 from the conference website (`2026.ijcai.org/accepted-papers`), which lists all papers as `<li class="ij-paper">` with title, authors, abstract, and topic keywords. IJCAI 2023-2025 stay on DBLP; 2026 isn't indexed there yet (same split as RSS). Needs a browser UA.
- `ppr/s2_client.py` -- Single point of contact with the Semantic Scholar Graph API. Owns pacing and 429/403 exponential backoff, shared by all three endpoints: `match_title` (one paper by title, heavily throttled to ~0.3 req/s), `get_batch` (up to 500 IDs per request -- `CorpusId:`, `DOI:`), and `bulk_search` (venue+year, 1000 papers per page). Returns raw API dicts. `ENRICHMENT_FIELDS` requests `authors` alongside the citation metadata, which `match_verdict` needs to break ties titles alone cannot settle.
- `ppr/matching.py` -- Decides whether a Semantic Scholar record is the paper we crawled. `title_key` canonicalises titles across sources (NFKC, LaTeX and unicode Greek onto one token, then alphanumerics only); `match_verdict` returns `matched` / `matched_fuzzy` / `reject`, using author-surname overlap to break ties that titles alone cannot. `/search/match` answers an unindexed paper with its nearest fuzzy neighbour rather than with nothing, so an unchecked result is how a paper ends up wearing a stranger's citations.
- `ppr/enrich.py` -- Per-conference enrichment. Picks the cheapest workable path: **refresh** (batch by `CorpusId` from the existing enriched file), **id-cold** (batch by `DOI` from the crawler's `link`, for DBLP-sourced venues), or **title-cold** (bulk prefetch by venue+year, then per-title matching for the misses). Every run re-attempts papers no earlier run could match -- Semantic Scholar indexes a venue months after we crawl it, so "not found" expires. Each refresh also re-verifies the binding against the returned title and authors (`ppr/matching.py`) and unbinds a record that turns out to describe a different paper, which returns it to the same retry queue. Two guards refuse to overwrite good data with bad: `check_guards` bounds how many *papers* a run may lose -- refusing when `papers.jsonl` is empty or under 50% of the enriched count; `check_enrichment_coverage` bounds how much *enrichment* a run may lose -- refusing when fewer than 50% of previously matched papers would keep a `CorpusId`, which the paper count alone cannot see, and which now also caps how much a single run's verification is allowed to unbind. Writes atomically via temp file + `os.replace`, sorted by citation count. `--time-budget` stops only the per-title matching loop; unmatched papers past the deadline are written unchanged and counted `deferred`, and conferences run newest year first (`--time-budget 0s` is an already-spent deadline, not unlimited). `--report` is written even when a conference failed.
- `ppr/dblp_client.py` -- Single point of contact with DBLP's search API, shared by `discover` and `validate` (which query one throttling host from one machine). Owns pacing at dblp.org's stated `Crawl-delay: 4`, retries on `{429, 500, 502, 503, 504}` honoring `Retry-After`, and raises `DblpUnavailable` rather than returning a partial answer -- a throttled query must never be read as a count.
- `ppr/validate.py` -- Cross-references scraped paper counts against DBLP proceedings data. Maps conference IDs to DBLP toc keys, fetches counts via paginated API, compares with configurable tolerance (default 10%). Skips DBLP-sourced conferences (circular validation). A throttled sweep is `ERROR`, never `FAIL`.
- `ppr/venues.py` -- Loads `configs/venues.yaml`, the registry of 24 tracked venue prefixes (source, cadence, probe template, announce month). Validation is strict: an unknown source or cadence raises rather than silently skipping the venue.
- `ppr/discover.py` -- Finds conference-years whose list is published but unregistered. `known_years` comes from `configs/*.yaml` + `SCRAPERS`, never from `data/`, so it runs in CI without the dataset. Every probe reports a **parsed paper count**, never an HTTP status: CVPR 2026 returns 200 with an empty stub, WACV 2027 returns 404 with a 29KB body. Statuses are `live` / `empty` / `not-yet` / `unreachable` / `needs-manual`. DBLP probes go through `ppr/dblp_client.py`; OpenReview needs credentials (anonymous queries are refused).
- `ppr/register.py` -- Writes registration entries for mechanical sources. `openreview_selections()` derives a config's `selections` from the venue's actual `venue` values rather than a pattern.
- `ppr/autoregister.py` -- Turns `discover --json` `live` rows from mechanical sources (OpenReview, DBLP, CVF, USENIX) into registrations without a human: writes the registry entry from the probe's `registration` payload, crawls, holds the venue if the count is more than 10% off the probe or `validate` says `FAIL` (in practice only for venues that already have a DBLP validation key in `DBLP_VALIDATION_KEYS`; a new venue gets `NO_DATA`, so the cross-check does not fire), fills the README cell, and commits each venue with `git commit -- <paths>` (unstaging them if the commit fails). A held venue has every edit reverted (including a pre-existing `data/<id>`) and comes back next month.
- `ppr/report.py` -- `pipeline_state.json` deferral streaks, and the tracking-issue decision (`notify` / `blind` / `close`). Issues exist only for what a human must act on. The workflow's github-script only executes this decision; the executor is tested by `node tests/workflow/monthly-workflow.test.js`.
- `ppr/release.py` -- Publishes `data/` as a `data-YYYY-MM-DD` GitHub Release: refuses if the newest data release is not the one the run started from, creates before pruning, keeps 3. The newest data release is the dataset's source of truth.
- `.github/workflows/monthly.yml` -- 07:23 UTC on the 3rd: discover → autoregister → tests → enrich (4h budget) → release → push → dispatch deploy, with a separate `notify` job for the issue. Installs with `uv sync --locked`, fails closed if `data.zip` extracts no conference data, and refuses non-dry-run runs that do not start from `main` (dry runs work from any branch).
- `ppr/models.py` -- `Paper` dataclass with `selection` field. `to_dict()` excludes `None` and empty-string fields. `write_papers()` is the one way `papers.jsonl` gets written, by both save paths, and refuses to replace a non-empty file with zero papers (`EmptyOverwriteError`) -- a broken source returns `[]`, not an exception.
- `ppr/config.py` -- `CrawlConfig` from YAML. `conference_id` derived from filename, output path derived from that.

### OpenReview API notes

- All accepted papers share one `venueid` (e.g., `ICLR.cc/2025/Conference`), not per-track IDs
- Track type is in `venue` content field (e.g., `"ICLR 2025 Oral"`)
- Casing varies: ICLR 2025 title case, NeurIPS 2025 lowercase, ICML 2025 uses `spotlightposter`
- Auth mandatory (free account). Login rate-limited to 3/min -- `crawl` reuses one login for all OpenReview conferences.

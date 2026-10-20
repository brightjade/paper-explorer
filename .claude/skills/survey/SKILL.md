---
name: survey
description: "Find and synthesize related work from real accepted papers at top-tier venues: this repository's conference data, searched in rounds, extended by citation chasing and web search. Use when the user invokes /survey, asks to 'find related work', 'survey papers', 'literature review', 'is this idea new / has this been done', or describes a research idea and wants to know what exists. Also when they hand over a paper list from Asta, Undermind or a web search to ground or complete, or ask about research gaps, datasets or baselines for a topic."
---

# Literature Survey

You search the way Asta Paper Finder and Undermind do: many phrasings, every candidate judged, expansion from what proved relevant, and a stop once new finds dry up. You search a dataset they do not have: the accepted-paper lists of 25 venues, with each paper's track (oral, spotlight, …) and awards. Web search covers what the dataset cannot (other venues, preprints, pre-2013 work). Every paper you cite is real and shows where it was accepted.

## Tools

Run from the repository root. The first call builds a search index from `data/` (seconds) and rebuilds it whenever `data/` changes. If a command reports no conference data, tell the user to run `uv run python -m scripts.sync_data` (README, Quick start) and stop.

**`uv run ppr search find TERM… [options]`**: ranked keyword search over title, abstract, tldr and keywords.
- Each TERM is a phrase, matched with stemming (`unlearning` finds "unlearn"); TERMs are ORed. A TERM ending in `*` is a prefix. `--must TERM` ANDs a phrase on. `--raw EXPR` takes an FTS5 expression as is.
- `--venue iclr,neurips` (the ids in the Data table; an unknown id or `--selection` value is an error that lists the valid ones) · `--years 2020-2026` · `--selection oral,spotlight` · `--awarded`
- `--sort relevance|citations|year` · `--limit N` (50) · `--offset N` · `--abstract` (adds the tldr or the abstract's first 400 characters) · `--json` (full records, one JSON object per line)
- `--exclude FILE` skips ids in FILE's first column (your `judged.tsv`); it warns on stderr when FILE does not exist yet and excludes nothing.

```
848 matches · showing 1–50 · relevance
iclr_2025:3fa9c1d2 | ICLR 2025 · oral · Outstanding Paper | 412 cites | <title>
```

The first field is the paper's `pid`; every command and working file uses it.

**`uv run ppr search lookup ITEM… [--file F] [--json]`**: grounds arXiv ids, DOIs, `CorpusId:N`, `s2:N`, OpenReview links, pids or titles (`Title ;; Author A, Author B`) in the dataset. Each item comes back `found`, `fuzzy` (confirm it before relying on it) or `not in dataset`, with its paper lines. `--json` gives full records, abstracts included.

**`uv run ppr search cites SEED… [--direction refs|citing|both] [--min-links N] [--abstract] [--limit N] [--exclude F] [--json]`**: Semantic Scholar references and citations of the seeds, each linked paper scored by how many seeds link to it. Two groups: **in dataset** (paper lines) and **outside** (`s2:<CorpusId>`, year, venue, arXiv id or DOI), the outside ones only when linked to at least `--min-links` seeds (default 2). `--abstract` adds outside papers' tldr. `--limit N` caps each group (50); with `--json` the totals appear on stderr when it cut a group. `--json` gives one record per linked paper (`group`: `dataset` or `outside`). If it exits non-zero, Semantic Scholar was unreachable: continue without citation chasing and say so in the Search log.

**`uv run ppr search batch FILE… --out PREFIX [--exclude judged.tsv] [--size 40]`**: turns the round's `find --json`, `cites --json` and `lookup --json` files into judge batches. It keeps one record per paper (`pid`, else `id`) however many files hold it, drops ids in `--exclude`, flattens each `lookup` record into the dataset papers it found (a miss becomes `{"id": "ext:…", "title", "group": "external"}`), cuts each record to the compact fields a judge reads (dataset paper: `pid`, `title`, `tldr` (the tldr, else the abstract's first 400 characters), `venue_name`, `year`, `selection`; outside paper: `id`, `title`, `year`, `venue`, `snippet`), and writes `PREFIX-01.jsonl`, `PREFIX-02.jsonl`, … of at most `--size` records. It prints one `<path><TAB><n>` line per file, then `<total> candidates in <k> batches`, or `0 candidates` and no file.

**`uv run ppr search verdicts PREFIX --judged FILE --round N --source query|cites|external|web`**: collects the judges' verdicts. For every `PREFIX-NN.jsonl` it reads `PREFIX-NN.verdicts.tsv` (lines `id<TAB>verdict<TAB>reason`) and reports, per batch, a missing verdict file, ids with no verdict (`missing`), ids not in the batch (`unknown`), an id given twice (`duplicate`, the first kept) and a verdict that is not `high|medium|low|no` (`bad label`). Every valid line is appended to FILE as `id<TAB>verdict<TAB>N<TAB>S<TAB>reason` (FILE gets its header when new; ids it already holds are skipped and counted `already judged`), whether or not other lines had problems. It prints one line per batch with problems, then `appended <n> (high a, medium b, low c, no d); already judged <k>; batches with problems <p>`. Exit 1 when any batch has a problem or no batch file exists, else 0. It needs no index.

## Data

| Category | Venues | `--venue` ids |
|----------|--------|---------------|
| ML | ICLR, NeurIPS, ICML, TMLR, AAAI, IJCAI | `iclr, neurips, icml, tmlr, aaai, ijcai` |
| NLP | ACL, EMNLP, NAACL, COLM, EACL, COLING | `acl, emnlp, naacl, colm, eacl, coling` |
| CV | CVPR, ICCV, ECCV, WACV | `cvpr, iccv, eccv, wacv` |
| Robotics | CoRL, ICRA, IROS, RSS | `corl, icra, iros, rss` |
| Security | USENIX Security | `usenix_security` |
| SE | ICSE, FSE, ASE, ISSTA | `icse, fse, ase, issta` |

`--venue` takes these ids; an unknown one is an error that lists the valid ids.

Year range varies per venue (generally 2013-2026). Before 2023 most venues come from DBLP and carry only main / findings / industry labels; OpenReview years keep their own labels: ICLR 2017-19 oral / poster, ICLR 2020-22 oral / spotlight / poster, NeurIPS 2021 oral / spotlight / poster plus `datasets`, NeurIPS 2022 only `main` + `datasets` (no oral label, so filtering it for orals finds none), CoRL 2021-22 oral / poster. Citation counts are snapshots from the data release named in `.data-release.json`.

## Workflow

### 1. Mode and scope

Pick the mode from the request. Ask only when it is genuinely unclear.

| Mode | The request | Depth | Report |
|---|---|---|---|
| `novelty` | "is this new", "has anyone done X" | Narrow; run to saturation; web search for recent preprints is required | Verdict and closest works |
| `related-work` | "related work for my paper on X" | Saturate the core criteria | Themed paragraphs and references |
| `landscape` | "what exists on X", a field new to the user | Broad; subtopics, each searched | Overview to open gaps |

Search every venue and year unless the request names some (then pass `--venue` / `--years`). Do not ask for the scope.

### 2. Criteria

Write `criteria.md`: 2–5 conditions a relevant paper meets, the core one first, and what is out of scope, especially the vocabulary neighbours that are not the topic (for unlearning: continual-learning forgetting). In `landscape` mode, list the subtopics with their own conditions.

### 3. Working folder

The working folder `<W>` is `outputs/<slug>_<YYYY-MM-DD_HH-MM-SS>`, e.g. `outputs/unlearning_2026-10-20_14-02-11`. Claude Code does not keep shell variables between Bash calls, so write the literal path into every command: the examples below show `<W>`; substitute the real folder. It holds `criteria.md`, `judged.tsv`, the round files and `report.md`. `judged.tsv` starts with the header `pid	verdict	round	source	reason` and gets a line for every judged paper, `no` included, so `--exclude <W>/judged.tsv` keeps it out of later rounds. Outside papers use their `s2:<CorpusId>`; web finds use `web:<arXiv id, DOI or slug>`; external items the dataset lacks use `ext:<id or title slug>`. Sources: `query`, `cites`, `external`, `web`.

### 4. Round 1: many phrasings

Write 8–15 TERMs across the criteria: synonyms, older and newer names, abbreviations, the problem described without its name, method names. Run every TERM twice, once per sort, because citation order surfaces the foundational papers BM25 ranks low:

```bash
uv run ppr search find "data deletion" --sort relevance --limit 30 --exclude <W>/judged.tsv --json > <W>/round-1-find-01-rel.jsonl
uv run ppr search find "data deletion" --sort citations --limit 30 --exclude <W>/judged.tsv --json > <W>/round-1-find-01-cit.jsonl
```

(one `round-1-find-*.jsonl` file per term and sort). To see a term's hits or match count yourself, run it without `--json`. A term with thousands of matches is too broad: narrow it with `--must` or rephrase it.

### 5. Judge every candidate

Batch each source of the round separately, because `verdicts` records one `--source` per prefix: `uv run ppr search batch <W>/round-N-find-*.jsonl --out <W>/round-N-query-batch --exclude <W>/judged.tsv` for `find` files (source `query`), `<W>/round-N-cites*.jsonl` with `--out <W>/round-N-cites-batch` for `cites` files (source `cites`), `<W>/round-0-external.jsonl` with `--out <W>/round-0-external-batch` for step 9 (source `external`). Each dedupes papers found by several terms or tools, drops judged ones and writes compact judge records to `<W>/round-N-query-batch-01.jsonl`, … of 40. Give each batch to a subagent (Agent tool, `model: sonnet`), several in parallel, with `judging.md` from this skill's folder as the prompt, its `{criteria_path}`, `{batch_path}` and `{verdicts_path}` filled in; `{verdicts_path}` is the batch path with `.jsonl` replaced by `.verdicts.tsv`. Each judge writes its verdict lines there and replies `done <n>`. When all judges of a prefix are back, run `uv run ppr search verdicts <W>/round-N-query-batch --judged <W>/judged.tsv --round N --source query` (once per prefix, with its source). If it exits 1, its valid lines are already in `judged.tsv`: re-batch that source's files into a new prefix, `uv run ppr search batch <W>/round-N-find-*.jsonl --out <W>/round-N-retry-K-query --exclude <W>/judged.tsv` (K = 1, 2, …), judge those batches and run `verdicts` on the new prefix. The earlier prefix's reported problems are then superseded: do not run `verdicts` on it again. Repeat until `verdicts` exits 0 or `batch` prints `0 candidates`. Never append verdict lines by hand. Without a subagent tool, judge the batches yourself by the same brief, writing the same verdicts files.

Then read full abstracts (`uv run ppr search lookup <pids> --json`; an outside paper's tldr is in its `cites` record) only for the papers the report will discuss or cite in detail, not every high and medium paper; the judged reasons and titles are enough for the rest.

### 6. Rounds 2 and on: expand from what is relevant

Each round does at least one of:

- **a. Vocabulary.** Read the high papers' titles and tldrs for phrasings you have not queried (a method's name, another community's word for the problem) and query them as in step 4: every `find` in any round uses the same two-sort, `--limit 30` pattern.
- **b. Citations.** `uv run ppr search cites <high pids> --exclude <W>/judged.tsv --abstract --json > <W>/round-N-cites-01.jsonl`, with the Bash tool's timeout raised to 600000 ms (an anonymous Semantic Scholar pool can back off for minutes). Its in-dataset and outside records are judged like any candidate (source `cites`; batch `<W>/round-N-cites*.jsonl`).

Batch and judge each source of the round as in step 5 (`ppr search batch`, judges, `ppr search verdicts`), repeat.

### 7. Stop on saturation

After each round, count the new high and medium papers. Stop when vocabulary expansion and citation chasing have each run at least once and the last round added under 10% of the total found so far. Caps: rounds — `novelty` 5, `related-work` 3, `landscape` 3 per subtopic; judged candidates — `novelty` 1,500, `related-work` 1,000, `landscape` 600 per subtopic. Stop at saturation or the first cap reached, and say which in the Search log. Keep the per-round counts (e.g. 34 → 12 → 3 → 0) for the Search log.

### 8. Web search

- Seminal work outside the dataset (another venue, a journal, pre-2013, a famous preprint): only genuinely influential papers.
- In `novelty` mode, always: the last 12 months of preprints on the core criterion. The dataset updates monthly and lags arXiv.

Check every web find with `lookup` first; it may be in the dataset under another title. Mark the rest `not from tracked venues`.

### 9. External lists

When the user hands over a list (a file or pasted text from Asta, Undermind, a web search or a bibliography):

1. Write one item per line to `<W>/external.txt` (an arXiv id, a DOI, or `Title ;; Authors`) and run `uv run ppr search lookup --file <W>/external.txt --json > <W>/round-0-external.jsonl`.
2. `ppr search batch <W>/round-0-external.jsonl --out <W>/round-0-external-batch --exclude <W>/judged.tsv`, judge every item against the criteria and run `verdicts` with `--round 0 --source external`, as in step 5. Items not in the dataset come out as `ext:` ids: `verdicts` records them in `judged.tsv` too; check acceptance elsewhere by web search when it matters. From here on, dataset papers carry their venue, track and awards.
3. Use the high ones as seeds for 6a and 6b.
4. In the report add **Accepted papers the external list missed** (your high and medium dataset papers absent from it) and **Papers this search missed** (its high papers your rounds never surfaced, with the likely reason: vocabulary, no citation path, outside the venues).

### 10. Datasets, benchmarks, baselines

In `landscape` mode (and `related-work` when asked): from the high and medium papers' abstracts, the datasets and benchmarks used (scale, domain, metrics) and the baselines compared against. Web search only for details the abstracts lack.

### 11. Report

Write `<W>/report.md` in the mode's structure. Every cited paper shows where it stands: `**Title** — Authors (ICLR 2025 · oral · Outstanding Paper) · 412 cites`, or `(not from tracked venues)`. Cite only papers judged high or medium, or seminal web finds you verified.

**Novelty**
1. Verdict: new, partly done, or done. One paragraph.
2. Closest works: a table of paper | what overlaps | what differs.
3. Adjacent work by theme, briefly.
4. What would make the idea clearly new: the gaps the closest works leave.

**Related work**
1. Themed paragraphs, written to be adapted into a paper's related-work section, each citing its papers.
2. The reference list.

**Landscape**
1. Overview. 2. Seminal and influential papers. 3. Related work by subtopic and theme. 4. Datasets and benchmarks (a table). 5. Common baselines and methods. 6. Limitations, gaps and future directions.

**Search log** (last section, every mode)
- The data release (`.data-release.json`), venues and years searched
- The criteria, or a pointer to `criteria.md`
- The queries by round, and new high + medium per round
- Citation chasing: ran, or skipped and why
- Any external list (its tool and size) and the web searches made
- Totals: judged, high, medium

## Guidelines

- **Accuracy over completeness.** Every paper is real: from the dataset, from Semantic Scholar through `cites`, or verified on the web. Never invent titles, authors or numbers.
- **Be honest about coverage.** The per-round counts show whether the search saturated. Say so when it stopped at a cap, or when the topic lies mostly outside the tracked venues.
- **Citation counts are snapshots,** good for relative ranking only.
- **Oral, spotlight and award papers** were judged top-tier by reviewers: weight them, especially recent ones with few citations yet.
- **The user is a researcher.** Be specific, cite concretely, and keep the technical content.

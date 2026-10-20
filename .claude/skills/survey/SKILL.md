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
- `--venue iclr,neurips` · `--years 2020-2026` · `--selection oral,spotlight` · `--awarded`
- `--sort relevance|citations|year` · `--limit N` (50) · `--offset N` · `--abstract` (adds the tldr or the abstract's first 400 characters) · `--json` (full records, one JSON object per line)
- `--exclude FILE` skips ids in FILE's first column (your `judged.tsv`).

```
848 matches · showing 1–50 · relevance
iclr_2025:3fa9c1d2 | ICLR 2025 · oral · Outstanding Paper | 412 cites | <title>
```

The first field is the paper's `pid`; every command and working file uses it.

**`uv run ppr search lookup ITEM… [--file F] [--json]`**: grounds arXiv ids, DOIs, `CorpusId:N`, `s2:N`, OpenReview links, pids or titles (`Title ;; Author A, Author B`) in the dataset. Each item comes back `found`, `fuzzy` (confirm it before relying on it) or `not in dataset`, with its paper lines. `--json` gives full records, abstracts included.

**`uv run ppr search cites SEED… [--direction refs|citing|both] [--min-links N] [--abstract] [--exclude F] [--json]`**: Semantic Scholar references and citations of the seeds, each linked paper scored by how many seeds link to it. Two groups: **in dataset** (paper lines) and **outside** (`s2:<CorpusId>`, year, venue, arXiv id or DOI), the outside ones only when linked to at least `--min-links` seeds (default 2). `--abstract` adds outside papers' tldr. `--json` gives one record per linked paper (`group`: `dataset` or `outside`). If it exits non-zero, Semantic Scholar was unreachable: continue without citation chasing and say so in the Search log.

## Data

| Category | Venues |
|----------|--------|
| ML | ICLR, NeurIPS, ICML, TMLR, AAAI, IJCAI |
| NLP | ACL, EMNLP, NAACL, COLM, EACL, COLING |
| CV | CVPR, ICCV, ECCV, WACV |
| Robotics | CoRL, ICRA, IROS, RSS |
| Security | USENIX Security |
| SE | ICSE, FSE, ASE, ISSTA |

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

`W=outputs/<slug>_<YYYY-MM-DD_HH-MM-SS>` holds `criteria.md`, `judged.tsv`, the round files and `report.md`. `judged.tsv` starts with the header `pid	verdict	round	source	reason` and gets a line for every judged paper, `no` included, so `--exclude $W/judged.tsv` keeps it out of later rounds. Outside papers use their `s2:<CorpusId>`; web finds use `web:<arXiv id, DOI or slug>`. Sources: `query`, `cites`, `external`, `web`.

### 4. Round 1: many phrasings

Write 8–15 TERMs across the criteria: synonyms, older and newer names, abbreviations, the problem described without its name, method names. For each:

```bash
uv run ppr search find "data deletion" --exclude $W/judged.tsv --json --limit 50 >> $W/round-1.raw.jsonl
```

then `sort -u $W/round-1.raw.jsonl > $W/round-1.jsonl`. To see a term's hits or match count yourself, run it without `--json`. A term with thousands of matches is too broad: narrow it with `--must` or rephrase it.

### 5. Judge every candidate

Split the round file into batches of 40 (`split -l 40 $W/round-1.jsonl $W/round-1-batch-`). Give each batch to a subagent (Agent tool, `model: sonnet`), several in parallel, with `judging.md` from this skill's folder as the prompt, its `{criteria_path}` and `{batch_path}` filled in. Each replies `pid<TAB>verdict<TAB>reason` lines. Append them to `judged.tsv` with the round number and source. Without a subagent tool, judge the batches yourself by the same brief.

Then read the high and medium papers properly: `uv run ppr search lookup <pids> --json` has dataset papers' abstracts; an outside paper's tldr is in its `cites` record.

### 6. Rounds 2 and on: expand from what is relevant

Each round does at least one of:

- **a. Vocabulary.** Read the high papers' titles and abstracts for phrasings you have not queried (a method's name, another community's word for the problem) and query them as in step 4.
- **b. Citations.** `uv run ppr search cites <high pids> --exclude $W/judged.tsv --abstract --json > $W/round-N-cites.jsonl`. Its in-dataset and outside records are judged like any candidate (source `cites`).
- **c. Classics.** Rerun the TERMs that produced high papers with `--sort citations`: BM25 ranks a foundational paper low when its abstract uses few of the words.

Judge (step 5), record, repeat.

### 7. Stop on saturation

After each round, count the new high and medium papers. Stop when vocabulary expansion and citation chasing have each run at least once and the last round added under 10% of the total found so far. Caps: `novelty` 6 rounds, `related-work` 5, `landscape` 4 per subtopic. Keep the per-round counts (e.g. 34 → 12 → 3 → 0) for the Search log.

### 8. Web search

- Seminal work outside the dataset (another venue, a journal, pre-2013, a famous preprint): only genuinely influential papers.
- In `novelty` mode, always: the last 12 months of preprints on the core criterion. The dataset updates monthly and lags arXiv.

Check every web find with `lookup` first; it may be in the dataset under another title. Mark the rest `not from tracked venues`.

### 9. External lists

When the user hands over a list (a file or pasted text from Asta, Undermind, a web search or a bibliography):

1. Write one item per line to `$W/external.txt` (an arXiv id, a DOI, or `Title ;; Authors`) and run `uv run ppr search lookup --file $W/external.txt`.
2. Judge every item against the criteria (source `external`). From here on, dataset papers carry their venue, track and awards.
3. Use the high ones as seeds for 6a and 6b.
4. In the report add **Accepted papers the external list missed** (your high and medium dataset papers absent from it) and **Papers this search missed** (its high papers your rounds never surfaced, with the likely reason: vocabulary, no citation path, outside the venues).

### 10. Datasets, benchmarks, baselines

In `landscape` mode (and `related-work` when asked): from the high and medium papers' abstracts, the datasets and benchmarks used (scale, domain, metrics) and the baselines compared against. Web search only for details the abstracts lack.

### 11. Report

Write `$W/report.md` in the mode's structure. Every cited paper shows where it stands: `**Title** — Authors (ICLR 2025 · oral · Outstanding Paper) · 412 cites`, or `(not from tracked venues)`. Cite only papers judged high or medium, or seminal web finds you verified.

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

---
name: venue-check
description: "Ground a paper list in accepted venues: for each paper on a list from Asta, Undermind, a bibliography or pasted titles and ids, where it was accepted, its track (oral, spotlight, findings, ...) and awards; and, when asked, the accepted papers at named venues the list missed. Use when the user hands over a paper list and asks for venues, tracks or awards, asks which of the papers were accepted or peer-reviewed, or asks what accepted papers at ICLR, NeurIPS, ACL and the like the list missed. For a full literature search from a research idea, use the survey skill instead."
---

# Venue check

Literature tools built on Semantic Scholar often label accepted papers as arXiv preprints, especially at OpenReview venues (ICML, ICLR, COLM), for months after the conference. This skill checks each paper against the accepted-paper lists of 25 venues (2013–2026), with each paper's track and awards. It is cheap: one lookup and, if asked, a few searches. No rounds and no judging fan-out.

## Tool

The tool is the `ppr` command, from any directory.

- If `ppr` is not found, tell the user to install it with `uv tool install git+https://github.com/brightjade/paper-explorer` and stop.
- Start with `ppr data status --json`. If `managed` is true and `tag` is null, or `last_check` is null or over a day old, run `ppr data update` before anything else, with the Bash tool's timeout raised to 600000 ms. The first download (about 124 MB) and the index build take minutes. A search would otherwise do them under the default 2-minute timeout and be cut off. After that, `ppr` checks for a newer release at most once a day. Messages go to stderr.
- If a command fails with an unknown subcommand or option, the tool is older than this skill. Tell the user to run `uv tool upgrade ppr` and `claude plugin update paper-explorer@paper-explorer`, then stop.
- If a command reports no data, pass its message on and stop.

Work in `surveys/venue-check_<YYYY-MM-DD_HH-MM-SS>/` (`<D>` below; write the literal path into every command).

## 1. Ground the list

1. Write the papers to `<D>/items.txt`, one per line. Lines starting with `#` are comments. Use the most specific id the list gives:
   - an arXiv id: `2303.07345`
   - a DOI
   - an OpenReview or arXiv link
   - `CorpusId:N`
   - else `Title ;; First Author, Second Author` (the authors break ties between similar titles)
2. Run `ppr search lookup --file <D>/items.txt --json > <D>/lookup.jsonl`. You get one JSON object per input line: `input`, `kind`, `status` (`found`, `fuzzy` or `not in dataset`) and `papers`. Each paper has `pid`, `venue`, `venue_name`, `year`, `title`, `selection` (the track), `awards` and `citation_count`.
3. Use the `ppr data status --json` you ran first: `tag` is the release in use, and `venues` gives the years held per venue.

## 2. Report

One table, in the list's order:

| # | Paper | Status | Venue · year · track | Awards | Cites |
|---|---|---|---|---|---|

- **found**: the venue, year and track from the record, e.g. `ICLR 2025 · oral`. Leave the track blank when it is `main` or `poster`.
- **fuzzy**: show the matched title next to the listed one, and mark the row "confirm". Never count it as found until the titles clearly agree.
- **not in dataset**: give the likely reason, from `ppr data status --json`:
  - the venue is not one of the 25 tracked ones;
  - the venue is tracked, but its year is not in this release yet. Example: NeurIPS when `venues.neurips` ends a year before the paper's;
  - otherwise, not accepted at a tracked venue: a preprint, a workshop, a journal or another venue.

  Never say "rejected". Search the web only when the user asks, and then verify acceptance on the venue's own page.

Below the table, give the counts (found, fuzzy, not in dataset), the release tag, and the papers whose venue the source list had wrong or missing. That last list is usually why the user ran this.

## 3. Sweep (only when asked, or when the user names venues)

Find accepted papers at those venues that the list missed.

1. Write the found papers' pids, one per line, to `<D>/found.tsv`.
2. Pick 3–6 terms from the list's common topic: its method names, the problem in other words, and the older names for it.
3. Run each term twice:

```bash
ppr search find "<term>" --venue <ids> --years <YYYY-YYYY> --sort relevance --limit 30 --abstract --exclude <D>/found.tsv
ppr search find "<term>" --venue <ids> --years <YYYY-YYYY> --sort citations --limit 30 --abstract --exclude <D>/found.tsv
```

4. Judge relevance yourself from each title and tldr. List the relevant accepted papers missing from the list, each with its title, venue · year · track, awards, citations and one line on why it belongs.
5. Say that this is keyword search: papers that use other words for the topic can be missed. An exhaustive search is the survey skill.

`--venue` ids: `iclr, neurips, icml, tmlr, aaai, ijcai` (ML) · `acl, emnlp, naacl, colm, eacl, coling` (NLP) · `cvpr, iccv, eccv, wacv` (CV) · `corl, icra, iros, rss` (Robotics) · `usenix_security` (Security) · `icse, fse, ase, issta` (SE). An unknown id is an error that lists the valid ones.

## Guidelines

- Only what the dataset says. Never invent a venue, a track or an award.
- Citation counts are snapshots from the release, good for relative ranking only.
- Oral, spotlight and award papers were judged top-tier by reviewers. Point them out, especially recent ones with few citations yet.

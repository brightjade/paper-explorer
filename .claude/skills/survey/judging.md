# Relevance judging brief

The survey skill hands this brief, filled in, to one subagent per batch of candidates (SKILL.md step 5).

You judge candidate papers for a literature search. You only judge: no searching, browsing or writing files.

- Criteria: `{criteria_path}`. Read it first.
- Candidates: `{batch_path}`, one JSON object per line. Dataset papers have `pid`, `title`, `tldr`, `abstract`, `venue_name`, `year`, `selection`. Papers from citation chasing outside the dataset have `id` (`s2:…`), `title`, `year`, `venue`, `snippet`. External items the dataset does not hold have `id` (`ext:…`), `title` and `group: "external"` (title only: judge from the title alone).

For every candidate decide:

- `high`: meets every required condition.
- `medium`: meets the core condition but misses a qualifier, or is a direct building block the topic relies on (its benchmark, its dataset, the method it extends).
- `low`: the same broad area, but not about the topic.
- `no`: unrelated, or it matches an out-of-scope condition.

Judge on the title and the tldr, abstract or snippet only. Never raise a verdict for the venue, track, awards or citation count. With no abstract or snippet, judge the title; if the title alone cannot settle it, answer `medium` with the reason `title only`.

Reply with exactly one line per candidate, in input order, and nothing else:

`<pid or id><TAB><verdict><TAB><reason, at most 15 words>`

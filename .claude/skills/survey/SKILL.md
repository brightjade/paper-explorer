---
name: survey
description: "Generate a grounded literature survey from real accepted papers at top-tier venues. Use this skill when the user invokes /survey, asks to 'find related work', 'survey papers', 'literature review', or describes a research idea and wants to know what already exists. Also trigger when the user asks about research gaps, relevant datasets, or baselines for a research topic. This skill searches through actual conference proceedings data stored in this repository."
---

# Literature Survey Generator

You are a research assistant that produces grounded literature surveys from **real accepted papers** at top-tier peer-reviewed venues. Unlike generic literature searches, your surveys are anchored in verified conference proceedings data stored in this repository, supplemented by web search only for genuinely seminal works that may reside outside these venues.

## Data Layout

Papers live in `data/<venue>/<year>.jsonl` (one JSON object per line). Each enriched paper has:

- `title`, `authors`, `abstract`, `keywords` — content fields for relevance matching
- `citation_count`, `influential_citation_count` — proxy for impact/influence
- `selection` — track info (oral, spotlight, poster, main, findings, etc.)
- `tldr` — short AI-generated summary
- `link` — URL to the paper
- `external_ids` — ArXiv ID, DOI, DBLP key, etc.

Conference IDs follow the pattern `<venue>_<year>` (e.g., `iclr_2025`, `emnlp_2024`).

### Available venue categories

| Category | Venues |
|----------|--------|
| ML | ICLR, NeurIPS, ICML, TMLR, AAAI, IJCAI |
| NLP | ACL, EMNLP, NAACL, COLM, EACL, COLING |
| CV | CVPR, ICCV, ECCV, WACV |
| Robotics | CoRL, ICRA, IROS, RSS |
| Security | USENIX Security |
| SE | ICSE, FSE, ASE, ISSTA |

Year range varies per venue (generally 2013-2026). Before 2023 most venues come from DBLP and carry only main / findings / industry labels; OpenReview years keep their own labels: ICLR 2017-19 oral / poster, ICLR 2020-22 oral / spotlight / poster, NeurIPS 2021 oral / spotlight / poster plus `datasets`, NeurIPS 2022 only `main` + `datasets` (no oral label, so filtering it for orals finds none), CoRL 2021-22 oral / poster. Not all conferences have enriched data.

---

## Workflow

### Step 1: Clarify scope

If the user has not specified conferences or year range, ask a clarifying question. Present the venue categories above and ask:

1. **Which venue categories or specific conferences** should be searched? Offer the categories as options (ML, NLP, CV, etc.) and let them also name specific venues.
2. **Year range** — default to all available years (2013-2026) but let the user narrow it.

Do not proceed until you know the research idea, target conferences, and year range.

### Step 2: Validate data availability

For each conference in scope, check whether `data/<venue>/<year>.jsonl` exists and is enriched (`citation_count` present on its lines).

- If enriched data is **missing** for some conferences, warn the user with a clear list of which conferences lack enriched data.
- **Do not proceed** until the user acknowledges the warning and tells you to continue (either with the available data, or after they refresh `data/` from the newest data release with `uv run python -m scripts.sync_data` -- the monthly pipeline enriches every conference -- or run `uv run ppr enrich` for the missing conferences).
- If enriched data exists for none of the requested conferences, stop and tell the user.

### Step 3: Search for relevant papers

This is the core step. You have thousands of papers per conference — you cannot read them all. Use a **multi-term grep strategy** to find candidates efficiently.

1. **Extract search terms** from the user's research idea. Generate 10-20 terms covering:
   - Core concepts (e.g., "visual grounding", "referring expression")
   - Methodological terms (e.g., "contrastive learning", "transformer")
   - Related/adjacent concepts (e.g., "object detection", "phrase localization")
   - Abbreviations and variants (e.g., "VLM", "vision-language", "multimodal")

2. **Grep each enriched JSONL file** for these terms (case-insensitive). Use the Grep tool with `output_mode: "content"` to get full matching lines. Each matching line is a complete JSON paper record.

3. **Deduplicate** by title. A paper may match multiple search terms — keep only one copy.

4. **Parse and assess** each unique match:
   - Read the title, abstract, and keywords
   - Judge relevance to the user's research idea (high / medium / low)
   - Note the citation count

5. **Expand search if needed.** If initial results seem thin for a topic you'd expect to have coverage, try additional search terms or broader phrases.

**Important performance notes:**
- Search one conference at a time to keep results manageable.
- Use `head_limit` on grep results if a term is too common (e.g., "learning" will match everything). Prefer specific multi-word phrases over single generic words.
- If a conference has many matches, focus first on high-citation papers (grep for the term, then sort the results by citation_count).

### Step 4: Categorize findings

Organize papers into three tiers:

**Seminal & Influential Papers** — Foundational works with high citation counts that shaped the field. These are the papers everyone in the area knows and cites. Look for:
- Papers with notably high `citation_count` relative to their publication date
- Papers in oral/spotlight tracks at top venues
- Papers that introduced key concepts, datasets, or benchmarks

**Comprehensive Related Work** — Papers that are directly relevant to the research idea. Group these by subtopic or methodological theme. These form the bulk of the survey and represent the current state of the art.

**Tangential but Notable** — Papers that are not directly about the research idea but are relevant in a broader sense (e.g., a general-purpose model that is commonly used as a backbone). Include these only if they add context.

### Step 5: Web search for missing seminal works

After compiling results from the conference data, critically assess: are there well-known seminal papers that should appear but didn't? This happens when:
- A famous paper was published at a venue not in the dataset
- A highly influential preprint was never formally published at a tracked conference
- A foundational paper predates the year range (pre-2013)

Use WebSearch to find these missing papers. **Only add web-searched papers if they are genuinely seminal and influential** — high citation count, widely recognized in the community. Do not pad the survey with random arXiv preprints. When you add a web-searched paper, clearly mark it as "not from conference proceedings" in the report.

### Step 6: Datasets, benchmarks, and baselines

From the papers you've found, extract:

1. **Datasets** — What datasets are commonly used for evaluation in this area? Note their scale, domain, and what they measure.
2. **Benchmarks** — Are there established benchmark suites or leaderboards? What metrics are standard?
3. **Baselines** — What methods are commonly used as baselines? What performance do they achieve?

Source this information primarily from the abstracts and content of found papers. Supplement with web search if the papers reference well-known benchmarks whose details aren't in the abstracts.

### Step 7: Discussion, limitations, and future directions

Synthesize what you've learned into:

1. **Research landscape summary** — What are the main approaches? How has the field evolved over the year range?
2. **Limitations of existing work** — What common limitations do the papers acknowledge? What problems remain unsolved?
3. **Research gaps** — Where are the opportunities? What hasn't been tried? What combinations of ideas seem promising?
4. **Future directions** — Based on trends in the data (newer papers, emerging topics), where is the field heading?

This section is the most valuable part of the survey for the user — they're looking for actionable research ideas.

---

## Output Format

Save the report to `outputs/<topic>_<YYYY-MM-DD_HH-MM-SS>.md` where `<topic>` is a short snake_case slug derived from the research idea. Create the `outputs/` directory if it doesn't exist.

Use this structure:

```markdown
# Literature Survey: [Research Topic]

> Generated on [date] | Conferences searched: [list] | Year range: [range]
> Based on accepted papers from [N] venues with enriched citation data.

## 1. Overview

[2-3 paragraph summary of the research landscape. What is this area about?
What are the main challenges? Why does it matter?]

## 2. Seminal & Influential Papers

[Table or list of foundational papers, ordered by influence. Include:]
- **Title** — Authors (Venue Year) | Citations: N
  > [1-2 sentence summary of contribution]

## 3. Comprehensive Related Work

### 3.1 [Subtopic / Theme 1]
[Papers grouped by theme, with brief descriptions]

### 3.2 [Subtopic / Theme 2]
[...]

(Continue as needed)

## 4. Datasets & Benchmarks

| Dataset/Benchmark | Domain | Scale | Key Metrics | Reference |
|-------------------|--------|-------|-------------|-----------|
| ... | ... | ... | ... | ... |

## 5. Common Baselines & Methods

[What methods are typically compared against? What performance levels are established?]

## 6. Discussion & Research Gaps

### 6.1 Current Limitations
[What problems remain unsolved across the surveyed papers?]

### 6.2 Research Gaps & Opportunities
[Specific gaps the user could address]

### 6.3 Future Directions
[Where the field is heading based on recent trends]

## References

[Full reference list with links. Format:]
1. [Title](link) — Authors. Venue Year. Citations: N.
   [Mark web-searched papers with: *Not from conference proceedings*]
```

---

## Important Guidelines

- **Accuracy over completeness.** Every paper you cite must be real — either from the JSONL data or verified via web search. Never fabricate paper titles, authors, or citation counts.
- **Citation counts are snapshots.** They reflect when the data was last enriched, not real-time counts. This is fine for relative ranking.
- **Be honest about coverage.** If the dataset doesn't have good coverage for a topic (e.g., the relevant venues aren't tracked), say so. Don't pretend the survey is comprehensive when it isn't.
- **Oral/spotlight papers deserve attention.** A paper selected for oral or spotlight presentation was judged as top-tier by reviewers — weight these higher even if their citation count is still low (they may be recent).
- **The user is a researcher.** Write at a level appropriate for someone actively working in the field. Be specific, cite concretely, and don't water down technical content.

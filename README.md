# paper-explorer

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/brightjade/paper-explorer)](https://github.com/brightjade/paper-explorer/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/brightjade/paper-explorer)](https://github.com/brightjade/paper-explorer/commits/main)
[![Sponsor](https://img.shields.io/badge/sponsor-brightjade-ea4aaa?logo=github-sponsors)](https://github.com/sponsors/brightjade)

Retrieve accepted paper metadata from ML/DL/NLP/CV/Robotics/Security/SE conferences. Uses the OpenReview API, web scraping, CVF Open Access, and the DBLP API.

## Getting Started

### 1. Install uv

[uv](https://docs.astral.sh/uv/) is a fast Python package manager used to manage dependencies.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing, restart your terminal so the `uv` command is available.

### 2. Clone and install dependencies

```bash
git clone https://github.com/brightjade/paper-explorer.git
cd paper-explorer
uv sync
source .venv/bin/activate
```

This creates a virtual environment and installs all required packages automatically. Activating it once lets you run `ppr` directly; re-run `source .venv/bin/activate` in each new shell.

### 3. Download paper data

The paper data is hosted as a GitHub Release asset. Run the setup script to download and extract it:

```bash
./setup.sh
```

This downloads the latest data snapshot (~95 MB) and extracts it to `data/`.

> **Note:** Requires either the [GitHub CLI](https://cli.github.com/) (`gh`) or `curl`. If you don't have `gh`, the script falls back to `curl` automatically.

### 4. Set up OpenReview credentials (optional)

Only needed if you want to crawl OpenReview conferences (ICLR, NeurIPS, ICML, COLM, CoRL). Other conferences are scraped from public websites and don't require authentication.

1. Create a free account at https://openreview.net/signup
2. Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

3. Edit `.env` with your OpenReview username and password.

## Usage

```bash
# Crawl one or more conferences
ppr crawl iclr_2025
ppr crawl iclr_2025 neurips_2025 icml_2025

# Enrich with citation counts and abstracts
ppr enrich iclr_2025
ppr enrich iclr_2025 neurips_2025 icml_2025
ppr enrich --all                      # refresh every conference under data/

# Every run also re-attempts papers no earlier run could match, and re-checks
# the papers it already matched against the record they are bound to.

# Validate paper counts against DBLP
ppr validate iclr_2025
ppr validate iclr_2025 neurips_2025 --tolerance 0.15

# Check tracked venues for accepted-paper lists we haven't registered yet
ppr discover
ppr discover --venue cvpr --venue iclr   # limit the sweep to some venues
ppr discover --json                      # machine-readable, for the monthly workflow

# Build static JSON for web app
./build.sh
```

## Available conferences

Conference ID format: `<venue>_<year>` (e.g., `iclr_2025`). Selections indicate available paper tracks.

### ML

| Conference | 2026 | 2025 | 2024 | 2023 |
|---|---|---|---|---|
| ICLR | oral, poster | oral, spotlight, poster | oral, spotlight, poster | oral, spotlight, poster |
| NeurIPS | | oral, spotlight, poster | oral, spotlight, poster | oral, spotlight, poster |
| ICML | main, spotlight | oral, spotlight, poster | oral, spotlight, poster | oral, poster |
| AAAI | main | main | main | main |
| IJCAI | main | main | main | main |

NeurIPS also includes `datasets_oral`, `datasets_spotlight`, `datasets_poster` tracks.

### NLP

| Conference | 2026 | 2025 | 2024 | 2023 |
|---|---|---|---|---|
| ACL | main, findings, industry | main, findings, industry | main, findings | main, findings, industry |
| EMNLP | | main, findings, industry | main, findings, industry | main, findings, industry |
| NAACL | | main, findings, industry | main, findings, industry | |
| COLM | main | main | main | |
| EACL | main, findings, industry | | main, findings | main, findings |
| COLING | | main, industry | main | |

### CV (CVF / ECVA)

| Conference | 2026 | 2025 | 2024 | 2023 |
|---|---|---|---|---|
| CVPR | main | main | main | main |
| ICCV | | main | | main |
| ECCV | | | main | |
| WACV | main | main | main | main |

### Robotics

| Conference | 2025 | 2024 | 2023 |
|---|---|---|---|
| CoRL | oral, poster | main | oral, poster |
| ICRA | main | main | main |
| IROS | main | main | main |
| RSS | main | main | main |

### Security

| Conference | 2026 | 2025 | 2024 | 2023 |
|---|---|---|---|---|
| USENIX Security | main | main | main | main |

### Software Engineering (DBLP)

| Conference | 2025 | 2024 | 2023 |
|---|---|---|---|
| ICSE | main | main | main |
| FSE | main | main | main |
| ASE | main | main | main |
| ISSTA | main | main | main |

## Literature Survey (Claude Code skill)

Use the `/survey` command in Claude Code to generate a grounded literature survey from the accepted papers in this repository. Requires enriched data (`papers_enriched.jsonl`) for the target conferences.

```
# Specify conferences and year range
/survey I'm exploring efficient inference methods for large language models,
like speculative decoding and early exit strategies. Search NLP and ML
conferences from 2023-2025.

# Let it ask you for scope
/survey What papers exist on 3D object detection from point clouds?

# Target specific venues
/survey Find related work on code generation with LLMs. Search ICSE, FSE,
ASE, ACL, and EMNLP from 2023-2025.
```

The survey searches through real accepted papers, ranks by citation count, identifies datasets and benchmarks, and highlights research gaps. Output is saved to `outputs/<topic>_<timestamp>.md`.

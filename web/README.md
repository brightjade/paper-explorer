# Paper Explorer web app

A static React + TypeScript + Vite site for browsing the dataset: a conference list (`/`), the cross-venue Top 100 (`/top`, by year and field, ranked by age-adjusted or raw citations), per-conference paper tables (`/conference/:id`), author pages (`/author/:name`) and topic and citation trends (`/trends`).

It reads only what `scripts/build_data.py` writes to `web/public/data/` (gitignored): `manifest.json`, `authors.json`, `trends.json`, `top.json`, and per conference a `<conference_id>.json`. The per-conference JSON and `top.json` carry each paper's `relative_citations` (see `scripts/impact.py`). The Download button builds `<conference_id>.jsonl` in the browser from the per-conference JSON and drops build-time fields such as `relative_citations`, so the download stays dataset content. When `data/<venue>/awards.json` exists (`ppr awards`), papers carry `awards` (`{label, kind}`, highest kind first) and the conference's manifest entry carries `test_of_time`. A test-of-time prize also lands on the paper it honors when an earlier edition of the same venue holds it, as `{label: "<label> (<Venue> <year>)", kind: "test_of_time"}`, and the awarding conference's `test_of_time` entry then carries `conference` (that edition's id).

## Local development

From the repository root, with `data/` populated:

```bash
./build.sh            # data/ -> web/public/data/
cd web
npm install
npm run dev
```

The site is served under `/paper-explorer/` (`base` in `vite.config.ts`, `basename` in `src/App.tsx`), matching its GitHub Pages URL.

## Checks and build

```bash
npm run lint
npm run build         # tsc -b && vite build -> web/dist/
```

## Deployment

`.github/workflows/deploy.yml` builds and deploys the site to GitHub Pages on every push to `main`, and when the monthly pipeline dispatches it after a data release. It always builds from the latest release's `data.zip`, not from a local `data/`.

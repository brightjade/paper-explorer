# Paper Explorer web app

A static React + TypeScript + Vite site for browsing the dataset: a conference list (`/`), the cross-venue Top 100 (`/top`, by year and field, ranked by age-adjusted or raw citations), per-conference paper tables (`/conference/:id`), author pages (`/author/:name`) and topic and citation trends (`/trends`).

It reads only what `scripts/build_data.py` writes to `web/public/data/` (gitignored): `manifest.json`, `authors.json`, `trends.json`, `top.json`, and per conference a `<conference_id>.json` plus a `<conference_id>.jsonl` copy offered for download. The per-conference JSON and `top.json` carry each paper's `relative_citations` (see `scripts/impact.py`); the download copy does not.

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

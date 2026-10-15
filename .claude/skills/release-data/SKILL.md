---
name: release-data
description: Publish the current data/ as a GitHub data release with `ppr release`. Use this skill when the user asks to "release the data", "publish data", "upload data", "push data to release", "update the release", or any variation of shipping the current data/ contents to GitHub Releases.
---

# Release Data

Publishes the current `data/` directory as a `data-YYYY-MM-DD` GitHub Release with `ppr release` (`ppr/release.py`), which zips `data/` (minus enrich checkpoint files), creates the release, marks it Latest and prunes to the newest 3. The newest data release is the dataset's source of truth: `setup.sh`, `scripts/sync_data.py`, the monthly workflow and `deploy.yml` all start from it.

The monthly workflow releases on its own. Use this skill only for a manual release, e.g. after a hand-registered venue was crawled and enriched locally.

## Steps

1. **Verify data exists**

   ```bash
   ls data/ | head -5
   ```

   If `data/` is empty or missing, stop and tell the user.

2. **Check the pipeline is not running** -- `gh run list --workflow monthly.yml --status in_progress`. If it is, stop: it will publish its own release and refuse to overwrite yours, or yours will be pruned by it.

3. **Find the release this data was built on.** `ppr release` refuses unless `--base-tag` is the newest data release, so a release made in the meantime is never silently replaced. If `data/` was installed by `scripts/sync_data.py`, the base is the tag it recorded:

   ```bash
   base=$(uv run python -c "import json; print(json.load(open('.data-release.json'))['tag'])")
   ```

   Without `.data-release.json` (data installed by `./setup.sh` or by hand), ask the user which release the work started from. The newest non-draft `data-*` release, the rule the monthly workflow uses, is the usual answer:

   ```bash
   gh release list --limit 100 --json tagName,createdAt,isDraft \
     --jq '[.[] | select((.tagName | startswith("data-")) and (.isDraft | not))] | sort_by(.createdAt) | last | .tagName'
   ```

   If there is no data release to build on, stop and tell the user.

4. **Dry run, then publish**

   ```bash
   uv run ppr release --base-tag "$base" --dry-run   # prints the tag it would create and the releases it would delete
   uv run ppr release --base-tag "$base"
   ```

   If it refuses because the newest release is not `$base`, a release (usually the monthly run's) landed after this `data/` was installed. Stop and tell the user; do not retry with the newer tag, because that would drop whatever the newer release added. The work has to be redone on top of the newer release.

5. **Confirm** -- report the new tag and release URL to the user.

6. **Re-adopt the release locally.** `scripts/sync_data.py` still records the old tag in `.data-release.json`, so it now sees `data/` as locally changed and refuses to sync. The new release holds exactly this work, so adopt it once with:

   ```bash
   uv run python -m scripts.sync_data --force
   ```

## Important

- Never commit `data.zip` to git. It is in `.gitignore`.
- Tags are `data-YYYY-MM-DD` (a `-2`, `-3` suffix if that date is taken); `ppr release` derives them and has no custom-tag option.
- The new release is created before old ones are pruned. Never create or delete data releases by hand: deleting first leaves the site with no data if the upload fails.
- Release before `git push`: `deploy.yml` builds the site from the latest release's `data.zip` whenever `main` is pushed.

---
name: release-data
description: Zip the data/ directory and upload it as a GitHub Release asset. Use this skill when the user asks to "release the data", "publish data", "upload data", "push data to release", "update the release", or any variation of shipping the current data/ contents to GitHub Releases.
---

# Release Data

Packages the current `data/` directory into `data.zip` and uploads it to a GitHub Release so users can download it via `setup.sh`.

## Steps

1. **Verify data exists**

   ```bash
   ls data/ | head -5
   ```

   If `data/` is empty or missing, stop and tell the user.

2. **Check the pipeline is not running** -- `gh run list --workflow monthly.yml --status in_progress`. If it is, stop: it will publish its own release and refuse to overwrite yours, or yours will be pruned by it.

3. **Publish**

   ```bash
   base=$(gh release list --json tagName,createdAt --jq '[.[]|select(.tagName|startswith("data-"))]|sort_by(.createdAt)|last|.tagName')
   uv run ppr release --base-tag "$base"
   ```

   This creates the new release first and only then prunes to the newest 3. Never delete releases by hand before creating one: a failure in between leaves the site with no data.

4. **Confirm** -- report the release URL to the user.

## Important

- Never commit `data.zip` to git. It is in `.gitignore`.
- Always use `--latest` when creating a release so `setup.sh` (which defaults to `latest`) picks it up.
- If the user specifies a custom tag, use that instead of the date-based default.

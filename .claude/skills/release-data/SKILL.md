---
name: release-data
description: Zip the data/ directory and upload it as a GitHub Release asset. Use this skill when the user asks to "release the data", "publish data", "upload data", "push data to release", "update the release", or any variation of shipping the current data/ contents to GitHub Releases.
---

# Release Data

Publishes the current `data/` directory as a GitHub Release (via `ppr release`, which zips, creates the release, and prunes old ones) so users can download it via `setup.sh`.

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

   If `$base` is empty there is no data release to build on: stop and tell the user.

   This creates the new release first and only then prunes to the newest 3. Never delete releases by hand before creating one: a failure in between leaves the site with no data.

4. **Confirm** -- report the release URL to the user.

## Important

- Never commit `data.zip` to git. It is in `.gitignore`.
- Tags are `data-YYYY-MM-DD` (a `-2`, `-3` suffix if that date is taken); `ppr release` derives them and has no custom-tag option.
- `ppr release` marks the new release Latest itself, so `setup.sh` (which defaults to `latest`) picks it up. Never create or delete data releases by hand.

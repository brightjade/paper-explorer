"""Decide what the monthly run tells a human, and remember deferral streaks.

Issues exist only for things a person has to act on. A venue that registered
cleanly is news, not a task: it goes to the commit, the release notes and the
job summary instead.
"""

DEFERRED_STREAK_ALERT = 3
UNBOUND_ALERT_RATIO = 0.05


def update_state(state: dict, enrich_results: list[dict]) -> dict:
    """Count consecutive runs in which each conference deferred papers.

    Only an `enriched` result moves the counter: a failed or skipped
    conference did not get a chance to defer, so it neither extends nor
    breaks its streak.
    """
    streak = dict(state.get("deferred_streak", {}))
    for r in enrich_results:
        if r.get("status") != "enriched":
            continue
        if r.get("deferred", 0) > 0:
            streak[r["conf_id"]] = streak.get(r["conf_id"], 0) + 1
        else:
            streak.pop(r["conf_id"], None)
    return {**state, "deferred_streak": streak}


def _last_stage(discover, register, enrich) -> str:
    if discover is None:
        return "setup or discover (steps 1-2)"
    if register is None:
        return "autoregister (step 3)"
    if enrich is None:
        return "tests or enrich (steps 4-5)"
    return "state, build, release, push or deploy (steps 6-9)"


def _section(title: str, lines: list[str]) -> str:
    return f"## {title}\n\n" + "\n".join(lines) if lines else ""


def decide_issue(*, discover: dict | None, register: dict | None, enrich: dict | None,
                 state: dict | None, pipeline_result: str, run_url: str, today: str) -> dict:
    results = (discover or {}).get("results", [])
    outcomes = (register or {}).get("outcomes", [])
    enrich_rows = (enrich or {}).get("results", [])
    streak = (state or {}).get("deferred_streak", {})

    failure = (
        [f"- The pipeline job ended `{pipeline_result}` during {_last_stage(discover, register, enrich)}. {run_url}"]
        if pipeline_result in ("failure", "cancelled") else []
    )
    held = [f"- `{o['conf_id']}` — {o['reason']} — {o.get('url', '')}"
            for o in outcomes if o["status"] == "held"]
    stale = [f"- `{c}`" for c in (discover or {}).get("stale_empty", [])]
    skipped = [f"- `{r['conf_id']}` — {r.get('reason', '')}"
               for r in enrich_rows if r["status"] == "skipped"]
    unbound = [f"- `{r['conf_id']}` — {r['unbound']} of {r['total']} unbound"
               for r in enrich_rows
               if r.get("total") and r.get("unbound", 0) > UNBOUND_ALERT_RATIO * r["total"]]
    deferred = [f"- `{r['conf_id']}` — deferred {r['deferred']} papers, {streak[r['conf_id']]} runs in a row"
                for r in enrich_rows
                if streak.get(r["conf_id"], 0) >= DEFERRED_STREAK_ALERT]
    unreachable = [f"- `{r['conf_id']}` — {r.get('note', '')}"
                   for r in results if r["status"] == "unreachable"]
    manual = [f"- `{r['conf_id']}` — {r.get('url', '')}"
              for r in results if r["status"] == "needs-manual"]
    registered = [f"- `{o['conf_id']}` — {o.get('count', 0)} papers"
                  for o in outcomes if o["status"] == "registered"]

    triggers = {"Pipeline failed": failure, "Held by autoregister": held,
                "Past their announce month but parsing 0 papers": stale,
                "Skipped by an enrich guard": skipped,
                f"Unbound above {UNBOUND_ALERT_RATIO:.0%}": unbound,
                f"Deferred {DEFERRED_STREAK_ALERT}+ runs in a row": deferred}
    fired = {k: v for k, v in triggers.items() if v}

    if not fired:
        if unreachable:
            comment = "\n\n".join([
                f"Run on {today} found nothing to act on, but {len(unreachable)} venue(s) "
                "could not be probed, so it proves nothing. Leaving this issue open.",
                "\n".join(unreachable), run_url,
            ])
            return {"action": "blind", "title": "", "body": "", "comment": comment}
        return {"action": "close", "title": "", "body": "",
                "comment": f"Run on {today} completed cleanly with nothing to act on. Closing. {run_url}"}

    body = "\n\n".join(filter(None, [
        *(_section(k, v) for k, v in fired.items()),
        _section("Not probed", unreachable),
        _section("Registered this run (context)", registered),
        _section("Need a hand-written scraper (context)", manual),
        f"Run: {run_url}",
        "_Run `/check-new-conferences` in Claude Code for the manual path._",
    ]))
    # The comment carries the items themselves: it is the only part of an
    # update that notifies anyone.
    comment = f"Run on {today} needs attention:\n\n" + "\n\n".join(
        f"**{k}**\n" + "\n".join(v) for k, v in fired.items()
    ) + "\n\nFull details in the issue body above."
    return {"action": "notify",
            "title": f"Monthly pipeline needs attention ({today})",
            "body": body, "comment": comment}

import json

from ppr.report import decide_issue, update_state

RUN = "https://github.com/o/r/actions/runs/1"


def _decide(**kw):
    base = dict(discover={"results": [], "stale_empty": []}, register={"outcomes": []},
                enrich={"results": []}, state={}, pipeline_result="success",
                run_url=RUN, today="2026-11-03")
    base.update(kw)
    return decide_issue(**base)


class TestUpdateState:
    def test_increments_and_resets(self):
        state = {"deferred_streak": {"icml_2026": 2, "cvpr_2026": 1}}
        out = update_state(state, [
            {"conf_id": "icml_2026", "status": "enriched", "deferred": 40},
            {"conf_id": "cvpr_2026", "status": "enriched", "deferred": 0},
            {"conf_id": "iclr_2026", "status": "enriched", "deferred": 5},
        ])
        assert out["deferred_streak"] == {"icml_2026": 3, "iclr_2026": 1}

    def test_failed_or_skipped_conferences_keep_their_streak(self):
        state = {"deferred_streak": {"a_2026": 2, "b_2026": 2}}
        out = update_state(state, [
            {"conf_id": "a_2026", "status": "failed", "deferred": 0},
            {"conf_id": "b_2026", "status": "skipped", "deferred": 0},
        ])
        assert out["deferred_streak"] == {"a_2026": 2, "b_2026": 2}

    def test_does_not_mutate_input(self):
        state = {"deferred_streak": {"a_2026": 1}}
        update_state(state, [{"conf_id": "a_2026", "status": "enriched", "deferred": 1}])
        assert state == {"deferred_streak": {"a_2026": 1}}


    def test_a_batch_only_archive_refresh_clears_an_old_streak(self):
        state = {"deferred_streak": {"cvpr_2019": 2}}
        out = update_state(state, [{"conf_id": "cvpr_2019", "status": "enriched", "deferred": 0}])
        assert "cvpr_2019" not in out["deferred_streak"]

    def test_not_due_neither_extends_nor_breaks_a_streak(self):
        state = {"deferred_streak": {"cvpr_2019": 2}}
        out = update_state(state, [{"conf_id": "cvpr_2019", "status": "not-due", "deferred": 0}])
        assert out["deferred_streak"] == {"cvpr_2019": 2}


class TestDecideIssue:
    def test_clean_run_closes(self):
        assert _decide()["action"] == "close"

    def test_successful_registration_alone_is_not_news(self):
        a = _decide(register={"outcomes": [{"conf_id": "colm_2026", "status": "registered", "count": 856}]})
        assert a["action"] == "close"

    def test_unreachable_without_triggers_is_blind(self):
        d = {"results": [{"conf_id": "fse_2026", "status": "unreachable", "note": "unparseable response", "url": "u"}],
             "stale_empty": []}
        a = _decide(discover=d)
        assert a["action"] == "blind"
        assert "fse_2026" in a["comment"]

    def test_held_venue_notifies_with_reason(self):
        a = _decide(register={"outcomes": [
            {"conf_id": "icml_2027", "status": "held", "reason": 'unknown track name "X"', "url": "u"}]})
        assert a["action"] == "notify"
        assert "icml_2027" in a["body"] and 'unknown track name "X"' in a["body"]
        assert "icml_2027" in a["comment"]

    def test_stale_empty_notifies(self):
        a = _decide(discover={"results": [], "stale_empty": ["cvpr_2027"]})
        assert a["action"] == "notify"
        assert "cvpr_2027" in a["body"]

    def test_guard_skip_notifies(self):
        a = _decide(enrich={"results": [{"conf_id": "a_2025", "status": "skipped", "reason": "guard", "total": 0, "unbound": 0, "deferred": 0}]})
        assert a["action"] == "notify"

    def test_unbound_above_five_percent_notifies(self):
        rows = [{"conf_id": "a_2025", "status": "enriched", "total": 100, "unbound": 6, "deferred": 0, "reason": ""}]
        assert _decide(enrich={"results": rows})["action"] == "notify"

    def test_unbound_at_five_percent_does_not(self):
        rows = [{"conf_id": "a_2025", "status": "enriched", "total": 100, "unbound": 5, "deferred": 0, "reason": ""}]
        assert _decide(enrich={"results": rows})["action"] == "close"

    def test_third_consecutive_deferral_notifies(self):
        rows = [{"conf_id": "icml_2026", "status": "enriched", "total": 6000, "unbound": 0, "deferred": 900, "reason": ""}]
        assert _decide(enrich={"results": rows}, state={"deferred_streak": {"icml_2026": 2}})["action"] == "close"
        a = _decide(enrich={"results": rows}, state={"deferred_streak": {"icml_2026": 3}})
        assert a["action"] == "notify"
        assert "icml_2026" in a["body"]

    def test_pipeline_failure_names_the_last_stage_reached(self):
        a = _decide(register=None, enrich=None, pipeline_result="failure")
        assert a["action"] == "notify"
        assert "autoregister" in a["body"]
        assert RUN in a["body"]

    def test_failed_enrich_row_names_the_conference_and_the_stage(self):
        e = {"results": [{"conf_id": "x_2026", "status": "failed", "reason": "S2 down"},
                         {"conf_id": "y_2026", "status": "enriched"}]}
        a = _decide(enrich=e, pipeline_result="failure")
        assert a["action"] == "notify"
        assert "during enrich." in a["body"]
        assert "`x_2026` — S2 down" in a["body"]
        assert "y_2026" not in a["body"]

    def test_nothing_at_all_means_it_died_before_discover(self):
        a = _decide(discover=None, register=None, enrich=None, state=None, pipeline_result="cancelled")
        assert a["action"] == "notify"
        assert "discover" in a["body"]

    def test_needs_manual_is_context_not_a_trigger(self):
        d = {"results": [{"conf_id": "acl_2027", "status": "needs-manual", "url": "u", "note": ""}], "stale_empty": []}
        a = _decide(discover=d)
        assert a["action"] == "close"


class TestCli:
    def test_missing_inputs_read_as_none(self, tmp_path):
        from ppr import cli

        out = tmp_path / "action.json"
        args = cli.build_parser().parse_args([
            "report", "issue", "--discover", str(tmp_path / "nope.json"),
            "--pipeline-result", "failure", "--run-url", RUN, "--out", str(out),
        ])
        cli.cmd_report(args)
        assert json.loads(out.read_text())["action"] == "notify"

    def test_state_round_trip(self, tmp_path):
        from ppr import cli

        enrich = tmp_path / "enrich.json"
        enrich.write_text(json.dumps({"results": [
            {"conf_id": "a_2026", "status": "enriched", "deferred": 1}]}))
        state = tmp_path / "pipeline_state.json"
        args = cli.build_parser().parse_args(
            ["report", "state", "--enrich", str(enrich), "--state", str(state)])
        cli.cmd_report(args)
        cli.cmd_report(args)
        assert json.loads(state.read_text())["deferred_streak"] == {"a_2026": 2}


class TestDeferredGate:
    """A streak only alerts on a conference that deferred in this run."""

    def test_failed_row_with_streak_does_not_alert(self):
        rows = [{"conf_id": "icml_2026", "status": "failed", "total": 0, "unbound": 0, "deferred": 0, "reason": "boom"}]
        a = _decide(enrich={"results": rows}, state={"deferred_streak": {"icml_2026": 3}})
        assert a["action"] == "close"

    def test_skipped_row_with_streak_has_no_deferred_section(self):
        rows = [{"conf_id": "icml_2026", "status": "skipped", "total": 0, "unbound": 0, "deferred": 0, "reason": "guard"}]
        a = _decide(enrich={"results": rows}, state={"deferred_streak": {"icml_2026": 3}})
        assert a["action"] == "notify"
        assert "Skipped by an enrich guard" in a["body"]
        assert "runs in a row" not in a["body"]

    def test_enriched_row_with_streak_but_no_deferral_this_run_does_not_alert(self):
        rows = [{"conf_id": "icml_2026", "status": "enriched", "total": 10, "unbound": 0, "deferred": 0, "reason": ""}]
        a = _decide(enrich={"results": rows}, state={"deferred_streak": {"icml_2026": 3}})
        assert a["action"] == "close"

    def test_row_missing_deferred_key_does_not_raise(self):
        rows = [{"conf_id": "icml_2026", "status": "enriched", "total": 10, "unbound": 0}]
        a = _decide(enrich={"results": rows}, state={"deferred_streak": {"icml_2026": 3}})
        assert a["action"] == "close"


class TestSparseRows:
    """Report rows missing optional keys must not raise on the failure path."""

    def test_held_row_without_reason_still_decides(self):
        a = _decide(pipeline_result="failure", register={"outcomes": [{"conf_id": "x_2027", "status": "held"}]})
        assert a["action"] == "notify"
        assert "x_2027" in a["body"]

    def test_sparse_enrich_and_discover_rows_do_not_raise(self):
        d = {"results": [{"conf_id": "fse_2026", "status": "unreachable"},
                         {"conf_id": "acl_2027", "status": "needs-manual"}], "stale_empty": []}
        e = {"results": [{"conf_id": "a_2025", "status": "skipped"},
                         {"conf_id": "b_2025", "status": "enriched", "total": 100}]}
        a = _decide(discover=d, enrich=e, pipeline_result="failure")
        assert a["action"] == "notify"


class TestCorruptJson:
    def test_corrupt_enrich_file_reads_as_none_and_failure_still_notifies(self, tmp_path):
        from ppr import cli

        bad = tmp_path / "enrich.json"
        bad.write_text("{not json", encoding="utf-8")
        out = tmp_path / "action.json"
        args = cli.build_parser().parse_args([
            "report", "issue", "--enrich", str(bad),
            "--pipeline-result", "failure", "--run-url", RUN, "--out", str(out),
        ])
        cli.cmd_report(args)
        assert json.loads(out.read_text())["action"] == "notify"

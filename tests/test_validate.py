import json
from unittest.mock import patch

import pytest

from ppr import dblp_client
from ppr.dblp_client import DblpUnavailable
from ppr.validate import (
    DBLP_VALIDATION_KEYS,
    DBLP_SOURCE_IDS,
    ValidationResult,
    fetch_dblp_count,
    validate_conference,
)


@pytest.fixture(autouse=True)
def paced_client(monkeypatch):
    """Validation now shares the discovery sweep's DBLP pacing, which means a
    test that did not stub the sleep would wait out the real crawl delay."""
    monkeypatch.setattr("ppr.dblp_client.time.sleep", lambda *_: None)
    monkeypatch.setattr(dblp_client, "_last_request", 0.0)


class TestFetchDblpCount:
    def test_counts_every_key_in_one_query(self):
        with patch("ppr.validate.dblp_client.toc_count", return_value=2387) as c:
            assert fetch_dblp_count(["a.bht", "b.bht"]) == 2387
        c.assert_called_once_with(["a.bht", "b.bht"])

    def test_goes_through_the_shared_client(self):
        import ppr.validate as validate_module

        assert validate_module.dblp_client is dblp_client


class TestThrottlingIsNotACount:
    def test_unavailable_propagates_instead_of_a_partial_count(self):
        """A short number handed to the caller is compared and announced as a
        mismatch that never existed."""
        with patch("ppr.validate.dblp_client.toc_count",
                   side_effect=DblpUnavailable("HTTP 429 after 5 attempts")):
            with pytest.raises(DblpUnavailable):
                fetch_dblp_count(["db/conf/cvpr/cvpr2023.bht"])

    def test_validate_reports_error_not_a_count_mismatch(self, tmp_path, monkeypatch):
        """`ppr validate` is what the skill tells the operator to run right
        after registering a DBLP venue, so a throttled run reading as FAIL
        would fire on the happy path."""
        conf_dir = tmp_path / "iclr_2023"
        conf_dir.mkdir()
        (conf_dir / "papers.jsonl").write_text(
            "\n".join(json.dumps({"title": f"P{i}", "link": "", "authors": []}) for i in range(100))
        )
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)

        with patch(
            "ppr.validate.fetch_dblp_count",
            side_effect=DblpUnavailable("HTTP 429 after 5 attempts"),
        ):
            result = validate_conference("iclr_2023")

        assert result.status == "ERROR"
        assert result.status != "FAIL"
        assert result.scraped == 100
        assert "429" in result.message

    def test_an_error_row_does_not_fail_the_command(self, capsys, monkeypatch):
        """ERROR means "we do not know", like SKIP and NO_DATA. Only a real
        count disagreement is worth a non-zero exit."""
        import argparse

        from ppr.cli import cmd_validate

        monkeypatch.setattr(
            "ppr.validate.validate_conference",
            lambda conf_id, tolerance=0.1: ValidationResult(
                conf_id, "ERROR", scraped=100, message="DBLP did not answer"
            ),
        )
        cmd_validate(argparse.Namespace(conferences=["iclr_2023"], tolerance=0.1))
        assert "ERROR" in capsys.readouterr().out


class TestValidateConference:
    def test_pass_when_counts_match(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / "iclr_2023"
        conf_dir.mkdir()
        papers_file = conf_dir / "papers.jsonl"
        papers_file.write_text(
            "\n".join(json.dumps({"title": f"P{i}", "link": "", "authors": []}) for i in range(100))
        )
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)

        with patch("ppr.validate.fetch_dblp_count", return_value=100):
            result = validate_conference("iclr_2023")

        assert result.status == "PASS"
        assert result.scraped == 100
        assert result.dblp == 100

    def test_fail_when_counts_differ_beyond_tolerance(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / "iclr_2023"
        conf_dir.mkdir()
        papers_file = conf_dir / "papers.jsonl"
        papers_file.write_text(
            "\n".join(json.dumps({"title": f"P{i}", "link": "", "authors": []}) for i in range(200))
        )
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)

        with patch("ppr.validate.fetch_dblp_count", return_value=100):
            result = validate_conference("iclr_2023", tolerance=0.1)

        assert result.status == "FAIL"
        assert result.scraped == 200
        assert result.dblp == 100

    def test_pass_within_tolerance(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / "iclr_2023"
        conf_dir.mkdir()
        papers_file = conf_dir / "papers.jsonl"
        papers_file.write_text(
            "\n".join(json.dumps({"title": f"P{i}", "link": "", "authors": []}) for i in range(105))
        )
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)

        with patch("ppr.validate.fetch_dblp_count", return_value=100):
            result = validate_conference("iclr_2023", tolerance=0.1)

        assert result.status == "PASS"

    def test_skip_dblp_sourced_conference(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)
        result = validate_conference("icra_2024")
        assert result.status == "SKIP"

    def test_no_data_when_not_in_dblp(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / "colm_2024"
        conf_dir.mkdir()
        (conf_dir / "papers.jsonl").write_text('{"title":"P","link":"","authors":[]}\n')
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)

        result = validate_conference("colm_2024")
        assert result.status == "NO_DATA"

    def test_no_data_when_no_output_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)
        result = validate_conference("iclr_2023")
        assert result.status == "NO_DATA"

    def test_no_data_when_dblp_returns_zero(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / "iclr_2023"
        conf_dir.mkdir()
        (conf_dir / "papers.jsonl").write_text('{"title":"P","link":"","authors":[]}\n')
        monkeypatch.setattr("ppr.validate.DATA_DIR", tmp_path)

        with patch("ppr.validate.fetch_dblp_count", return_value=0):
            result = validate_conference("iclr_2023")

        assert result.status == "NO_DATA"


class TestMappingConsistency:
    def test_dblp_source_ids_matches_scraper(self):
        """DBLP_SOURCE_IDS must exactly match the conferences in dblp.py."""
        from ppr.scrapers.dblp import DBLP_CONFERENCES

        assert DBLP_SOURCE_IDS == set(DBLP_CONFERENCES.keys())

    def test_no_overlap_between_source_and_validation(self):
        """A conference should not be both DBLP-sourced and have validation keys."""
        overlap = DBLP_SOURCE_IDS & set(DBLP_VALIDATION_KEYS.keys())
        assert overlap == set(), f"Overlap: {overlap}"

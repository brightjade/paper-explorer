import pytest
from pathlib import Path

from ppr.config import CrawlConfig


class TestCrawlConfig:
    def test_from_yaml_valid(self, tmp_path):
        config_file = tmp_path / "iclr_2025.yaml"
        config_file.write_text("""
conference:
  name: "ICLR"
  year: 2025
  venue_id: "ICLR.cc/2025/Conference"
  selections:
    oral: "ICLR 2025 Oral"
    poster: "ICLR 2025 Poster"
""")
        config = CrawlConfig.from_yaml(config_file)
        assert config.name == "ICLR"
        assert config.year == 2025
        assert config.venue_id == "ICLR.cc/2025/Conference"
        assert config.selections["oral"] == "ICLR 2025 Oral"
        assert config.conference_id == "iclr_2025"
        assert config.get_save_path() == Path("data/iclr/2025.jsonl")

    def test_from_yaml_missing_file(self):
        with pytest.raises(FileNotFoundError):
            CrawlConfig.from_yaml("/nonexistent/path.yaml")

    def test_from_yaml_missing_conference(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("foo: bar\n")
        with pytest.raises(ValueError, match="conference"):
            CrawlConfig.from_yaml(config_file)

    def test_from_yaml_missing_name(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("""
conference:
  year: 2025
  venue_id: "X"
  selections:
    oral: "X"
""")
        with pytest.raises(ValueError, match="name"):
            CrawlConfig.from_yaml(config_file)

    def test_from_yaml_missing_venue_id(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("""
conference:
  name: "X"
  year: 2025
  selections:
    oral: "X"
""")
        with pytest.raises(ValueError, match="venue_id"):
            CrawlConfig.from_yaml(config_file)

    def test_from_yaml_selections_must_be_dict(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("""
conference:
  name: "X"
  year: 2025
  venue_id: "X"
  selections: ["oral", "poster"]
""")
        with pytest.raises(ValueError, match="dict"):
            CrawlConfig.from_yaml(config_file)

    def test_get_save_path(self):
        config = CrawlConfig(
            name="ICLR", year=2025, venue_id="ICLR.cc/2025/Conference",
            selections={"oral": "X"}, conference_id="iclr_2025",
        )
        assert config.get_save_path() == Path("data/iclr/2025.jsonl")

    def test_uses_safe_load(self, tmp_path):
        config_file = tmp_path / "evil.yaml"
        config_file.write_text("""
conference: !!python/object:builtins.dict
  name: "ICLR"
  year: 2025
  venue_id: "X"
  selections:
    oral: "X"
""")
        with pytest.raises(Exception):
            CrawlConfig.from_yaml(config_file)


def _write(tmp_path, body: str, name="iclr_2019.yaml"):
    path = tmp_path / name
    path.write_text(body)
    return path


class TestV1BackfillConfig:
    BASE = """conference:
  name: "ICLR"
  year: 2019
  venue_id: "ICLR.cc/2019/Conference"
  api_version: 1
"""

    def test_reads_decisions_and_submission_invitation(self, tmp_path):
        cfg = CrawlConfig.from_yaml(_write(tmp_path, self.BASE + """  submission_invitation: "X/-/submission"
  decisions: {reply_suffix: Meta_Review, field: recommendation}
  selections: {oral: "Accept (Oral)", poster: "Accept (Poster)"}
"""))
        assert cfg.submission_invitation == "X/-/submission"
        assert cfg.decisions == {"reply_suffix": "Meta_Review", "field": "recommendation"}

    def test_selection_may_list_several_strings(self, tmp_path):
        cfg = CrawlConfig.from_yaml(_write(tmp_path, self.BASE + """  selections:
    datasets: ["Round 1", "Round 2"]
"""))
        assert cfg.selections == {"datasets": ["Round 1", "Round 2"]}

    def test_defaults_are_none(self, tmp_path):
        cfg = CrawlConfig.from_yaml(_write(tmp_path, self.BASE + "  selections: {oral: X}\n"))
        assert (cfg.submission_invitation, cfg.decisions) == (None, None)

    @pytest.mark.parametrize("extra", [
        "  decisions: {field: decision}\n",
        "  decisions: {invitation: A, reply_suffix: B, field: decision}\n",
        "  decisions: {invitation: A}\n",
        "  decisions: {invitation: A, field: decision}\n  extra_venue_ids: [Y]\n",
        "  selections_bad: true\n",
    ])
    def test_rejects_malformed_decisions(self, tmp_path, extra):
        body = self.BASE + extra
        if "selections:" not in body:
            body += "  selections: {oral: X}\n"
        if "selections_bad" in extra:
            body = self.BASE + "  selections: {oral: []}\n"
        with pytest.raises(ValueError):
            CrawlConfig.from_yaml(_write(tmp_path, body))

    def test_decisions_need_api_v1(self, tmp_path):
        body = self.BASE.replace("api_version: 1", "api_version: 2") + \
            "  decisions: {invitation: A, field: decision}\n  selections: {oral: X}\n"
        with pytest.raises(ValueError, match="api_version"):
            CrawlConfig.from_yaml(_write(tmp_path, body))


class TestYearFromPdate:
    BODY = """conference:
  name: "TMLR"
  year: 2025
  venue_id: "TMLR"
  selections: {main: "Accepted by TMLR"}
"""

    def test_year_from_pdate_defaults_to_false(self, tmp_path):
        assert CrawlConfig.from_yaml(_write(tmp_path, self.BODY)).year_from_pdate is False

    def test_year_from_pdate_is_read(self, tmp_path):
        body = self.BODY + "  year_from_pdate: true\n"
        assert CrawlConfig.from_yaml(_write(tmp_path, body)).year_from_pdate is True

    def test_year_from_pdate_must_be_a_bool(self, tmp_path):
        body = self.BODY + '  year_from_pdate: "yes"\n'
        with pytest.raises(ValueError, match="year_from_pdate"):
            CrawlConfig.from_yaml(_write(tmp_path, body))

    def test_year_from_pdate_needs_api_v2(self, tmp_path):
        body = self.BODY + "  year_from_pdate: true\n  api_version: 1\n"
        with pytest.raises(ValueError, match="api_version"):
            CrawlConfig.from_yaml(_write(tmp_path, body))


def test_tmlr_configs():
    for y in range(2022, 2027):
        cfg = CrawlConfig.from_yaml(Path(__file__).resolve().parents[1] / "configs" / f"tmlr_{y}.yaml")
        assert cfg.venue_id == "TMLR"
        assert cfg.year == y
        assert cfg.year_from_pdate is True
        assert cfg.selections == {"main": "Accepted by TMLR"}

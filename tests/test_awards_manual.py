import pytest

from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.manual import MANUAL_DIR, load_manual
from ppr.discover import known_conference_ids

EXPECTED = {
    "wacv_2023": 17, "fse_2023": 15, "fse_2026": 10, "cvpr_2023": 12,
    "usenix_security_2025": 25, "usenix_security_2026": 22, "neurips_2024": 2,
}


def test_the_committed_files_are_the_expected_ones():
    assert sorted(p.stem for p in MANUAL_DIR.glob("*.yaml")) == sorted(EXPECTED)


@pytest.mark.parametrize("conf_id,count", EXPECTED.items())
def test_every_committed_file_loads_and_every_label_is_an_award(conf_id, count):
    awards = load_manual(conf_id)
    assert len(awards) == count
    assert all(a.kind is not None and a.via == "manual" for a in awards)
    assert all(a.source.startswith("https://") for a in awards)


def test_test_of_time_entries_carry_their_link():
    tot = [a for a in load_manual("neurips_2024") if a.kind == "test_of_time"]
    assert [a.title for a in tot] == ["Generative Adversarial Nets",
                                      "Sequence to Sequence Learning with Neural Networks"]
    assert all(a.url for a in tot)


def test_missing_file_is_none(tmp_path):
    assert load_manual("icml_2031", tmp_path) is None


def _write(tmp_path, label):
    (tmp_path / "x_2024.yaml").write_text(
        f'source: https://x.test/\nretrieved: 2026-10-15\nawards:\n  - {{label: "{label}", title: "P"}}\n',
        encoding="utf-8")


def test_unknown_label_raises(tmp_path):
    _write(tmp_path, "Community Choice")
    with pytest.raises(UnknownAwardLabel):
        load_manual("x_2024", tmp_path)


def test_a_non_award_label_raises(tmp_path):
    _write(tmp_path, "Highlight")
    with pytest.raises(UnknownAwardLabel):
        load_manual("x_2024", tmp_path)


def test_the_directory_is_never_mistaken_for_a_conference_config():
    assert "awards_manual" not in known_conference_ids()

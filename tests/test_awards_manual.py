import pytest

from ppr.awards.labels import UnknownAwardLabel
from ppr.awards.manual import CONFIGS_DIR, load_manual, replaced_titles
from ppr.layout import manual_awards_path
from ppr.discover import known_conference_ids
from ppr.matching import title_key

EXPECTED = {
    "wacv_2023": 17, "fse_2023": 15, "fse_2026": 10, "cvpr_2023": 12,
    "usenix_security_2025": 25, "usenix_security_2026": 22, "neurips_2024": 2,
    "neurips_2013": 4, "neurips_2014": 2, "neurips_2015": 2, "neurips_2016": 2, "neurips_2017": 4,
    "neurips_2018": 5, "icml_2013": 6, "icml_2014": 4, "icml_2015": 3, "icml_2017": 7, "icml_2018": 6,
    "icml_2022": 3, "iclr_2021": 8,
    "neurips_2022": 1, "icml_2016": 4, "icml_2021": 1, "iclr_2016": 2, "iclr_2017": 3, "iclr_2018": 3,
    "iclr_2019": 2, "wacv_2021": 2, "fse_2015": 1,
    "cvpr_2019": 45, "cvpr_2020": 27, "cvpr_2021": 35, "cvpr_2022": 2, "iccv_2019": 7, "eccv_2022": 1,
    "wacv_2022": 4, "icse_2013": 6, "icse_2014": 9, "icse_2021": 1, "icse_2022": 1,
}


@pytest.mark.parametrize("conf_id,replaced", [
    ("eccv_2022", "Pose-NDF: Modelling Human Pose Manifolds with Neural Distance Fields"),
    ("icse_2021", "ATVHunter: Reliable Version Detection of Third-Party Libraries for Vulnerability "
                  "Identification in Android Apps"),
    ("icse_2022", "Lessons from Eight Years of Operational Data from a Continuous Integration Service: "
                  "A Case Study of CircleCI"),
])
def test_title_corrections(conf_id, replaced):
    assert title_key(replaced) in {key for _, key in replaced_titles(conf_id)}


def test_the_committed_files_are_the_expected_ones():
    assert sorted(f"{p.parent.parent.name}_{p.stem}" for p in CONFIGS_DIR.glob("*/awards/*.yaml")) == sorted(EXPECTED)


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
    path = manual_awards_path(tmp_path, "x_2024")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
    assert "awards" not in known_conference_ids()


def _file(tmp_path, body, name="x_2024"):
    path = manual_awards_path(tmp_path, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_entries_carry_forum_id_and_url(tmp_path):
    _file(tmp_path, 'source: https://x.test/\nretrieved: 2026-10-17\nawards:\n'
                    '  - {label: "Best Paper", title: "P", forum_id: "abc123", url: "https://x.test/p"}\n')
    [a] = load_manual("x_2024", tmp_path)
    assert (a.forum_id, a.url) == ("abc123", "https://x.test/p")


def test_a_secondary_list_needs_its_corroboration(tmp_path):
    _file(tmp_path, 'source: https://x.test/\nofficial: false\nretrieved: 2026-10-17\n'
                    'awards:\n  - {label: "Best Paper", title: "P"}\n')
    with pytest.raises(ValueError, match="also"):
        load_manual("x_2024", tmp_path)
    _file(tmp_path, 'source: https://x.test/\nofficial: false\nalso: [https://y.test/]\nretrieved: 2026-10-17\n'
                    'awards:\n  - {label: "Best Paper", title: "P"}\n')
    assert len(load_manual("x_2024", tmp_path)) == 1


def test_replaced_titles_are_kind_and_title_key(tmp_path):
    _file(tmp_path, 'source: https://x.test/\nretrieved: 2026-10-17\nawards:\n'
                    '  - {label: "Best Paper Honorable Mention", title: "Pose-NDF: Modeling Poses",'
                    ' replaces: "Pose-NDF: Modelling Poses"}\n'
                    '  - {label: "Best Paper", title: "Q"}\n')
    assert replaced_titles("x_2024", tmp_path) == {("honorable", title_key("Pose-NDF: Modelling Poses"))}
    assert replaced_titles("x_2031", tmp_path) == set()


@pytest.mark.parametrize("conf_id", sorted(EXPECTED))
def test_every_committed_secondary_list_names_its_corroboration(conf_id):
    import yaml
    raw = yaml.safe_load(manual_awards_path(CONFIGS_DIR, conf_id).read_text(encoding="utf-8"))
    if raw.get("official", True) is False:
        assert raw["also"] and all(u.startswith("https://") for u in raw["also"])

import itertools

import pytest

from ppr.search.index import open_index
from ppr.search.lookup import FOUND, FUZZY, MISSING, classify, format_result, lookup, read_items, result_dict
from tests.search_helpers import CDR, ERASE, MU, make_dataset, write_papers


@pytest.fixture
def con(tmp_path):
    return open_index(make_dataset(tmp_path), tmp_path / ".cache" / "search.sqlite")


@pytest.mark.parametrize("raw,kind,value", [
    ("2401.00001", "arxiv", "2401.00001"),
    ("2401.00001v3", "arxiv", "2401.00001"),
    ("arXiv:2401.00001", "arxiv", "2401.00001"),
    ("https://arxiv.org/abs/2401.00001v2", "arxiv", "2401.00001"),
    ("https://arxiv.org/pdf/2401.00001.pdf", "arxiv", "2401.00001"),
    ("10.48550/arXiv.2401.00001", "arxiv", "2401.00001"),
    ("https://doi.org/10.48550/arXiv.2401.00001", "arxiv", "2401.00001"),
    ("10.5555/CDR.1", "doi", "10.5555/cdr.1"),
    ("HTTPS://DOI.ORG/10.5555/CDR.1", "doi", "10.5555/cdr.1"),
    ("doi:10.5555/CDR.1", "doi", "10.5555/cdr.1"),
    ("CorpusId:102", "corpus", "102"),
    ("s2:102", "corpus", "102"),
    ("https://openreview.net/forum?id=abc123XYZ9", "openreview", "abc123XYZ9"),
    ("https://openreview.net/pdf?id=abc123XYZ9", "openreview", "abc123XYZ9"),
    ("abc123XYZ9", "openreview", "abc123XYZ9"),
    ("iclr_2024:3fa9c1d2", "pid", "iclr_2024:3fa9c1d2"),
    ("usenix_security_2025:0123abcd.2", "pid", "usenix_security_2025:0123abcd.2"),
    (ERASE, "title", ERASE),
])
def test_classify(raw, kind, value):
    item = classify(raw)
    assert (item.kind, item.value) == (kind, value)


def test_title_with_authors():
    item = classify("Some Title ;; Ann Lee, Bo Kim")
    assert (item.kind, item.value, item.authors) == ("title", "Some Title", ("Ann Lee", "Bo Kim"))


def test_ids_find_their_paper(con):
    for raw in ("arXiv:2401.00001", "10.48550/arXiv.2401.00001", "CorpusId:101", "s2:101",
                "https://openreview.net/forum?id=abc123XYZ9", "abc123XYZ9"):
        result = lookup(con, raw)
        assert result.status == FOUND and [r["title"] for r in result.rows] == [MU], raw
    assert lookup(con, "https://doi.org/10.5555/CDR.1").rows[0]["corpus_id"] == 102
    assert lookup(con, "2303.07345v5").rows[0]["conf_id"] == "cvpr_2023"


def test_pid_round_trips(con):
    pid = lookup(con, "CorpusId:104").rows[0]["pid"]
    assert lookup(con, pid).rows[0]["corpus_id"] == 104


def test_exact_title_ignores_case_and_punctuation(con):
    assert lookup(con, "“erasing concepts from diffusion models”.").status == FOUND


def test_near_title_with_authors_is_fuzzy(con):
    result = lookup(con, "Certified Data Removal From Machine-Learning Model ;; Chris Park")
    assert result.status == FUZZY and [r["title"] for r in result.rows] == [CDR]


def test_near_title_without_authors_needs_near_identity(con):
    assert lookup(con, "Certified Data Removal from Machine Learning Model").status == FUZZY
    assert lookup(con, "Certified Removal of Data").status == MISSING


def test_unknown_items_are_not_in_dataset(con):
    for raw in ("2501.99999", "10.1000/none", "CorpusId:999", "zzz999zzz999", "A Title Nobody Wrote"):
        assert lookup(con, raw).status == MISSING, raw


def test_a_paper_in_two_conference_years_lists_both(tmp_path):
    data_dir = make_dataset(tmp_path)
    write_papers(data_dir, "tmlr_2023", [{"title": MU, "authors": ["Ann Lee"],
                                          "external_ids": {"ArXiv": "2401.00001"}}])
    con = open_index(data_dir, tmp_path / ".cache" / "search.sqlite")
    assert [r["conf_id"] for r in lookup(con, "2401.00001").rows] == ["tmlr_2023", "iclr_2024"]


def test_read_items(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text("# exported from Asta\n2401.00001\n\n  A Title  \n", encoding="utf-8")
    assert read_items(["CorpusId:1"], f) == ["CorpusId:1", "2401.00001", "A Title"]
    assert read_items([], None) == []


def test_formats(con):
    assert format_result(lookup(con, "CorpusId:999")) == "not in dataset\tCorpusId:999"
    found = lookup(con, "CorpusId:101")
    assert format_result(found).splitlines()[1].startswith(f"    {found.rows[0]['pid']} | ICLR 2024")
    d = result_dict(found)
    assert (d["input"], d["kind"], d["status"]) == ("CorpusId:101", "corpus", "found")
    assert d["papers"][0]["awards"][0]["label"] == "Outstanding Paper"


def test_near_title_of_a_paper_among_many_shared_words(tmp_path):
    data_dir = make_dataset(tmp_path)
    target = "Language Models are Few-Shot Learners"
    words = "Language Models are Few Shot Learner".split()
    fillers = [{"title": " ".join(p), "authors": ["A B"]}  # same words, other order: as long as the target
               for p in itertools.islice(itertools.permutations(words), 1, 41)]
    write_papers(data_dir, "neurips_2020", fillers + [{"title": target, "authors": ["Tom Brown"]}])
    con = open_index(data_dir, tmp_path / ".cache" / "search.sqlite")
    result = lookup(con, "Language Models are Few-Shot Learner")
    assert result.status == FUZZY and [r["title"] for r in result.rows] == [target]

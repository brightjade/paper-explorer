import pytest

from ppr.search import find
from ppr.search.find import Filters, QueryError, build_match, parse_years, phrase, read_exclude, search
from ppr.search.index import open_index
from tests.search_helpers import CDR, ERASE, MU, VLM, make_dataset, write_papers

UNLEARNING = ["unlearning", "data deletion", "concept erasure"]


@pytest.fixture
def con(tmp_path):
    return open_index(make_dataset(tmp_path), tmp_path / ".cache" / "search.sqlite")


def titles(rows):
    return [row["title"] for row in rows]


class TestQuery:
    def test_phrase_quotes_everything(self):
        assert phrase("vision-language") == '"vision-language"'
        assert phrase('say "hi"') == '"say ""hi"""'
        assert phrase("NOT") == '"NOT"'
        assert phrase(" unlearn* ") == '"unlearn"*'

    def test_empty_term_is_an_error(self):
        with pytest.raises(QueryError):
            phrase(" * ")

    def test_terms_are_ored_and_must_is_anded(self):
        assert build_match(["a", "b"], ["c"]) == '("a" OR "b") AND "c"'
        assert build_match([], ["c"]) == '"c"'

    def test_raw_replaces_terms(self):
        assert build_match(["ignored"], raw="title : x") == "title : x"

    def test_nothing_to_search_is_an_error(self):
        with pytest.raises(QueryError):
            build_match([], [])
        with pytest.raises(QueryError):
            build_match([], raw="  ")

    def test_years(self):
        assert parse_years("2020-2024") == (2020, 2024)
        assert parse_years(" 2023 ") == (2023, 2023)
        for bad in ("20-24", "2024-2020", "recent"):
            with pytest.raises(QueryError):
                parse_years(bad)

    def test_split_list(self):
        assert find.split_list(" ICLR, neurips ,") == ("iclr", "neurips")
        assert find.split_list(None) == ()


class TestSearch:
    def test_or_terms_find_every_phrasing(self, con):
        total, rows = search(con, build_match(UNLEARNING))
        assert total == 3 and set(titles(rows)) == {MU, CDR, ERASE}

    def test_operator_words_and_punctuation_are_plain_text(self, con):
        for terms in (["NOT"], ["AND", "OR"], ['say "hi"'], ["C++"], ["GPT-4"], ["vision-language"]):
            search(con, build_match(terms))  # never raises
        assert titles(search(con, build_match(["vision-language", "GPT-4"]))[1]) == [VLM]

    def test_prefix(self, con):
        assert search(con, build_match(["forget*"]))[0] == 1

    def test_a_title_hit_outranks_an_abstract_hit(self, con):
        total, rows = search(con, build_match(["removal"]))
        assert total == 3 and titles(rows)[0] == CDR  # stems: removal, removing, removes

    def test_sorts(self, con):
        match = build_match(UNLEARNING)
        assert titles(search(con, match, sort="citations")[1]) == [CDR, ERASE, MU]
        assert [r["year"] for r in search(con, match, sort="year")[1]] == [2024, 2024, 2023]

    def test_filters(self, con):
        match = build_match(UNLEARNING)
        assert titles(search(con, match, Filters(venues=("cvpr",)))[1]) == [ERASE]
        assert search(con, match, Filters(years=(2024, 2026)))[0] == 2
        assert titles(search(con, match, Filters(selections=("oral",)))[1]) == [MU]
        assert titles(search(con, match, Filters(awarded=True))[1]) == [MU]

    def test_exclude_drops_judged_papers_before_counting(self, con, tmp_path):
        match = build_match(UNLEARNING)
        first = search(con, match)[1][0]["pid"]
        judged = tmp_path / "judged.tsv"
        judged.write_text(f"pid\tverdict\n{first}\thigh\n# note\n\n", encoding="utf-8")
        total, rest = search(con, match, exclude=read_exclude(judged))
        assert total == 2 and first not in {r["pid"] for r in rest}

    def test_missing_exclude_file_excludes_nothing(self, tmp_path):
        assert read_exclude(tmp_path / "judged.tsv") == frozenset()
        assert read_exclude(None) == frozenset()

    def test_abstract_less_papers_rank_after_abstract_bearing_matches(self, tmp_path):
        data_dir = make_dataset(tmp_path)
        write_papers(data_dir, "icml_2022", [{"title": "Unlearning", "authors": ["Zed"], "selection": "poster",
                                              "citation_count": 1000, "external_ids": {"CorpusId": 110}}])
        con = open_index(data_dir, tmp_path / ".cache" / "search.sqlite")
        match = build_match(["unlearning"])
        assert titles(search(con, match)[1]) == [MU, "Unlearning"]
        assert titles(search(con, match, sort="citations")[1]) == ["Unlearning", MU]

    def test_unknown_venue_or_selection_is_an_error_listing_the_known(self, con):
        match = build_match(UNLEARNING)
        with pytest.raises(QueryError, match=r"nips.*cvpr, iclr"):
            search(con, match, Filters(venues=("nips",)))
        with pytest.raises(QueryError, match=r"spotlight.*main, oral, poster"):
            search(con, match, Filters(selections=("spotlight",)))
        assert search(con, match, Filters(venues=("iclr",), selections=("oral",)))[0] == 1

    def test_paging(self, con):
        total, page = search(con, build_match(UNLEARNING), limit=1, offset=1)
        assert total == 3 and len(page) == 1

    def test_malformed_raw_is_a_query_error(self, con):
        with pytest.raises(QueryError):
            search(con, build_match([], raw='"unclosed'))


class TestFormat:
    def test_line_shows_venue_track_and_awards(self, con):
        row = search(con, build_match(["unlearning"]))[1][0]
        assert find.format_line(row) == (
            f"{row['pid']} | ICLR 2024 · oral · Outstanding Paper | 120 cites | {MU}")

    def test_main_track_is_left_out(self, con):
        row = search(con, build_match(["concept erasure"]))[1][0]
        assert find.format_line(row) == f"{row['pid']} | CVPR 2023 | 600 cites | {ERASE}"

    def test_results_header_and_snippet(self, con):
        total, rows = search(con, build_match(["unlearning"]))
        lines = find.format_results(total, rows, 0, "relevance", abstract=True).splitlines()
        assert lines[0] == "1 matches · showing 1–1 · relevance"
        assert lines[2] == "    An unlearning method for LLMs."

    def test_snippet_falls_back_to_a_clipped_abstract(self, con):
        row = search(con, build_match(["data deletion"]))[1][0]
        assert find.snippet(row) == "Data deletion with provable guarantees."
        long = {"tldr": "", "abstract": "abcd" * 300}
        assert find.snippet(long) == "abcd" * 100 + "…"

    def test_empty_page_header(self):
        assert find.format_results(0, [], 0, "citations") == "0 matches · showing none · citations"

    def test_row_dict(self, con):
        d = find.row_dict(search(con, build_match(["unlearning"]))[1][0])
        assert d["awards"] == [{"label": "Outstanding Paper", "kind": "award"}]
        assert "id" not in d and d["corpus_id"] == 101

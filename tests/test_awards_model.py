import json

from ppr.awards.model import Award, awards_path, merge, read_awards, write_awards


def _a(label, kind, title, via="virtual", **kw):
    return Award(label=label, kind=kind, title=title, via=via, source=f"https://{via}.test/", **kw)


class TestMerge:
    def test_drops_a_paper_listed_twice_under_one_label(self):
        # ICML lists an outstanding paper once for its oral and once for its poster.
        out = merge([[_a("Outstanding Paper", "award", "A Watermark for LLMs"),
                      _a("Outstanding Paper", "award", "A watermark for LLMs.")]])
        assert len(out) == 1

    def test_keeps_two_different_labels_of_one_kind_from_one_source(self):
        out = merge([[_a("Best Paper", "award", "P"), _a("Best Student Paper", "award", "P")]])
        assert [a.label for a in out] == ["Best Paper", "Best Student Paper"]

    def test_earlier_source_wins_across_sources(self):
        # ECCV 2024: awards_detail and the CVF registry both list the same honorable mention.
        out = merge([[_a("Best Paper Honorable Mention", "honorable", "P")],
                     [_a("Honorable Mention", "honorable", "P", via="cvf_registry")]])
        assert [(a.label, a.via) for a in out] == [("Best Paper Honorable Mention", "virtual")]

    def test_different_kinds_of_one_paper_are_both_kept(self):
        # WACV 2023: every winner is also one of the 12 finalists.
        out = merge([[_a("Best Paper", "award", "P"), _a("Award Finalist", "candidate", "P")]])
        assert [a.kind for a in out] == ["award", "candidate"]

    def test_sorted_by_kind_then_label_then_title(self):
        out = merge([[_a("Test of Time Award", "test_of_time", "Z"),
                      _a("Honorable Mention", "honorable", "B"),
                      _a("Best Paper", "award", "C"),
                      _a("Best Paper", "award", "A")]])
        assert [(a.kind, a.title) for a in out] == [
            ("award", "A"), ("award", "C"), ("honorable", "B"), ("test_of_time", "Z")]

    def test_no_results_merge_to_nothing(self):
        assert merge([]) == []
        assert merge([[], []]) == []


class TestStorage:
    def test_round_trip_and_key_order(self, tmp_path):
        path = awards_path(tmp_path, "neurips_2024")
        awards = [_a("Best Paper", "award", "P"),
                  _a("Test of Time Award", "test_of_time", "GAN", via="manual", url="https://x.test/gan")]
        write_awards(path, "neurips_2024", awards)

        assert path == tmp_path / "neurips_2024" / "awards.json"
        assert read_awards(path) == awards
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["conf_id"] == "neurips_2024"
        assert list(raw["awards"][1]) == ["label", "kind", "title", "url", "via", "source"]

    def test_missing_file_reads_as_none(self, tmp_path):
        assert read_awards(tmp_path / "awards.json") is None

    def test_rewrite_with_same_awards_is_byte_identical(self, tmp_path):
        path = tmp_path / "awards.json"
        awards = [_a("Best Paper", "award", "Ünïcode — title")]
        write_awards(path, "x_2024", awards)
        first = path.read_bytes()
        write_awards(path, "x_2024", awards)
        assert path.read_bytes() == first
        assert "Ünïcode".encode() in first  # ensure_ascii=False

    def test_leaves_no_temp_file(self, tmp_path):
        write_awards(tmp_path / "awards.json", "x_2024", [_a("Best Paper", "award", "P")])
        assert [p.name for p in tmp_path.iterdir()] == ["awards.json"]

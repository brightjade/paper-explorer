import json

import pytest

from scripts.build_data import (
    parse_conference_id,
    load_papers,
    build_manifest_entry,
    build_author_index,
    build_trends,
    build_all,
    category_of,
    present_categories,
)


@pytest.fixture
def sample_outputs(tmp_path):
    """Create a minimal outputs directory with two conferences."""
    iclr_dir = tmp_path / "iclr_2025"
    iclr_dir.mkdir()
    papers = [
        {
            "title": "Paper A",
            "authors": ["Alice", "Bob"],
            "selection": "oral",
            "keywords": ["nlp", "transformers"],
            "abstract": "Abstract A",
            "link": "https://example.com/a",
            "citation_count": 100,
        },
        {
            "title": "Paper B",
            "authors": ["Bob", "Carol"],
            "selection": "poster",
            "keywords": ["vision"],
            "abstract": "Abstract B",
            "link": "https://example.com/b",
            "citation_count": 50,
        },
        {
            "title": "Paper C",
            "authors": ["Alice"],
            "selection": "poster",
            "keywords": ["nlp"],
            "abstract": "",
            "link": "https://example.com/c",
            "citation_count": 10,
        },
    ]
    with open(iclr_dir / "papers_enriched.jsonl", "w") as f:
        for p in papers:
            f.write(json.dumps(p) + "\n")

    acl_dir = tmp_path / "acl_2025"
    acl_dir.mkdir()
    papers2 = [
        {
            "title": "Paper D",
            "authors": ["Alice", "Dave"],
            "selection": "main",
            "keywords": ["nlp"],
        },
    ]
    with open(acl_dir / "papers.jsonl", "w") as f:
        for p in papers2:
            f.write(json.dumps(p) + "\n")

    return tmp_path


class TestParseConferenceId:
    def test_iclr(self):
        assert parse_conference_id("iclr_2025") == ("ICLR", 2025)

    def test_neurips(self):
        assert parse_conference_id("neurips_2024") == ("NeurIPS", 2024)

    def test_usenix_security(self):
        assert parse_conference_id("usenix_security_2023") == ("USENIX Security", 2023)

    def test_colm(self):
        assert parse_conference_id("colm_2024") == ("COLM", 2024)

    def test_icse(self):
        assert parse_conference_id("icse_2024") == ("ICSE", 2024)

    def test_fse(self):
        assert parse_conference_id("fse_2024") == ("FSE", 2024)

    def test_ase(self):
        assert parse_conference_id("ase_2024") == ("ASE", 2024)

    def test_issta(self):
        assert parse_conference_id("issta_2024") == ("ISSTA", 2024)

    def test_cvpr(self):
        assert parse_conference_id("cvpr_2025") == ("CVPR", 2025)

    def test_iccv(self):
        assert parse_conference_id("iccv_2023") == ("ICCV", 2023)

    def test_eccv(self):
        assert parse_conference_id("eccv_2024") == ("ECCV", 2024)

    def test_wacv(self):
        assert parse_conference_id("wacv_2025") == ("WACV", 2025)

    def test_icra(self):
        assert parse_conference_id("icra_2024") == ("ICRA", 2024)

    def test_iros(self):
        assert parse_conference_id("iros_2024") == ("IROS", 2024)

    def test_rss(self):
        assert parse_conference_id("rss_2024") == ("RSS", 2024)

    def test_ijcai(self):
        assert parse_conference_id("ijcai_2024") == ("IJCAI", 2024)

    def test_corl(self):
        assert parse_conference_id("corl_2024") == ("CoRL", 2024)

    def test_eacl(self):
        assert parse_conference_id("eacl_2024") == ("EACL", 2024)

    def test_coling(self):
        assert parse_conference_id("coling_2024") == ("COLING", 2024)


class TestCategories:
    @pytest.mark.parametrize(
        "conf_id, expected",
        [
            ("iclr_2025", "ML"),
            ("aaai_2025", "ML"),
            ("colm_2024", "NLP"),
            ("coling_2025", "NLP"),
            ("wacv_2026", "CV"),
            ("corl_2025", "Robotics"),
            ("rss_2026", "Robotics"),
            ("issta_2026", "SE"),
            ("usenix_security_2025", "Security"),
            ("somethingnew_2026", "Others"),
        ],
    )
    def test_category_of(self, conf_id, expected):
        assert category_of(conf_id) == expected

    def test_present_categories_keep_display_order_and_skip_empty(self):
        assert present_categories(["usenix_security_2025", "cvpr_2025", "iclr_2025"]) == [
            "ML",
            "CV",
            "Security",
        ]


class TestLoadPapers:
    def test_prefers_enriched(self, sample_outputs):
        papers = load_papers(sample_outputs / "iclr_2025")
        assert len(papers) == 3
        assert papers[0]["citation_count"] == 100

    def test_falls_back_to_plain(self, sample_outputs):
        papers = load_papers(sample_outputs / "acl_2025")
        assert len(papers) == 1
        assert "citation_count" not in papers[0]


class TestBuildManifestEntry:
    def test_with_citations(self, sample_outputs):
        papers = load_papers(sample_outputs / "iclr_2025")
        entry = build_manifest_entry("iclr_2025", papers)
        assert entry["id"] == "iclr_2025"
        assert entry["venue"] == "ICLR"
        assert entry["year"] == 2025
        assert entry["category"] == "ML"
        assert entry["paper_count"] == 3
        assert entry["has_citations"] is True
        assert sorted(entry["tracks"]) == ["oral", "poster"]
        assert len(entry["top_papers"]) == 3
        assert entry["top_papers"][0]["citation_count"] == 100
        assert entry["total_citations"] == 160

    def test_without_citations(self, sample_outputs):
        papers = load_papers(sample_outputs / "acl_2025")
        entry = build_manifest_entry("acl_2025", papers)
        assert entry["has_citations"] is False
        assert entry["total_citations"] == 0
        assert entry["top_papers"] == []


class TestBuildAuthorIndex:
    def test_aggregation(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
            "acl_2025": load_papers(sample_outputs / "acl_2025"),
        }
        authors = build_author_index(all_papers)
        alice = next(a for a in authors if a["name"] == "Alice")
        assert alice["paper_count"] == 3
        assert alice["total_citations"] == 110
        assert sorted(alice["conferences"]) == ["acl_2025", "iclr_2025"]

        bob = next(a for a in authors if a["name"] == "Bob")
        assert bob["paper_count"] == 2
        assert bob["total_citations"] == 150


class TestBuildTrends:
    def test_overview_section(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
            "acl_2025": load_papers(sample_outputs / "acl_2025"),
        }
        trends = build_trends(all_papers)
        overview = trends["overview"]
        assert overview["venue_counts_by_year"]["2025"]["ICLR"] == 3
        assert overview["venue_counts_by_year"]["2025"]["ACL"] == 1
        assert overview["citation_counts_by_year"]["2025"]["ICLR"] == 160
        assert overview["citation_counts_by_year"]["2025"]["ACL"] == 0

    def test_top_level_keys(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        assert "overview" in trends
        assert "topics" in trends
        assert "impact" in trends
        assert "composition" in trends

    def test_impact_citation_stats(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        stats = trends["impact"]["citation_stats_by_year"]["2025"]["ICLR"]
        assert stats["min"] == 10
        assert stats["max"] == 100
        assert "median" in stats
        assert "q1" in stats
        assert "q3" in stats

    def test_impact_has_no_top_papers(self, sample_outputs):
        """The top-20 table moved to top.json (the Top 100 page)."""
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        assert "top_papers_by_year" not in trends["impact"]

    def test_composition_track_breakdown(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        tracks = trends["composition"]["track_breakdown_by_year"]["2025"]["ICLR"]
        assert tracks["oral"] == 1
        assert tracks["poster"] == 2

    def test_composition_venue_counts_all_years(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        all_years = trends["composition"]["venue_counts_all_years"]
        assert all_years["ICLR"]["2025"] == 3

    def test_growth_pct_requires_two_years(self, sample_outputs):
        """Growth percentage requires at least two years of data."""
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        assert trends["overview"]["growth_pct_by_year"] == {}

    def test_topics_section_present(self, sample_outputs):
        all_papers = {
            "iclr_2025": load_papers(sample_outputs / "iclr_2025"),
        }
        trends = build_trends(all_papers)
        topics = trends["topics"]
        assert "top_ngrams_by_year" in topics
        assert "rising_falling_by_year" in topics
        assert "ngram_trends" in topics
        assert "venue_ngram_matrix_by_year" in topics


class TestBuildAll:
    def test_ships_no_jsonl_copies(self, sample_outputs, tmp_path):
        """Downloads are generated in the browser from the per-conference JSON;
        the copies were half the deploy (222 MB) and would pass 1 GB after the
        backfill."""
        out_dir = tmp_path / "web_data"
        build_all(sample_outputs, out_dir)
        assert list(out_dir.glob("*.jsonl")) == []

    def test_produces_all_files(self, sample_outputs, tmp_path):
        out_dir = tmp_path / "web_data"
        build_all(sample_outputs, out_dir)

        assert (out_dir / "manifest.json").exists()
        assert (out_dir / "iclr_2025.json").exists()
        assert (out_dir / "acl_2025.json").exists()
        assert (out_dir / "authors.json").exists()
        assert (out_dir / "trends.json").exists()
        assert (out_dir / "top.json").exists()

        manifest = json.loads((out_dir / "manifest.json").read_text())
        assert len(manifest["conferences"]) == 2

        iclr_data = json.loads((out_dir / "iclr_2025.json").read_text())
        assert len(iclr_data) == 3

    def test_per_conference_json_carries_relative_citations(self, sample_outputs, tmp_path):
        out_dir = tmp_path / "web_data"
        build_all(sample_outputs, out_dir)
        iclr = json.loads((out_dir / "iclr_2025.json").read_text())
        # One cohort (iclr_2025 has no dates -> 2025-01-15): mean (100+50+10)/3
        assert [p["relative_citations"] for p in iclr] == [1.88, 0.94, 0.19]
        acl = json.loads((out_dir / "acl_2025.json").read_text())
        assert all("relative_citations" not in p for p in acl)

    def test_relative_citations_never_reach_data(self, sample_outputs, tmp_path):
        """relative_citations is build output only. The download is built in the
        browser and drops it (web/src/pages/Conference.tsx), so the one place
        left to guard is data/ itself: the build must not write it back."""
        sources = sorted(sample_outputs.glob("*/*.jsonl"))
        assert sources  # the fixture's iclr_2025 and acl_2025 files
        before = {p: p.read_bytes() for p in sources}
        build_all(sample_outputs, tmp_path / "web_data")
        assert {p: p.read_bytes() for p in sources} == before
        for p in sources:
            assert all("relative_citations" not in json.loads(line)
                       for line in p.read_text().splitlines() if line.strip())

    def test_writes_top_json(self, sample_outputs, tmp_path):
        out_dir = tmp_path / "web_data"
        build_all(sample_outputs, out_dir)
        top = json.loads((out_dir / "top.json").read_text())
        assert top["categories"] == ["ML", "NLP"]
        assert top["years"] == ["2025"]
        ranked = [top["papers"][i]["title"] for i in top["lists"]["all"]["all"]["relative"]]
        assert ranked == ["Paper A", "Paper B", "Paper C"]
        # acl_2025 is NLP but never enriched: the list exists and is empty
        assert top["lists"]["2025"]["NLP"]["relative"] == []

    def test_manifest_carries_category(self, sample_outputs, tmp_path):
        out_dir = tmp_path / "web_data"
        build_all(sample_outputs, out_dir)
        manifest = json.loads((out_dir / "manifest.json").read_text())
        assert {c["id"]: c["category"] for c in manifest["conferences"]} == {
            "iclr_2025": "ML",
            "acl_2025": "NLP",
        }

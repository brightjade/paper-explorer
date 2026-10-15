from unittest.mock import MagicMock

import pytest

from ppr.register import (
    TRACK_VOCABULARY,
    RegistrationError,
    openreview_selections,
    register_cvf,
    register_dblp,
    register_researchr,
    register_usenix,
    render_openreview_config,
    selections_from_notes,
)


def _module(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


DBLP_SRC = '''DBLP_CONFERENCES = {
    "icse_2025": {"key": "db/conf/icse/icse2025.bht"},
}
'''

DBLP_SRC_WITH_COMMENT = '''# icse_2026 will be added once its toc key is known
DBLP_CONFERENCES = {
    "icse_2025": {"key": "db/conf/icse/icse2025.bht"},
}
'''

CVF_SRC = '''CVF_CONFERENCES = {
    "cvpr_2025": {"url": f"{CVF_BASE_URL}/CVPR2025?day=all", "parser": "openaccess"},
}
'''

USENIX_SRC = '''USENIX_CONFERENCES = {
    "usenix_security_2025": "usenixsecurity25",
}
'''


class TestRegisterDblp:
    def test_inserts_before_the_closing_brace(self, tmp_path):
        p = _module(tmp_path, "dblp.py", DBLP_SRC)
        register_dblp("icse_2026", "db/conf/icse/icse2026.bht", p)
        text = p.read_text()
        assert '"icse_2026": {"key": "db/conf/icse/icse2026.bht"},' in text
        assert text.index("icse_2025") < text.index("icse_2026")
        assert "icse_2025" in text  # existing entries survive

    def test_refuses_a_duplicate(self, tmp_path):
        p = _module(tmp_path, "dblp.py", DBLP_SRC)
        with pytest.raises(RegistrationError, match="already registered"):
            register_dblp("icse_2025", "db/conf/icse/icse2025.bht", p)

    def test_raises_when_the_dict_is_absent(self, tmp_path):
        p = _module(tmp_path, "dblp.py", "SOMETHING_ELSE = {}\n")
        with pytest.raises(RegistrationError, match="DBLP_CONFERENCES"):
            register_dblp("icse_2026", "k", p)

    def test_id_appearing_only_in_a_comment_does_not_block_registration(self, tmp_path):
        """The duplicate check must be scoped to the dict's own span.

        `icse_2026` appears in a comment above `DBLP_CONFERENCES`, not inside
        the dict itself, so registration must still succeed.
        """
        p = _module(tmp_path, "dblp.py", DBLP_SRC_WITH_COMMENT)
        register_dblp("icse_2026", "db/conf/icse/icse2026.bht", p)
        text = p.read_text()
        assert '"icse_2026": {"key": "db/conf/icse/icse2026.bht"},' in text
        assert "icse_2025" in text


class TestRegisterCvf:
    def test_inserts_entry(self, tmp_path):
        p = _module(tmp_path, "cvf.py", CVF_SRC)
        register_cvf("cvpr_2026", "https://openaccess.thecvf.com/CVPR2026?day=all", "openaccess", p)
        assert (
            '"cvpr_2026": {"url": f"{CVF_BASE_URL}/CVPR2026?day=all", "parser": "openaccess"},'
            in p.read_text()
        )

    def test_ecva_url_uses_its_constant(self, tmp_path):
        p = _module(tmp_path, "cvf.py", CVF_SRC)
        register_cvf("eccv_2026", "https://www.ecva.net/papers.php", "ecva", p, year=2026)
        assert (
            '"eccv_2026": {"url": f"{ECVA_BASE_URL}/papers.php", "parser": "ecva", "year": 2026},'
            in p.read_text()
        )

    def test_foreign_host_stays_a_plain_string(self, tmp_path):
        p = _module(tmp_path, "cvf.py", CVF_SRC)
        register_cvf("wacv_2027", "https://wacv.thecvf.com/Conferences/2027/AcceptedPapers",
                     "accepted", p)
        assert '"url": "https://wacv.thecvf.com/Conferences/2027/AcceptedPapers"' in p.read_text()

    def test_includes_year_for_the_ecva_parser(self, tmp_path):
        p = _module(tmp_path, "cvf.py", CVF_SRC)
        register_cvf("eccv_2026", "https://www.ecva.net/papers.php", "ecva", p, year=2026)
        assert '"year": 2026' in p.read_text()


DBLP_GROUPED_SRC = '''DBLP_CONFERENCES = {
    # ICSE
    "icse_2024": {"key": "db/conf/icse/icse2024.bht"},
    "icse_2025": {"key": "db/conf/icse/icse2025.bht"},
    # FSE
    "fse_2025": {"key": "db/journals/pacmse/pacmse2.bht", "number": "FSE"},
}
'''


class TestGroupedInsertion:
    def test_lands_after_its_own_venue_group(self, tmp_path):
        p = _module(tmp_path, "dblp.py", DBLP_GROUPED_SRC)
        register_dblp("icse_2026", "db/conf/icse/icse2026.bht", p)
        lines = p.read_text().splitlines()
        i = next(n for n, l in enumerate(lines) if "icse_2026" in l)
        assert "icse_2025" in lines[i - 1]
        assert lines[i + 1].strip() == "# FSE"

    def test_unknown_prefix_goes_before_the_closing_brace(self, tmp_path):
        p = _module(tmp_path, "dblp.py", DBLP_GROUPED_SRC)
        register_dblp("ase_2026", "db/conf/kbse/ase2026.bht", p)
        lines = p.read_text().splitlines()
        assert "ase_2026" in lines[-2]
        assert lines[-1] == "}"

    def test_prefix_is_not_a_substring_match(self, tmp_path):
        # "fse_" must not match an "issta_..." line that merely mentions FSE.
        src = '''DBLP_CONFERENCES = {
    "fse_2025": {"key": "a"},
    "issta_2025": {"key": "a", "number": "FSE_like"},
}
'''
        p = _module(tmp_path, "dblp.py", src)
        register_dblp("fse_2026", "b", p)
        lines = p.read_text().splitlines()
        assert "fse_2026" in lines[2]
        assert "issta_2025" in lines[3]


class TestRegisterDblpNumber:
    def test_writes_the_number_filter(self, tmp_path):
        p = _module(tmp_path, "dblp.py", DBLP_SRC)
        register_dblp("fse_2026", "db/journals/pacmse/pacmse3.bht", p, number="FSE")
        assert (
            '"fse_2026": {"key": "db/journals/pacmse/pacmse3.bht", "number": "FSE"},'
            in p.read_text()
        )


class TestRegisterUsenix:
    def test_inserts_entry(self, tmp_path):
        p = _module(tmp_path, "usenix.py", USENIX_SRC)
        register_usenix("usenix_security_2026", "usenixsecurity26", p)
        assert '"usenix_security_2026": "usenixsecurity26",' in p.read_text()


class TestOpenreviewSelections:
    def _client(self, venues):
        notes = []
        for v in venues:
            n = MagicMock()
            n.content = {"venue": {"value": v}}
            notes.append(n)
        c = MagicMock()
        c.get_all_notes.return_value = notes
        return c

    def test_single_venue_value_yields_one_main_selection(self):
        """CoRL 2024 tags every paper 'CoRL 2024' -- the bug this prevents."""
        client = self._client(["CoRL 2024"] * 264)
        assert openreview_selections(client, "robot-learning.org/CoRL/2024/Conference") == {
            "main": "CoRL 2024"
        }

    def test_oral_and_poster_are_named_from_the_venue_strings(self):
        client = self._client(["ICLR 2026 Oral"] * 5 + ["ICLR 2026 Poster"] * 50)
        assert openreview_selections(client, "ICLR.cc/2026/Conference") == {
            "oral": "ICLR 2026 Oral",
            "poster": "ICLR 2026 Poster",
        }

    def test_spotlight_is_recognised(self):
        client = self._client(["ICML 2026 Oral", "ICML 2026 Spotlight", "ICML 2026 Poster"])
        assert set(openreview_selections(client, "ICML.cc/2026/Conference")) == {
            "oral", "spotlight", "poster"
        }

    def test_no_notes_raises_rather_than_writing_an_empty_config(self):
        c = MagicMock()
        c.get_all_notes.return_value = []
        with pytest.raises(RegistrationError, match="no papers"):
            openreview_selections(c, "ICLR.cc/2027/Conference")

    def test_all_blank_venues_raises_rather_than_writing_empty_selections(self):
        """Notes came back, but none carried a venue string.

        Without this guard, `values` empties out after discarding blanks,
        `len(values) == 1` is false, the loop over an empty set produces `{}`,
        and the caller would write a config with no selections -- the same
        failure mode as the corl_2024 bug, just triggered a different way.
        """
        client = self._client([""] * 5)
        with pytest.raises(RegistrationError, match="none carried a venue"):
            openreview_selections(client, "SOME.cc/2026/Conference")

    def test_colliding_track_words_raises_instead_of_silently_dropping_one(self):
        """Two distinct venue strings both containing 'poster' must not
        silently collapse into a single selection with one of them lost."""
        client = self._client(["NeurIPS 2026 Poster", "NeurIPS 2026 Poster Session"])
        with pytest.raises(RegistrationError) as exc_info:
            openreview_selections(client, "NeurIPS.cc/2026/Conference")
        message = str(exc_info.value)
        assert "NeurIPS 2026 Poster" in message
        assert "NeurIPS 2026 Poster Session" in message


class TestRenderOpenreviewConfig:
    def test_renders_loadable_yaml(self):
        import yaml

        text = render_openreview_config("CoRL", 2024, "robot-learning.org/CoRL/2024/Conference",
                                        {"main": "CoRL 2024"})
        parsed = yaml.safe_load(text)["conference"]
        assert parsed["name"] == "CoRL"
        assert parsed["year"] == 2024
        assert parsed["venue_id"] == "robot-learning.org/CoRL/2024/Conference"
        assert parsed["selections"] == {"main": "CoRL 2024"}
        # api_version is intentionally omitted: it must match the shape of
        # most existing configs (iclr_2025.yaml, icml_2025.yaml, etc.), which
        # rely on CrawlConfig's default rather than stating it explicitly.
        assert "api_version" not in parsed

    def test_omitted_api_version_still_resolves_to_2_through_crawlconfig(self, tmp_path):
        """Pin the behavior even though the field is gone from the rendered text."""
        from ppr.config import CrawlConfig

        text = render_openreview_config("CoRL", 2024, "robot-learning.org/CoRL/2024/Conference",
                                        {"main": "CoRL 2024"})
        p = tmp_path / "corl_2024.yaml"
        p.write_text(text)
        config = CrawlConfig.from_yaml(p)
        assert config.api_version == 2


class TestRegularIsMain:
    def test_icml_2026_regular_maps_to_main(self):
        client = TestOpenreviewSelections()._client(
            ["ICML 2026 regular"] * 10 + ["ICML 2026 spotlight"] * 3
        )
        assert openreview_selections(client, "ICML.cc/2026/Conference") == {
            "main": "ICML 2026 regular",
            "spotlight": "ICML 2026 spotlight",
        }

    def test_unknown_word_still_falls_back_to_a_slug(self):
        # Manual registration keeps its old behaviour; autoregister is the one
        # that refuses names outside TRACK_VOCABULARY.
        client = TestOpenreviewSelections()._client(["X 2026 Long", "X 2026 Poster"])
        sel = openreview_selections(client, "X.cc/2026/Conference")
        assert sel["x_2026_long"] == "X 2026 Long"

    def test_vocabulary(self):
        assert TRACK_VOCABULARY == ("main", "oral", "spotlight", "poster", "findings", "industry")


class TestSelectionsFromNotes:
    def test_works_on_notes_directly(self):
        notes = TestOpenreviewSelections()._client(["COLM 2026"] * 3).get_all_notes()
        assert selections_from_notes(notes, "colmweb.org/COLM/2026/Conference") == {
            "main": "COLM 2026"
        }


class TestRenderExtraVenueIds:
    def test_extra_venue_ids_round_trip_through_crawlconfig(self, tmp_path):
        from ppr.config import CrawlConfig

        text = render_openreview_config(
            "NeurIPS", 2026, "NeurIPS.cc/2026/Conference",
            {"poster": "NeurIPS 2026 poster", "datasets_poster": "NeurIPS 2026 Datasets and Benchmarks Track poster"},
            extra_venue_ids=["NeurIPS.cc/2026/Datasets_and_Benchmarks_Track"],
        )
        p = tmp_path / "neurips_2026.yaml"
        p.write_text(text)
        config = CrawlConfig.from_yaml(p)
        assert config.extra_venue_ids == ["NeurIPS.cc/2026/Datasets_and_Benchmarks_Track"]
        assert config.selections["datasets_poster"].endswith("Track poster")

    def test_no_extra_ids_renders_no_key(self):
        text = render_openreview_config("CoRL", 2026, "v", {"main": "CoRL 2026"})
        assert "extra_venue_ids" not in text


RESEARCHR_SRC = '''RESEARCHR_CONFERENCES = {
    # ICSE
    "icse_2025": {"url": "https://conf.researchr.org/track/icse-2025/icse-2025-research-track", "track": "Research Track"},
    # ASE
    "ase_2025": {"url": "https://conf.researchr.org/track/ase-2025/ase-2025-papers", "track": "Research Papers"},
}
'''

ICSE_2026_URL = "https://conf.researchr.org/track/icse-2026/icse-2026-research-track"


class TestRegisterResearchr:
    def test_inserts_the_entry_in_its_venue_group(self, tmp_path):
        p = _module(tmp_path, "researchr.py", RESEARCHR_SRC)
        register_researchr("icse_2026", ICSE_2026_URL, "Research Track", p)
        text = p.read_text()
        line = f'"icse_2026": {{"url": "{ICSE_2026_URL}", "track": "Research Track"}},'
        assert line in text
        assert text.index('"icse_2025"') < text.index('"icse_2026"') < text.index("# ASE")

    def test_refuses_a_duplicate(self, tmp_path):
        p = _module(tmp_path, "researchr.py", RESEARCHR_SRC)
        with pytest.raises(RegistrationError):
            register_researchr("icse_2025", ICSE_2026_URL, "Research Track", p)

    def test_the_written_module_still_parses(self, tmp_path):
        p = _module(tmp_path, "researchr.py", RESEARCHR_SRC)
        register_researchr("icse_2026", ICSE_2026_URL, "Research Track", p)
        namespace: dict = {}
        exec(p.read_text(), namespace)
        assert namespace["RESEARCHR_CONFERENCES"]["icse_2026"]["track"] == "Research Track"

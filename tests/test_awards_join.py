import json

from ppr.awards.join import attach, attach_test_of_time, load_entries


def _e(label, kind, title, **kw):
    return {"label": label, "kind": kind, "title": title, "via": "v", "source": "s", **kw}


def test_matches_by_title_key_across_punctuation_and_quotes():
    papers = [{"title": "Why Diffusion Models Don't Memorize: The Role of Implicit Dynamical Regularization"}]
    out = attach(papers, [_e("Best Paper", "award",
                             "Why Diffusion Models Don’t Memorize:  The Role of Implicit Dynamical Regularization.")])
    assert out.papers[0]["awards"] == [{"label": "Best Paper", "kind": "award"}]
    assert out.unmatched == []


def test_forum_id_beats_title():
    # The ICLR 2025 blog says "Model Editing" where OpenReview says "Knowledge Editing".
    papers = [{"title": "AlphaEdit: Null-Space Constrained Knowledge Editing for Language Models",
               "forum_id": "HvSytvg3Jh"}]
    out = attach(papers, [_e("Outstanding Papers", "award",
                             "AlphaEdit: Null-Space Constrained Model Editing for Language Models",
                             forum_id="HvSytvg3Jh")])
    assert out.papers[0]["awards"] == [{"label": "Outstanding Papers", "kind": "award"}]


def test_unknown_forum_id_falls_back_to_title():
    papers = [{"title": "P", "forum_id": "aaa"}]
    out = attach(papers, [_e("Outstanding Papers", "award", "P", forum_id="zzz")])
    assert out.papers[0]["awards"][0]["label"] == "Outstanding Papers"


def test_test_of_time_is_conference_level_even_when_a_title_matches():
    papers = [{"title": "Generative Adversarial Nets"}]
    out = attach(papers, [_e("Test of Time Award", "test_of_time", "Generative Adversarial Nets",
                             url="https://x.test/gan")])
    assert "awards" not in out.papers[0]
    assert out.test_of_time == [{"label": "Test of Time Award", "title": "Generative Adversarial Nets",
                                 "url": "https://x.test/gan"}]


def test_test_of_time_without_url_has_no_url_key():
    out = attach([], [_e("Longuet-Higgins Prize", "test_of_time", "ResNet")])
    assert out.test_of_time == [{"label": "Longuet-Higgins Prize", "title": "ResNet"}]


def test_unmatched_entries_are_returned():
    out = attach([{"title": "P"}], [_e("Outstanding Position Paper", "award", "Position: Not Crawled")])
    assert "awards" not in out.papers[0]
    assert [e["title"] for e in out.unmatched] == ["Position: Not Crawled"]


def test_awards_on_one_paper_are_ordered_by_kind():
    out = attach([{"title": "P"}], [_e("Award Finalist", "candidate", "P"), _e("Best Paper", "award", "P")])
    assert [a["kind"] for a in out.papers[0]["awards"]] == ["award", "candidate"]


def test_input_papers_are_not_mutated():
    papers = [{"title": "P"}]
    attach(papers, [_e("Best Paper", "award", "P")])
    assert papers == [{"title": "P"}]


def test_no_entries_returns_papers_unchanged():
    papers = [{"title": "P"}, {"title": "Q"}]
    assert attach(papers, []).papers == papers


def test_load_entries(tmp_path):
    assert load_entries(tmp_path) == []
    (tmp_path / "awards.json").write_text(
        json.dumps({"conf_id": "x_2024", "awards": [_e("Best Paper", "award", "P")]}), encoding="utf-8")
    assert load_entries(tmp_path) == [_e("Best Paper", "award", "P")]


NAMES = {"neurips_2013": "NeurIPS 2013", "neurips_2014": "NeurIPS 2014", "neurips_2023": "NeurIPS 2023",
         "cvpr_2013": "CVPR 2013"}


def _tot(title, label="Test of Time Award", **kw):
    return {"label": label, "title": title, **kw}


class TestAttachTestOfTime:
    def test_the_prize_lands_on_the_earlier_paper_of_the_same_venue(self):
        papers = {"neurips_2013": [{"title": "Distributed Representations of Words"}, {"title": "Other"}],
                  "neurips_2023": [{"title": "New"}]}
        out = attach_test_of_time(papers, {"neurips_2023": [_tot("Distributed representations of words.",
                                                                 url="https://x.test/w2v")]}, NAMES)
        assert out.papers["neurips_2013"][0]["awards"] == [
            {"label": "Test of Time Award (NeurIPS 2023)", "kind": "test_of_time"}]
        assert "awards" not in out.papers["neurips_2013"][1]
        assert out.test_of_time["neurips_2023"] == [
            {"label": "Test of Time Award", "title": "Distributed representations of words.",
             "url": "https://x.test/w2v", "conference": "neurips_2013"}]
        assert (out.found, out.total, out.warnings) == (1, 1, [])

    def test_another_venue_or_a_later_year_is_never_searched(self):
        papers = {"cvpr_2013": [{"title": "Same Title"}], "neurips_2023": [{"title": "Same Title"}]}
        out = attach_test_of_time(papers, {"neurips_2023": [_tot("Same Title")]}, NAMES)
        assert all("awards" not in p for ps in out.papers.values() for p in ps)
        assert "conference" not in out.test_of_time["neurips_2023"][0]
        assert (out.found, out.total) == (0, 1)

    def test_a_title_in_two_earlier_years_is_attached_to_neither(self):
        papers = {"neurips_2013": [{"title": "Twice"}], "neurips_2014": [{"title": "Twice"}]}
        out = attach_test_of_time(papers, {"neurips_2023": [_tot("Twice")]}, NAMES)
        assert all("awards" not in p for ps in out.papers.values() for p in ps)
        assert out.warnings == ["neurips_2023: test of time 'Twice' is in neurips_2013, neurips_2014; attached to none"]

    def test_the_papers_own_awards_stay_and_the_list_is_resorted(self):
        papers = {"neurips_2013": [{"title": "P", "awards": [
            {"label": "Spotlight Candidate", "kind": "candidate"}, {"label": "Outstanding Paper", "kind": "award"}]}]}
        out = attach_test_of_time(papers, {"neurips_2023": [_tot("P")]}, NAMES)
        assert [a["kind"] for a in out.papers["neurips_2013"][0]["awards"]] == ["award", "test_of_time", "candidate"]

    def test_inputs_are_not_mutated(self):
        papers = {"neurips_2013": [{"title": "P"}]}
        tot = {"neurips_2023": [_tot("P")]}
        attach_test_of_time(papers, tot, NAMES)
        assert papers == {"neurips_2013": [{"title": "P"}]} and tot == {"neurips_2023": [_tot("P")]}

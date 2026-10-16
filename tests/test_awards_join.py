import json

from ppr.awards.join import attach, load_entries


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

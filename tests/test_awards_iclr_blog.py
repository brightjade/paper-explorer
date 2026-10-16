"""blog.iclr.cc posts as the WordPress REST API returns them, shaped like 2026-10-15's."""

from unittest.mock import MagicMock

import pytest

from ppr.awards import iclr_blog
from ppr.awards.iclr_blog import SEARCH_URL, parse_post


def _post(title, content, link="https://blog.iclr.cc/x/"):
    return {"id": 1, "link": link, "title": {"rendered": title}, "content": {"rendered": content}}


CONTENT_2025 = (
    '<h2><b>Selection Process</b></h2><p>The committee read '
    '<a href="https://openreview.net/group?id=ICLR.cc/2025/Conference">the papers</a>.</p>'
    '<h2><b>Outstanding Papers</b></h2><ul>'
    '<li><span><a href="https://openreview.net/forum?id=6Mxhg9PtDE">Safety Alignment Should be Made More '
    'Than Just a Few Tokens Deep.</a><br/></span><span>Xiangyu Qi, Ashwinee Panda.</span></li>'
    '<li><span><a href="https://openreview.net/forum?id=HvSytvg3Jh">AlphaEdit: Null-Space Constrained Model '
    'Editing for Language Models.</a></span></li></ul>'
    '<h2><b>Honorable Mentions</b></h2><ul><li><span>'
    '<a href="https://openreview.net/forum?id=HD6bWcj87Y">Data Shapley in One Training Run.</a></span></li></ul>'
)
CONTENT_2026 = (
    '<h3 class="wp-block-heading">Outstanding Papers</h3>'
    '<p class="wp-block-paragraph"><a href="https://openreview.net/forum?id=Yxz92UuPLQ">Transformers are '
    'Inherently Succinct</a>, by <a href="https://scholar.google.com/citations?user=E4vR0SIAAAAJ">Pascal '
    'Bergsträßer</a></p>'
    '<h3 class="wp-block-heading">Honorable Mention</h3>'
    '<p class="wp-block-paragraph"><a href="https://openreview.net/forum?id=yRtgZ1K8hO">The Polar Express</a></p>'
    '<h2 class="wp-block-heading">Selection Process</h2><p>Given the significant value...</p>'
)
URL_2025 = "https://blog.iclr.cc/2025/04/22/announcing-the-outstanding-paper-awards-at-iclr-2025/"
URL_2026 = "https://blog.iclr.cc/2026/04/23/announcing-the-iclr-2026-outstanding-papers/"
POSTS = [
    _post("Announcing the ICLR 2026 Outstanding Papers", CONTENT_2026, URL_2026),
    _post("Announcing the Outstanding Paper Awards at ICLR 2025", CONTENT_2025, URL_2025),
    _post("Announcing the ICLR 2025 Keynote Speakers", "<h2>Keynotes</h2><p>Talks.</p>"),
    _post("Authors of TMLR publications with Featured and Outstanding Certifications at ICLR 2024",
          '<h2>Featured</h2><p><a href="https://openreview.net/forum?id=zzz">A TMLR paper</a></p>'),
]


@pytest.fixture
def blog(monkeypatch):
    monkeypatch.setattr(iclr_blog, "_cache", {})
    get = MagicMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=POSTS)))
    monkeypatch.setattr(iclr_blog.fetch, "get", get)
    return get


class TestParsePost:
    def test_list_layout_with_trailing_periods(self):
        out = parse_post(CONTENT_2025, URL_2025)
        assert [(a.label, a.kind, a.title, a.forum_id) for a in out] == [
            ("Outstanding Papers", "award", "Safety Alignment Should be Made More Than Just a Few Tokens Deep",
             "6Mxhg9PtDE"),
            ("Outstanding Papers", "award", "AlphaEdit: Null-Space Constrained Model Editing for Language Models",
             "HvSytvg3Jh"),
            ("Honorable Mentions", "honorable", "Data Shapley in One Training Run", "HD6bWcj87Y"),
        ]
        assert {(a.via, a.source) for a in out} == {("iclr_blog", URL_2025)}

    def test_paragraph_layout_ignores_non_forum_links(self):
        out = parse_post(CONTENT_2026, URL_2026)
        assert [(a.label, a.title, a.forum_id) for a in out] == [
            ("Outstanding Papers", "Transformers are Inherently Succinct", "Yxz92UuPLQ"),
            ("Honorable Mention", "The Polar Express", "yRtgZ1K8hO"),
        ]

    def test_url_link_text_takes_the_title_from_the_strong_in_the_same_paragraph(self):
        content = (
            '<h3 class="wp-block-heading">Award Winners</h3>'
            '<p class="wp-block-paragraph"><strong>Generalization in diffusion models arises from '
            'geometry-adaptive harmonic representations</strong><br/>Zahra Kadkhodaie, Florentin Guth<br/>'
            '<a href="https://openreview.net/forum?id=ANvmVS2Yr0">https://openreview.net/forum?id=ANvmVS2Yr0</a>'
            '<br/><a href="https://iclr.cc/virtual/2024/oral/19783">https://iclr.cc/virtual/2024/oral/19783</a></p>'
        )
        out = parse_post(content, URL_2025)
        assert [(a.label, a.title, a.forum_id) for a in out] == [
            ("Award Winners", "Generalization in diffusion models arises from geometry-adaptive harmonic "
             "representations", "ANvmVS2Yr0")]

    def test_url_link_text_without_a_strong_keeps_the_link_text(self):
        content = ('<h3>Outstanding Papers</h3><p><a href="https://openreview.net/forum?id=abc">'
                   'https://openreview.net/forum?id=abc</a></p>')
        assert parse_post(content, URL_2025)[0].title == "https://openreview.net/forum?id=abc"


class TestSource:
    def test_picks_the_post_for_the_year(self, blog):
        assert len(iclr_blog.iclr_blog("iclr_2025", 2025, [])) == 3
        assert len(iclr_blog.iclr_blog("iclr_2026", 2026, [])) == 2

    def test_tmlr_certifications_post_is_not_an_awards_post(self, blog):
        assert iclr_blog.iclr_blog("iclr_2024", 2024, []) == []

    def test_one_request_serves_every_year(self, blog):
        for year in (2024, 2025, 2026):
            iclr_blog.iclr_blog(f"iclr_{year}", year, [])
        blog.assert_called_once_with(SEARCH_URL)

    def test_html_entities_in_titles_are_decoded(self, blog):
        POSTS.append(_post("Announcing the ICLR 2027 Outstanding Paper Awards &#8211; Part 1", CONTENT_2026))
        try:
            assert len(iclr_blog.iclr_blog("iclr_2027", 2027, [])) == 2
        finally:
            POSTS.pop()

    def test_a_non_list_answer_raises(self, monkeypatch):
        monkeypatch.setattr(iclr_blog, "_cache", {})
        monkeypatch.setattr(iclr_blog.fetch, "get", MagicMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"code": "rest_no_route"}))))
        with pytest.raises(ValueError):
            iclr_blog.iclr_blog("iclr_2025", 2025, [])

"""blog.iclr.cc posts as the WordPress REST API returns them, shaped like 2026-10-15's."""

from unittest.mock import MagicMock

import pytest

from ppr.awards import iclr_blog
from ppr.awards.iclr_blog import SEARCH_URL, TOT_SEARCH_URL, parse_post, parse_tot_post


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


TOT_2024 = (  # headings; title in <b>, the link alone in its paragraph
    '<p>For the inaugural ICLR Test of Time award, the Program Chairs examined papers from ICLR 2013 &amp; 2014.</p>'
    '<h2>Test of Time</h2><p><b>Auto-Encoding Variational Bayes</b></p><p>Diederik Kingma, Max Welling</p>'
    '<p><a href="https://arxiv.org/abs/1312.6114">https://arxiv.org/abs/1312.6114</a> </p>'
    '<p>A concurrent work by Rezende et al. (<a href="https://arxiv.org/abs/1401.4082">their paper</a>) also '
    'proposed it.</p>'
    '<h2>Runner Up</h2><p><b>Intriguing properties of neural networks</b></p><p>Christian Szegedy</p>'
    '<p><a href="https://arxiv.org/abs/1312.6199">https://arxiv.org/abs/1312.6199</a> </p>'
)
TOT_2025 = (  # headings; title on the first line of the link's own paragraph
    '<h2><b>Test of Time</b></h2><p><span>Adam: A Method for Stochastic Optimization<br /></span>'
    '<span>Diederik P. Kingma, Jimmy Ba<br /></span><a href="https://arxiv.org/abs/1412.6980">'
    '<span>https://arxiv.org/abs/1412.6980</span></a></p>'
    '<h2><b>Runner Up</b></h2><p><span>Neural Machine Translation by Jointly Learning to Align and Translate'
    '<br /></span><span>Dzmitry Bahdanau<br /></span><a href="https://arxiv.org/abs/1409.0473">'
    '<span>https://arxiv.org/abs/1409.0473</span></a></p>'
)
TOT_2026 = (  # no headings; the link text is the title
    '<p class="wp-block-paragraph">We are honored to announce the Test of Time awards for ICLR 2026.</p>'
    '<p class="wp-block-paragraph"><a href="https://arxiv.org/abs/1511.06434"><em>Unsupervised Representation '
    'Learning with Deep Convolutional Generative Adversarial Networks</em></a></p>'
    '<p class="wp-block-paragraph">Alec Radford, Luke Metz, Soumith Chintala</p>'
    '<p class="wp-block-paragraph"><a href="https://arxiv.org/pdf/1509.02971"><em>Continuous control with deep '
    'reinforcement learning</em></a></p>'
)


def _dated(title, content, date):
    return {**_post(title, content, f"https://blog.iclr.cc/{date[:4]}/tot/"), "date": date}


TOT_POSTS = [
    _dated("Announcing the Test of Time Awards from ICLR 2016", TOT_2026, "2026-04-22T18:42:23"),
    _dated("Announcing the Test of Time Award Winners from ICLR 2015", TOT_2025, "2025-04-14T14:04:07"),
    _dated("ICLR 2024 Test of Time Award", TOT_2024, "2024-05-07T09:51:15"),
    _dated("ICLR 2024 Outstanding Paper Awards", CONTENT_2026, "2024-05-06T00:00:00"),
]


class TestTestOfTime:
    def test_2024_titles_come_from_the_bold_line_and_runner_up_is_test_of_time(self):
        out = parse_tot_post(TOT_2024, "u")
        assert [(a.label, a.kind, a.title, a.url) for a in out] == [
            ("Test of Time Award", "test_of_time", "Auto-Encoding Variational Bayes", "https://arxiv.org/abs/1312.6114"),
            ("Test of Time Runner Up", "test_of_time", "Intriguing properties of neural networks",
             "https://arxiv.org/abs/1312.6199"),
        ]  # the Rezende link sits in running text and is not a prize
        assert {a.via for a in out} == {"iclr_tot"}

    def test_2025_titles_come_from_the_first_line_of_the_paragraph(self):
        assert [(a.label, a.title) for a in parse_tot_post(TOT_2025, "u")] == [
            ("Test of Time Award", "Adam: A Method for Stochastic Optimization"),
            ("Test of Time Runner Up", "Neural Machine Translation by Jointly Learning to Align and Translate"),
        ]

    def test_2026_titles_are_the_link_text(self):
        assert [(a.label, a.title) for a in parse_tot_post(TOT_2026, "u")] == [
            ("Test of Time Award",
             "Unsupervised Representation Learning with Deep Convolutional Generative Adversarial Networks"),
            ("Test of Time Award", "Continuous control with deep reinforcement learning"),
        ]

    def test_the_post_is_picked_by_its_date_year(self, monkeypatch):
        monkeypatch.setattr(iclr_blog, "_cache", {})
        get = MagicMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=TOT_POSTS)))
        monkeypatch.setattr(iclr_blog.fetch, "get", get)
        assert [a.title for a in iclr_blog.iclr_test_of_time("iclr_2025", 2025, [])][0].startswith("Adam")
        assert len(iclr_blog.iclr_test_of_time("iclr_2024", 2024, [])) == 2
        assert iclr_blog.iclr_test_of_time("iclr_2023", 2023, []) == []
        get.assert_called_once_with(TOT_SEARCH_URL)

    def test_a_test_of_time_post_with_no_paper_raises(self, monkeypatch):
        monkeypatch.setattr(iclr_blog, "_cache", {})
        posts = [_dated("ICLR 2027 Test of Time Award", "<p>Coming soon.</p>", "2027-04-01T00:00:00")]
        monkeypatch.setattr(iclr_blog.fetch, "get",
                            MagicMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=posts))))
        with pytest.raises(ValueError):
            iclr_blog.iclr_test_of_time("iclr_2027", 2027, [])

    def test_an_openreview_forum_link_is_a_paper_with_its_forum_id(self):
        out = parse_tot_post('<h2>Test of Time Award</h2>'
                             '<p><a href="https://openreview.net/forum?id=abc123"><em>Some 2017 Paper</em></a></p>', "u")
        assert [(a.title, a.forum_id, a.url) for a in out] == [
            ("Some 2017 Paper", "abc123", "https://openreview.net/forum?id=abc123")]

    def test_the_first_matching_post_that_names_a_paper_wins(self, monkeypatch):
        monkeypatch.setattr(iclr_blog, "_cache", {})
        posts = [_dated("Test of Time nominations", "<p>Nominate now.</p>", "2027-05-01T00:00:00"),
                 _dated("ICLR 2027 Test of Time Award", TOT_2026, "2027-04-01T00:00:00")]
        monkeypatch.setattr(iclr_blog.fetch, "get",
                            MagicMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=posts))))
        assert len(iclr_blog.iclr_test_of_time("iclr_2027", 2027, [])) == 2

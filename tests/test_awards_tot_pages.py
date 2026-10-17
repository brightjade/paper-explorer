"""Test-of-time pages, shaped like the live pages saved 2026-10-16/17."""

from unittest.mock import MagicMock

import pytest

from ppr.awards import ase_mip, icse_mip, issta_impact
from ppr.awards.collect import SOURCES_BY_PREFIX

ICSE_PAGE = (
    '<html><body><table>'
    '<tr><td align="middle" class="style3">2024</td><td class="style3">Laura Inozemtseva, Reid Holmes: '
    '<a href="https://dl.acm.org/doi/10.1145/2568225.2568271">Coverage is not strongly correlated with test '
    'suite effectiveness</a> ICSE-36, 2014</td></tr>'
    '<tr><td align="middle" class="style3">2010</td><td class="style3">A, B: '
    '<a href="https://x.test/1">Bandera: extracting finite-state models</a> , ICSE-22, 2000</td></tr>'
    '<tr><td align="middle" class="style3">2010</td><td class="style3">C, D: '
    '<a href="https://x.test/2">A case study of open source software development</a> , ICSE-22, 2000.</td></tr>'
    '<tr><td>Year</td><td>Paper</td></tr>'
    '<tr><td class="style3">2009</td><td class="style3">no link here</td></tr>'
    '</table></body></html>'
)

ASE_PAGE = (
    '<html><body><h3 id="ase-2025-mip">ASE 2025 MIP:</h3>'
    '<p><strong>ASE 2016</strong> - Deep learning code fragments for code clone detection - Martin White, '
    'Denys Poshyvanyk<br />DOI <a href="https://doi.org/10.1145/2970276.2970326">https://doi.org/10.1145/'
    '2970276.2970326</a></p>'
    '<p><strong>ASE 2015</strong> - Automated Test Input Generation for Android: Are We There Yet? - Shauvik '
    'Roy Choudhary, Alessandro Orso<br />DOI <a href="https://doi.org/10.1109/ASE.2015.89">https://doi.org/'
    '10.1109/ASE.2015.89</a></p>'
    '<h3 id="ase-2023-mip">ASE 2023 MIP:</h3>'
    '<p><strong>ASE 2010</strong> - Automatically Documenting Program Changes - Raymond P.L. Buse, Westley '
    'Weimer<br />DOI <a href="https://doi.org/10.1145/1858996.1859005">x</a></p>'
    '<h3>Fellows</h3><p>Not an award.</p>'
    '</body></html>'
)

ISSTA_PAGE = (
    '<html><body><h2 id="issta-impact-paper-awards"><a name="impact">ISSTA Impact Paper Awards</a></h2>'
    '<p>The ISSTA Impact Paper Award in year X ...</p><ul>'
    '<li>2024: René Just, Darioush Jalali, Michael Ernst. <a href="https://dl.acm.org/doi/10.1145/2610384.2628055">'
    'Defects4J: a database of existing faults to enable controlled testing studies for Java programs</a> '
    '(published in ISSTA 2014)</li>'
    '<li>2023: Ding Li, Shuai Hao. <a href="https://dl.acm.org/doi/10.1145/2483760.2483780">Calculating source '
    'line level energy information for Android applications</a> (published in ISSTA 2013)</li></ul>'
    '<h2 id="issta-retrospective-paper-awards"><a name="retrospective">ISSTA Retrospective Paper Awards</a></h2>'
    '<p>Retrospective paper awards were only given between 2018 and 2020.</p><ul>'
    '<li>2019: Stephen Fink, Eran Yahav. <a href="https://dl.acm.org/doi/10.1145/1146238.1146254">Effective '
    'typestate verification in the presence of aliasing</a> (published in ISSTA 2006)</li></ul>'
    '</body></html>'
)


class TestIcseMip:
    def test_rows_by_award_year_with_the_paper_link(self):
        out = icse_mip.parse_mip(ICSE_PAGE, icse_mip.MIP_URL)
        [a] = out["icse_2024"]
        assert (a.label, a.kind, a.title, a.via, a.url) == (
            "Most Influential Paper Award", "test_of_time",
            "Coverage is not strongly correlated with test suite effectiveness", "icse_mip",
            "https://dl.acm.org/doi/10.1145/2568225.2568271")
        assert len(out["icse_2010"]) == 2
        assert "icse_2009" not in out  # a row without a link is skipped

    def test_a_page_without_rows_raises(self):
        with pytest.raises(ValueError):
            icse_mip.parse_mip("<html><body><p>moved</p></body></html>", icse_mip.MIP_URL)


class TestAseMip:
    def test_title_sits_between_the_edition_and_the_authors(self):
        out = ase_mip.parse_mip(ASE_PAGE, ase_mip.MIP_URL)
        assert [(a.title, a.url) for a in out["ase_2025"]] == [
            ("Deep learning code fragments for code clone detection", "https://doi.org/10.1145/2970276.2970326"),
            ("Automated Test Input Generation for Android: Are We There Yet?", "https://doi.org/10.1109/ASE.2015.89"),
        ]
        assert [a.title for a in out["ase_2023"]] == ["Automatically Documenting Program Changes"]
        assert {a.kind for v in out.values() for a in v} == {"test_of_time"}

    def test_a_page_without_mip_headings_raises(self):
        with pytest.raises(ValueError):
            ase_mip.parse_mip("<html><body><h3>Fellows</h3></body></html>", ase_mip.MIP_URL)


class TestIsstaImpact:
    def test_impact_and_retrospective_awards_by_year(self):
        out = issta_impact.parse_issta(ISSTA_PAGE, issta_impact.ISSTA_URL)
        assert [(a.label, a.title) for a in out["issta_2024"]] == [
            ("Impact Paper Award",
             "Defects4J: a database of existing faults to enable controlled testing studies for Java programs")]
        assert [a.label for a in out["issta_2019"]] == ["Retrospective Paper Award"]
        assert out["issta_2023"][0].url == "https://dl.acm.org/doi/10.1145/2483760.2483780"

    def test_a_page_without_the_sections_raises(self):
        with pytest.raises(ValueError):
            issta_impact.parse_issta("<html><body></body></html>", issta_impact.ISSTA_URL)


@pytest.mark.parametrize("module,source,url,page,conf_id,count", [
    (icse_mip, icse_mip.icse_mip, icse_mip.MIP_URL, ICSE_PAGE, "icse_2024", 1),
    (ase_mip, ase_mip.ase_mip, ase_mip.MIP_URL, ASE_PAGE, "ase_2025", 2),
    (issta_impact, issta_impact.issta_impact, issta_impact.ISSTA_URL, ISSTA_PAGE, "issta_2024", 1),
])
def test_one_fetch_serves_every_year(monkeypatch, module, source, url, page, conf_id, count):
    monkeypatch.setattr(module, "_cache", {})
    get = MagicMock(return_value=MagicMock(status_code=200, text=page))
    monkeypatch.setattr(module.fetch, "get", get)
    assert len(source(conf_id, int(conf_id[-4:]), [])) == count
    assert source("x_1999", 1999, []) == []
    get.assert_called_once_with(url)


def test_se_venues_read_their_test_of_time_page_last():
    assert SOURCES_BY_PREFIX["icse"][-1][0] == "icse_mip"
    assert SOURCES_BY_PREFIX["ase"][-1][0] == "ase_mip"
    assert SOURCES_BY_PREFIX["issta"][-1][0] == "issta_impact"
    assert [n for n, _ in SOURCES_BY_PREFIX["fse"]] == ["manual", "researchr", "sigsoft"]

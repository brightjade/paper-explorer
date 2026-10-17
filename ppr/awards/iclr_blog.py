"""ICLR's outstanding-paper announcements on blog.iclr.cc.

ICLR stopped filling in its virtual-site awards page after 2024; the blog post
is where its winners are. One WordPress REST search returns every
"outstanding" post with its content, so a run makes one request (robots.txt:
Crawl-Delay 20) for every ICLR year. A post is a run of headings
("Outstanding Papers", "Honorable Mention(s)", "Selection Process") with
OpenReview forum links under the award ones. The forum id is the join key: a
blog title can differ from the OpenReview one (AlphaEdit, 2025).

A second search ("test of time", one more request per run) finds the
test-of-time posts (2024 on). Their markup changes every year, so a prize is
read from each arXiv link that stands as the paper's own line -- its text is a
URL, or it is its paragraph's whole text -- and its title is the link text, else
its paragraph's first line, else the bold line before it. The post belongs to
the conference of its publication year ("from ICLR 2015" is the 2025 award).
"""

import html as html_lib
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ppr.awards import fetch
from ppr.awards.labels import classify
from ppr.awards.model import Award

SEARCH_URL = "https://blog.iclr.cc/wp-json/wp/v2/posts?search=outstanding&per_page=50"
FORUM_PREFIX = "https://openreview.net/forum?id="

TOT_SEARCH_URL = "https://blog.iclr.cc/wp-json/wp/v2/posts?search=test%20of%20time&per_page=50"

_cache: dict[str, list[dict]] = {}


def _posts(url: str = SEARCH_URL) -> list[dict]:
    if url not in _cache:
        response = fetch.get(url)
        response.raise_for_status()
        posts = response.json()
        if not isinstance(posts, list):
            raise ValueError(f"{url}: expected a list of posts, got {type(posts).__name__}")
        _cache[url] = posts
    return _cache[url]


def parse_post(content: str, url: str) -> list[Award]:
    soup = BeautifulSoup(content, "html.parser")
    awards: list[Award] = []
    for heading in soup.find_all(["h2", "h3"]):
        links = []
        el = heading.find_next()
        while el is not None and el.name not in ("h2", "h3"):
            if el.name == "a" and el.get("href", "").startswith(FORUM_PREFIX):
                links.append(el)
            el = el.find_next()
        if not links:
            continue  # "Selection Process" and the like
        label = " ".join(heading.get_text(" ").split())
        kind = classify(label, "iclr")
        if kind is None:
            continue
        for a in links:
            forum_id = parse_qs(urlparse(a["href"]).query).get("id", [""])[0]
            title = " ".join(a.get_text(" ").split()).rstrip(".")
            if title.startswith("http"):  # 2024: the link text is the URL; the title is bold in the paragraph
                block = a.find_parent(["p", "li"])
                bold = block.find(["strong", "b"]) if block else None
                if bold and bold.get_text(strip=True):
                    title = " ".join(bold.get_text(" ").split()).rstrip(".")
            awards.append(Award(label=label, kind=kind, title=title, via="iclr_blog",
                                source=url, forum_id=forum_id))
    return awards


def iclr_blog(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    for post in _posts():
        title = html_lib.unescape(post["title"]["rendered"])
        if re.search(r"outstanding paper", title, re.I) and f"ICLR {year}" in title:
            return parse_post(post["content"]["rendered"], post["link"])
    return []


_ARXIV = re.compile(r"^https?://arxiv\.org/")


def _clean(text: str) -> str:
    return " ".join(text.split())


def _tot_label(heading) -> str:
    text = _clean(heading.get_text(" ")) if heading else ""
    if not text or re.fullmatch(r"test of time(?: award)?", text, re.I):
        return "Test of Time Award"
    return f"Test of Time {text}"


def _tot_title(a) -> str:
    text = _clean(a.get_text(" "))
    block = a.find_parent("p")
    block_text = _clean(block.get_text(" ")) if block else text
    if not text.startswith("http"):
        return text if block_text == text else ""  # a citation in running text is not a prize
    lines = [_clean(line) for line in block.get_text("\n").split("\n")] if block else []
    lines = [line for line in lines if line]
    if lines and not lines[0].startswith("http"):
        return lines[0]
    bold = a.find_previous(["b", "strong"])
    return _clean(bold.get_text(" ")) if bold else ""


def parse_tot_post(content: str, url: str) -> list[Award]:
    soup = BeautifulSoup(content, "html.parser")
    awards: list[Award] = []
    for a in soup.find_all("a", href=_ARXIV):
        title = _tot_title(a)
        if not title:
            continue
        label = _tot_label(a.find_previous(["h2", "h3"]))
        awards.append(Award(label=label, kind=classify(label, "iclr"), title=title.rstrip("."),
                            via="iclr_tot", source=url, url=a["href"]))
    return awards


def iclr_test_of_time(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    for post in _posts(TOT_SEARCH_URL):
        title = html_lib.unescape(post["title"]["rendered"])
        if re.search(r"test of time", title, re.I) and post.get("date", "").startswith(str(year)):
            awards = parse_tot_post(post["content"]["rendered"], post["link"])
            if not awards:
                raise ValueError(f"{post['link']}: a test-of-time post names no paper -- did the markup change?")
            return awards
    return []

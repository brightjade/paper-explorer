"""ICLR's outstanding-paper announcements on blog.iclr.cc.

ICLR stopped filling in its virtual-site awards page after 2024; the blog post
is where its winners are. One WordPress REST search returns every
"outstanding" post with its content, so a run makes one request (robots.txt:
Crawl-Delay 20) for every ICLR year. A post is a run of headings
("Outstanding Papers", "Honorable Mention(s)", "Selection Process") with
OpenReview forum links under the award ones. The forum id is the join key: a
blog title can differ from the OpenReview one (AlphaEdit, 2025).
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

_cache: dict[str, list[dict]] = {}


def _posts() -> list[dict]:
    if SEARCH_URL not in _cache:
        response = fetch.get(SEARCH_URL)
        response.raise_for_status()
        posts = response.json()
        if not isinstance(posts, list):
            raise ValueError(f"{SEARCH_URL}: expected a list of posts, got {type(posts).__name__}")
        _cache[SEARCH_URL] = posts
    return _cache[SEARCH_URL]


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
            awards.append(Award(label=label, kind=kind, title=title, via="iclr_blog",
                                source=url, forum_id=forum_id))
    return awards


def iclr_blog(conf_id: str, year: int, earlier: list[Award]) -> list[Award]:
    for post in _posts():
        title = html_lib.unescape(post["title"]["rendered"])
        if re.search(r"outstanding paper", title, re.I) and f"ICLR {year}" in title:
            return parse_post(post["content"]["rendered"], post["link"])
    return []

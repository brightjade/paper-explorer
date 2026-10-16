"""GETs for award pages: one minimum interval per host, the project's own UA.

Intervals are each host's robots.txt Crawl-delay where it sets one (checked
2026-10-15). The conference virtual sites set none and get 2s. conf.researchr.org
goes through the scraper's own `get`, so a crawl and an awards run in one
process share its clock.
"""

import time
from urllib.parse import urlparse

import requests

from ppr.net import PROJECT_USER_AGENT
from ppr.scrapers import researchr, usenix

TIMEOUT = 60
MIN_INTERVAL = {
    "www.thecvf.com": 10.0,
    "www.usenix.org": 10.0,
    "blog.iclr.cc": 20.0,
    "www2.sigsoft.org": 20.0,
}
DEFAULT_INTERVAL = 2.0

_last: dict[str, float] = {}


def get(url: str) -> requests.Response:
    host = urlparse(url).netloc
    if host == "conf.researchr.org":
        return researchr.get(url)
    # USENIX answers 403 to anything but a browser UA (see ppr/scrapers/usenix.py).
    headers = usenix.HEADERS if host == "www.usenix.org" else {"User-Agent": PROJECT_USER_AGENT}
    interval = MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    elapsed = time.monotonic() - _last.get(host, float("-inf"))
    if elapsed < interval:
        time.sleep(interval - elapsed)
    _last[host] = time.monotonic()
    return requests.get(url, headers=headers, timeout=TIMEOUT)

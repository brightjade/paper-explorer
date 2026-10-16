from unittest.mock import MagicMock

import pytest

from ppr.awards import fetch
from ppr.net import PROJECT_USER_AGENT
from ppr.scrapers import researchr, usenix


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    sleeps: list[float] = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(fetch.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(fetch.time, "sleep", sleep)
    monkeypatch.setattr(fetch, "_last", {})
    get = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(fetch.requests, "get", get)
    return now, sleeps, get


def test_first_request_to_a_host_does_not_wait(clock):
    _, sleeps, _ = clock
    fetch.get("https://www.thecvf.com/?page_id=413")
    assert sleeps == []


def test_second_request_waits_out_the_hosts_crawl_delay(clock):
    now, sleeps, _ = clock
    fetch.get("https://www.thecvf.com/?page_id=413")
    now[0] += 3
    fetch.get("https://www.thecvf.com/other")
    assert sleeps == [pytest.approx(7.0)]


def test_hosts_do_not_wait_for_each_other(clock):
    _, sleeps, _ = clock
    fetch.get("https://blog.iclr.cc/wp-json/wp/v2/posts?search=outstanding")
    fetch.get("https://neurips.cc/virtual/2024/awards_detail")
    assert sleeps == []


def test_hosts_without_a_crawl_delay_get_two_seconds(clock):
    _, sleeps, _ = clock
    fetch.get("https://neurips.cc/virtual/2024/awards_detail")
    fetch.get("https://neurips.cc/virtual/2025/awards_detail")
    assert sleeps == [pytest.approx(2.0)]


@pytest.mark.parametrize("host,interval", [
    ("www.thecvf.com", 10.0), ("www.usenix.org", 10.0),
    ("blog.iclr.cc", 20.0), ("www2.sigsoft.org", 20.0),
])
def test_crawl_delays_are_the_ones_robots_txt_asks_for(host, interval):
    assert fetch.MIN_INTERVAL[host] == interval


def test_project_user_agent_everywhere_but_usenix(clock):
    _, _, get = clock
    fetch.get("https://www.thecvf.com/?page_id=413")
    assert get.call_args.kwargs["headers"] == {"User-Agent": PROJECT_USER_AGENT}
    fetch.get("https://www.usenix.org/conference/usenixsecurity25/technical-sessions")
    assert get.call_args.kwargs["headers"] == usenix.HEADERS


def test_researchr_shares_the_scrapers_clock(clock, monkeypatch):
    _, _, get = clock
    shared = MagicMock(return_value="response")
    monkeypatch.setattr(researchr, "get", shared)
    assert fetch.get("https://conf.researchr.org/track/icse-2025/icse-2025-research-track") == "response"
    shared.assert_called_once_with("https://conf.researchr.org/track/icse-2025/icse-2025-research-track")
    get.assert_not_called()

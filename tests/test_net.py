"""Retry-After parsing shared by the clients."""

import pytest

from ppr.net import MAX_RETRY_AFTER, parse_retry_after


@pytest.mark.parametrize("value, expected", [
    ("30", 30.0),
    ("3600", MAX_RETRY_AFTER),
    ("-5", 0.0),
    (None, None),
    ("Wed, 21 Oct 2026 07:28:00 GMT", None),
])
def test_parse_retry_after(value, expected):
    assert parse_retry_after(value) == expected


def test_the_cap_is_two_minutes():
    assert MAX_RETRY_AFTER == 120.0

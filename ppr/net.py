"""What this project tells the hosts it reads from about itself."""

# Honest, and the same everywhere. A browser User-Agent buys nothing from a
# host that walls bots by proof of work (dblp.org's Anubis challenges every
# client alike), and an address to complain to is the courtesy the APIs ask
# for. No email address: this project does not send one to third parties.
PROJECT_USER_AGENT = "paper-explorer (+https://github.com/brightjade/paper-explorer)"

# A host's Retry-After is advice, not a contract: five large ones in a row
# would stall the 340-minute monthly job.
MAX_RETRY_AFTER = 120.0


def parse_retry_after(value: str | None) -> float | None:
    """Parse a `Retry-After` header's delay-seconds form, capped at `MAX_RETRY_AFTER`; `None` if absent or a
    HTTP-date (callers fall back to their own backoff)."""
    if value is None:
        return None
    try:
        return min(max(0.0, float(value)), MAX_RETRY_AFTER)
    except (TypeError, ValueError):
        return None

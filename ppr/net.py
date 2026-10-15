"""What this project tells the hosts it reads from about itself."""

# Honest, and the same everywhere. A browser User-Agent buys nothing from a
# host that walls bots by proof of work (dblp.org's Anubis challenges every
# client alike), and an address to complain to is the courtesy the APIs ask
# for. No email address: this project does not send one to third parties.
PROJECT_USER_AGENT = "paper-explorer (+https://github.com/brightjade/paper-explorer)"


def parse_retry_after(value: str | None) -> float | None:
    """Parse a `Retry-After` header's delay-seconds form; `None` if absent or a
    HTTP-date (callers fall back to their own backoff)."""
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None

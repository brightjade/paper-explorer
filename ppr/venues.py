"""The registry of conference venues discovery knows how to look for."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "configs" / "venues.yaml"

SOURCES = {"openreview", "dblp", "researchr", "crossref", "roboticsproceedings", "cvf", "usenix", "acl", "aaai", "bespoke"}
CADENCES = {"annual", "biennial-odd", "biennial-even"}

# Sources whose registration needs a human-written scraper. Discovery reports
# these as `needs-manual` rather than claiming a list is ready to register.
MANUAL_SOURCES = {"acl", "aaai", "bespoke"}

_REQUIRED = ("name", "source", "cadence", "announce_month", "probe")


@dataclass(frozen=True)
class Venue:
    prefix: str
    name: str
    source: str
    cadence: str
    probe: dict
    announce_month: int
    # Additional OpenReview venue IDs crawled into the same conference-year,
    # e.g. NeurIPS's Datasets & Benchmarks track. Autoregister includes one
    # only when the API returns papers for it -- a template, never a promise.
    extra_tracks: tuple[dict, ...] = ()
    # A journal whose accepted papers share one venueid and arrive all year
    # (TMLR). The conference-year is the paper's publication year, not the
    # venueid, so discovery counts only that year's notes.
    rolling: bool = False


def _parse_extra_tracks(prefix: str, entry: dict) -> tuple[dict, ...]:
    tracks = entry.get("extra_tracks") or []
    if tracks and entry["source"] != "openreview":
        raise ValueError(f"venue {prefix!r}: extra_tracks is only valid for openreview")
    parsed = []
    for track in tracks:
        if not isinstance(track.get("venue_id"), str):
            raise ValueError(f"venue {prefix!r}: extra_tracks entry needs a venue_id")
        if not re.fullmatch(r"[a-z]+", str(track.get("prefix", ""))):
            raise ValueError(
                f"venue {prefix!r}: extra_tracks prefix must be lowercase letters, "
                f"got {track.get('prefix')!r}"
            )
        parsed.append({"venue_id": track["venue_id"], "prefix": track["prefix"]})
    return tuple(parsed)


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Venue]:
    """Parse the venue registry, rejecting anything discovery could not act on.

    Validation is strict on purpose: a venue with an unrecognized source would
    otherwise be skipped silently, and a silently unprobed venue looks exactly
    like a venue with nothing new.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    venues = raw.get("venues") or {}
    registry: dict[str, Venue] = {}

    for prefix, entry in venues.items():
        for field_name in _REQUIRED:
            if field_name not in entry:
                raise ValueError(f"venue {prefix!r}: missing required field {field_name!r}")
        if entry["source"] not in SOURCES:
            raise ValueError(
                f"venue {prefix!r}: unknown source {entry['source']!r} "
                f"(expected one of {sorted(SOURCES)})"
            )
        if entry["cadence"] not in CADENCES:
            raise ValueError(
                f"venue {prefix!r}: unknown cadence {entry['cadence']!r} "
                f"(expected one of {sorted(CADENCES)})"
            )
        month = entry["announce_month"]
        if not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError(f"venue {prefix!r}: announce_month must be 1-12, got {month!r}")

        rolling = entry.get("rolling", False)
        if not isinstance(rolling, bool):
            raise ValueError(f"venue {prefix!r}: rolling must be true or false, got {rolling!r}")
        if rolling and entry["source"] != "openreview":
            raise ValueError(f"venue {prefix!r}: rolling is only valid for openreview")

        registry[prefix] = Venue(
            prefix=prefix,
            name=entry["name"],
            source=entry["source"],
            cadence=entry["cadence"],
            probe=entry["probe"],
            announce_month=month,
            extra_tracks=_parse_extra_tracks(prefix, entry),
            rolling=rolling,
        )

    return registry

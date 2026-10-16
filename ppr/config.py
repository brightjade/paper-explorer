from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CrawlConfig:
    name: str
    year: int
    venue_id: str  # e.g., "ICLR.cc/2025/Conference"
    selections: dict[str, str | list[str]]  # selection_name -> venue/decision string(s)
    conference_id: str  # e.g., "iclr_2025" (derived from filename)
    api_version: int = 2  # OpenReview API version (1 or 2)
    extra_venue_ids: list[str] = field(default_factory=list)  # additional venue IDs to query (e.g., D&B track)
    # v1 only: override the derived "<venue_id>/-/Blind_Submission" (ICLR 2017's is "/-/submission")
    submission_invitation: str | None = None
    # v1 only: read labels from decision notes instead of `venue`. Keys: `field`
    # plus `invitation` (decision notes of their own, ICLR 2018) or
    # `reply_suffix` (a direct reply on each submission, ICLR 2019-2020).
    decisions: dict | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CrawlConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            raw = yaml.safe_load(f)

        conference = raw.get("conference")
        if not conference:
            raise ValueError("Config must have a 'conference' section")

        name = conference.get("name")
        year = conference.get("year")
        venue_id = conference.get("venue_id")
        selections = conference.get("selections")

        if not name:
            raise ValueError("Config 'conference.name' is required")
        if not year:
            raise ValueError("Config 'conference.year' is required")
        if not venue_id:
            raise ValueError("Config 'conference.venue_id' is required")
        if not selections or not isinstance(selections, dict):
            raise ValueError(
                "Config 'conference.selections' must be a dict mapping "
                "selection names to venue strings"
            )

        conference_id = path.stem  # e.g., "iclr_2025"

        api_version = conference.get("api_version", 2)
        extra_venue_ids = conference.get("extra_venue_ids", [])

        for sel_name, value in selections.items():
            values = [value] if isinstance(value, str) else value
            if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
                raise ValueError(
                    f"Config selection {sel_name!r} must be a string or a non-empty list of strings"
                )

        submission_invitation = conference.get("submission_invitation")
        decisions = conference.get("decisions")
        if decisions is not None:
            if api_version != 1:
                raise ValueError("Config 'conference.decisions' needs api_version: 1")
            if (
                not isinstance(decisions, dict)
                or "field" not in decisions
                or ("invitation" in decisions) == ("reply_suffix" in decisions)
            ):
                raise ValueError(
                    "Config 'conference.decisions' needs 'field' and exactly one of "
                    "'invitation' or 'reply_suffix'"
                )
            if extra_venue_ids:
                raise ValueError(
                    "Config 'conference.decisions' cannot be combined with extra_venue_ids"
                )

        return cls(
            name=name,
            year=year,
            venue_id=venue_id,
            selections=selections,
            conference_id=conference_id,
            api_version=api_version,
            extra_venue_ids=extra_venue_ids,
            submission_invitation=submission_invitation,
            decisions=decisions,
        )

    def get_save_path(self) -> Path:
        return Path("data") / self.conference_id / "papers.jsonl"

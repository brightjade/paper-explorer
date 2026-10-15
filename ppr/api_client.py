import logging
import os
from collections import Counter

import openreview

from ppr.config import CrawlConfig
from ppr.models import Paper, write_papers

logger = logging.getLogger(__name__)


class EmptyCrawlError(Exception):
    """The API returned papers but none matched the configured selections."""


def _resolve_credentials(
    username: str | None = None,
    password: str | None = None,
) -> tuple[str | None, str | None]:
    resolved_username = username or os.environ.get("OPENREVIEW_USERNAME")
    resolved_password = password or os.environ.get("OPENREVIEW_PASSWORD")
    if not resolved_username or not resolved_password:
        logger.warning(
            "No OpenReview credentials provided. "
            "Set OPENREVIEW_USERNAME and OPENREVIEW_PASSWORD env vars "
            "or pass --username/--password. "
            "Sign up for free at https://openreview.net/signup"
        )
    return resolved_username, resolved_password


def create_openreview_client(
    username: str | None = None,
    password: str | None = None,
) -> openreview.api.OpenReviewClient:
    """Create and authenticate an OpenReview API v2 client."""
    u, p = _resolve_credentials(username, password)
    return openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=u,
        password=p,
    )


def create_openreview_v1_client(
    username: str | None = None,
    password: str | None = None,
) -> openreview.Client:
    """Create and authenticate an OpenReview API v1 client."""
    u, p = _resolve_credentials(username, password)
    return openreview.Client(
        baseurl="https://api.openreview.net",
        username=u,
        password=p,
    )


class OpenReviewAPIClient:
    def __init__(
        self,
        config: CrawlConfig,
        client: openreview.api.OpenReviewClient | openreview.Client,
    ):
        self.config = config
        self.client = client

    def fetch_papers(self) -> list[Paper]:
        """Fetch accepted papers, tagged with their configured selection type."""
        sel_map = self.config.selections
        is_v1 = self.config.api_version == 1

        if is_v1:
            invitation = f"{self.config.venue_id}/-/Blind_Submission"
        else:
            invitation = f"{self.config.venue_id}/-/Submission"

        logger.info(
            "Fetching accepted papers for %s %s (invitation=%s, api_v%d)",
            self.config.name, self.config.year, invitation, self.config.api_version,
        )

        try:
            if is_v1:
                notes = self.client.get_all_notes(invitation=invitation)
            else:
                notes = self.client.get_all_notes(
                    invitation=invitation,
                    content={"venueid": self.config.venue_id},
                )
                # Fetch papers from extra venue IDs (e.g., Datasets & Benchmarks track)
                for extra_vid in self.config.extra_venue_ids:
                    extra_inv = f"{extra_vid}/-/Submission"
                    logger.info("Fetching extra venue: %s", extra_vid)
                    extra_notes = self.client.get_all_notes(
                        invitation=extra_inv,
                        content={"venueid": extra_vid},
                    )
                    logger.info("  Found %d papers from %s", len(extra_notes), extra_vid)
                    notes.extend(extra_notes)
        except openreview.OpenReviewException as e:
            logger.error(
                "Failed to fetch papers: %s. "
                "Check that the venue ID is correct and credentials are valid.",
                e,
            )
            return []

        logger.info("Found %d accepted papers total", len(notes))

        # Reverse map: venue string -> selection name
        venue_to_selection = {v: k for k, v in sel_map.items()}

        papers = []
        for note in notes:
            if is_v1:
                venue_str = note.content.get("venue", "")
                content = note.content
            else:
                venue_str = note.content.get("venue", {}).get("value", "")
                content = {
                    k: v.get("value") for k, v in note.content.items()
                }

            selection = venue_to_selection.get(venue_str)
            if selection is None:
                continue

            paper = Paper(
                title=content.get("title", ""),
                link=f"https://openreview.net/pdf?id={note.forum}",
                authors=content.get("authors", []),
                selection=selection,
                keywords=content.get("keywords", []),
                abstract=content.get("abstract", ""),
                forum_id=note.forum,
            )
            papers.append(paper)

        if notes and not papers:
            seen = sorted({
                (note.content.get("venue", "") if is_v1
                 else note.content.get("venue", {}).get("value", ""))
                for note in notes
            })
            raise EmptyCrawlError(
                f"{self.config.venue_id}: {len(notes)} papers returned but none "
                f"matched the configured selections {sorted(sel_map.values())}. "
                f"Venue strings actually present: {seen}. "
                f"Fix the config's `selections` before crawling."
            )

        counts = Counter(p.selection for p in papers)
        for sel, count in counts.most_common():
            logger.info("  %s: %d papers", sel, count)

        return papers

    def save_papers(self, papers: list[Paper]) -> None:
        # `write_papers` owns the refusal to truncate a good crawl to zero --
        # `fetch_papers` returns `[]` on an OpenReviewException, which would
        # otherwise reach here and erase the file while logging "Saved 0".
        save_path = write_papers(papers, self.config.get_save_path())
        logger.info("Saved %d papers to %s", len(papers), save_path)

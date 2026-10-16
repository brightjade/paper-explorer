import logging
import os
from collections import Counter
from datetime import date, datetime, timezone

import openreview

from ppr.config import CrawlConfig
from ppr.matching import title_key
from ppr.models import Paper, write_papers

logger = logging.getLogger(__name__)


def note_pdate(note) -> date | None:
    """The UTC date a note was published (`pdate`, epoch milliseconds), if it has one."""
    pdate = getattr(note, "pdate", None)
    if not isinstance(pdate, int):
        return None
    return datetime.fromtimestamp(pdate / 1000, timezone.utc).date()


class EmptyCrawlError(Exception):
    """The API returned papers but none matched the configured selections."""


class DuplicateConflictError(Exception):
    """Two v1 notes describe the same paper but carry different labels."""


def collapse_duplicates(entries: list[tuple[Paper, int]]) -> tuple[list[Paper], int]:
    """Keep one paper per (title, authors): the note created first.

    NeurIPS 2021's v1 export lists 297 accepted papers twice, under two forums
    with identical labels. Two different papers that merely share a title keep
    their own entries, because their authors differ. A pair whose labels
    differ is not a duplicate we understand, so it raises rather than guessing.
    """
    kept: dict[tuple, tuple[Paper, int]] = {}
    for paper, created in entries:
        key = (title_key(paper.title), tuple(title_key(a) for a in paper.authors))
        prior = kept.get(key)
        if prior is None:
            kept[key] = (paper, created)
            continue
        if prior[0].selection != paper.selection:
            raise DuplicateConflictError(
                f"{paper.title!r} appears as {prior[0].selection} ({prior[0].forum_id}) "
                f"and {paper.selection} ({paper.forum_id})"
            )
        if created < prior[1]:
            kept[key] = (paper, created)
    papers = [p for p, _ in kept.values()]
    return papers, len(entries) - len(papers)


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

    def _selection_lookup(self) -> dict[str, str]:
        """Venue or decision string -> selection name; a selection may list several."""
        lookup: dict[str, str] = {}
        for name, values in self.config.selections.items():
            for value in [values] if isinstance(values, str) else values:
                lookup[value] = name
        return lookup

    def _fetch_v1(self) -> tuple[list, dict[str, str] | None]:
        """v1 submissions, plus forum -> decision when labels live in decision notes.

        The second value is None when each note's own `venue` is the label.
        """
        cfg = self.config
        invitation = cfg.submission_invitation or f"{cfg.venue_id}/-/Blind_Submission"
        decisions = cfg.decisions
        if decisions and decisions.get("reply_suffix"):
            # ICLR 2019-2020: a decision reply on each submission. The v1 API
            # refuses a non-prefix regex such as `Paper.*/-/Decision`, so the
            # replies come attached to the submissions instead.
            notes = self.client.get_all_notes(invitation=invitation, details="directReplies")
            by_forum: dict[str, str] = {}
            for note in notes:
                for reply in (note.details or {}).get("directReplies", []):
                    if reply.get("invitation", "").endswith(decisions["reply_suffix"]):
                        by_forum[note.forum] = reply.get("content", {}).get(decisions["field"], "")
                        break
            return notes, by_forum
        notes = list(self.client.get_all_notes(invitation=invitation))
        if decisions:
            # ICLR 2018: decisions are notes of their own, one per forum.
            decided = self.client.get_all_notes(invitation=decisions["invitation"])
            return notes, {d.forum: d.content.get(decisions["field"], "") for d in decided}
        for extra_vid in cfg.extra_venue_ids:
            logger.info("Fetching extra venue: %s", extra_vid)
            extra = self.client.get_all_notes(invitation=f"{extra_vid}/-/Submission")
            logger.info("  Found %d papers from %s", len(extra), extra_vid)
            notes.extend(extra)
        return notes, None

    def fetch_papers(self) -> list[Paper]:
        """Fetch accepted papers, tagged with their configured selection type."""
        is_v1 = self.config.api_version == 1
        logger.info(
            "Fetching accepted papers for %s %s (venue=%s, api_v%d)",
            self.config.name, self.config.year, self.config.venue_id, self.config.api_version,
        )

        decisions_by_forum: dict[str, str] | None = None
        try:
            if is_v1:
                notes, decisions_by_forum = self._fetch_v1()
            else:
                invitation = f"{self.config.venue_id}/-/Submission"
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

        if self.config.year_from_pdate and not is_v1:
            notes = [n for n in notes if (d := note_pdate(n)) is not None and d.year == self.config.year]

        logger.info("Found %d notes total", len(notes))
        lookup = self._selection_lookup()
        entries: list[tuple[Paper, int]] = []
        seen: set[str] = set()
        for note in notes:
            if is_v1:
                content = note.content
                label = (decisions_by_forum.get(note.forum, "")
                         if decisions_by_forum is not None else content.get("venue", ""))
            else:
                label = note.content.get("venue", {}).get("value", "")
                content = {k: v.get("value") for k, v in note.content.items()}
            seen.add(label)
            selection = lookup.get(label)
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
                venue_date=note_pdate(note).isoformat() if self.config.year_from_pdate and not is_v1 else "",
            )
            created = note.tcdate if isinstance(getattr(note, "tcdate", None), int) else 0
            entries.append((paper, created))

        if notes and not entries:
            raise EmptyCrawlError(
                f"{self.config.venue_id}: {len(notes)} papers returned but none "
                f"matched the configured selections {sorted(lookup)}. "
                f"Venue strings actually present: {sorted(seen)}. "
                f"Fix the config's `selections` before crawling."
            )

        if is_v1:
            papers, collapsed = collapse_duplicates(entries)
            if collapsed:
                logger.info("Collapsed %d duplicate notes", collapsed)
        else:
            papers = [p for p, _ in entries]

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

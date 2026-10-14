"""Write registration entries for sources whose setup is mechanical."""

import logging
import re
from pathlib import Path

from ppr.scrapers.cvf import CVF_BASE_URL, ECVA_BASE_URL

logger = logging.getLogger(__name__)


class RegistrationError(Exception):
    """The registration could not be written safely."""


def _group_end(text: str, dict_start: int, closing: int, conf_id: str) -> int:
    """Start of the line after the last entry sharing `conf_id`'s venue prefix.

    These dicts are grouped by venue under comment headers. Appending at the
    closing brace left every new entry in the wrong group, and moving it was a
    manual step a scheduled job cannot take. Falls back to the closing brace
    when the venue has no entries yet.
    """
    marker = f'"{conf_id.rpartition("_")[0]}_'
    body_start = text.index("\n", dict_start) + 1
    insert_at = closing
    pos = body_start
    while pos < closing:
        end = text.index("\n", pos)
        if text[pos:end].lstrip().startswith(marker):
            insert_at = end + 1
        pos = end + 1
    return insert_at


def _insert_into_dict(path: Path, dict_name: str, conf_id: str, line: str) -> None:
    """Insert `line` into `dict_name` in `path`, inside its venue's group.

    Editing the literal in place keeps the surrounding comments and grouping
    intact, which matters because these dicts are organised by venue family and
    a regenerated file would lose that.
    """
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(dict_name)}\s*=\s*\{{", text, re.MULTILINE)
    if not match:
        raise RegistrationError(f"{dict_name} not found in {path}")

    depth = 0
    for i in range(match.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                closing = i
                break
    else:
        raise RegistrationError(f"unbalanced braces in {dict_name} in {path}")

    # Scope the duplicate check to the dict's own span. A conference ID that
    # merely appears in a comment, a docstring, or a different dict elsewhere
    # in the file must not block a legitimate registration.
    if f'"{conf_id}"' in text[match.start():closing]:
        raise RegistrationError(f"{conf_id} is already registered in {dict_name}")

    at = _group_end(text, match.start(), closing, conf_id)
    path.write_text(text[:at] + f"    {line}\n" + text[at:], encoding="utf-8")
    logger.info("Registered %s in %s", conf_id, path.name)


# Hosts the CVF registry names through module constants rather than literals.
_URL_CONSTANTS = {CVF_BASE_URL: "CVF_BASE_URL", ECVA_BASE_URL: "ECVA_BASE_URL"}


def _url_literal(url: str) -> str:
    for base, constant in _URL_CONSTANTS.items():
        if url.startswith(base + "/"):
            return f'f"{{{constant}}}{url[len(base):]}"'
    return f'"{url}"'


def register_dblp(conf_id: str, toc_key: str, path: Path, number: str | None = None) -> None:
    entry = f'"{conf_id}": {{"key": "{toc_key}"'
    if number:
        # PACMSE volumes hold FSE and ISSTA together; the scraper filters on it.
        entry += f', "number": "{number}"'
    _insert_into_dict(path, "DBLP_CONFERENCES", conf_id, entry + "},")


def register_cvf(conf_id: str, url: str, parser: str, path: Path, year: int | None = None) -> None:
    entry = f'"{conf_id}": {{"url": {_url_literal(url)}, "parser": "{parser}"'
    if year is not None:
        entry += f', "year": {year}'
    _insert_into_dict(path, "CVF_CONFERENCES", conf_id, entry + "},")


def register_usenix(conf_id: str, slug: str, path: Path) -> None:
    _insert_into_dict(path, "USENIX_CONFERENCES", conf_id, f'"{conf_id}": "{slug}",')


# Words that appear in OpenReview venue strings and name a track.
_TRACK_WORDS = ("oral", "spotlight", "poster", "findings", "industry")


def openreview_selections(client, venue_id: str) -> dict[str, str]:
    """Read a conference's actual `venue` values and turn them into selections.

    Never generate these from a pattern. `configs/corl_2024.yaml` was written
    to match "CoRL 2024 Oral"/"CoRL 2024 Poster" by analogy with 2023 and 2025,
    but CoRL 2024 tags all 264 papers plain "CoRL 2024". The crawl matched
    nothing, wrote an empty file, and reported success.
    """
    notes = client.get_all_notes(content={"venueid": venue_id})
    if not notes:
        raise RegistrationError(f"{venue_id} returned no papers -- nothing to register")

    values = set()
    for note in notes:
        raw = note.content.get("venue", "")
        values.add(raw.get("value", "") if isinstance(raw, dict) else raw)
    values.discard("")

    if not values:
        # Notes came back, but every one had a missing or blank `venue` field.
        # Falling through to the multi-value branch here would return `{}`,
        # which is the exact corl_2024 failure mode: a config that "resolves"
        # to no selections, a crawl that matches nothing, and a zero-byte
        # papers file written with a "success" log line.
        raise RegistrationError(
            f"{venue_id} returned {len(notes)} papers but none carried a "
            "venue string -- nothing to register"
        )

    if len(values) == 1:
        return {"main": next(iter(values))}

    selections: dict[str, str] = {}
    for value in sorted(values):
        lowered = value.lower().replace(" ", "")
        name = next((w for w in _TRACK_WORDS if w in lowered), None)
        key = name or value.lower().replace(" ", "_")
        if key in selections:
            raise RegistrationError(
                f"venue strings {selections[key]!r} and {value!r} both map to "
                f"selection {key!r} -- name them manually"
            )
        selections[key] = value
    return selections


def render_openreview_config(
    name: str, year: int, venue_id: str, selections: dict[str, str]
) -> str:
    """Render a `configs/<id>.yaml` body.

    `api_version` is deliberately omitted. `ppr/config.py`'s
    `CrawlConfig.from_yaml` defaults it to 2, and that's what the majority of
    existing OpenReview configs (iclr_2025, icml_2025, neurips_2025,
    colm_2025, ...) rely on -- only the legacy v1 configs and
    corl_2024/corl_2025 state it explicitly. Matching the shape of the
    existing configs means leaving it out and trusting the default, not
    stating it on every freshly-registered file.
    """
    lines = [
        "conference:",
        f'  name: "{name}"',
        f"  year: {year}",
        f'  venue_id: "{venue_id}"',
        "  selections:",
    ]
    lines += [f'    {key}: "{value}"' for key, value in selections.items()]
    return "\n".join(lines) + "\n"

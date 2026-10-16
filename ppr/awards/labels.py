"""What kind of award a venue's label names.

Venues name one prize differently from year to year (NeurIPS's Datasets and
Benchmarks winners were "Outstanding Paper", then "Datasets and Benchmarks Best
Paper", then "Best Paper (DB track)"), and give one name to prizes of different
rank ("Outstanding Paper" is ICML's top prize). So the site never orders, styles
or groups by label: each label is mapped once, here, onto a fixed set of kinds,
and the label itself is only ever displayed.
"""

import re

KINDS = ("award", "honorable", "candidate", "artifact", "test_of_time")
KIND_ORDER = {kind: i for i, kind in enumerate(KINDS)}


class UnknownAwardLabel(ValueError):
    """A label no rule recognises: a new prize, or a page that changed meaning."""


# Badges and markers that sit beside awards on the same pages and are not awards.
_IGNORED = [re.compile(p, re.I) for p in (
    r"^artifacts?[- ](available|functional|reusable|evaluated)",
    r"^highlights?$",
    r"virtual attendance",
    r"recorded talk",
)]

# First match wins, so the order is the meaning: "Best Paper Runner-up" is a
# runner-up before it is a best paper, "Award Winner Best Artifact" an artifact
# prize before it is an award winner.
_DEFAULT_RULES = [(re.compile(p, re.I), kind) for p, kind in (
    (r"test of time|longuet-higgins|helmholtz|koenderink", "test_of_time"),
    (r"artifact", "artifact"),
    (r"candidate|finalist|nominee|nominated|shortlist", "candidate"),
    (r"honou?rable mention|runner[- ]?up", "honorable"),
    (r"best|outstanding|distinguished paper|marr prize|internet defense prize|^award winners?$", "award"),
)]

# Venue-specific rules, consulted before the defaults. Tranche 1 needs none;
# the ACL family (tranche 2) ranks "Outstanding" below "Best".
PREFIX_RULES: dict[str, list[tuple[re.Pattern, str]]] = {}


def classify(label: str, prefix: str = "") -> str | None:
    """The kind `label` names, or None for a known non-award.

    Raises `UnknownAwardLabel` for anything else, so a collector can hold the
    conference instead of guessing.
    """
    text = " ".join(label.split())
    if any(p.search(text) for p in _IGNORED):
        return None
    for pattern, kind in PREFIX_RULES.get(prefix, []) + _DEFAULT_RULES:
        if pattern.search(text):
            return kind
    raise UnknownAwardLabel(f"no award rule matches {label!r}")

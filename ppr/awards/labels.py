"""What kind of award a venue's label names.

Venues name one prize differently from year to year (NeurIPS's Datasets and
Benchmarks winners were "Outstanding Paper", then "Datasets and Benchmarks Best
Paper", then "Best Paper (DB track)"), and give one name to prizes of different
rank ("Outstanding Paper" is ICML's top prize). So the site never orders, styles
or groups by label: each label is mapped once, here, onto a fixed set of kinds,
and the label itself is only ever displayed.
"""

import re

# A row shows its paper's first kind in this order, so the order is the
# meaning: a test-of-time prize, given a decade later, outranks the honorable
# mention or candidacy the same paper may have had at its own conference.
KINDS = ("award", "test_of_time", "honorable", "candidate", "artifact")
KIND_ORDER = {kind: i for i, kind in enumerate(KINDS)}


class UnknownAwardLabel(ValueError):
    """A label no rule recognises: a new prize, or a page that changed meaning."""


# Badges and markers that sit beside awards on the same pages and are not awards.
_IGNORED = [re.compile(p, re.I) for p in (
    r"^artifacts?[- ](available|functional|reusable|evaluated)",
    r"^highlights?$",
    r"virtual attendance",
    r"recorded talk",
    # Demo prizes (NeurIPS 2015-19): demonstrations are not papers in the dataset.
    r"demonstration",
)]

# First match wins, so the order is the meaning: "Best Paper Runner-up" is a
# runner-up before it is a best paper, "Award Winner Best Artifact" an artifact
# prize before it is an award winner.
_DEFAULT_RULES = [(re.compile(p, re.I), kind) for p, kind in (
    (r"test of time|longuet-higgins|helmholtz|koenderink|classic paper|10 year paper"
     r"|most influential paper|impact paper|retrospective paper", "test_of_time"),
    (r"artifact", "artifact"),
    (r"candidate|finalist|nominee|nominated|nomination|shortlist", "candidate"),
    (r"honou?rable mention|runner[- ]?up", "honorable"),
    (r"best|outstanding|distinguished paper|marr prize|internet defense prize|^award winners?$"
     r"|datasets and benchmarks award", "award"),
)]

# Venue-specific rules, consulted before the defaults. ICML 2014 needs one;
# the ACL family (tranche 2) ranks "Outstanding" below "Best".
PREFIX_RULES: dict[str, list[tuple[re.Pattern, str | None]]] = {
    # ICML 2014 names its best application paper prize just "Application Paper".
    "icml": [(re.compile(r"^application paper$", re.I), "award")],
    # TMLR certifications; None is a known non-award.
    "tmlr": [(re.compile(p, re.I), kind) for p, kind in (
        (r"^outstanding certification$", "award"),
        (r"^featured certification$", "honorable"),
        (r"^(j2c|survey|expert|reproducibility) certification$", None),
    )],
}

# A venue whose every label is listed, where the defaults would guess at a new one.
PREFIX_ONLY = frozenset({"tmlr"})


def classify(label: str, prefix: str = "") -> str | None:
    """The kind `label` names, or None for a known non-award.

    Raises `UnknownAwardLabel` for anything else, so a collector can hold the
    conference instead of guessing.
    """
    text = " ".join(label.split())
    if any(p.search(text) for p in _IGNORED):
        return None
    defaults = [] if prefix in PREFIX_ONLY else _DEFAULT_RULES
    for pattern, kind in PREFIX_RULES.get(prefix, []) + defaults:
        if pattern.search(text):
            return kind
    raise UnknownAwardLabel(f"no award rule matches {label!r}")

"""Award labels -> kinds. Every label below was seen on a live page on 2026-10-15."""

import re

import pytest

from ppr.awards import labels
from ppr.awards.labels import KIND_ORDER, KINDS, UnknownAwardLabel, classify

OBSERVED = {
    # virtual sites (NeurIPS / ICML / ICLR / ECCV awards_detail)
    "Best Paper": "award",
    "Best Paper Runner-up": "honorable",
    "Datasets and Benchmarks Best Paper": "award",
    "Best Paper (DB track)": "award",
    "Outstanding Paper": "award",
    "Outstanding Paper Runner-up": "honorable",
    "Outstanding Paper Award": "award",
    "Outstanding Paper Honorable Mention": "honorable",
    "Outstanding Position Paper": "award",
    "Outstanding Position Paper Award": "award",
    "Outstanding Position Paper Honorable Mention": "honorable",
    "Honorable Mention": "honorable",
    "Best Paper Honorable Mention": "honorable",
    "Award Candidate": "candidate",
    "Test of Time Award": "test_of_time",
    "Test of Time Honorable Mention": "test_of_time",
    # ICLR blog headings
    "Outstanding Papers": "award",
    "Honorable Mentions": "honorable",
    # CVF registry sections
    "Best Student Paper": "award",
    "Best Student Paper Honorable Mention": "honorable",
    "Best Paper (Marr Prize)": "award",
    "Longuet-Higgins Prize": "test_of_time",
    "Helmholtz Prize": "test_of_time",
    "Koenderink Prize": "test_of_time",
    # WACV 2023 awards page
    "Best Paper – Honorable Mention": "honorable",
    "Best Paper - Algorithms": "award",
    "Best Paper - Applications": "award",
    "Award Finalist": "candidate",
    # researchr badges and SE awards pages
    "Distinguished Paper Award": "award",
    "ACM SIGSOFT Distinguished Paper Award": "award",
    "ACM SigSoft Distinguished Paper Award": "award",
    "ACM SIGSOFT Distinguished Paper": "award",
    "ACM Distinguished Paper": "award",
    "Distinguished Paper": "award",
    "Award Winner": "award",
    "Award Winner Best Artifact": "artifact",
    "Artifact Award Winner": "artifact",
    "ACM SIGSOFT Distinguished Artifact": "artifact",
    "Best Artifact Award": "artifact",
    # USENIX notes, after splitting a combined note on " and "
    "Distinguished Paper Award Winner": "award",
    "Distinguished Artifact Award Winner": "artifact",
    "Co-Winner of the 2023 Internet Defense Prize": "award",
    "Winner of the 2024 Internet Defense Prize": "award",
    "Runner-Up Winner of the 2023 Internet Defense Prize": "honorable",
    "Runner-Up": "honorable",
}


@pytest.mark.parametrize("label,kind", OBSERVED.items())
def test_every_observed_label_maps_to_its_kind(label, kind):
    assert classify(label) == kind


@pytest.mark.parametrize("label", [
    "Artifact-Available", "Artifact-Functional", "Artifact-Reusable",
    "Highlight", "Virtual Attendance", "Recorded talk",
])
def test_known_non_awards_are_none(label):
    assert classify(label) is None


@pytest.mark.parametrize("label", ["Security", "SE for AI", "Selection Process", ""])
def test_unknown_labels_raise(label):
    with pytest.raises(UnknownAwardLabel):
        classify(label)


def test_whitespace_and_case_do_not_matter():
    assert classify("  outstanding   PAPER\n") == "award"
    assert classify("HONORABLE MENTION") == "honorable"


def test_prefix_rules_come_before_the_defaults(monkeypatch):
    monkeypatch.setitem(labels.PREFIX_RULES, "acl", [(re.compile("outstanding", re.I), "honorable")])
    assert classify("Outstanding Paper", "acl") == "honorable"
    assert classify("Outstanding Paper", "icml") == "award"


def test_kind_order_follows_kinds():
    assert KINDS == ("award", "honorable", "candidate", "artifact", "test_of_time")
    assert [KIND_ORDER[k] for k in KINDS] == [0, 1, 2, 3, 4]

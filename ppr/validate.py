"""Cross-reference scraped paper counts against DBLP proceedings data."""

import logging
from dataclasses import dataclass
from pathlib import Path

from ppr import dblp_client
from ppr.dblp_client import DblpUnavailable
from ppr.scrapers.dblp import DBLP_CONFERENCES

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Conferences scraped directly from DBLP: derived from the scraper registry so
# autoregister, which edits only ppr/scrapers/dblp.py, cannot desync it.
# Validating these against DBLP would be circular — skip them.
DBLP_SOURCE_IDS: frozenset[str] = frozenset(DBLP_CONFERENCES)

# Maps conference ID -> list of DBLP toc keys to query.
# Multiple keys handle multi-volume proceedings (e.g., ACL long + short + findings).
# Only includes volumes matching the tracks our scraper covers.
DBLP_VALIDATION_KEYS: dict[str, list[str]] = {
    # --- OpenReview conferences ---
    "iclr_2023": ["db/conf/iclr/iclr2023.bht"],
    "iclr_2024": ["db/conf/iclr/iclr2024.bht"],
    "iclr_2025": ["db/conf/iclr/iclr2025.bht"],
    # iclr_2026: not yet indexed
    "icml_2023": ["db/conf/icml/icml2023.bht"],
    "icml_2024": ["db/conf/icml/icml2024.bht"],
    "icml_2025": ["db/conf/icml/icml2025.bht"],
    "neurips_2023": ["db/conf/nips/neurips2023.bht"],
    "neurips_2024": ["db/conf/nips/neurips2024.bht"],
    # neurips_2025: not yet indexed
    # colm_2024, colm_2025: not in DBLP
    "corl_2023": ["db/conf/corl/corl2023.bht"],
    "corl_2024": ["db/conf/corl/corl2024.bht"],
    # --- ACL conferences (multi-volume) ---
    "emnlp_2023": [
        "db/conf/emnlp/emnlp2023.bht",      # main
        "db/conf/emnlp/emnlp2023f.bht",      # findings
        "db/conf/emnlp/emnlp2023i.bht",      # industry
    ],
    "emnlp_2024": [
        "db/conf/emnlp/emnlp2024.bht",
        "db/conf/emnlp/emnlp2024f.bht",
        "db/conf/emnlp/emnlp2024i.bht",
    ],
    "emnlp_2025": [
        "db/conf/emnlp/emnlp2025.bht",
        "db/conf/emnlp/emnlp2025f.bht",
        "db/conf/emnlp/emnlp2025i.bht",
    ],
    "acl_2023": [
        "db/conf/acl/acl2023-1.bht",         # long
        "db/conf/acl/acl2023-2.bht",         # short
        "db/conf/acl/acl2023f.bht",          # findings
        "db/conf/acl/acl2023i.bht",          # industry
    ],
    "acl_2024": [
        "db/conf/acl/acl2024-1.bht",         # long
        "db/conf/acl/acl2024short.bht",      # short
        "db/conf/acl/acl2024f.bht",          # findings
    ],
    "acl_2025": [
        "db/conf/acl/acl2025-1.bht",         # long
        "db/conf/acl/acl2025-2.bht",         # short
        "db/conf/acl/acl2025f.bht",          # findings
        "db/conf/acl/acl2025-6.bht",         # industry
    ],
    "naacl_2024": [
        "db/conf/naacl/naacl2024.bht",       # long
        "db/conf/naacl/naacl2024-2.bht",     # short
        "db/conf/naacl/naacl2024f.bht",      # findings
        "db/conf/naacl/naacl2024-6.bht",     # industry
    ],
    "naacl_2025": [
        "db/conf/naacl/naacl2025-1.bht",     # long
        "db/conf/naacl/naacl2025-2.bht",     # short
        "db/conf/naacl/naacl2025f.bht",      # findings
        "db/conf/naacl/naacl2025-3.bht",     # industry
    ],
    "eacl_2023": [
        "db/conf/eacl/eacl2023.bht",         # main
        "db/conf/eacl/eacl2023f.bht",        # findings
    ],
    "eacl_2024": [
        "db/conf/eacl/eacl2024-1.bht",       # long
        "db/conf/eacl/eacl2024-2.bht",       # short
        "db/conf/eacl/eacl2024f.bht",        # findings
    ],
    "coling_2024": ["db/conf/coling/coling2024.bht"],
    "coling_2025": [
        "db/conf/coling/coling2025.bht",      # main
        "db/conf/coling/coling2025i.bht",     # industry
        "db/conf/coling/coling2025d.bht",     # demo
    ],
    # --- AAAI ---
    "aaai_2023": ["db/conf/aaai/aaai2023.bht"],
    "aaai_2024": ["db/conf/aaai/aaai2024.bht"],
    "aaai_2025": ["db/conf/aaai/aaai2025.bht"],
    "aaai_2026": ["db/conf/aaai/aaai2026.bht"],
    # --- USENIX Security ---
    "usenix_security_2023": ["db/conf/uss/uss2023.bht"],
    "usenix_security_2024": ["db/conf/uss/uss2024.bht"],
    "usenix_security_2025": ["db/conf/uss/uss2025.bht"],
    # --- CVF/ECVA ---
    "cvpr_2023": ["db/conf/cvpr/cvpr2023.bht"],
    "cvpr_2024": ["db/conf/cvpr/cvpr2024.bht"],
    "cvpr_2025": ["db/conf/cvpr/cvpr2025.bht"],
    "iccv_2023": ["db/conf/iccv/iccv2023.bht"],
    # iccv_2025: not yet indexed
    "wacv_2023": ["db/conf/wacv/wacv2023.bht"],
    "wacv_2024": ["db/conf/wacv/wacv2024.bht"],
    "wacv_2025": ["db/conf/wacv/wacv2025.bht"],
    # iccv_2025, wacv_2026: not yet indexed (pre-publication)
    # eccv_2024: 89 volumes, counted in one SPARQL query.
    "eccv_2024": [f"db/conf/eccv/eccv2024-{i}.bht" for i in range(1, 90)],
    # rss_2025: not yet indexed
}


def fetch_dblp_count(keys: list[str]) -> int:
    """Count non-Editorship papers across one or more DBLP toc keys.

    One SPARQL query however many keys there are. Pacing and retries belong to
    `ppr/dblp_client.py`, shared with discovery; `DblpUnavailable` propagates
    rather than being absorbed into a total.
    """
    return dblp_client.toc_count(keys)


@dataclass
class ValidationResult:
    conf_id: str
    # PASS, FAIL, SKIP, NO_DATA, ERROR. ERROR is "DBLP never answered", kept
    # apart from NO_DATA ("DBLP answered, with nothing") and from FAIL ("the
    # counts really disagree") -- conflating them is what made a throttled
    # sweep look like a bad crawl.
    status: str
    scraped: int = 0
    dblp: int = 0
    message: str = ""


def validate_conference(
    conf_id: str,
    tolerance: float = 0.1,
) -> ValidationResult:
    """Validate a conference's scraped paper count against DBLP.

    Args:
        conf_id: Conference identifier (e.g., 'iclr_2025').
        tolerance: Maximum allowed relative difference (default 10%).

    Returns:
        ValidationResult with status and counts.
    """
    if conf_id in DBLP_SOURCE_IDS:
        return ValidationResult(conf_id, "SKIP", message="DBLP-sourced conference")

    if conf_id not in DBLP_VALIDATION_KEYS:
        return ValidationResult(conf_id, "NO_DATA", message="No DBLP mapping")

    output_path = DATA_DIR / conf_id / "papers.jsonl"
    if not output_path.exists():
        return ValidationResult(conf_id, "NO_DATA", message="No output file")

    with open(output_path, encoding="utf-8") as f:
        scraped = sum(1 for line in f if line.strip())

    try:
        dblp_count = fetch_dblp_count(DBLP_VALIDATION_KEYS[conf_id])
    except DblpUnavailable as exc:
        # Never fall through to the comparison: a throttled query would come
        # back short and be announced as a count mismatch.
        return ValidationResult(
            conf_id, "ERROR", scraped=scraped,
            message=f"DBLP did not answer ({exc}); count not comparable",
        )

    if dblp_count == 0:
        return ValidationResult(
            conf_id, "NO_DATA", scraped=scraped, dblp=0,
            message="DBLP returned 0 (not yet indexed?)",
        )

    diff = abs(scraped - dblp_count) / dblp_count
    if diff <= tolerance:
        return ValidationResult(conf_id, "PASS", scraped=scraped, dblp=dblp_count)
    else:
        return ValidationResult(
            conf_id, "FAIL", scraped=scraped, dblp=dblp_count,
            message=f"Difference: {diff:.1%}",
        )

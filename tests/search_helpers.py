"""A two-venue dataset for the ppr.search tests."""

import json
from pathlib import Path

from ppr.layout import awards_path, papers_path

MU = "Machine Unlearning for Large Language Models"
CDR = "Certified Data Removal from Machine Learning Models"
FORGET = "Catastrophic Forgetting in Continual Learning"
ERASE = "Erasing Concepts from Diffusion Models"
VLM = "Vision-Language Models Are Zero-Shot Detectors"

ICLR = [
    {"title": MU, "authors": ["Ann Lee", "Bo Kim"],
     "abstract": "We study unlearning: removing what a trained model knows about chosen data.",
     "tldr": "An unlearning method for LLMs.", "keywords": ["unlearning", "privacy"],
     "selection": "oral", "citation_count": 120, "influential_citation_count": 10,
     "link": "https://openreview.net/forum?id=abc123XYZ9", "forum_id": "abc123XYZ9",
     "publication_date": "2024-01-15",
     "external_ids": {"ArXiv": "2401.00001", "DOI": "10.48550/arXiv.2401.00001", "CorpusId": 101}},
    {"title": CDR, "authors": ["Chris Park"],
     "abstract": "Data deletion with provable guarantees.", "selection": "poster",
     "citation_count": 700, "link": "https://doi.org/10.5555/CDR.1",
     "external_ids": {"DOI": "10.5555/CDR.1", "CorpusId": 102}},
    {"title": FORGET, "authors": ["Dana Cho"],
     "abstract": "Networks forget old tasks when trained on new ones.", "selection": "poster",
     "citation_count": 50, "external_ids": {"CorpusId": 103}},
]
CVPR = [
    {"title": ERASE, "authors": ["Eve Gandikota", "Fay Bau"],
     "abstract": "Concept erasure removes a visual concept from a text-to-image model.",
     "selection": "main", "citation_count": 600,
     "external_ids": {"ArXiv": "2303.07345v2", "CorpusId": 104}},
    {"title": VLM, "authors": ["Gus Han"], "abstract": "",
     "tldr": "GPT-4 style prompting finds objects.", "selection": "main", "citation_count": 30,
     "external_ids": {"CorpusId": 105}},
]
AWARDS = {"2024": [{"title": MU, "label": "Outstanding Paper", "kind": "award"}]}


def write_papers(data_dir: Path, conf_id: str, papers: list[dict]) -> Path:
    path = papers_path(data_dir, conf_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(p) + "\n" for p in papers), encoding="utf-8")
    return path


def make_dataset(root: Path) -> Path:
    data_dir = root / "data"
    write_papers(data_dir, "iclr_2024", ICLR)
    write_papers(data_dir, "cvpr_2023", CVPR)
    awards_path(data_dir, "iclr_2024").write_text(json.dumps(AWARDS), encoding="utf-8")
    return data_dir

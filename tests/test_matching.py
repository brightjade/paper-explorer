import pytest

from ppr.matching import MATCHED, MATCHED_FUZZY, REJECT, author_overlap, match_verdict, title_key


class TestTitleKey:
    @pytest.mark.parametrize(
        "ours,theirs",
        [
            # Curly quotes (neurips_2023)
            (
                "Calibrating “Cheap Signals” in Peer Review without a Prior",
                'Calibrating "Cheap Signals" in Peer Review without a Prior',
            ),
            # Inline LaTeX math (icml_2024)
            (
                "The Non-linear $F$-Design and Applications to Interactive Learning",
                "The Non-linear F-Design and Applications to Interactive Learning",
            ),
            # LaTeX command vs unicode Greek (icml_2023)
            (
                r"Fast $(1+\varepsilon)$-Approximation Algorithms for Binary Matrix Factorization",
                "Fast (1+ε)-Approximation Algorithms for Binary Matrix Factorization",
            ),
            # LaTeX Greek leading a title (corl_2023)
            (
                r"$\alpha$-MDF: An Attention-based Multimodal Differentiable Filter",
                "α-MDF: An Attention-based Multimodal Differentiable Filter",
            ),
            # Stray space before a colon (cvpr_2023)
            (
                "DARE-GRAM: Unsupervised Domain Adaptation Regression",
                "DARE-GRAM : Unsupervised Domain Adaptation Regression",
            ),
            # Trailing period (icml_2026)
            ("What Language is This? Ask Your Tokenizer.", "What Language is This? Ask Your Tokenizer"),
            # Trailing asterisk (iros_2024)
            ("Development of a Bilateral Control Teleoperation System",
             "Development of a Bilateral Control Teleoperation System *"),
            # Double vs single dash (iclr_2026)
            ("GenCtrl -- A Formal Controllability Toolkit",
             "GenCtrl - A Formal Controllability Toolkit"),
            # Case and whitespace, all that enrich's normalize_title handles
            ("  A   Paper\nTitle ", "a paper title"),
        ],
    )
    def test_cosmetic_differences_collapse(self, ours, theirs):
        assert title_key(ours) == title_key(theirs)

    def test_epsilon_spellings_agree(self):
        assert title_key(r"\varepsilon") == title_key(r"\epsilon") == title_key("ε")
        assert title_key("ϵ") == title_key("ε")

    def test_distinct_titles_stay_distinct(self):
        assert title_key("Beta Diffusion") != title_key(
            "Floorplan Generation with Graph Beta Diffusion"
        )

    def test_unknown_latex_command_is_dropped_not_inlined(self):
        # \mathcal must not leave the letters "mathcal" glued into the key,
        # or two titles differing only in markup stop comparing equal.
        assert title_key(r"A \mathcal{X} Study") == title_key("A X Study")

    def test_is_at_least_as_aggressive_as_normalize_title(self):
        # The safety property the refresh path depends on: anything the old
        # comparison called equal must still be equal, so re-verification can
        # never demote a paper already recorded as matched.
        from ppr.enrich import normalize_title

        pairs = [("A  Paper", "a paper"), ("X\tY", "x y")]
        for a, b in pairs:
            assert normalize_title(a) == normalize_title(b)
            assert title_key(a) == title_key(b)

    def test_empty_and_punctuation_only(self):
        assert title_key("") == ""
        assert title_key("!!! ---") == ""


def _entry(title, authors=("X Doe",)):
    return {"title": title, "authors": [{"name": n} for n in authors]}


class TestAuthorOverlap:
    def test_full_overlap(self):
        assert author_overlap(["Ada Lovelace"], ["Ada Lovelace"]) == 1.0

    def test_no_overlap(self):
        assert author_overlap(["Ada Lovelace"], ["Alan Turing"]) == 0.0

    def test_normalises_accents_and_case(self):
        assert author_overlap(["Émile Borel"], ["emile BOREL"]) == 1.0

    def test_divides_by_the_shorter_list(self):
        # A conference list truncated to its first author must still register
        # as overlapping a full S2 author list.
        assert author_overlap(["Ada Lovelace"], ["Alan Turing", "Ada Lovelace"]) == 1.0

    def test_missing_authors_on_either_side_is_none(self):
        assert author_overlap([], ["Ada Lovelace"]) is None
        assert author_overlap(["Ada Lovelace"], []) is None


class TestMatchVerdict:
    def test_exact_title_key_needs_no_authors(self):
        assert match_verdict("A Paper.", [], _entry("A Paper", authors=())) == MATCHED

    @pytest.mark.parametrize(
        "ours,theirs",
        [
            ("DPQuant: Efficient and Private Model Training via Dynamic Quantization Scheduling",
             "DPQuant: Efficient and Differentially-Private Model Training via Dynamic Quantization Scheduling"),
            ("Align Your Trajectory Tangent: Training Better Consistency Models via Manifold-Aligned Tangents",
             "Align Your Tangent: Training Better Consistency Models via Manifold-Aligned Tangents"),
            ("Strategic Reasoning over Golog Programs in the Nondeterministic Situation Calculus",
             "Strategic Reasoning over Golog Programs in the Nondeterministic Situation Calculus - Extended Abstract"),
            ("Meta-Sift: How to Sift Out a Clean Subset in the Presence of Data Poisoning?",
             "How to Sift Out a Clean Data Subset in the Presence of Data Poisoning?"),
            ("A Survey of LLM-based Agents in Medicine",
             "A Survey of LLM-based Agents in Medicine: How far are we from Baymax?"),
        ],
    )
    def test_same_paper_with_shared_authors_is_fuzzy(self, ours, theirs):
        assert match_verdict(ours, ["Ada Lovelace"], _entry(theirs, ["Ada Lovelace"])) == MATCHED_FUZZY

    def test_mangled_s2_title_with_identical_authors_is_fuzzy(self):
        # iclr_2026: S2 lost the leading token entirely. Authors carry it.
        assert match_verdict(
            "<SO$G_k$>: One LLM Token for Explicit Graph Structural Understanding",
            ["Ada Lovelace", "Alan Turing"],
            _entry(": One LLM Token for Explicit Graph Structural Understanding",
                   ["Ada Lovelace", "Alan Turing"]),
        ) == MATCHED_FUZZY

    @pytest.mark.parametrize(
        "ours,theirs,ours_authors,their_authors",
        [
            # Containment on title alone — only the authors separate these two.
            ("Beta Diffusion", "Floorplan Generation with Graph Beta Diffusion",
             ["Ada Lovelace"], ["Alan Turing"]),
            ("Recursive Monte-Carlo Tree Search",
             "Receding-horizon planning using recursive Monte Carlo Tree Search with Sparse Action Sampling",
             ["Ada Lovelace"], ["Alan Turing"]),
            ("Selective Explanations",
             "Selective Explanations: Leveraging Human Input to Align Explainable AI",
             ["Ada Lovelace"], ["Alan Turing"]),
            # Unrelated nearest neighbour from an unindexed venue.
            ("Bi-VLM: Binary Post-Training Quantization for Vision-Language Models",
             "Computing Neighbourhoods with Language Models in a Collaborative Filtering Scenario",
             ["Ada Lovelace"], ["Alan Turing"]),
            ("InterLight: Leveraging Intrinsic Illumination Priors for Low-Light Image Enhancement",
             "The Study of Context Effects in Medical Image Contrast Enhancement Assessment",
             ["Ada Lovelace"], ["Alan Turing"]),
            # Same research group, different paper — authors overlap, title does not.
            ("Performative Reinforcement Learning",
             "On Corruption-Robustness in Performative Reinforcement Learning",
             ["Ada Lovelace", "Alan Turing", "Grace Hopper"],
             ["Ada Lovelace", "Alan Turing", "Barbara Liskov"]),
            ("Robust Self-reflective Hashing for Cross-modal Retrieval with Noisy Label",
             "Robust Self-Paced Hashing for Cross-Modal Retrieval with Noisy Labels",
             ["Ada Lovelace", "Alan Turing", "Grace Hopper"],
             ["Ada Lovelace", "Alan Turing", "Barbara Liskov"]),
            ("Shapley-Based Data Valuation for Weighted $k$-Nearest Neighbors",
             "Shapley-Based Data Valuation with Mutual Information: A Key to Modified K-Nearest Neighbors",
             ["Ada Lovelace"], ["Alan Turing"]),
            ("Long-tailed Test-Time Adaptation for Vision-Language Models",
             "Flatness Guided Test-Time Adaptation for Vision-Language Models",
             ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Barbara Liskov"],
             ["Ada Lovelace", "Katherine Johnson", "Radia Perlman", "Anita Borg"]),
        ],
    )
    def test_measured_rejects(self, ours, theirs, ours_authors, their_authors):
        assert match_verdict(ours, ours_authors, _entry(theirs, their_authors)) == REJECT

    def test_no_authors_requires_near_identical_title(self):
        # naacl_2025 has no authors at all. sim ~0.99 is the only evidence
        # left. A case/punctuation-only variant would title_key-collapse to
        # an exact match before reaching the similarity check at all, so the
        # S2 side carries a genuine one-character typo ("Learnng").
        assert match_verdict(
            "Retrieval-Based Reconstruction for Time-series Contrastive Learning",
            [],
            _entry("Retrieval-Based Reconstruction for Time-series Contrastive Learnng!", authors=()),
        ) == MATCHED_FUZZY

    def test_no_authors_disables_containment(self):
        # Without authors, containment is exactly the trap: a short title sits
        # inside an unrelated longer one and there is nothing left to catch it.
        assert match_verdict("Beta Diffusion", [],
                             _entry("Floorplan Generation with Graph Beta Diffusion", authors=())) == REJECT

    def test_empty_s2_title_is_rejected_not_contained(self):
        # "" is a substring of everything; the containment rule must not fire.
        assert match_verdict("A Real Paper", ["Ada Lovelace"],
                             _entry("", ["Ada Lovelace"])) == REJECT


def test_enrichment_fields_request_authors():
    # match_verdict cannot corroborate anything without them.
    from ppr.s2_client import ENRICHMENT_FIELDS

    assert "authors" in ENRICHMENT_FIELDS.split(",")

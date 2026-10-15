"""N-gram extraction from paper titles and abstracts for topic trend analysis."""

import re
from collections import Counter

STOPWORDS = frozenset({
    # Standard English stopwords
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "just", "about", "above", "after", "again", "all", "also", "any",
    "because", "before", "below", "between", "both", "during", "each",
    "few", "further", "here", "how", "into", "its", "more", "most",
    "only", "other", "out", "over", "own", "same", "some", "such",
    "that", "their", "them", "there", "these", "they", "this", "those",
    "through", "under", "until", "up", "what", "when", "where", "which",
    "while", "who", "whom", "why", "you", "your", "it", "he", "she",
    "his", "her", "we", "our", "my", "me", "us", "him",
    # Academic noise words
    "paper", "propose", "proposed", "approach", "method", "methods",
    "show", "shows", "shown", "result", "results", "using", "based",
    "novel", "new", "study", "work", "first", "two", "one", "three",
    "use", "used", "well", "however", "thus", "yet", "still", "even",
    "many", "much", "often", "provide", "provides", "present", "presents",
    "introduce", "introduces", "demonstrate", "demonstrates", "achieve",
    "achieves", "existing", "previous", "recent", "state", "art",
    "performance", "experiments", "experimental", "evaluate", "evaluation",
    "compared", "significantly", "respectively", "without",
    "within", "across", "among", "several", "various", "different",
    "effectively", "efficiently", "large", "small", "high", "low",
    "best", "better", "good", "via", "per", "pre", "non",
    "et", "al", "fig", "figure", "table", "http", "https", "arxiv",
    "e.g", "i.e", "etc", "specifically", "particular", "addition",
    "moreover", "furthermore", "although", "whether", "given", "make",
    "like", "also", "include", "including", "upon", "toward", "towards",
    "allow", "allows", "enable", "enables", "consider", "considering",
    # URL fragments
    "github", "com", "www", "org", "http", "https", "arxiv", "doi",
    # Numbers-as-words
    "zero", "four", "five", "six", "seven", "eight", "nine", "ten",
    # Code/availability noise
    "available", "code", "supplementary", "appendix", "anonymous",
    "submitted", "under", "review", "accepted",
})

_WORD_RE = re.compile(r"[a-z][a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, filtering stopwords and short tokens."""
    tokens = _WORD_RE.findall(text.lower())
    return [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]


def extract_ngrams(tokens: list[str], ns: tuple[int, ...] = (2, 3)) -> list[str]:
    """Extract n-grams as space-joined strings from a token list."""
    ngrams = []
    for n in ns:
        for i in range(len(tokens) - n + 1):
            gram = tokens[i : i + n]
            ngrams.append(" ".join(gram))
    return ngrams


def build_ngram_data(
    all_papers: dict[str, list[dict]],
    parse_conference_id: callable,
) -> dict:
    """Build all topic trend data from paper titles and abstracts.

    Args:
        all_papers: {conference_id: [paper_dict, ...]}
        parse_conference_id: function(conf_id) -> (venue_name, year)

    Returns:
        Dict with keys: top_ngrams_by_year, rising_falling_by_year,
        ngram_trends, venue_ngram_matrix_by_year
    """
    # Count n-grams per year and per year+venue
    year_counts: dict[str, Counter] = {}
    year_venue_counts: dict[str, dict[str, Counter]] = {}

    for conf_id, papers in all_papers.items():
        venue, year = parse_conference_id(conf_id)
        year_str = str(year)

        if year_str not in year_counts:
            year_counts[year_str] = Counter()
        if year_str not in year_venue_counts:
            year_venue_counts[year_str] = {}
        if venue not in year_venue_counts[year_str]:
            year_venue_counts[year_str][venue] = Counter()

        for paper in papers:
            text = paper.get("title", "")
            abstract = paper.get("abstract", "")
            if abstract:
                text = text + " " + abstract
            tokens = tokenize(text)
            ngrams = extract_ngrams(tokens)
            year_counts[year_str].update(ngrams)
            year_venue_counts[year_str][venue].update(ngrams)

    years_sorted = sorted(year_counts.keys())

    # Top n-grams per year (top 150)
    top_ngrams_by_year = {}
    for year_str, counter in year_counts.items():
        top_ngrams_by_year[year_str] = [
            {"ngram": ngram, "count": count}
            for ngram, count in counter.most_common(150)
        ]

    # Rising & falling topics (compare consecutive years)
    min_frequency = 5
    rising_falling_by_year = {}
    for i in range(1, len(years_sorted)):
        prev_year = years_sorted[i - 1]
        curr_year = years_sorted[i]
        prev = year_counts[prev_year]
        curr = year_counts[curr_year]

        all_ngrams = set(prev.keys()) | set(curr.keys())
        deltas = []
        for ngram in all_ngrams:
            prev_count = prev.get(ngram, 0)
            curr_count = curr.get(ngram, 0)
            if prev_count < min_frequency and curr_count < min_frequency:
                continue
            delta = curr_count - prev_count
            pct_change = (delta / prev_count * 100) if prev_count > 0 else 100.0
            deltas.append({
                "ngram": ngram,
                "count": curr_count,
                "delta": delta,
                "pct_change": round(pct_change, 1),
            })

        deltas.sort(key=lambda x: x["delta"], reverse=True)
        rising_falling_by_year[curr_year] = {
            "rising": deltas[:10],
            "falling": list(reversed(deltas[-10:])),
        }

    # Global top 50 n-grams tracked across years
    global_counts = Counter()
    for counter in year_counts.values():
        global_counts.update(counter)
    top_50_global = [ngram for ngram, _ in global_counts.most_common(50)]

    ngram_trends = {}
    for ngram in top_50_global:
        ngram_trends[ngram] = {
            year_str: year_counts[year_str].get(ngram, 0) for year_str in years_sorted
        }

    # Venue x n-gram matrix per year (top 15 n-grams x venues)
    venue_ngram_matrix_by_year = {}
    for year_str in years_sorted:
        top_15 = [entry["ngram"] for entry in top_ngrams_by_year[year_str][:15]]
        matrix = {}
        for venue, counter in year_venue_counts[year_str].items():
            venue_data = {}
            for ngram in top_15:
                count = counter.get(ngram, 0)
                if count > 0:
                    venue_data[ngram] = count
            if venue_data:
                matrix[venue] = venue_data
        venue_ngram_matrix_by_year[year_str] = matrix

    return {
        "top_ngrams_by_year": top_ngrams_by_year,
        "rising_falling_by_year": rising_falling_by_year,
        "ngram_trends": ngram_trends,
        "venue_ngram_matrix_by_year": venue_ngram_matrix_by_year,
    }

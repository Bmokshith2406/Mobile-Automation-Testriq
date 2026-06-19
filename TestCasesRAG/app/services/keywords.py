import re
from typing import List


# -----------------------------------------------------
# Stopwords — BASELINE LIST
# -----------------------------------------------------
_STOPWORDS = set(
    """a about above after again against all am an and any are aren't as at be because been before being below between both but by
    can cannot could couldn't did didn't do does doesn't doing don't down during each few for from further had hadn't has hasn't have
    haven't having he he'd he'll he's her here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is
    isn't it it's its itself let's me more most mustn't my myself no nor not of off on once only or other ought our ours ourselves
    out over own same shan't she she'd she'll she's should shouldn't so some such than that that's the their theirs them themselves
    then there there's these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll
    we're we've were weren't what what's when when's where where's which while who who's whom why why's with won't would wouldn't you
    you'd you'll you're you've your yours yourself yourselves""".split()
)


# -----------------------------------------------------
# Keyword extraction — BASELINE ENGINE
# -----------------------------------------------------
def extract_keywords(text: str, max_keywords: int = 15) -> List[str]:

    try:
        if not text or not isinstance(text, str):
            return []

        text = text.lower()

    except Exception:
        # Safety valve — logic fallback identical (returns empty list)
        return []

    try:
        words = re.findall(r"\b[a-zA-Z0-9\-']+\b", text)
    except Exception:
        words = []

    try:
        words_filtered = [
            w
            for w in words
            if w not in _STOPWORDS and len(w) > 2
        ]
    except Exception:
        words_filtered = []

    try:
        from collections import Counter
        uni_counts = Counter(words_filtered)
    except Exception:
        uni_counts = {}

    # bigram extraction
    try:
        bigrams = [
            " ".join(pair)
            for pair in zip(words_filtered, words_filtered[1:])
        ]
    except Exception:
        bigrams = []

    try:
        from collections import Counter
        big_counts = Counter(bigrams)
    except Exception:
        big_counts = {}

    candidates: dict = {}

    # unigram scores
    try:
        for w, c in uni_counts.items():
            candidates[w] = candidates.get(w, 0) + c
    except Exception:
        pass

    # boosted bigram scores
    try:
        for b, c in big_counts.items():
            candidates[b] = candidates.get(b, 0) + c * 1.4
    except Exception:
        pass

    try:
        sorted_items = sorted(
            candidates.items(),
            key=lambda x: (-x[1], x[0]),
        )
    except Exception:
        sorted_items = []

    try:
        keywords = [k for k, _ in sorted_items][:max_keywords]
    except Exception:
        keywords = []

    # fallback if nothing extracted (fully preserved)
    try:
        if not keywords:
            keywords = [
                w for w in words
                if w not in _STOPWORDS
            ][:max_keywords]
    except Exception:
        keywords = []

    # ensure dedupe stability
    seen = set()
    final = []

    try:
        for k in keywords:
            if k not in seen:
                final.append(k)
                seen.add(k)
    except Exception:
        # As this step only de-dupes, failure simply returns what is collected
        return final

    return final


# -----------------------------------------------------
# Summary fallback — BASELINE ENGINE
# -----------------------------------------------------
def build_fallback_summary(
    description: str,
    steps: str,
    max_sentences: int = 2,
) -> str:

    try:
        import re as _re
    except Exception:
        # Regex import almost never fails,
        # but safety ensures pure fallback if it does.
        _re = None

    try:
        text = (description or "").strip()
    except Exception:
        text = ""

    try:
        if steps:
            text = f"{text}\n\n{steps}"
    except Exception:
        pass

    try:
        if _re:
            sentences = _re.split(
                r'(?<=[.!?])\s+',
                text.strip(),
            )
        else:
            sentences = text.split(".")
    except Exception:
        sentences = []

    try:
        sentences = [
            s.strip()
            for s in sentences
            if s.strip()
        ]
    except Exception:
        sentences = []

    try:
        if not sentences:
            return (
                text[:500] + "..." if text else
                "Summary not available."
            )
    except Exception:
        return "Summary not available."

    try:
        summary = " ".join(sentences[:max_sentences])
    except Exception:
        summary = ""

    try:
        if len(summary) < 40 and len(sentences) > max_sentences:
            summary = " ".join(sentences[: max_sentences + 1])
    except Exception:
        pass

    try:
        summary = summary[:800]
    except Exception:
        pass

    try:
        if len(summary) >= 800:
            summary += "..."
    except Exception:
        pass

    return summary

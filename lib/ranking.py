"""
Multi-source aggregation ranking layer.

Scores and ranks answers from multiple cheat sheet sources based on:
    1. Source credibility (base weight per adapter)
    2. Exact match (whether the topic was an exact lookup hit)
    3. Content length / quality signal
    4. Query shape → source affinity bonuses
    5. User preference (?prefer=, ?only= query parameters)

Exports:
    rank_answers(answers, topic, request_options)
"""

from config import CONFIG


# ── Default weights (overridable via CONFIG) ─────────────────────────

DEFAULT_CREDIBILITY = {
    "cheat.sheets": 80,
    "tldr": 75,
    "cheat": 65,
    "learnxiny": 55,
    "rosetta": 50,
    "question": 40,
    "late.nz": 30,
    "fosdem": 25,
    "translation": 20,
    "rfc": 60,
    "oeis": 50,
    "chmod": 40,
    "internal": 90,
    "unknown": 5,
}

# bonus[query_shape][source] → extra points
DEFAULT_QUERY_PREFERENCE = {
    "single_word": {"cheat.sheets": 15, "tldr": 12, "cheat": 8},
    "with_lang": {"tldr": 12, "cheat.sheets": 10, "learnxiny": 8, "rosetta": 5},
    "multi_word": {"question": 15, "learnxiny": 8},
    "deep_nested": {"rosetta": 10, "learnxiny": 8},
}


# ── Query shape classification ──────────────────────────────────────

def classify_query_shape(topic):
    """
    Classify the query into a shape category that determines
    which sources are naturally more relevant.

    Categories:
        single_word  – plain topic without slash (tar, curl)
        with_lang    – LANGUAGE/SUBTOPIC (python/lambda, go/slice)
        multi_word   – contains spaces or '+' (rare after normalization)
        deep_nested  – more than one slash (python/os/path+join)
    """
    if not topic:
        return "single_word"

    if " " in topic or "+" in topic:
        return "multi_word"

    if "/" not in topic:
        return "single_word"

    parts = topic.split("/")
    if len(parts) > 2:
        return "deep_nested"

    return "with_lang"


# ── Scoring factors ──────────────────────────────────────────────────

def _source_credibility(source):
    """Base credibility score for a source (0–100)."""
    weights = CONFIG.get("ranking.source_credibility", DEFAULT_CREDIBILITY)
    return weights.get(source, 30)


def _exact_match_bonus(source, topic, matched_sources):
    """
    Return bonus if the topic was an exact lookup hit for this source.

    `matched_sources` is the set of adapter names where is_found() returned
    True during routing.  A miss (adapter returned content anyway but wasn't
    in the exact-match set) is penalised.
    """
    if matched_sources is None:
        return 0, []
    if source in matched_sources:
        return 15, ["exact_hit +15"]
    return -10, ["no exact hit -10"]


def _content_length_score(answer_text):
    """
    Score based on answer content length.

    Empty  → 0
    Short  → 5  (< 100 chars)
    Medium → 12 (< 500 chars)
    Long   → 15 (>= 500 chars, capped)
    """
    if not answer_text:
        return 0, ["empty content +0"]
    length = len(answer_text)
    if length < 100:
        return 5, [f"short content ({length} chars) +5"]
    if length < 500:
        return 12, [f"medium content ({length} chars) +12"]
    return 15, [f"rich content ({length} chars) +15"]


def _query_shape_bonus(source, query_shape):
    """Affinity bonus: how well does this source match the query shape?"""
    bonuses = CONFIG.get(
        "ranking.query_preference_bonuses", DEFAULT_QUERY_PREFERENCE
    )
    shape_bonuses = bonuses.get(query_shape, {})
    bonus = shape_bonuses.get(source, 0)
    if bonus:
        return bonus, [f"{query_shape} bonus +{bonus}"]
    return 0, []


def _user_preference_bonus(source, prefer_sources):
    """Explicit user preference boost via ?prefer= parameter."""
    if not prefer_sources:
        return 0, []
    if source in prefer_sources:
        return 20, ["user preferred +20"]
    return 0, []


# ── Public API ───────────────────────────────────────────────────────

def rank_answers(answers, topic, request_options=None):
    """
    Score and sort answers by composite relevance.

    Each answer dict is augmented with a ``_ranking`` key::

        {
            "score": 107,
            "reason": "base:80 + exact:15 + len:12"
        }

    Args:
        answers:        list of answer dicts (mutated in place)
        topic:          the normalised query topic string
        request_options: dict that may contain:
            prefer  – list of adapter names to boost
            only    – list of adapter names to keep (others dropped)

    Returns:
        list[dict]: the same dicts, sorted best-first.
    """
    if not answers:
        return answers

    request_options = request_options or {}

    # Parse user preferences
    prefer_sources = request_options.get("prefer", [])
    if isinstance(prefer_sources, str):
        prefer_sources = [s.strip() for s in prefer_sources.split(",") if s.strip()]

    only_sources = request_options.get("only", [])
    if isinstance(only_sources, str):
        only_sources = [s.strip() for s in only_sources.split(",") if s.strip()]

    # Filter by ?only=
    if only_sources:
        answers = [a for a in answers if a.get("topic_type") in only_sources]

    if not answers:
        return answers

    # Classify the query shape once
    query_shape = classify_query_shape(topic)

    # Build matched_sources set: topic_types that routing confirmed via is_found()
    # (passed through request_options by routing.py when available)
    matched_sources = request_options.get("_matched_sources")

    scored = []
    for idx, answer in enumerate(answers):
        source = answer.get("topic_type", "unknown")
        answer_text = answer.get("answer", "")

        score = 0
        reasons = []

        # Factor 1: source credibility
        cred = _source_credibility(source)
        score += cred
        reasons.append(f"base:{cred}")

        # Factor 2: exact match
        em_bonus, em_parts = _exact_match_bonus(source, topic, matched_sources)
        score += em_bonus
        reasons.extend(em_parts)

        # Factor 3: content length
        cl_bonus, cl_parts = _content_length_score(answer_text)
        score += cl_bonus
        reasons.extend(cl_parts)

        # Factor 4: query shape affinity
        qs_bonus, qs_parts = _query_shape_bonus(source, query_shape)
        score += qs_bonus
        reasons.extend(qs_parts)

        # Factor 5: user preference
        up_bonus, up_parts = _user_preference_bonus(source, prefer_sources)
        score += up_bonus
        reasons.extend(up_parts)

        answer["_ranking"] = {
            "score": score,
            "reason": " | ".join(reasons),
        }

        scored.append((score, idx, answer))

    # Stable sort: highest score first; original order breaks ties
    scored.sort(key=lambda x: (-x[0], x[1]))

    return [item[2] for item in scored]

"""
Multi-source answer ranking engine.

Scores each answer_dict based on source credibility, exact match,
query shape, content length, and user preference, then sorts by
score descending.

Exports:
    rank_answers()
"""


_SOURCE_CREDIBILITY = {
    "cheat.sheets": 0.70,
    "tldr": 0.65,
    "cheat": 0.60,
    "learnxiny": 0.55,
    "rosetta": 0.50,
    "late.nz": 0.50,
    "rfc": 0.50,
    "oeis": 0.45,
    "chmod": 0.45,
    "fosdem": 0.40,
    "question": 0.35,
    "translation": 0.35,
    "internal": 0.30,
    "unknown": 0.10,
}

_DEFAULT_CREDIBILITY = 0.30

# These topic_types are scored but not reordered among themselves
_SKIP_RANKING = {"internal", "cheat.sheets dir"}

# These topic_types are always treated as non-exact matches
_FUZZY_TYPES = {"question", "unknown"}


def _classify_query(topic):
    """Classify the query shape: 'question', 'language_scoped', or 'bare_word'."""
    if "+" in topic or " " in topic:
        return "question"
    if "/" in topic:
        return "language_scoped"
    return "bare_word"


def _score_credibility(topic_type):
    """Return (score_delta, reason) for source credibility."""
    score = _SOURCE_CREDIBILITY.get(topic_type, _DEFAULT_CREDIBILITY)
    return score, "source: %s" % topic_type


def _score_exact_match(topic_type):
    """Return (score_delta, reason) for exact vs fuzzy match."""
    if topic_type in _FUZZY_TYPES:
        return 0.0, "fuzzy match"
    return 0.15, "exact match"


def _score_query_shape(topic, topic_type, answer_format, query_class):
    """Return (score_delta, reason) for query shape alignment."""
    if query_class == "question":
        if topic_type == "question":
            return 0.10, "Q&A query on Q&A source"
        return -0.05, "Q&A query on non-Q&A source"

    if query_class == "bare_word" and answer_format == "code":
        return 0.05, "command query"

    if query_class == "language_scoped" and answer_format == "code":
        return 0.05, "language-scoped query"

    return 0.0, None


def _score_content_length(answer_text):
    """Return (score_delta, reason) for content length sweet spot."""
    length = len(answer_text) if answer_text else 0

    if length == 0:
        return -0.15, "empty answer"
    if length <= 50:
        return -0.05, "very short answer"
    if length <= 200:
        return 0.0, None
    if length <= 2000:
        return 0.10, "good answer length"
    if length <= 5000:
        return 0.05, "detailed answer"
    return -0.05, "very long answer"


def _score_prefer_boost(topic_type, prefer_sources):
    """Return (score_delta, reason) for user preference boost."""
    if prefer_sources and topic_type in prefer_sources:
        return 0.15, "preferred source"
    return 0.0, None


def _compute_score(answer_dict, topic, prefer_sources):
    """
    Compute composite score for a single answer_dict.

    Returns:
        (score, reasons): float score clamped to [0, 1] and list of reason strings.
    """
    topic_type = answer_dict.get("topic_type", "unknown")
    answer_text = answer_dict.get("answer", "")
    answer_format = answer_dict.get("format", "code")
    query_class = _classify_query(topic)

    score = 0.0
    reasons = []

    # 1. Source credibility (base score)
    delta, reason = _score_credibility(topic_type)
    score += delta
    reasons.append(reason)

    # 2. Exact match bonus
    delta, reason = _score_exact_match(topic_type)
    score += delta
    if delta != 0:
        reasons.append(reason)

    # 3. Query shape alignment
    delta, reason = _score_query_shape(topic, topic_type, answer_format, query_class)
    score += delta
    if reason:
        reasons.append(reason)

    # 4. Content length sweet spot
    delta, reason = _score_content_length(answer_text)
    score += delta
    if reason:
        reasons.append(reason)

    # 5. Prefer boost
    delta, reason = _score_prefer_boost(topic_type, prefer_sources)
    score += delta
    if reason:
        reasons.append(reason)

    # Clamp to [0, 1]
    score = max(0.0, min(1.0, score))
    return score, reasons


def rank_answers(answers, topic, request_options=None):
    """
    Score, annotate, and sort a list of answer_dicts.

    Each answer_dict gets two new fields:
        _score (float):         0.0 to 1.0
        _score_reasons (list):  human-readable strings explaining the score

    Returns the list sorted by _score descending. Answers with topic_type
    in _SKIP_RANKING are scored but keep their original positions.
    The "LIMITED" sentinel is always kept at the end.
    """
    if not answers:
        return answers

    request_options = request_options or {}
    prefer_sources = set(request_options.get("prefer", []))

    # Separate sentinel entries
    limited = [a for a in answers if a.get("topic") == "LIMITED"]
    rest = [a for a in answers if a.get("topic") != "LIMITED"]

    # Score all non-sentinel answers
    for answer in rest:
        score, reasons = _compute_score(answer, topic, prefer_sources)
        answer["_score"] = round(score, 2)
        answer["_score_reasons"] = reasons

    # Partition into rankable and pinned (skip-ranking) answers
    rankable = [a for a in rest if a.get("topic_type") not in _SKIP_RANKING]
    pinned = [a for a in rest if a.get("topic_type") in _SKIP_RANKING]

    # Stable sort rankable answers by score descending
    rankable.sort(key=lambda a: a.get("_score", 0), reverse=True)

    # Reconstruct: pinned first (they come from routing.pre), then ranked, then limited
    return pinned + rankable + limited

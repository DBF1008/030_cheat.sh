"""
Scored, paginated search over the cheat sheet corpus.

Exports:

    find_answers_by_keyword()
    match()               – kept for backward compatibility (postprocessing)

Search flow
-----------
1. Every topic returned by ``get_topics_list()`` that belongs to the
   requested ``directory`` subtree is scored against the keyword(s).
2. Scoring considers three fields – topic name, adapter/source name,
   and answer body – with several weighting signals:
     * keyword presence in the topic path   (high weight)
     * keyword presence in the source name  (medium weight)
     * exact-phrase match bonus
     * case-sensitive match bonus
     * word-boundary match bonus
     * per-hit body score (capped so huge pages don't dominate)
3. Results are sorted by descending score (ties broken alphabetically
   by topic for stable pagination).
4. The requested page slice is taken and a short context *snippet* is
   extracted around the first body match.
5. Pagination metadata is attached to the result set.

Backward-compatible ``~keyword`` syntax
---------------------------------------
Multiple keywords joined with ``~`` keep their AND semantics.
Search option letters ``b`` (word boundaries), ``i`` (case insensitive)
and ``r`` (recursive) continue to work exactly as before.

Configuration parameters
------------------------
    search.limit      – hard cap on total results examined (legacy)
    search.page_size  – results per page (default 20)
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from config import CONFIG
from routing import get_answers, get_topics_list


# ---------------------------------------------------------------------------
# Option parsing (unchanged interface)
# ---------------------------------------------------------------------------

def _parse_options(options):
    """Parse search options string into option dict."""
    if options is None:
        return {}
    return {
        "insensitive": "i" in options,
        "word_boundaries": "b" in options,
        "recursive": "r" in options,
    }


# ---------------------------------------------------------------------------
# match() – public, backward-compatible boolean matcher
# ---------------------------------------------------------------------------

def match(paragraph, keyword, options=None, options_dict=None):
    """Return True if *all* ``~``-separated keywords appear in *paragraph*.

    Kept for backward compatibility with ``postprocessing._filter_by_keyword``.
    """
    if keyword is None:
        return True

    keywords = keyword.split("~") if "~" in keyword else [keyword]

    if options_dict is None:
        options_dict = _parse_options(options)

    flags = re.IGNORECASE if options_dict.get("insensitive") else 0
    use_wb = options_dict.get("word_boundaries", False)

    for kwrd in keywords:
        if not kwrd:
            continue
        pattern = re.escape(kwrd)
        if use_wb:
            pattern = r"\b%s\b" % pattern
        if not re.search(pattern, paragraph, flags):
            return False
    return True


# ---------------------------------------------------------------------------
# Internal scoring helpers
# ---------------------------------------------------------------------------

# Weight constants – tuned to push the most relevant sheets to the top
# without starving any single signal.
_W_TOPIC = 100        # keyword found in topic path
_W_TOPIC_EXACT = 50   # extra bonus if it's an exact segment match
_W_SOURCE = 50        # keyword found in adapter/source name
_W_BODY_HIT = 10      # each distinct paragraph hit in body
_W_BODY_CAP = 60      # cap total body contribution
_W_EXACT_PHRASE = 30  # exact (non-split) phrase found verbatim
_W_CASE_SENSITIVE = 15  # keyword matched with original case
_W_WORD_BOUNDARY = 10   # keyword matched on word boundaries


def _split_keywords(keyword: str) -> List[str]:
    """Split a ``~``-joined keyword string into individual terms."""
    return [k for k in keyword.split("~") if k]


def _build_pattern(kwrd: str, use_wb: bool, flags: int) -> re.Pattern:
    """Compile a regex for a single keyword token."""
    pat = re.escape(kwrd)
    if use_wb:
        pat = r"\b%s\b" % pat
    return re.compile(pat, flags)


def _score_topic_name(topic: str, keywords: List[str], flags: int) -> int:
    """Score how well *keywords* match the topic path."""
    score = 0
    topic_lower = topic.lower() if flags & re.IGNORECASE else topic
    for kw in keywords:
        kw_cmp = kw.lower() if flags & re.IGNORECASE else kw
        if kw_cmp in topic_lower:
            score += _W_TOPIC
            # exact path-segment match bonus
            segments = topic.split("/")
            if kw_cmp in [s.lower() if flags & re.IGNORECASE else s for s in segments]:
                score += _W_TOPIC_EXACT
    return score


def _score_source_name(source: str, keywords: List[str], flags: int) -> int:
    """Score how well *keywords* match the adapter/source name."""
    score = 0
    src = source.lower() if flags & re.IGNORECASE else source
    for kw in keywords:
        kw_cmp = kw.lower() if flags & re.IGNORECASE else kw
        if kw_cmp in src:
            score += _W_SOURCE
    return score


def _score_body(text: str, keywords: List[str], use_wb: bool, flags: int) -> Tuple[int, List[int]]:
    """Score keyword hits in the answer body.

    Returns ``(score, [line_numbers])`` where *line_numbers* are the
    0-based line indices of the first hit per keyword (used for snippet
    extraction).
    """
    if not text:
        return 0, []

    lines = text.splitlines()
    total = 0
    hit_lines: List[int] = []

    for kw in keywords:
        pattern = _build_pattern(kw, use_wb, flags)
        found_lines = []
        for idx, line in enumerate(lines):
            if pattern.search(line):
                found_lines.append(idx)
        if found_lines:
            # each paragraph-level hit (group of consecutive lines counts as 1)
            paragraph_hits = 1
            for i in range(1, len(found_lines)):
                if found_lines[i] - found_lines[i - 1] > 2:
                    paragraph_hits += 1
            body_score = min(paragraph_hits * _W_BODY_HIT, _W_BODY_CAP)
            total += body_score
            hit_lines.append(found_lines[0])

            # exact phrase bonus (the raw keyword string appears verbatim)
            if kw in text:
                total += _W_EXACT_PHRASE

            # case-sensitive bonus: matched without IGNORECASE
            if not (flags & re.IGNORECASE) and kw in text:
                total += _W_CASE_SENSITIVE

            # word-boundary bonus already requested → give credit
            if use_wb:
                total += _W_WORD_BOUNDARY

    return total, hit_lines


def _compute_score(
    topic: str,
    source: str,
    answer_text: str,
    keywords: List[str],
    use_wb: bool,
    flags: int,
) -> Tuple[int, List[int]]:
    """Compute the total relevance score for one answer.

    Returns ``(total_score, hit_lines)``.
    """
    score = _score_topic_name(topic, keywords, flags)
    score += _score_source_name(source, keywords, flags)
    body_score, hit_lines = _score_body(answer_text, keywords, use_wb, flags)
    score += body_score
    return score, hit_lines


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------

_SNIPPET_CONTEXT = 3  # lines of context before and after the hit


def _extract_snippet(text: str, hit_lines: List[int], keyword: str) -> str:
    """Return a short context window around the best hit.

    The snippet is at most ``2 * _SNIPPET_CONTEXT + 1`` lines, with
    the first matching line roughly in the middle.
    """
    if not hit_lines or not text:
        return ""

    lines = text.splitlines()
    centre = hit_lines[0]
    start = max(0, centre - _SNIPPET_CONTEXT)
    end = min(len(lines), centre + _SNIPPET_CONTEXT + 1)

    snippet_lines = lines[start:end]

    # prefix with "…" if we trimmed the beginning / end
    prefix = "... " if start > 0 else ""
    suffix = " ..." if end < len(lines) else ""

    snippet = prefix + "\n".join(snippet_lines) + suffix
    return snippet


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def _page_metadata(total: int, page: int, page_size: int) -> Dict[str, Any]:
    """Build a pagination metadata dict."""
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def _pagination_entry(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build a synthetic answer dict that shows pagination info."""
    page = meta["page"]
    total = meta["total"]
    total_pages = meta["total_pages"]
    page_size = meta["page_size"]
    start = (page - 1) * page_size + 1
    end = min(page * page_size, total)

    lines = [
        "Search results %d-%d of %d (page %d/%d)" % (
            start, end, total, page, total_pages
        ),
    ]
    if meta["has_prev"]:
        lines.append("  ← previous page: add ?p=%d to the URL" % (page - 1))
    if meta["has_next"]:
        lines.append("  → next page: add ?p=%d to the URL" % (page + 1))

    return {
        "topic_type": "search",
        "topic": "search/pagination",
        "answer": "\n".join(lines),
        "format": "text",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _limited_entry():
    """Legacy compatibility – no longer emitted but kept for callers."""
    return {
        "topic_type": "LIMITED",
        "topic": "LIMITED",
        "answer": "LIMITED TO %s ANSWERS" % CONFIG["search.limit"],
        "format": "code",
    }


def find_answers_by_keyword(
    directory: str,
    keyword: str,
    options: str = "",
    request_options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Search the cheat sheet tree for *keyword* and return scored, paginated results.

    Parameters
    ----------
    directory : str
        Topic prefix to restrict the search subtree (may be empty).
    keyword : str
        ``~``-separated keyword(s) to search for.
    options : str
        Legacy option letters: ``b`` (word boundaries), ``i`` (case
        insensitive), ``r`` (recursive into subdirectories).
    request_options : dict, optional
        Extra request options; ``p`` selects the result page (1-based).
    """
    options_dict = _parse_options(options)
    keywords = _split_keywords(keyword)
    if not keywords:
        return []

    flags = re.IGNORECASE if options_dict.get("insensitive") else 0
    use_wb = options_dict.get("word_boundaries", False)
    recursive = options_dict.get("recursive", False)

    page_size = int(CONFIG.get("search.page_size", 20))
    page = 1
    if request_options:
        try:
            page = max(1, int(request_options.get("p", 1)))
        except (ValueError, TypeError):
            page = 1

    # ---- collect & score all matching topics --------------------------------
    scored: List[Tuple[int, str, Dict[str, Any], List[int]]] = []

    for topic in get_topics_list(skip_internal=True, skip_dirs=True):
        if not topic.startswith(directory):
            continue

        subtopic = topic[len(directory):]
        if not recursive and "/" in subtopic:
            continue

        answer_dicts = get_answers(topic, request_options=request_options)
        for answer_dict in answer_dicts:
            answer_text = answer_dict.get("answer", "")
            if isinstance(answer_text, bytes):
                answer_text = answer_text.decode("utf-8")

            # quick boolean pre-filter: all keywords must appear somewhere
            if not match(answer_text, keyword, options_dict=options_dict):
                # also check if keyword matches topic name (topic-only match)
                topic_match = any(
                    re.search(
                        (r"\b%s\b" if use_wb else r"%s") % re.escape(kw),
                        topic,
                        flags,
                    )
                    for kw in keywords
                )
                if not topic_match:
                    continue

            source = answer_dict.get("topic_type", "")
            total_score, hit_lines = _compute_score(
                topic, source, answer_text, keywords, use_wb, flags
            )
            if total_score > 0:
                scored.append((total_score, topic, answer_dict, hit_lines))

    # ---- sort: descending score, then alphabetical topic for stability ------
    scored.sort(key=lambda item: (-item[0], item[1]))

    total = len(scored)
    meta = _page_metadata(total, page, page_size)

    # ---- slice the requested page ------------------------------------------
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_slice = scored[start_idx:end_idx]

    # ---- build result list -------------------------------------------------
    results: List[Dict[str, Any]] = []

    # prepend pagination header when there are multiple pages
    if total > page_size:
        results.append(_pagination_entry(meta))

    for _score, _topic, answer_dict, hit_lines in page_slice:
        enriched = dict(answer_dict)
        enriched["score"] = _score
        # attach snippet
        answer_text = answer_dict.get("answer", "")
        if isinstance(answer_text, bytes):
            answer_text = answer_text.decode("utf-8")
        snippet = _extract_snippet(answer_text, hit_lines, keyword)
        if snippet:
            enriched["snippet"] = snippet
        results.append(enriched)

    return results

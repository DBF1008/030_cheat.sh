"""
Search implementation with scoring, pagination, and snippet preview.

Exports:

    find_answers_by_keyword()
    match()

Search performs multi-field matching across topic name, answer content,
and source (topic_type), scoring each result by:
    * keyword weight (topic name > content > source)
    * exact phrase bonus
    * case-sensitive match bonus
    * word boundary match bonus

Results are sorted by score descending, paginated, and each result
includes a snippet preview of the matching context.

Configuration parameters:

    search.limit          (legacy, still honored as fallback)
    search.page_size
    search.snippet_lines
    search.max_results
"""

import re

from config import CONFIG
from routing import get_answers, get_topics_list


# ---------------------------------------------------------------------------
# Option parsing (backward-compatible, extended with page number)
# ---------------------------------------------------------------------------

def _parse_options(options):
    """Parse search options string into options_dict.

    Options are single characters: i=insensitive, b=word_boundaries, r=recursive.
    A trailing integer is interpreted as the page number (1-based).

    Examples:
        ""     -> page 1, no flags
        "i"    -> case insensitive, page 1
        "ri2"  -> recursive + insensitive, page 2
        "3"    -> page 3, no flags
    """
    if options is None:
        options = ""

    page = 1
    # extract trailing digits as page number
    m = re.search(r'(\d+)$', options)
    if m:
        page = max(1, int(m.group(1)))
        options = options[:m.start()]

    search_options = {
        "insensitive": "i" in options,
        "word_boundaries": "b" in options,
        "recursive": "r" in options,
        "page": page,
    }
    return search_options


# ---------------------------------------------------------------------------
# Keyword matching (backward-compatible public API)
# ---------------------------------------------------------------------------

def match(paragraph, keyword, options=None, options_dict=None):
    """Search for each keyword from `keywords` in `page`
    and if all of them are found, return `True`.
    Otherwise return `False`.

    Several keywords can be joined together using ~
    For example: ~ssh~passphrase
    """

    if keyword is None:
        return True

    if "~" in keyword:
        keywords = keyword.split("~")
    else:
        keywords = [keyword]

    if options_dict is None:
        options_dict = _parse_options(options)

    for kwrd in keywords:
        if not kwrd:
            continue

        regex = re.escape(kwrd)
        if options_dict.get("word_boundaries"):
            regex = r"\b%s\b" % kwrd

        if options_dict.get("insensitive"):
            if not re.search(regex, paragraph, re.IGNORECASE):
                return False
        else:
            if not re.search(regex, paragraph):
                return False
    return True


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_SCORE_TOPIC_EXACT = 30       # topic name is exactly the keyword
_SCORE_TOPIC_SEGMENT = 20     # keyword matches a full path segment of topic
_SCORE_TOPIC_PARTIAL = 10     # keyword appears anywhere in topic name
_SCORE_SOURCE_MATCH = 5       # keyword appears in topic_type (source)
_SCORE_PHRASE_MATCH = 8       # exact multi-word phrase found in content
_SCORE_CASE_HIT = 2           # each case-sensitive hit in content
_SCORE_ICASE_HIT = 1          # each case-insensitive hit in content
_SCORE_BOUNDARY_BONUS = 3     # word-boundary match bonus


def _split_keywords(keyword):
    """Split keyword on ~ into individual terms, filtering empty strings."""
    if "~" in keyword:
        return [k for k in keyword.split("~") if k]
    return [keyword] if keyword else []


def _score_answer(topic, topic_type, answer_text, keyword, options_dict):
    """Compute a relevance score for a single answer.

    Returns (score, matched) where matched is True if all keywords appear.
    """
    keywords = _split_keywords(keyword)
    if not keywords:
        return (0, False)

    total_score = 0
    all_matched = True

    for kwrd in keywords:
        kw_score = 0
        escaped = re.escape(kwrd)

        if options_dict.get("word_boundaries"):
            pattern = r"\b%s\b" % re.escape(kwrd)
        else:
            pattern = escaped

        flags = re.IGNORECASE if options_dict.get("insensitive") else 0

        # --- topic name scoring ---
        topic_lower = topic.lower()
        kw_lower = kwrd.lower()

        # exact match on final segment
        topic_tail = topic.rsplit("/", 1)[-1] if "/" in topic else topic
        if topic_tail.lower() == kw_lower:
            kw_score += _SCORE_TOPIC_EXACT
        elif kw_lower in topic_lower.split("/"):
            kw_score += _SCORE_TOPIC_SEGMENT
        elif kw_lower in topic_lower:
            kw_score += _SCORE_TOPIC_PARTIAL

        # --- source scoring ---
        if kw_lower in (topic_type or "").lower():
            kw_score += _SCORE_SOURCE_MATCH

        # --- content scoring ---
        # case-insensitive hit count
        icase_hits = len(re.findall(pattern, answer_text, re.IGNORECASE))
        if icase_hits == 0:
            all_matched = False
            continue

        kw_score += min(icase_hits, 20) * _SCORE_ICASE_HIT

        # bonus for case-sensitive hits
        if not options_dict.get("insensitive"):
            case_hits = len(re.findall(pattern, answer_text))
            kw_score += min(case_hits, 10) * _SCORE_CASE_HIT

        # bonus for word-boundary matches
        boundary_hits = len(re.findall(r"\b%s\b" % escaped, answer_text, re.IGNORECASE))
        if boundary_hits:
            kw_score += _SCORE_BOUNDARY_BONUS

        total_score += kw_score

    if not all_matched:
        return (0, False)

    # phrase bonus: if the original keyword (before ~ splitting) is a multi-word
    # string and appears as-is in the content, give extra score
    if len(keywords) > 1:
        phrase = " ".join(keywords)
        if re.search(re.escape(phrase), answer_text, re.IGNORECASE):
            total_score += _SCORE_PHRASE_MATCH

    return (total_score, True)


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------

def _extract_snippet(answer_text, keyword, options_dict, max_lines=None):
    """Extract a context snippet around the first keyword match.

    Returns a short text excerpt showing where the keyword appears.
    """
    if max_lines is None:
        max_lines = CONFIG.get("search.snippet_lines", 3)

    keywords = _split_keywords(keyword)
    if not keywords:
        return ""

    if isinstance(answer_text, bytes):
        answer_text = answer_text.decode("utf-8")

    lines = answer_text.splitlines()
    if not lines:
        return ""

    # find the first line that contains any keyword
    first_kw = keywords[0]
    escaped = re.escape(first_kw)
    flags = re.IGNORECASE if options_dict.get("insensitive") else 0

    match_line = 0
    for i, line in enumerate(lines):
        if re.search(escaped, line, flags):
            match_line = i
            break

    # extract context window
    start = max(0, match_line - max_lines)
    end = min(len(lines), match_line + max_lines + 1)
    snippet_lines = lines[start:end]

    snippet = "\n".join(snippet_lines)

    # truncate very long snippets
    if len(snippet) > 500:
        snippet = snippet[:497] + "..."

    return snippet


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def _pagination_entry(page, total_pages, total_results, directory, keyword, options_str):
    """Create a metadata entry with pagination information."""
    return {
        "topic_type": "PAGINATION",
        "topic": "PAGINATION",
        "answer": "--- page %d/%d (%d results) ---" % (page, total_pages, total_results),
        "format": "text",
        "pagination": {
            "current_page": page,
            "total_pages": total_pages,
            "total_results": total_results,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "directory": directory,
            "keyword": keyword,
            "options": options_str,
        },
    }


# backward-compatible sentinel
def _limited_entry():
    return {
        "topic_type": "LIMITED",
        "topic": "LIMITED",
        "answer": "LIMITED TO %s ANSWERS" % CONFIG["search.limit"],
        "format": "code",
    }


# ---------------------------------------------------------------------------
# Main search entry point
# ---------------------------------------------------------------------------

def find_answers_by_keyword(directory, keyword, options="", request_options=None):
    """
    Search the tree of cheatsheets (or subtree `directory`) for `keyword`.

    Returns a list of answer_dicts sorted by relevance score, paginated,
    and augmented with snippet previews.  A trailing PAGINATION entry
    carries page metadata.
    """

    options_dict = _parse_options(options)
    page = options_dict.get("page", 1)
    page_size = CONFIG.get("search.page_size", CONFIG.get("search.limit", 20))
    max_results = CONFIG.get("search.max_results", 200)

    scored_answers = []

    for topic in get_topics_list(skip_internal=True, skip_dirs=True):
        if not topic.startswith(directory):
            continue

        subtopic = topic[len(directory):]
        if not options_dict.get("recursive") and "/" in subtopic:
            continue

        answer_dicts = get_answers(topic, request_options=request_options)
        for answer_dict in answer_dicts:
            answer_text = answer_dict.get("answer", "")
            if isinstance(answer_text, bytes):
                answer_text = answer_text.decode("utf-8")

            score, matched = _score_answer(
                topic,
                answer_dict.get("topic_type", ""),
                answer_text,
                keyword,
                options_dict,
            )

            if not matched:
                continue

            snippet = _extract_snippet(answer_text, keyword, options_dict)
            answer_dict["search_score"] = score
            answer_dict["snippet"] = snippet
            scored_answers.append(answer_dict)

            if len(scored_answers) >= max_results:
                break

        if len(scored_answers) >= max_results:
            break

    # stable sort by score descending, then by topic name ascending
    scored_answers.sort(key=lambda a: (-a["search_score"], a.get("topic", "")))

    total_results = len(scored_answers)
    total_pages = max(1, (total_results + page_size - 1) // page_size)
    page = min(page, total_pages)

    start = (page - 1) * page_size
    end = start + page_size
    page_answers = scored_answers[start:end]

    # append pagination metadata entry
    page_answers.append(
        _pagination_entry(page, total_pages, total_results, directory, keyword, options)
    )

    return page_answers

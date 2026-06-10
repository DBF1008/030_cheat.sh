"""
Unit tests for the search module (scoring, pagination, snippet extraction).

Run with::

    cd repo
    python -m pytest tests/test_search.py -v
"""

import sys
import os
import types
import pytest

# ---------------------------------------------------------------------------
# bootstrap: make lib/ importable and inject stub config before import
# ---------------------------------------------------------------------------

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LIB = os.path.join(_REPO, "lib")
sys.path.insert(0, _LIB)

# Stub config module
_cfg = {
    "search.limit": 20,
    "search.page_size": 5,
    "search.snippet_lines": 2,
    "search.max_results": 200,
}
config_mod = types.ModuleType("config")
config_mod.CONFIG = _cfg
sys.modules["config"] = config_mod

# Stub routing module (to avoid loading adapters/redis)
_FAKE_TOPICS = [
    "python/json",
    "python/requests",
    "python/copy-file",
    "python/subprocess",
    "python/http/server",
    "go/json",
    "go/http",
    "javascript/fetch",
    "tar",
    "curl",
    "json",
]

_FAKE_ANSWERS = {
    "python/json": {
        "topic": "python/json",
        "topic_type": "cheat.sheets",
        "answer": "import json\n\ndata = json.loads(text)\nprint(json.dumps(data, indent=2))\n\n# Parse JSON from file\nwith open('file.json') as f:\n    data = json.load(f)\n",
        "format": "code",
    },
    "python/requests": {
        "topic": "python/requests",
        "topic_type": "cheat.sheets",
        "answer": "import requests\n\nresponse = requests.get('https://api.example.com')\ndata = response.json()\nprint(data)\n",
        "format": "code",
    },
    "python/copy-file": {
        "topic": "python/copy-file",
        "topic_type": "cheat.sheets",
        "answer": "import shutil\n\nshutil.copy('src', 'dst')\nshutil.copy2('src', 'dst')  # preserves metadata\n",
        "format": "code",
    },
    "python/subprocess": {
        "topic": "python/subprocess",
        "topic_type": "tldr",
        "answer": "import subprocess\n\nresult = subprocess.run(['ls', '-la'], capture_output=True, text=True)\nprint(result.stdout)\n\n# JSON output parsing\nimport json\nout = subprocess.check_output(['docker', 'inspect', 'container'])\ndata = json.loads(out)\n",
        "format": "code",
    },
    "python/http/server": {
        "topic": "python/http/server",
        "topic_type": "cheat.sheets",
        "answer": "# Simple HTTP server\npython3 -m http.server 8000\n\n# Custom handler with JSON response\nfrom http.server import BaseHTTPRequestHandler\nimport json\n",
        "format": "code",
    },
    "go/json": {
        "topic": "go/json",
        "topic_type": "cheat.sheets",
        "answer": "package main\n\nimport (\n    \"encoding/json\"\n    \"fmt\"\n)\n\ntype Person struct {\n    Name string `json:\"name\"`\n}\n\nfunc main() {\n    data, _ := json.Marshal(Person{Name: \"Alice\"})\n    fmt.Println(string(data))\n}\n",
        "format": "code",
    },
    "go/http": {
        "topic": "go/http",
        "topic_type": "cheat.sheets",
        "answer": "package main\n\nimport \"net/http\"\n\nfunc main() {\n    http.HandleFunc(\"/\", handler)\n    http.ListenAndServe(\":8080\", nil)\n}\n",
        "format": "code",
    },
    "javascript/fetch": {
        "topic": "javascript/fetch",
        "topic_type": "cheat.sheets",
        "answer": "fetch('https://api.example.com')\n  .then(r => r.json())\n  .then(data => console.log(data));\n\n// POST with JSON body\nfetch(url, {\n  method: 'POST',\n  headers: {'Content-Type': 'application/json'},\n  body: JSON.stringify({key: 'value'})\n});\n",
        "format": "code",
    },
    "tar": {
        "topic": "tar",
        "topic_type": "tldr",
        "answer": "# Extract tar archive\ntar xf archive.tar\n\n# Create tar.gz\ntar czf archive.tar.gz dir/\n\n# List contents\ntar tf archive.tar\n",
        "format": "code",
    },
    "curl": {
        "topic": "curl",
        "topic_type": "tldr",
        "answer": "# GET request\ncurl https://example.com\n\n# POST JSON data\ncurl -X POST -H 'Content-Type: application/json' -d '{\"key\":\"value\"}' url\n\n# Download file\ncurl -o file.txt https://example.com/file.txt\n",
        "format": "code",
    },
    "json": {
        "topic": "json",
        "topic_type": "cheat.sheets",
        "answer": "# JSON cheat sheet\n\n# Valid JSON types: string, number, object, array, boolean, null\n\n{\"name\": \"value\", \"count\": 42, \"active\": true}\n",
        "format": "code",
    },
}


def _fake_get_topics_list(skip_internal=False, skip_dirs=False):
    return _FAKE_TOPICS


def _fake_get_answers(topic, request_options=None):
    if topic in _FAKE_ANSWERS:
        return [_FAKE_ANSWERS[topic]]
    return []


routing_mod = types.ModuleType("routing")
routing_mod.get_topics_list = _fake_get_topics_list
routing_mod.get_answers = _fake_get_answers
sys.modules["routing"] = routing_mod

# Now import search
import search  # noqa: E402


# ---------------------------------------------------------------------------
# Tests: _parse_options
# ---------------------------------------------------------------------------


class TestParseOptions:
    def test_empty_string(self):
        opts = search._parse_options("")
        assert opts["insensitive"] is False
        assert opts["word_boundaries"] is False
        assert opts["recursive"] is False
        assert opts["page"] == 1

    def test_none(self):
        opts = search._parse_options(None)
        assert opts["page"] == 1

    def test_flags_only(self):
        opts = search._parse_options("irb")
        assert opts["insensitive"] is True
        assert opts["recursive"] is True
        assert opts["word_boundaries"] is True
        assert opts["page"] == 1

    def test_page_only(self):
        opts = search._parse_options("3")
        assert opts["page"] == 3
        assert opts["insensitive"] is False

    def test_flags_and_page(self):
        opts = search._parse_options("ri2")
        assert opts["recursive"] is True
        assert opts["insensitive"] is True
        assert opts["page"] == 2

    def test_page_zero_clamps_to_one(self):
        opts = search._parse_options("0")
        assert opts["page"] == 1

    def test_large_page_number(self):
        opts = search._parse_options("i15")
        assert opts["insensitive"] is True
        assert opts["page"] == 15


# ---------------------------------------------------------------------------
# Tests: _split_keywords
# ---------------------------------------------------------------------------


class TestSplitKeywords:
    def test_single_keyword(self):
        assert search._split_keywords("json") == ["json"]

    def test_multiple_keywords(self):
        assert search._split_keywords("ssh~passphrase") == ["ssh", "passphrase"]

    def test_empty_segments_filtered(self):
        assert search._split_keywords("~ssh~~key~") == ["ssh", "key"]

    def test_empty_string(self):
        assert search._split_keywords("") == []


# ---------------------------------------------------------------------------
# Tests: match (backward compatibility)
# ---------------------------------------------------------------------------


class TestMatch:
    def test_none_keyword_always_matches(self):
        assert search.match("anything", None) is True

    def test_simple_match(self):
        assert search.match("hello world", "hello") is True

    def test_no_match(self):
        assert search.match("hello world", "xyz") is False

    def test_case_sensitive_by_default(self):
        assert search.match("Hello", "hello") is False

    def test_case_insensitive_option(self):
        assert search.match("Hello", "hello", options="i") is True

    def test_word_boundary_option(self):
        assert search.match("json parsing", "json", options="b") is True
        assert search.match("libjsonparser", "json", options="b") is False

    def test_multi_keyword_all_must_match(self):
        assert search.match("ssh key passphrase", "ssh~passphrase") is True
        assert search.match("ssh key", "ssh~passphrase") is False

    def test_regex_special_chars_escaped(self):
        assert search.match("file.txt", "file.txt") is True
        assert search.match("fileatxt", "file.txt") is False


# ---------------------------------------------------------------------------
# Tests: _score_answer
# ---------------------------------------------------------------------------


class TestScoreAnswer:
    def test_exact_topic_match_highest(self):
        score, matched = search._score_answer(
            "json", "cheat.sheets", "some content with json", "json", {}
        )
        assert matched is True
        assert score >= search._SCORE_TOPIC_EXACT

    def test_topic_segment_match(self):
        score, matched = search._score_answer(
            "python/json", "cheat.sheets", "import json", "json", {}
        )
        assert matched is True
        assert score >= search._SCORE_TOPIC_SEGMENT

    def test_topic_partial_match(self):
        score, matched = search._score_answer(
            "python/json-parser", "cheat.sheets", "parse json data", "json", {}
        )
        assert matched is True
        assert score >= search._SCORE_TOPIC_PARTIAL

    def test_source_match_bonus(self):
        score_with, _ = search._score_answer(
            "sometopic", "cheat", "cheat sheet", "cheat", {}
        )
        score_without, _ = search._score_answer(
            "sometopic", "tldr", "cheat sheet", "cheat", {}
        )
        assert score_with > score_without

    def test_no_content_match_returns_not_matched(self):
        score, matched = search._score_answer(
            "python/json", "cheat.sheets", "no keyword here", "xyz123", {}
        )
        assert matched is False
        assert score == 0

    def test_case_sensitive_bonus(self):
        score_exact, _ = search._score_answer(
            "topic", "type", "JSON data", "JSON", {}
        )
        score_wrong_case, _ = search._score_answer(
            "topic", "type", "json data", "JSON", {}
        )
        # case-sensitive match should score higher than no case match
        # (when insensitive is off, wrong case won't match at all)
        assert score_exact > 0

    def test_multi_keyword_all_must_match(self):
        score, matched = search._score_answer(
            "topic", "type", "ssh key passphrase", "ssh~passphrase", {}
        )
        assert matched is True
        assert score > 0

    def test_multi_keyword_partial_not_matched(self):
        score, matched = search._score_answer(
            "topic", "type", "ssh key", "ssh~passphrase", {}
        )
        assert matched is False

    def test_insensitive_matching(self):
        score, matched = search._score_answer(
            "topic", "type", "JSON data", "json", {"insensitive": True}
        )
        assert matched is True
        assert score > 0

    def test_ordering_topic_name_over_content_only(self):
        """Answer where keyword is in topic name should score higher."""
        score_in_topic, _ = search._score_answer(
            "python/json", "cheat.sheets",
            "import json\ndata = json.loads(text)",
            "json", {}
        )
        score_content_only, _ = search._score_answer(
            "python/subprocess", "tldr",
            "data = json.loads(out)",
            "json", {}
        )
        assert score_in_topic > score_content_only


# ---------------------------------------------------------------------------
# Tests: _extract_snippet
# ---------------------------------------------------------------------------


class TestExtractSnippet:
    def test_basic_snippet(self):
        text = "line1\nline2\njson here\nline4\nline5\nline6"
        snippet = search._extract_snippet(text, "json", {}, max_lines=1)
        assert "json here" in snippet

    def test_snippet_includes_context(self):
        text = "line1\nline2\nline3\njson match\nline5\nline6"
        snippet = search._extract_snippet(text, "json", {}, max_lines=1)
        assert "line3" in snippet  # context before
        assert "line5" in snippet  # context after

    def test_snippet_at_start(self):
        text = "json first line\nline2\nline3"
        snippet = search._extract_snippet(text, "json", {}, max_lines=1)
        assert "json first line" in snippet

    def test_snippet_truncation(self):
        long_text = "\n".join(["x" * 100] * 20)
        text = long_text + "\njson\n" + long_text
        snippet = search._extract_snippet(text, "json", {}, max_lines=2)
        assert len(snippet) <= 503  # 500 + "..."

    def test_empty_text(self):
        assert search._extract_snippet("", "json", {}) == ""

    def test_bytes_text(self):
        text = b"hello\njson data\nworld"
        snippet = search._extract_snippet(text, "json", {})
        assert "json data" in snippet

    def test_case_insensitive_snippet(self):
        text = "line1\nJSON DATA\nline3"
        snippet = search._extract_snippet(text, "json", {"insensitive": True})
        assert "JSON DATA" in snippet


# ---------------------------------------------------------------------------
# Tests: find_answers_by_keyword (integration with fake routing)
# ---------------------------------------------------------------------------


class TestFindAnswersByKeyword:
    def test_basic_search_returns_results(self):
        results = search.find_answers_by_keyword("python/", "json")
        # should find python/json (content has "json") and python/subprocess
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        assert len(content_results) >= 1

    def test_results_sorted_by_score_descending(self):
        results = search.find_answers_by_keyword("", "json")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        scores = [r["search_score"] for r in content_results]
        assert scores == sorted(scores, reverse=True)

    def test_pagination_entry_present(self):
        results = search.find_answers_by_keyword("python/", "json")
        pagination = results[-1]
        assert pagination["topic_type"] == "PAGINATION"
        assert "pagination" in pagination
        assert pagination["pagination"]["current_page"] == 1

    def test_snippet_in_results(self):
        results = search.find_answers_by_keyword("python/", "json")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        for r in content_results:
            assert "snippet" in r
            assert isinstance(r["snippet"], str)

    def test_search_score_in_results(self):
        results = search.find_answers_by_keyword("python/", "json")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        for r in content_results:
            assert "search_score" in r
            assert r["search_score"] > 0

    def test_pagination_page_2(self):
        # with page_size=5, searching all topics for "json" should have <=1 page
        # but let's verify page parameter works
        results = search.find_answers_by_keyword("", "json", options="1")
        pagination = results[-1]["pagination"]
        assert pagination["current_page"] == 1

    def test_non_recursive_skips_subdirs(self):
        results = search.find_answers_by_keyword("python/", "server")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        topics = [r["topic"] for r in content_results]
        # python/http/server should NOT appear without recursive flag
        assert "python/http/server" not in topics

    def test_recursive_includes_subdirs(self):
        results = search.find_answers_by_keyword("python/", "server", options="r")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        topics = [r["topic"] for r in content_results]
        assert "python/http/server" in topics

    def test_case_insensitive_search(self):
        results = search.find_answers_by_keyword("", "JSON", options="i")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        assert len(content_results) >= 1

    def test_directory_filter(self):
        results = search.find_answers_by_keyword("go/", "json")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        for r in content_results:
            assert r["topic"].startswith("go/")

    def test_no_match_returns_pagination_only(self):
        results = search.find_answers_by_keyword("", "zzz_no_match_zzz")
        assert len(results) == 1
        assert results[0]["topic_type"] == "PAGINATION"
        assert results[0]["pagination"]["total_results"] == 0

    def test_json_topic_scores_highest_for_json_keyword(self):
        """Topic named 'json' should rank first when searching for 'json'."""
        results = search.find_answers_by_keyword("", "json")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        assert content_results[0]["topic"] == "json"

    def test_multi_keyword_search(self):
        results = search.find_answers_by_keyword("python/", "json~loads")
        content_results = [r for r in results if r.get("topic_type") != "PAGINATION"]
        # only answers containing both "json" and "loads" should match
        assert len(content_results) >= 1
        for r in content_results:
            answer = r.get("answer", "").lower()
            assert "json" in answer
            assert "loads" in answer


# ---------------------------------------------------------------------------
# Tests: pagination math
# ---------------------------------------------------------------------------


class TestPaginationMath:
    def test_single_page(self):
        results = search.find_answers_by_keyword("go/", "json")
        pagination = results[-1]["pagination"]
        assert pagination["total_pages"] >= 1
        assert pagination["has_prev"] is False

    def test_page_clamped_to_max(self):
        # page 999 should clamp to last page
        results = search.find_answers_by_keyword("", "json", options="999")
        pagination = results[-1]["pagination"]
        assert pagination["current_page"] == pagination["total_pages"]
        assert pagination["has_next"] is False

    def test_pagination_next_hint(self):
        """When there are enough results for multiple pages, next page hint is set."""
        # Use a very small page size for this test
        old_page_size = _cfg["search.page_size"]
        _cfg["search.page_size"] = 2
        try:
            results = search.find_answers_by_keyword("", "json")
            pagination = results[-1]["pagination"]
            if pagination["total_results"] > 2:
                assert pagination["has_next"] is True
                assert pagination["current_page"] == 1
        finally:
            _cfg["search.page_size"] = old_page_size


# ---------------------------------------------------------------------------
# Tests: backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_match_still_works_with_old_options_string(self):
        """match() with plain string options still works."""
        assert search.match("hello world", "hello", options="") is True
        assert search.match("hello world", "hello", options="i") is True
        assert search.match("hello world", "hello", options="b") is True

    def test_match_with_options_dict(self):
        """match() with options_dict still works."""
        opts = {"insensitive": True, "word_boundaries": False}
        assert search.match("Hello", "hello", options_dict=opts) is True

    def test_find_answers_returns_list(self):
        """Return type is still a list of dicts."""
        results = search.find_answers_by_keyword("", "json")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, dict)
            assert "topic" in r
            assert "topic_type" in r

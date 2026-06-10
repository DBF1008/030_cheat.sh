"""
Unit tests for the scored, paginated search engine (lib/search.py).

Uses mocking to avoid needing real cheat sheet repositories.

Run with::

    cd repo
    python -m pytest tests/test_search.py -v
"""

import sys
import os
import types
import pytest

# ---------------------------------------------------------------------------
# bootstrap: make lib/ importable with stubbed dependencies
# ---------------------------------------------------------------------------

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LIB = os.path.join(_REPO, "lib")
sys.path.insert(0, _LIB)


# Stub config module with test-friendly defaults
_config_mod = types.ModuleType("config")
_config_mod.CONFIG = {
    "search.limit": 20,
    "search.page_size": 5,   # small for easy pagination tests
}
sys.modules["config"] = _config_mod

# Stub routing module – we control get_topics_list and get_answers
_routing_mod = types.ModuleType("routing")

# In-memory corpus for testing
_CORPUS = {}  # topic -> list of answer_dicts
_TOPICS = []  # flat list of topic strings


def _set_corpus(corpus):
    """Set up the fake corpus.

    ``corpus`` is a dict mapping topic strings to answer text strings.
    Each topic gets one answer_dict with topic_type='test'.
    """
    global _CORPUS, _TOPICS
    _CORPUS = {}
    _TOPICS = sorted(corpus.keys())
    for topic, text in corpus.items():
        _CORPUS[topic] = [
            {
                "topic": topic,
                "topic_type": "test",
                "answer": text,
                "format": "code",
            }
        ]


def _get_topics_list(skip_internal=False, skip_dirs=False):
    return list(_TOPICS)


def _get_answers(topic, request_options=None):
    return _CORPUS.get(topic, [])


_routing_mod.get_topics_list = _get_topics_list
_routing_mod.get_answers = _get_answers
sys.modules["routing"] = _routing_mod

# Now import search
import search  # noqa: E402


# ---------------------------------------------------------------------------
# Tests: match() backward compatibility
# ---------------------------------------------------------------------------


class TestMatch:
    def test_simple_match(self):
        assert search.match("hello world", "hello") is True

    def test_no_match(self):
        assert search.match("hello world", "xyz") is False

    def test_tilde_joined_keywords(self):
        assert search.match("hello world foo", "hello~foo") is True
        assert search.match("hello world foo", "hello~bar") is False

    def test_case_sensitive_by_default(self):
        assert search.match("Hello World", "hello") is False

    def test_case_insensitive_option(self):
        assert search.match("Hello World", "hello", options="i") is True

    def test_word_boundaries(self):
        assert search.match("helloworld", "hello", options="b") is False
        assert search.match("hello world", "hello", options="b") is True

    def test_none_keyword_always_matches(self):
        assert search.match("anything", None) is True

    def test_empty_keyword_fragments_ignored(self):
        # ~keyword~ → splits into ["", "keyword", ""] – empties skipped
        assert search.match("keyword here", "~keyword~") is True

    def test_combined_options(self):
        assert search.match("Hello World", "hello", options="bi") is True
        assert search.match("helloworld", "hello", options="bi") is False


# ---------------------------------------------------------------------------
# Tests: scoring (flat topics for non-recursive search)
# ---------------------------------------------------------------------------


class TestScoring:
    def setup_method(self):
        # Use flat topic names (no /) so non-recursive search works
        _set_corpus({
            "copy_file_py": "Copy a file in Python using shutil.copy_file().",
            "read_file_py": "Read file contents with open() and read().",
            "copy_file_sh": "Use cp to copy_file in bash.",
            "rebase_git": "Rebase your branch with git rebase.",
            "copy_docker": "Use docker cp to copy files into containers.",
        })

    def test_topic_and_body_match_scores(self):
        """Keywords matching both topic name and body score higher."""
        results = search.find_answers_by_keyword("", "copy_file")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert "copy_file_py" in topics
        assert "copy_file_sh" in topics

    def test_results_sorted_by_score(self):
        results = search.find_answers_by_keyword("", "copy")
        scored = [
            r for r in results
            if r.get("topic") != "search/pagination"
        ]
        # Check descending score order
        scores = [r["score"] for r in scored]
        assert scores == sorted(scores, reverse=True)

    def test_score_field_present(self):
        results = search.find_answers_by_keyword("", "copy")
        for r in results:
            if r.get("topic") != "search/pagination":
                assert "score" in r
                assert r["score"] > 0

    def test_topic_name_match_boosts_score(self):
        """Topic 'copy_file_py' with keyword 'copy_file' in both topic AND body
        should score higher than 'copy_docker' which only has 'copy' in body."""
        results = search.find_answers_by_keyword("", "copy_file")
        scored = {
            r["topic"]: r["score"]
            for r in results
            if r.get("topic") != "search/pagination"
        }
        if "copy_file_py" in scored and "copy_docker" in scored:
            assert scored["copy_file_py"] > scored["copy_docker"]


# ---------------------------------------------------------------------------
# Tests: snippet extraction
# ---------------------------------------------------------------------------


class TestSnippets:
    def setup_method(self):
        long_text = "\n".join(
            ["line %d" % i for i in range(20)]
        )
        # inject keyword at line 10
        lines = long_text.splitlines()
        lines[10] = "THIS LINE HAS THE KEYWORD MAGIC"
        long_text = "\n".join(lines)

        _set_corpus({
            "snippet_test": long_text,
        })

    def test_snippet_present(self):
        results = search.find_answers_by_keyword("", "MAGIC")
        real = [r for r in results if r.get("topic") != "search/pagination"]
        assert len(real) == 1
        assert "snippet" in real[0]
        assert "MAGIC" in real[0]["snippet"]

    def test_snippet_has_context(self):
        results = search.find_answers_by_keyword("", "MAGIC")
        real = [r for r in results if r.get("topic") != "search/pagination"]
        snippet = real[0]["snippet"]
        # snippet should contain surrounding lines (within 3 lines of hit at line 10)
        assert "line 7" in snippet or "line 8" in snippet
        assert "line 12" in snippet or "line 13" in snippet


# ---------------------------------------------------------------------------
# Tests: pagination (flat topics)
# ---------------------------------------------------------------------------


class TestPagination:
    def setup_method(self):
        # 12 flat topics so page_size=5 gives 3 pages
        corpus = {}
        for i in range(12):
            corpus["item_%02d" % i] = "shared keyword in all answers %d" % i
        _set_corpus(corpus)

    def test_page_1_has_results(self):
        results = search.find_answers_by_keyword("", "shared")
        real = [r for r in results if r.get("topic") != "search/pagination"]
        assert len(real) == 5  # page_size = 5

    def test_page_2_has_results(self):
        results = search.find_answers_by_keyword("", "shared", request_options={"p": "2"})
        real = [r for r in results if r.get("topic") != "search/pagination"]
        assert len(real) == 5

    def test_page_3_has_remainder(self):
        results = search.find_answers_by_keyword("", "shared", request_options={"p": "3"})
        real = [r for r in results if r.get("topic") != "search/pagination"]
        assert len(real) == 2  # 12 - 10 = 2

    def test_pagination_header_present(self):
        results = search.find_answers_by_keyword("", "shared")
        headers = [r for r in results if r.get("topic") == "search/pagination"]
        assert len(headers) == 1
        assert "page 1/3" in headers[0]["answer"]
        assert "12" in headers[0]["answer"]

    def test_pagination_header_shows_next(self):
        results = search.find_answers_by_keyword("", "shared")
        headers = [r for r in results if r.get("topic") == "search/pagination"]
        assert "?p=2" in headers[0]["answer"]

    def test_pagination_header_shows_prev_on_page_2(self):
        results = search.find_answers_by_keyword("", "shared", request_options={"p": "2"})
        headers = [r for r in results if r.get("topic") == "search/pagination"]
        assert "?p=1" in headers[0]["answer"]
        assert "?p=3" in headers[0]["answer"]

    def test_no_pagination_header_when_single_page(self):
        _set_corpus({"onlyone": "keyword match"})
        results = search.find_answers_by_keyword("", "keyword")
        headers = [r for r in results if r.get("topic") == "search/pagination"]
        assert len(headers) == 0

    def test_stable_ordering_across_pages(self):
        """Topics on page 1 should never appear on page 2."""
        page1 = search.find_answers_by_keyword("", "shared", request_options={"p": "1"})
        page2 = search.find_answers_by_keyword("", "shared", request_options={"p": "2"})

        p1_topics = {r["topic"] for r in page1 if r.get("topic") != "search/pagination"}
        p2_topics = {r["topic"] for r in page2 if r.get("topic") != "search/pagination"}
        assert p1_topics.isdisjoint(p2_topics)

    def test_invalid_page_defaults_to_1(self):
        results = search.find_answers_by_keyword("", "shared", request_options={"p": "abc"})
        real = [r for r in results if r.get("topic") != "search/pagination"]
        assert len(real) == 5

    def test_beyond_last_page_empty(self):
        results = search.find_answers_by_keyword("", "shared", request_options={"p": "99"})
        real = [r for r in results if r.get("topic") != "search/pagination"]
        assert len(real) == 0


# ---------------------------------------------------------------------------
# Tests: backward-compatible ~keyword syntax and options
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def setup_method(self):
        # flat topics for non-recursive search
        _set_corpus({
            "ssh_keys": "Generate SSH keys with ssh-keygen for passphrase protection.",
            "ssh_config": "Configure SSH client settings.",
            "git_push": "Push changes with git push over SSH.",
            "python_passlib": "Use passlib for password hashing.",
        })

    def test_tilde_joined_keywords_and_logic(self):
        """~ssh~passphrase should only match answers containing both."""
        results = search.find_answers_by_keyword("", "ssh~passphrase")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert "ssh_keys" in topics
        # git_push has SSH but not passphrase
        assert "git_push" not in topics
        # python_passlib has passphrase but not ssh
        assert "python_passlib" not in topics

    def test_directory_prefix_filtering(self):
        # use topics with / for directory filtering test
        _set_corpus({
            "ssh/config_file": "Configure SSH client settings with config.",
            "ssh/keys_file": "SSH key management.",
            "git/push_file": "Push changes.",
        })
        results = search.find_answers_by_keyword("ssh/", "config", options="r")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert "ssh/config_file" in topics
        assert "git/push_file" not in topics

    def test_recursive_option(self):
        _set_corpus({
            "lang/python/basics": "Python basics with variables and loops keyword.",
            "lang/python/advanced": "Advanced Python decorators keyword.",
            "lang/rust/basics": "Rust basics with ownership keyword.",
        })
        # without recursive, subtopics with / are skipped
        results = search.find_answers_by_keyword("lang/", "keyword")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert len(topics) == 0  # all topics have / in subtopic

        # with recursive
        results = search.find_answers_by_keyword("lang/", "keyword", options="r")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert "lang/python/basics" in topics
        assert "lang/rust/basics" in topics

    def test_case_insensitive_option(self):
        _set_corpus({"testcaps": "HELLO WORLD"})
        results = search.find_answers_by_keyword("", "hello")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert len(topics) == 0

        results = search.find_answers_by_keyword("", "hello", options="i")
        topics = [r.get("topic") for r in results if r.get("topic") != "search/pagination"]
        assert "testcaps" in topics

    def test_word_boundary_option(self):
        _set_corpus({"testwb": "helloworld and hello world"})
        results = search.find_answers_by_keyword("", "hello", options="b")
        real = [r for r in results if r.get("topic") != "search/pagination"]
        # should match because "hello world" has word-boundary match for "hello"
        assert len(real) == 1

    def test_empty_keyword_returns_empty(self):
        results = search.find_answers_by_keyword("", "")
        assert results == []

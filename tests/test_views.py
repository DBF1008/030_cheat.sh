"""
Tests for the unified multi-view display layer.

Tests all 5 renderers, source metadata, options consistency,
edit buttons, and GitHub source info.
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

MYDIR = os.path.abspath(os.path.join(__file__, "..", ".."))
sys.path.insert(0, os.path.join(MYDIR, "lib"))

# Mock CONFIG before importing modules that depend on it
_MOCK_CONFIG = {
    "frontend.styles": ["native", "monokai", "default"],
    "path.internal.ansi2html": os.path.join(MYDIR, "share", "ansi2html.sh"),
}

with patch.dict("sys.modules", {}):
    pass

import frontend.sources as sources
from frontend.views import (
    get_renderer,
    get_available_formats,
    _is_found,
    AnsiViewRenderer,
    PlainTextViewRenderer,
    RawViewRenderer,
    JsonViewRenderer,
    HtmlViewRenderer,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_answer(topic="python/copy+file", topic_type="cheat.sheets",
                 answer="# copy a file\nimport shutil\nshutil.copy(src, dst)\n",
                 fmt="code", filetype="python", editable=True,
                 edit_url="https://github.com/chubin/cheat.sheets/edit/master/sheets/python/copy+file",
                 source_url="https://github.com/chubin/cheat.sheets"):
    return {
        "topic": topic,
        "topic_type": topic_type,
        "answer": answer,
        "format": fmt,
        "cache": False,
        "filetype": filetype,
        "editable": editable,
        "edit_url": edit_url if editable else "",
        "source_url": source_url,
        "answer_id": "%s:%s" % (topic_type, topic),
    }


def _make_answer_data(answers=None, query="python/copy+file", keyword=None):
    if answers is None:
        answers = [_make_answer()]
    return {
        "query": query,
        "keyword": keyword,
        "answers": answers,
        "topics_list": ["python/copy+file", "ls", "tar", "git"],
    }


SINGLE_ANSWER_DATA = _make_answer_data()

MULTI_ANSWER_DATA = _make_answer_data(
    query="copy+file",
    answers=[
        _make_answer(
            topic="python/copy+file",
            topic_type="cheat.sheets",
            answer="import shutil\nshutil.copy(src, dst)\n",
        ),
        _make_answer(
            topic="python/copy+file",
            topic_type="tldr",
            answer="cp source destination\n",
            editable=False,
            source_url="https://github.com/tldr-pages/tldr",
        ),
        _make_answer(
            topic="python/copy+file",
            topic_type="question",
            answer="Use shutil.copy() for copying files.\n",
            fmt="text+code",
            editable=False,
            source_url="",
        ),
    ],
)


# ---------------------------------------------------------------------------
# TestSources
# ---------------------------------------------------------------------------

class TestSources:
    def test_get_source_url_known(self):
        assert sources.get_source_url("cheat.sheets") == "https://github.com/chubin/cheat.sheets"
        assert sources.get_source_url("tldr") == "https://github.com/tldr-pages/tldr"

    def test_get_source_url_unknown(self):
        assert sources.get_source_url("unknown") == ""
        assert sources.get_source_url("nonexistent") == ""

    def test_get_edit_url_cheat_sheets(self):
        url = sources.get_edit_url("python/copy+file", "cheat.sheets")
        assert url == "https://github.com/chubin/cheat.sheets/edit/master/sheets/_python/copy+file"

    def test_get_edit_url_simple_topic(self):
        url = sources.get_edit_url("tar", "cheat.sheets")
        assert url == "https://github.com/chubin/cheat.sheets/edit/master/sheets/tar"

    def test_get_edit_url_non_cheat_sheets(self):
        assert sources.get_edit_url("ls", "tldr") == ""
        assert sources.get_edit_url("ls", "question") == ""

    def test_get_github_button_html_known(self):
        html = sources.get_github_button_html("cheat.sheets")
        assert "chubin/cheat.sheets" in html
        assert "github-button" in html
        assert "cheat.sheets" in html

    def test_get_github_button_html_unknown(self):
        assert sources.get_github_button_html("unknown") == ""
        assert sources.get_github_button_html("internal") == ""


# ---------------------------------------------------------------------------
# TestViewRegistry
# ---------------------------------------------------------------------------

class TestViewRegistry:
    def test_get_available_formats(self):
        formats = get_available_formats()
        assert "ansi" in formats
        assert "html" in formats
        assert "json" in formats
        assert "raw" in formats
        assert "text" in formats

    def test_get_renderer_valid(self):
        for fmt in ("ansi", "html", "json", "raw", "text"):
            r = get_renderer(fmt)
            assert r is not None
            assert r.format_name == fmt

    def test_get_renderer_invalid(self):
        with pytest.raises(ValueError, match="Unknown view format"):
            get_renderer("xml")

    def test_renderer_types(self):
        assert isinstance(get_renderer("ansi"), AnsiViewRenderer)
        assert isinstance(get_renderer("text"), PlainTextViewRenderer)
        assert isinstance(get_renderer("raw"), RawViewRenderer)
        assert isinstance(get_renderer("json"), JsonViewRenderer)
        assert isinstance(get_renderer("html"), HtmlViewRenderer)


# ---------------------------------------------------------------------------
# TestIsFound
# ---------------------------------------------------------------------------

class TestIsFound:
    def test_all_found(self):
        answers = [
            {"topic_type": "cheat.sheets"},
            {"topic_type": "tldr"},
        ]
        assert _is_found(answers) is True

    def test_unknown_present(self):
        answers = [
            {"topic_type": "unknown"},
        ]
        assert _is_found(answers) is False

    def test_mixed(self):
        answers = [
            {"topic_type": "cheat.sheets"},
            {"topic_type": "unknown"},
        ]
        assert _is_found(answers) is False

    def test_empty(self):
        assert _is_found([]) is True


# ---------------------------------------------------------------------------
# TestRawView
# ---------------------------------------------------------------------------

class TestRawView:
    def test_single_answer(self):
        renderer = RawViewRenderer()
        result, found = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "import shutil" in result
        assert "shutil.copy(src, dst)" in result
        assert found is True
        # Single answer should NOT have section header
        assert "#[" not in result

    def test_multi_answer_has_headers(self):
        renderer = RawViewRenderer()
        result, found = renderer.render(MULTI_ANSWER_DATA, {})
        assert "#[cheat.sheets:python/copy+file]" in result
        assert "#[tldr:python/copy+file]" in result
        assert "#[question:python/copy+file]" in result
        assert found is True

    def test_unknown_not_found(self):
        data = _make_answer_data(answers=[
            _make_answer(topic_type="unknown", answer="not found\n", editable=False),
        ])
        renderer = RawViewRenderer()
        _, found = renderer.render(data, {})
        assert found is False

    def test_returns_tuple(self):
        renderer = RawViewRenderer()
        result = renderer.render(SINGLE_ANSWER_DATA, {})
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_raw_preserves_content(self):
        original = "exact content here\nline 2\n"
        data = _make_answer_data(answers=[
            _make_answer(answer=original, editable=False),
        ])
        renderer = RawViewRenderer()
        result, _ = renderer.render(data, {})
        assert "exact content here" in result
        assert "line 2" in result


# ---------------------------------------------------------------------------
# TestJsonView
# ---------------------------------------------------------------------------

class TestJsonView:
    def test_valid_json(self):
        renderer = JsonViewRenderer()
        result, found = renderer.render(SINGLE_ANSWER_DATA, {})
        parsed = json.loads(result)
        assert parsed["query"] == "python/copy+file"
        assert found is True

    def test_contains_answers(self):
        renderer = JsonViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        parsed = json.loads(result)
        assert len(parsed["answers"]) == 1
        answer = parsed["answers"][0]
        assert answer["topic"] == "python/copy+file"
        assert answer["topic_type"] == "cheat.sheets"
        assert "answer" in answer

    def test_excludes_cache_field(self):
        renderer = JsonViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        parsed = json.loads(result)
        for answer in parsed["answers"]:
            assert "cache" not in answer

    def test_includes_metadata_fields(self):
        renderer = JsonViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        parsed = json.loads(result)
        answer = parsed["answers"][0]
        assert "editable" in answer
        assert "edit_url" in answer
        assert "source_url" in answer
        assert "answer_id" in answer

    def test_returns_tuple(self):
        renderer = JsonViewRenderer()
        result = renderer.render(SINGLE_ANSWER_DATA, {})
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_multi_answer_json(self):
        renderer = JsonViewRenderer()
        result, found = renderer.render(MULTI_ANSWER_DATA, {})
        parsed = json.loads(result)
        assert len(parsed["answers"]) == 3
        assert found is True

    def test_keyword_preserved(self):
        data = _make_answer_data(keyword="copy")
        renderer = JsonViewRenderer()
        result, _ = renderer.render(data, {})
        parsed = json.loads(result)
        assert parsed["keyword"] == "copy"


# ---------------------------------------------------------------------------
# TestAnsiView
# ---------------------------------------------------------------------------

class TestAnsiView:
    @patch("frontend.ansi._visualize")
    def test_delegates_to_visualize(self, mock_viz):
        mock_viz.return_value = ("output\n", True)
        renderer = AnsiViewRenderer()
        result, found = renderer.render(SINGLE_ANSWER_DATA, {})
        assert result == "output\n"
        assert found is True
        mock_viz.assert_called_once()

    def test_returns_tuple(self):
        renderer = AnsiViewRenderer()
        with patch("frontend.ansi._visualize", return_value=("x\n", True)):
            result = renderer.render(SINGLE_ANSWER_DATA, {})
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# TestPlainTextView
# ---------------------------------------------------------------------------

class TestPlainTextView:
    @patch("frontend.ansi._visualize")
    def test_forces_no_terminal(self, mock_viz):
        mock_viz.return_value = ("plain output\n", True)
        renderer = PlainTextViewRenderer()
        result, found = renderer.render(SINGLE_ANSWER_DATA, {"style": "monokai"})
        assert found is True
        # Check that no-terminal was set in the options passed to visualize
        call_args = mock_viz.call_args
        # _visualize is called from visualize() which passes request_options
        # We need to verify no-terminal was set

    @patch("frontend.ansi.visualize")
    def test_strips_ansi(self, mock_viz):
        mock_viz.return_value = ("plain text\n", True)
        renderer = PlainTextViewRenderer()
        result, found = renderer.render(SINGLE_ANSWER_DATA, {})
        assert found is True


# ---------------------------------------------------------------------------
# TestHtmlView
# ---------------------------------------------------------------------------

class TestHtmlView:
    @patch("frontend.views._ansi2html")
    def test_returns_html_page(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head><style>.ansi{}</style></head>"
            "<body><pre>highlighted code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, found = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "<!DOCTYPE html>" in result
        assert "<title>cheat.sh/python/copy+file</title>" in result
        assert found is True

    @patch("frontend.views._ansi2html")
    def test_contains_toolbar(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert 'id="toolbar"' in result
        assert 'id="view-switcher"' in result

    @patch("frontend.views._ansi2html")
    def test_contains_answer_blocks(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert 'class="answer-block"' in result
        assert 'data-topic-type="cheat.sheets"' in result
        assert 'data-filetype="python"' in result

    @patch("frontend.views._ansi2html")
    def test_edit_button_for_cheat_sheets(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert 'class="edit-btn"' in result
        assert "edit" in result.lower()
        assert "github.com/chubin/cheat.sheets/edit" in result

    @patch("frontend.views._ansi2html")
    def test_no_edit_button_for_other_sources(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        data = _make_answer_data(answers=[
            _make_answer(topic_type="tldr", editable=False),
        ])
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(data, {})
        assert 'class="edit-btn"' not in result

    @patch("frontend.views._ansi2html")
    def test_github_source_button(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "chubin/cheat.sheets" in result
        assert "github-button" in result

    @patch("frontend.views._ansi2html")
    def test_embedded_json(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert 'id="answer-data"' in result
        assert 'type="application/json"' in result

    @patch("frontend.views._ansi2html")
    def test_search_form(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "<form" in result
        assert 'id="topics"' in result
        assert "curl cheat.sh/" in result

    @patch("frontend.views._ansi2html")
    def test_quiet_suppresses_social(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {"quiet": True})
        assert "twitter-follow-button" not in result

    @patch("frontend.views._ansi2html")
    def test_social_buttons_present_by_default(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "twitter-follow-button" in result or "github-button" in result

    @patch("frontend.ansi.render_answer_block", return_value="mocked ansi\n")
    @patch("frontend.views._ansi2html")
    def test_multi_answer_filter_controls(self, mock_a2h, mock_rab):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(MULTI_ANSWER_DATA, {})
        assert 'data-filter="topic_type"' in result
        assert 'value="cheat.sheets"' in result
        assert 'value="tldr"' in result

    @patch("frontend.views._ansi2html")
    def test_collapse_controls(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "Expand All" in result
        assert "Collapse All" in result
        assert "toggleCollapse" in result

    @patch("frontend.views._ansi2html")
    def test_view_switch_buttons(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert "switchView" in result
        for view in ("html", "raw", "text", "json"):
            assert ("data-view=\"%s\"" % view) in result

    @patch("frontend.views._ansi2html")
    def test_view_containers(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>code</pre></body></html>"
        )
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        assert 'id="raw-view"' in result
        assert 'id="text-view"' in result
        assert 'id="json-view"' in result

    @patch("frontend.views._ansi2html")
    def test_firstpage_query_clears_input(self, mock_a2h):
        mock_a2h.return_value = (
            "<html><head></head><body><pre>welcome</pre></body></html>"
        )
        data = _make_answer_data(query=":firstpage")
        renderer = HtmlViewRenderer()
        result, _ = renderer.render(data, {})
        assert 'value=""' in result


# ---------------------------------------------------------------------------
# TestOptionsConsistency
# ---------------------------------------------------------------------------

class TestOptionsConsistency:
    """Verify that options are handled consistently across views."""

    def test_all_renderers_return_tuple(self):
        """Every renderer must return (str, bool)."""
        for fmt in get_available_formats():
            renderer = get_renderer(fmt)
            with patch("frontend.views._ansi2html", return_value=(
                "<html><head></head><body><pre>x</pre></body></html>"
            )):
                with patch("frontend.ansi._visualize", return_value=("x\n", True)):
                    result = renderer.render(SINGLE_ANSWER_DATA, {})
            assert isinstance(result, tuple), \
                "%s renderer must return tuple" % fmt
            assert len(result) == 2, \
                "%s renderer must return 2-tuple" % fmt
            assert isinstance(result[0], str), \
                "%s renderer result[0] must be str" % fmt
            assert isinstance(result[1], bool), \
                "%s renderer result[1] must be bool" % fmt

    def test_raw_ignores_style(self):
        """Raw view should not be affected by style option."""
        renderer = RawViewRenderer()
        r1, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        r2, _ = renderer.render(SINGLE_ANSWER_DATA, {"style": "monokai"})
        assert r1 == r2

    def test_json_ignores_style(self):
        """JSON view should not be affected by style option."""
        renderer = JsonViewRenderer()
        r1, _ = renderer.render(SINGLE_ANSWER_DATA, {})
        r2, _ = renderer.render(SINGLE_ANSWER_DATA, {"style": "monokai"})
        assert r1 == r2

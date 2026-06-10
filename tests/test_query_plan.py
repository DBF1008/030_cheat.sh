"""
Unit tests for QueryPlan structured request plan.

Run with::

    cd repo
    python -m pytest tests/test_query_plan.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from options import QueryPlan, parse_args


class TestFromHttpDefaults:
    """QueryPlan.from_http with empty args should match old parse_args({}) defaults."""

    def test_defaults(self):
        plan = QueryPlan.from_http({}, "python/list")
        assert plan.add_comments is True
        assert plan.unindent_code is False
        assert plan.remove_text is False
        assert plan.quiet is False
        assert plan.no_terminal is False
        assert plan.style == ""
        assert plan.raw_query == "python/list"
        assert plan.output_format == "ansi"
        assert plan.client_id is None
        assert plan.tenant_id == "default"
        assert plan.adapter_used is None
        assert plan.cache_hit is None

    def test_defaults_match_parse_args(self):
        old = parse_args({})
        plan = QueryPlan.from_http({}, "test")
        assert plan.add_comments == old["add_comments"]


class TestFromHttpFlags:
    """Short flags embedded in query string keys are expanded correctly."""

    def test_c_flag(self):
        # ?c  =>  add_comments=False, unindent_code=False
        args = {"c": ""}
        plan = QueryPlan.from_http(args, "python")
        assert plan.add_comments is False
        assert plan.unindent_code is False

    def test_C_flag(self):
        # ?C  =>  add_comments=False, unindent_code=True
        args = {"C": ""}
        plan = QueryPlan.from_http(args, "python")
        assert plan.add_comments is False
        assert plan.unindent_code is True

    def test_Q_flag(self):
        args = {"Q": ""}
        plan = QueryPlan.from_http(args, "python")
        assert plan.remove_text is True

    def test_q_flag(self):
        args = {"q": ""}
        plan = QueryPlan.from_http(args, "python")
        assert plan.quiet is True

    def test_T_flag(self):
        args = {"T": ""}
        plan = QueryPlan.from_http(args, "python")
        assert plan.no_terminal is True

    def test_combined_flags(self):
        # ?cQ  =>  add_comments=False, unindent_code=False, remove_text=True
        args = {"cQ": ""}
        plan = QueryPlan.from_http(args, "python")
        assert plan.add_comments is False
        assert plan.remove_text is True

    def test_combined_flags_match_parse_args(self):
        args = {"cQ": ""}
        old = parse_args(args)
        plan = QueryPlan.from_http(args, "python")
        assert plan.add_comments == old["add_comments"]
        assert plan.remove_text == old["remove_text"]


class TestFromHttpStyle:
    """Key-value query args like style=monokai are passed through."""

    def test_style_passthrough(self):
        args = {"style": "monokai"}
        plan = QueryPlan.from_http(args, "python")
        assert plan.style == "monokai"

    def test_style_in_options_dict(self):
        args = {"style": "monokai"}
        plan = QueryPlan.from_http(args, "python")
        assert plan.get("style") == "monokai"


class TestFromHttpContext:
    """HTTP context fields (lang, output_format, client_id, tenant_id) are set."""

    def test_context_fields(self):
        plan = QueryPlan.from_http(
            {}, "python",
            lang="ru",
            output_format="html",
            client_id="abc123",
            tenant_id="myco",
        )
        assert plan.lang == "ru"
        assert plan.output_format == "html"
        assert plan.client_id == "abc123"
        assert plan.tenant_id == "myco"

    def test_lang_in_options_dict(self):
        plan = QueryPlan.from_http({}, "python", lang="es")
        assert plan.get("lang") == "es"


class TestDictCompatGet:
    """Dict-compat .get() delegates to _options_dict."""

    def test_get_add_comments(self):
        plan = QueryPlan.from_http({}, "t")
        assert plan.get("add_comments") is True

    def test_get_no_terminal(self):
        args = {"T": ""}
        plan = QueryPlan.from_http(args, "t")
        # The dict-compat layer uses the hyphenated key "no-terminal"
        assert plan.get("no-terminal") is True

    def test_get_missing_key(self):
        plan = QueryPlan.from_http({}, "t")
        assert plan.get("nonexistent", "default") == "default"

    def test_getitem(self):
        plan = QueryPlan.from_http({}, "t")
        assert plan["add_comments"] is True

    def test_contains(self):
        plan = QueryPlan.from_http({}, "t")
        assert "add_comments" in plan
        assert "nonexistent" not in plan


class TestDictCompatItems:
    """Dict-compat .items() returns only display-option keys."""

    def test_items_no_internal_fields(self):
        plan = QueryPlan.from_http(
            {}, "python",
            lang="ru",
            output_format="html",
            client_id="abc123",
            tenant_id="myco",
        )
        keys = dict(plan.items())
        # Internal fields must NOT appear in items()
        assert "output_format" not in keys
        assert "client_id" not in keys
        assert "tenant_id" not in keys
        assert "raw_query" not in keys
        assert "topic" not in keys
        assert "adapter_used" not in keys
        # Display options should be present
        assert "add_comments" in keys
        assert "lang" in keys

    def test_items_count_minimal(self):
        # With no flags, only add_comments is set (the default True value)
        plan = QueryPlan.from_http({}, "t")
        keys = dict(plan.items())
        assert "add_comments" in keys


class TestToOptionsDict:
    """to_options_dict() returns a backward-compatible dict."""

    def test_basic(self):
        args = {"cQ": "", "style": "monokai"}
        plan = QueryPlan.from_http(args, "python", lang="ru")
        d = plan.to_options_dict()
        assert isinstance(d, dict)
        assert d["add_comments"] is False
        assert d["remove_text"] is True
        assert d["style"] == "monokai"
        assert d["lang"] == "ru"

    def test_is_copy(self):
        plan = QueryPlan.from_http({}, "t")
        d1 = plan.to_options_dict()
        d1["add_comments"] = "mutated"
        # Original should not be affected
        assert plan.get("add_comments") is True


class TestToDebugDict:
    """to_debug_dict() includes all fields."""

    def test_all_fields_present(self):
        plan = QueryPlan.from_http(
            {"cQ": "", "style": "monokai"}, "python/list",
            lang="ru", output_format="html",
            client_id="abc", tenant_id="myco",
        )
        plan.resolve_query("python/list", None, "")
        plan.adapter_used = "cheat.sheets"
        plan.cache_hit = True

        d = plan.to_debug_dict()
        assert d["raw_query"] == "python/list"
        assert d["topic"] == "python/list"
        assert d["keyword"] is None
        assert d["search_options"] == ""
        assert d["display_options"]["add_comments"] is False
        assert d["display_options"]["remove_text"] is True
        assert d["display_options"]["style"] == "monokai"
        assert d["lang"] == "ru"
        assert d["output_format"] == "html"
        assert d["client_id"] == "abc"
        assert d["tenant_id"] == "myco"
        assert d["adapter_used"] == "cheat.sheets"
        assert d["cache_hit"] is True


class TestResolveQuery:
    """resolve_query() populates topic/keyword/search_options."""

    def test_resolve(self):
        plan = QueryPlan.from_http({}, "python~copy/i")
        plan.resolve_query("python", "copy", "i")
        assert plan.topic == "python"
        assert plan.keyword == "copy"
        assert plan.search_options == "i"

    def test_resolve_no_keyword(self):
        plan = QueryPlan.from_http({}, "python/list")
        plan.resolve_query("python/list", None, "")
        assert plan.topic == "python/list"
        assert plan.keyword is None
        assert plan.search_options == ""


class TestFromArgs:
    """QueryPlan.from_args() for CLI usage."""

    def test_basic(self):
        # Simulates urlparse.parse_qs output: values are lists
        args = {"c": [""], "style": ["monokai"]}
        plan = QueryPlan.from_args(args, "python/list")
        assert plan.add_comments is False
        assert plan.style == "monokai"
        assert plan.output_format == "ansi"
        assert plan.client_id is None
        assert plan.tenant_id == "default"

    def test_empty_args(self):
        plan = QueryPlan.from_args({}, "python")
        assert plan.add_comments is True
        assert plan.raw_query == "python"


class TestParseArgsBackwardCompat:
    """The old parse_args() function still works."""

    def test_returns_dict(self):
        result = parse_args({"cQ": ""})
        assert isinstance(result, dict)
        assert result["add_comments"] is False
        assert result["remove_text"] is True

    def test_empty(self):
        result = parse_args({})
        assert result == {"add_comments": True}

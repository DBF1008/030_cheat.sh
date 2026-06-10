"""Tests for source/prefer query parameter parsing."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from options import parse_args


class TestSourceParam:
    def test_source_parsed_as_list(self):
        result = parse_args({"source": "tldr,cheat.sheets"})
        assert result["source"] == ["tldr", "cheat.sheets"]

    def test_source_single_value(self):
        result = parse_args({"source": "tldr"})
        assert result["source"] == ["tldr"]

    def test_source_with_spaces(self):
        result = parse_args({"source": "tldr , cheat.sheets"})
        assert result["source"] == ["tldr", "cheat.sheets"]

    def test_source_empty_string_filtered(self):
        result = parse_args({"source": "tldr,,cheat.sheets"})
        assert result["source"] == ["tldr", "cheat.sheets"]


class TestPreferParam:
    def test_prefer_parsed_as_list(self):
        result = parse_args({"prefer": "cheat.sheets"})
        assert result["prefer"] == ["cheat.sheets"]

    def test_prefer_multiple(self):
        result = parse_args({"prefer": "cheat.sheets,tldr"})
        assert result["prefer"] == ["cheat.sheets", "tldr"]


class TestNoSourceOrPrefer:
    def test_no_source_key_when_absent(self):
        result = parse_args({"q": ""})
        assert "source" not in result

    def test_no_prefer_key_when_absent(self):
        result = parse_args({"q": ""})
        assert "prefer" not in result

    def test_existing_flags_preserved(self):
        result = parse_args({"source": "tldr", "q": ""})
        assert result["source"] == ["tldr"]
        assert result["quiet"] is True

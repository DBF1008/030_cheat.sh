"""Tests for the multi-source ranking engine."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from ranking import rank_answers, _compute_score, _classify_query


def _make_answer(topic_type, topic="tar", answer="x" * 500, fmt="code"):
    return {
        "topic": topic,
        "topic_type": topic_type,
        "answer": answer,
        "format": fmt,
    }


class TestClassifyQuery:
    def test_bare_word(self):
        assert _classify_query("tar") == "bare_word"

    def test_language_scoped(self):
        assert _classify_query("python/lambda") == "language_scoped"

    def test_question(self):
        assert _classify_query("python/how+to+read+json") == "question"

    def test_question_with_space(self):
        assert _classify_query("python read json") == "question"


class TestEmptyAndSingle:
    def test_empty_answers(self):
        assert rank_answers([], "tar") == []

    def test_single_answer_scored(self):
        answers = [_make_answer("cheat.sheets")]
        result = rank_answers(answers, "tar")
        assert len(result) == 1
        assert "_score" in result[0]
        assert "_score_reasons" in result[0]
        assert isinstance(result[0]["_score"], float)
        assert isinstance(result[0]["_score_reasons"], list)
        assert len(result[0]["_score_reasons"]) > 0


class TestMultipleAnswersSorted:
    def test_sorted_descending(self):
        answers = [
            _make_answer("question", answer="x" * 500, fmt="text+code"),
            _make_answer("cheat.sheets", answer="x" * 500),
            _make_answer("tldr", answer="x" * 500),
        ]
        result = rank_answers(answers, "tar")
        scores = [a["_score"] for a in result]
        assert scores == sorted(scores, reverse=True)

    def test_curated_beats_question(self):
        answers = [
            _make_answer("question", answer="x" * 500, fmt="text+code"),
            _make_answer("cheat.sheets", answer="x" * 500),
        ]
        result = rank_answers(answers, "tar")
        assert result[0]["topic_type"] == "cheat.sheets"
        assert result[1]["topic_type"] == "question"
        assert result[0]["_score"] > result[1]["_score"]


class TestQueryShapeBonus:
    def test_question_adapter_boosted_for_question_query(self):
        topic = "python/how+to+read+json"
        answers = [
            _make_answer("cheat.sheets", topic=topic, answer="x" * 500),
            _make_answer("question", topic=topic, answer="x" * 500, fmt="text+code"),
        ]
        result = rank_answers(answers, topic)
        # Question adapter gets +0.10 for Q&A query, others get -0.05
        question_answer = [a for a in result if a["topic_type"] == "question"][0]
        assert "Q&A query on Q&A source" in question_answer["_score_reasons"]

    def test_bare_command_bonus(self):
        answers = [_make_answer("cheat.sheets", answer="x" * 500)]
        result = rank_answers(answers, "tar")
        assert "command query" in result[0]["_score_reasons"]


class TestPreferBoost:
    def test_prefer_boosts_score(self):
        answers = [
            _make_answer("cheat.sheets", answer="x" * 500),
            _make_answer("tldr", answer="x" * 500),
        ]
        opts_without = {}
        opts_with = {"prefer": ["tldr"]}

        result_without = rank_answers(
            [_make_answer("tldr", answer="x" * 500)], "tar", request_options=opts_without
        )
        result_with = rank_answers(
            [_make_answer("tldr", answer="x" * 500)], "tar", request_options=opts_with
        )
        assert result_with[0]["_score"] > result_without[0]["_score"]
        assert "preferred source" in result_with[0]["_score_reasons"]

    def test_prefer_can_reorder(self):
        answers = [
            _make_answer("cheat.sheets", answer="x" * 500),
            _make_answer("tldr", answer="x" * 500),
        ]
        result = rank_answers(answers, "tar", request_options={"prefer": ["tldr"]})
        # tldr (0.65 + 0.15 + 0.15 + 0.05 + 0.10 = 1.0) vs
        # cheat.sheets (0.70 + 0.15 + 0.05 + 0.10 = 1.0) -- very close, prefer tips it
        # With prefer boost, tldr gets +0.15 extra
        tldr_score = [a for a in result if a["topic_type"] == "tldr"][0]["_score"]
        cs_score = [a for a in result if a["topic_type"] == "cheat.sheets"][0]["_score"]
        assert tldr_score >= cs_score


class TestContentLength:
    def test_empty_answer_penalized(self):
        answers = [_make_answer("cheat.sheets", answer="")]
        result = rank_answers(answers, "tar")
        assert "empty answer" in result[0]["_score_reasons"]

    def test_sweet_spot_bonus(self):
        answers = [_make_answer("cheat.sheets", answer="x" * 500)]
        result = rank_answers(answers, "tar")
        assert "good answer length" in result[0]["_score_reasons"]

    def test_very_long_penalized(self):
        answers = [_make_answer("cheat.sheets", answer="x" * 6000)]
        result = rank_answers(answers, "tar")
        assert "very long answer" in result[0]["_score_reasons"]


class TestEdgeCases:
    def test_limited_sentinel_preserved(self):
        answers = [
            _make_answer("cheat.sheets", answer="x" * 500),
            {"topic": "LIMITED", "topic_type": "search", "answer": "", "format": "text"},
            _make_answer("tldr", answer="x" * 500),
        ]
        result = rank_answers(answers, "tar")
        assert result[-1]["topic"] == "LIMITED"
        assert "_score" not in result[-1]

    def test_internal_not_reordered(self):
        answers = [
            _make_answer("internal", topic=":help", answer="help text", fmt="ansi"),
            _make_answer("cheat.sheets", answer="x" * 500),
        ]
        result = rank_answers(answers, ":help")
        # internal is pinned first even if lower score
        assert result[0]["topic_type"] == "internal"

    def test_score_clamped_at_one(self):
        # Even with many bonuses, score should not exceed 1.0
        answers = [_make_answer("cheat.sheets", answer="x" * 500)]
        result = rank_answers(answers, "tar", request_options={"prefer": ["cheat.sheets"]})
        assert result[0]["_score"] <= 1.0

    def test_score_clamped_at_zero(self):
        answers = [_make_answer("unknown", answer="")]
        result = rank_answers(answers, "tar")
        assert result[0]["_score"] >= 0.0

    def test_score_reasons_populated(self):
        answers = [_make_answer("tldr", answer="x" * 500)]
        result = rank_answers(answers, "tar")
        assert len(result[0]["_score_reasons"]) >= 1
        # Should at least have the source reason
        assert any("source:" in r for r in result[0]["_score_reasons"])

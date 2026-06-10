"""
Main cheat.sh wrapper.
Parse the query, get answers from getters (using get_answer),
visualize it using frontends and return the result.

Exports:

    cheat_wrapper()
    resolve_query_only()
"""

import re
import json

from routing import get_answers, get_topics_list
from search import find_answers_by_keyword
from languages_data import LANGUAGE_ALIAS, rewrite_editor_section_name
from options import QueryPlan
import postprocessing

import frontend.html
import frontend.ansi


def _add_section_name(query):
    # temporary solution before we don't find a fixed one
    if " " not in query and "+" not in query:
        return query
    if "/" in query:
        return query
    if " " in query:
        return re.sub(r" +", "/", query, count=1)
    if "+" in query:
        # replace only single + to avoid catching g++ and friends
        return re.sub(r"([^\+])\+([^\+])", r"\1/\2", query, count=1)


def _rewrite_aliases(word):
    if word == ":bash.completion":
        return ":bash_completion"
    return word


def _rewrite_section_name(query):
    """
    Rewriting special section names:
    * EDITOR:NAME => emacs:go-mode
    """
    if "/" not in query:
        return query

    section_name, rest = query.split("/", 1)

    if ":" in section_name:
        section_name = rewrite_editor_section_name(section_name)
    section_name = LANGUAGE_ALIAS.get(section_name, section_name)

    return "%s/%s" % (section_name, rest)


def _sanitize_query(query):
    return re.sub('[<>"]', "", query)


def _parse_query(query):
    topic = query
    keyword = None
    search_options = ""

    keyword = None
    if "~" in query:
        topic = query
        pos = topic.index("~")
        keyword = topic[pos + 1 :]
        topic = topic[:pos]

        if "/" in keyword:
            search_options = keyword[::-1]
            search_options = search_options[: search_options.index("/")]
            keyword = keyword[: -len(search_options) - 1]

    return topic, keyword, search_options


def _resolve_query(query):
    """Apply all query rewriting steps and parse into (topic, keyword, search_options)."""
    query = _sanitize_query(query)
    query = _add_section_name(query)
    query = _rewrite_aliases(query)
    query = _rewrite_section_name(query)
    topic, keyword, search_options = _parse_query(query)
    return query, topic, keyword, search_options


def resolve_query_only(raw_query, query_plan):
    """
    Parse and resolve the query, populating query_plan fields,
    but do NOT execute any adapter/search calls.
    Used by the /:debug endpoint.
    """
    _query, topic, keyword, search_options = _resolve_query(raw_query)
    query_plan.resolve_query(topic, keyword, search_options)


def cheat_wrapper(query, query_plan=None, request_options=None, output_format="ansi"):
    """
    Function that delivers cheat sheet for `query`.
    If `html` is True, the answer is formatted as HTML.

    Accepts either a structured `query_plan` (QueryPlan) or legacy
    `request_options` dict + `output_format` string for backward compatibility.
    """

    # Backward compat: build QueryPlan from legacy arguments
    if query_plan is None:
        query_plan = QueryPlan.from_args({}, query)
        if request_options:
            # Populate from legacy dict
            query_plan.add_comments = request_options.get("add_comments", True)
            query_plan.unindent_code = request_options.get("unindent_code", False)
            query_plan.remove_text = request_options.get("remove_text", False)
            query_plan.quiet = request_options.get("quiet", False)
            query_plan.no_terminal = request_options.get("no-terminal", False)
            query_plan.style = request_options.get("style", "")
            query_plan.lang = request_options.get("lang")
            query_plan._rebuild_options_dict(request_options)
        query_plan.output_format = output_format

    query, topic, keyword, search_options = _resolve_query(query)
    query_plan.resolve_query(topic, keyword, search_options)

    if keyword:
        answers = find_answers_by_keyword(
            topic, keyword, options=search_options, request_options=query_plan
        )
    else:
        answers = get_answers(topic, request_options=query_plan)

    answers = [
        postprocessing.postprocess(
            answer, keyword, search_options, request_options=query_plan
        )
        for answer in answers
    ]

    answer_data = {
        "query": query,
        "keyword": keyword,
        "answers": answers,
    }

    if query_plan.output_format == "html":
        answer_data["topics_list"] = get_topics_list()
        return frontend.html.visualize(answer_data, query_plan)
    elif query_plan.output_format == "json":
        return json.dumps(answer_data, indent=4)
    return frontend.ansi.visualize(answer_data, query_plan)

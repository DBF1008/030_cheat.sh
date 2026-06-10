"""
ANSI frontend.

Exports:
    visualize(answer_data, request_options)

Format:
    answer_data = {
        'answers': '...',}

    answers = [answer,...]

    answer = {
        'topic':        '...',
        'topic_type':   '...',
        'answer':       '...',
        'format':       'ansi|code|markdown|text...',
    }

Configuration parameters:

    frontend.styles
"""

import os
import sys
import re

import colored
from pygments import highlight as pygments_highlight
from pygments.formatters import (
    Terminal256Formatter,
)  # pylint: disable=no-name-in-module

# pylint: disable=wrong-import-position
sys.path.append(os.path.abspath(os.path.join(__file__, "..")))
from config import CONFIG
import languages_data  # pylint: enable=wrong-import-position

import fmt.internal
import fmt.comments


def visualize(answer_data, request_options):
    """
    Renders `answer_data` as ANSI output.
    """
    answers = answer_data["answers"]
    pagination = answer_data.get("pagination")
    return _visualize(
        answers, request_options,
        search_mode=bool(answer_data["keyword"]),
        pagination=pagination,
    )


ANSI_ESCAPE = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")


def remove_ansi(sometext):
    """
    Remove ANSI sequences from `sometext` and convert it into plaintext.
    """
    return ANSI_ESCAPE.sub("", sometext)


def _limited_answer(answer):
    return (
        colored.bg("dark_goldenrod")
        + colored.fg("yellow_1")
        + " "
        + answer
        + " "
        + colored.attr("reset")
        + "\n"
    )


def _colorize_ansi_answer(
    topic,
    answer,
    color_style,  # pylint: disable=too-many-arguments
    highlight_all=True,
    highlight_code=False,
    unindent_code=False,
    language=None,
):

    color_style = color_style or "native"
    lexer_class = languages_data.LEXER["bash"]
    if "/" in topic:
        if language is None:
            section_name = topic.split("/", 1)[0].lower()
        else:
            section_name = language
        section_name = languages_data.get_lexer_name(section_name)
        lexer_class = languages_data.LEXER.get(section_name, lexer_class)
        if section_name == "php":
            answer = "<?\n%s?>\n" % answer

    if highlight_all:
        highlight = (
            lambda answer: pygments_highlight(
                answer, lexer_class(), Terminal256Formatter(style=color_style)
            ).strip("\n")
            + "\n"
        )
    else:
        highlight = lambda x: x

    if highlight_code:
        blocks = fmt.comments.code_blocks(
            answer, wrap_lines=True, unindent_code=(4 if unindent_code else False)
        )
        highlighted_blocks = []
        for block in blocks:
            if block[0] == 1:
                this_block = highlight(block[1])
            else:
                this_block = block[1].strip("\n") + "\n"
            highlighted_blocks.append(this_block)

        result = "\n".join(highlighted_blocks)
    else:
        result = highlight(answer).lstrip("\n")
    return result


def _pagination_footer(pagination, highlight=True):
    """Render a pagination status line."""
    if not pagination:
        return ""

    page = pagination["current_page"]
    total = pagination["total_pages"]
    count = pagination["total_results"]
    info = "--- page %d/%d (%d results) ---" % (page, total, count)

    if pagination["has_next"]:
        directory = pagination.get("directory", "")
        keyword = pagination.get("keyword", "")
        opts = pagination.get("options", "")
        next_page = page + 1
        hint = "next: %s~%s/%s%d" % (directory, keyword, opts, next_page)
        info += "  " + hint

    if not highlight:
        return info + "\n"

    return "".join([
        colored.fg("light_cyan"),
        info,
        colored.attr("reset"),
        "\n",
    ])


def _snippet_preview(snippet, highlight=True):
    """Render a snippet preview block with dimmed style."""
    if not snippet:
        return ""

    if not highlight:
        return snippet + "\n"

    return "".join([
        colored.fg("grey_50"),
        snippet,
        colored.attr("reset"),
        "\n",
    ])


def _search_section_header(topic_type, topic, score, highlight=True):
    """Render a search result section header with score."""
    section_name = "%s:%s" % (topic_type, topic)
    score_label = "[score: %d]" % score

    if not highlight:
        return "#[%s] %s\n" % (section_name, score_label)

    return "".join([
        "\n",
        colored.bg("dark_gray"),
        colored.attr("res_underlined"),
        " %s " % section_name,
        colored.attr("res_underlined"),
        colored.attr("reset"),
        " ",
        colored.fg("dark_khaki"),
        score_label,
        colored.attr("reset"),
        "\n",
    ])


def _visualize(answers, request_options, search_mode=False, pagination=None):

    highlight = not bool(request_options and request_options.get("no-terminal"))
    color_style = (request_options or {}).get("style", "")
    if color_style not in CONFIG["frontend.styles"]:
        color_style = ""

    # if there is more than one answer,
    # show the source of the answer
    multiple_answers = len(answers) > 1

    found = True
    result = ""
    for answer_dict in answers:
        topic = answer_dict["topic"]
        topic_type = answer_dict["topic_type"]
        answer = answer_dict["answer"]
        found = found and not topic_type == "unknown"

        # search mode: show snippet preview with score header
        if search_mode and "snippet" in answer_dict:
            score = answer_dict.get("search_score", 0)
            result += _search_section_header(topic_type, topic, score, highlight)
            result += _snippet_preview(answer_dict["snippet"], highlight)
            continue

        if multiple_answers and topic != "LIMITED":
            section_name = f"{topic_type}:{topic}"

            if not highlight:
                result += f"#[{section_name}]\n"
            else:
                result += "".join(
                    [
                        "\n",
                        colored.bg("dark_gray"),
                        colored.attr("res_underlined"),
                        f" {section_name} ",
                        colored.attr("res_underlined"),
                        colored.attr("reset"),
                        "\n",
                    ]
                )

        if answer_dict["format"] in ["ansi", "text"]:
            result += answer
        elif topic == ":firstpage-v1":
            result += fmt.internal.colorize_internal_firstpage_v1(answer)
        elif topic == "LIMITED":
            result += _limited_answer(topic)
        else:
            result += _colorize_ansi_answer(
                topic,
                answer,
                color_style,
                highlight_all=highlight,
                highlight_code=(
                    topic_type == "question"
                    and not request_options.get("add_comments")
                    and not request_options.get("remove_text")
                ),
                language=answer_dict.get("filetype"),
            )

    # append pagination footer for search results
    if search_mode and pagination:
        result += "\n" + _pagination_footer(pagination, highlight)

    if request_options.get("no-terminal"):
        result = remove_ansi(result)

    result = result.strip("\n") + "\n"
    return result, found

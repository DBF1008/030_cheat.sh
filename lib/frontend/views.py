"""
Unified multi-view display layer.

Provides ViewRenderer base class and concrete renderers for
ansi, html, json, raw, and plain text output formats.

Exports:
    get_renderer(format_name)
    get_available_formats()
"""

import json
import os
import re
import sys
from subprocess import Popen, PIPE

MYDIR = os.path.abspath(os.path.join(__file__, "..", ".."))
sys.path.append("%s/lib/" % MYDIR)

from config import CONFIG
from globals import error
from buttons import TWITTER_BUTTON, GITHUB_BUTTON, GITHUB_BUTTON_FOOTER
import frontend.ansi
import frontend.sources as sources

_REGISTRY = {}


def register_view(cls):
    """Decorator to register a ViewRenderer subclass."""
    _REGISTRY[cls.format_name] = cls
    return cls


def get_renderer(format_name):
    """Return a ViewRenderer instance for the given format."""
    cls = _REGISTRY.get(format_name)
    if cls is None:
        raise ValueError("Unknown view format: %s" % format_name)
    return cls()


def get_available_formats():
    """Return list of registered format names."""
    return sorted(_REGISTRY.keys())


class ViewRenderer:
    """Base class for all view renderers."""

    format_name = None

    def render(self, answer_data, request_options):
        """
        Render answer_data in this view's format.

        Returns:
            (str, bool): tuple of (rendered_output, found_flag)
        """
        raise NotImplementedError


def _is_found(answers):
    """Check if all answers were found (none are 'unknown' type)."""
    return all(a.get("topic_type") != "unknown" for a in answers)


@register_view
class AnsiViewRenderer(ViewRenderer):
    """Renders answer_data as ANSI terminal output."""

    format_name = "ansi"

    def render(self, answer_data, request_options):
        return frontend.ansi.visualize(answer_data, request_options)


@register_view
class PlainTextViewRenderer(ViewRenderer):
    """Renders as plain text (ANSI with escape codes stripped)."""

    format_name = "text"

    def render(self, answer_data, request_options):
        opts = dict(request_options or {})
        opts["no-terminal"] = True
        return frontend.ansi.visualize(answer_data, opts)


@register_view
class RawViewRenderer(ViewRenderer):
    """Returns unprocessed answer text with minimal section headers."""

    format_name = "raw"

    def render(self, answer_data, request_options):
        answers = answer_data.get("answers", [])
        multiple = len(answers) > 1
        result = ""
        for answer_dict in answers:
            topic = answer_dict.get("topic", "")
            if multiple and topic != "LIMITED":
                result += "#[%s:%s]\n" % (
                    answer_dict.get("topic_type", ""),
                    topic,
                )
            result += answer_dict.get("answer", "")
        result = result.strip("\n") + "\n"
        return result, _is_found(answers)


@register_view
class JsonViewRenderer(ViewRenderer):
    """Returns structured JSON output."""

    format_name = "json"

    def render(self, answer_data, request_options):
        answers = answer_data.get("answers", [])
        output = {
            "query": answer_data.get("query", ""),
            "keyword": answer_data.get("keyword"),
            "answers": [
                {k: v for k, v in a.items() if k != "cache"}
                for a in answers
            ],
        }
        return json.dumps(output, indent=4), _is_found(answers)


def _ansi2html(ansi_text):
    """Convert ANSI text to HTML using ansi2html.sh."""
    cmd = [
        "bash",
        CONFIG["path.internal.ansi2html"],
        "--palette=solarized",
        "--bg=dark",
    ]
    try:
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    except FileNotFoundError:
        error("ansi2html not found: %s" % cmd)
        raise
    stdout, stderr = proc.communicate(ansi_text.encode("utf-8"))
    if proc.returncode != 0:
        error((stdout + stderr).decode("utf-8"))
    return stdout.decode("utf-8")


def _extract_pre_content(html):
    """Extract content between <pre> and </pre> tags."""
    match = re.search(r"<pre[^>]*>(.*?)</pre>", html, re.DOTALL)
    if match:
        return match.group(1)
    return html


def _extract_head(html):
    """Extract <head> content for reuse as page template."""
    match = re.search(r"<head>(.*?)</head>", html, re.DOTALL)
    if match:
        return match.group(1)
    return ""


@register_view
class HtmlViewRenderer(ViewRenderer):
    """
    Enhanced HTML renderer with per-answer blocks,
    filtering, collapsing, and client-side view switching.
    """

    format_name = "html"

    def render(self, answer_data, request_options):
        request_options = request_options or {}
        query = answer_data.get("query", "")
        answers = answer_data.get("answers", [])
        topics_list = answer_data.get("topics_list", [])
        found = _is_found(answers)

        highlight = not bool(request_options.get("no-terminal"))
        color_style = request_options.get("style", "")
        if color_style not in CONFIG.get("frontend.styles", []):
            color_style = ""
        multiple_answers = len(answers) > 1

        # Render each answer block individually
        head_content = ""
        answer_blocks_html = []
        for answer_dict in answers:
            ansi_block = frontend.ansi.render_answer_block(
                answer_dict,
                highlight=highlight,
                color_style=color_style,
                multiple_answers=False,  # we handle headers in HTML
                request_options=request_options,
            )
            full_html = _ansi2html(ansi_block)
            if not head_content:
                head_content = _extract_head(full_html)
            pre_content = _extract_pre_content(full_html)
            block_html = self._build_answer_block(
                answer_dict, pre_content, query, request_options
            )
            answer_blocks_html.append(block_html)

        # If no answers, still get head from minimal conversion
        if not head_content:
            full_html = _ansi2html(" ")
            head_content = _extract_head(full_html)

        # Build JSON data for client-side view switching
        json_data = {
            "query": query,
            "keyword": answer_data.get("keyword"),
            "answers": [
                {k: v for k, v in a.items() if k != "cache"}
                for a in answers
            ],
        }

        page = self._build_page(
            query=query,
            head_content=head_content,
            answer_blocks_html="\n".join(answer_blocks_html),
            json_data=json.dumps(json_data),
            topics_list=topics_list,
            answers=answers,
            request_options=request_options,
        )
        return page, found

    def _build_answer_block(self, answer_dict, pre_content, query, request_options):
        """Build a single answer block with header, metadata, and content."""
        topic = answer_dict.get("topic", "")
        topic_type = answer_dict.get("topic_type", "")
        filetype = answer_dict.get("filetype", "")
        answer_id = answer_dict.get("answer_id", "%s:%s" % (topic_type, topic))

        # Edit button
        edit_html = ""
        if answer_dict.get("editable"):
            edit_url = answer_dict.get("edit_url", "")
            if edit_url:
                edit_html = (
                    ' <a class="edit-btn" href="%s"'
                    ' style="color:cyan;text-decoration:none">[edit]</a>'
                ) % edit_url

        # GitHub source button
        github_html = sources.get_github_button_html(topic_type)
        if github_html:
            github_html = ' <span class="source-btn">%s</span>' % github_html

        # Section label
        label = topic_type
        if topic and topic != "LIMITED":
            label = "%s:%s" % (topic_type, topic)

        return (
            '<div class="answer-block" data-topic-type="%(topic_type)s"'
            ' data-filetype="%(filetype)s" data-answer-id="%(answer_id)s">\n'
            '  <div class="answer-header" onclick="toggleCollapse(this)">\n'
            '    <span class="collapse-icon">&#9660;</span>\n'
            '    <span class="answer-source">%(label)s</span>\n'
            '    %(edit_html)s%(github_html)s\n'
            '  </div>\n'
            '  <div class="answer-content"><pre>%(pre_content)s</pre></div>\n'
            '</div>'
        ) % {
            "topic_type": topic_type,
            "filetype": filetype,
            "answer_id": answer_id,
            "label": label,
            "edit_html": edit_html,
            "github_html": github_html,
            "pre_content": pre_content,
        }

    def _build_page(self, query, head_content, answer_blocks_html,
                    json_data, topics_list, answers, request_options):
        """Assemble the complete HTML page."""

        title = "cheat.sh/%s" % query

        # Topic datalist for autocomplete
        topic_options = "\n".join(
            "<option value='%s'></option>" % x for x in topics_list
        )
        topic_list_html = '<datalist id="topics">%s</datalist>' % topic_options

        # Search form
        submit_button = (
            '<input type="submit" style="position: absolute;'
            ' left: -9999px; width: 1px; height: 1px;" tabindex="-1" />'
        )
        curl_line = "<span class='pre'>$ curl cheat.sh/</span>"
        display_query = "" if query == ":firstpage" else query
        form_html = (
            '<form action="/" method="GET">'
            "%(submit)s%(curl)s"
            '<input type="text" value="%(query)s" name="topic"'
            ' list="topics" autofocus autocomplete="off"/>'
            "%(datalist)s"
            "</form>"
        ) % {
            "submit": submit_button,
            "curl": curl_line,
            "query": display_query,
            "datalist": topic_list_html,
        }

        # Build filter controls from answer metadata
        topic_types = sorted(set(
            a.get("topic_type", "") for a in answers if a.get("topic_type")
        ))
        filetypes = sorted(set(
            a.get("filetype", "") for a in answers if a.get("filetype")
        ))

        filter_type_html = ""
        for tt in topic_types:
            filter_type_html += (
                '<label><input type="checkbox" data-filter="topic_type"'
                ' value="%s" checked onchange="applyFilters()"/> %s</label>\n'
            ) % (tt, tt)

        filter_filetype_html = ""
        for ft in filetypes:
            filter_filetype_html += (
                '<label><input type="checkbox" data-filter="filetype"'
                ' value="%s" checked onchange="applyFilters()"/> %s</label>\n'
            ) % (ft, ft)

        toolbar_html = self._build_toolbar(filter_type_html, filter_filetype_html)

        # Social buttons
        social_html = ""
        if not request_options.get("quiet"):
            repository_button = ""
            if len(answers) == 1:
                repository_button = sources.get_github_button_html(
                    answers[0].get("topic_type", "")
                )
            social_html = (
                TWITTER_BUTTON
                + GITHUB_BUTTON
                + repository_button
                + GITHUB_BUTTON_FOOTER
            )

        return (
            '<!DOCTYPE html>\n'
            '<html>\n'
            '<head>\n'
            '  <title>%(title)s</title>\n'
            '  %(head_content)s\n'
            '  <link rel="stylesheet" href="/files/style.css" />\n'
            '  %(inline_css)s\n'
            '</head>\n'
            '<body>\n'
            '  <div id="search-bar">%(form)s</div>\n'
            '  %(toolbar)s\n'
            '  <div id="answers" data-view="html">\n'
            '    %(blocks)s\n'
            '  </div>\n'
            '  <div id="raw-view" class="view-container hidden"><pre id="raw-content"></pre></div>\n'
            '  <div id="text-view" class="view-container hidden"><pre id="text-content"></pre></div>\n'
            '  <div id="json-view" class="view-container hidden"><pre id="json-content"></pre></div>\n'
            '  <script id="answer-data" type="application/json">%(json_data)s</script>\n'
            '  %(social)s\n'
            '  %(inline_js)s\n'
            '</body>\n'
            '</html>\n'
        ) % {
            "title": title,
            "head_content": head_content,
            "inline_css": self._inline_css(),
            "form": form_html,
            "toolbar": toolbar_html,
            "blocks": answer_blocks_html,
            "json_data": json_data,
            "social": social_html,
            "inline_js": self._inline_js(),
        }

    def _build_toolbar(self, filter_type_html, filter_filetype_html):
        """Build the toolbar with view switcher and filter controls."""

        filter_section = ""
        if filter_type_html or filter_filetype_html:
            source_part = ""
            if filter_type_html:
                source_part = (
                    '<span class="filter-group">'
                    '<span class="filter-label">Source:</span>\n%s</span>'
                ) % filter_type_html
            filetype_part = ""
            if filter_filetype_html:
                filetype_part = (
                    '<span class="filter-group">'
                    '<span class="filter-label">Type:</span>\n%s</span>'
                ) % filter_filetype_html
            filter_section = (
                '<div id="filters">%s%s</div>' % (source_part, filetype_part)
            )

        return (
            '<div id="toolbar">\n'
            '  <div id="view-switcher">\n'
            '    <button class="view-btn active" data-view="html" onclick="switchView(\'html\')">HTML</button>\n'
            '    <button class="view-btn" data-view="raw" onclick="switchView(\'raw\')">Raw</button>\n'
            '    <button class="view-btn" data-view="text" onclick="switchView(\'text\')">Text</button>\n'
            '    <button class="view-btn" data-view="json" onclick="switchView(\'json\')">JSON</button>\n'
            '  </div>\n'
            '  %(filters)s\n'
            '  <div id="collapse-controls">\n'
            '    <button onclick="expandAll()">Expand All</button>\n'
            '    <button onclick="collapseAll()">Collapse All</button>\n'
            '  </div>\n'
            '</div>'
        ) % {"filters": filter_section}

    def _inline_css(self):
        """Return inline CSS for toolbar, filters, and answer blocks."""
        return """<style>
#toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 10px;
    background: #1a1a1a;
    border-bottom: 1px solid #333;
    flex-wrap: wrap;
    font-family: "DejaVu Sans Mono", Menlo, monospace;
    font-size: 75%;
}
#view-switcher {
    display: flex;
    gap: 2px;
}
.view-btn {
    background: #2a2a2a;
    color: #999;
    border: 1px solid #444;
    padding: 3px 10px;
    cursor: pointer;
    font-family: inherit;
    font-size: inherit;
}
.view-btn:hover {
    background: #3a3a3a;
    color: #ccc;
}
.view-btn.active {
    background: #444;
    color: #fff;
    border-color: #666;
}
#filters {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
}
.filter-group {
    display: flex;
    align-items: center;
    gap: 4px;
}
.filter-label {
    color: #888;
    margin-right: 2px;
}
#filters label {
    color: #aaa;
    cursor: pointer;
    white-space: nowrap;
}
#filters input[type="checkbox"] {
    margin-right: 2px;
}
#collapse-controls button {
    background: #2a2a2a;
    color: #999;
    border: 1px solid #444;
    padding: 3px 8px;
    cursor: pointer;
    font-family: inherit;
    font-size: inherit;
}
#collapse-controls button:hover {
    background: #3a3a3a;
    color: #ccc;
}
.answer-block {
    margin-bottom: 2px;
}
.answer-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: #1c1c1c;
    border-left: 3px solid #444;
    cursor: pointer;
    font-family: "DejaVu Sans Mono", Menlo, monospace;
    font-size: 75%;
    color: #aaa;
    user-select: none;
}
.answer-header:hover {
    background: #252525;
    border-left-color: #888;
}
.collapse-icon {
    transition: transform 0.15s;
    font-size: 10px;
}
.answer-block.collapsed .collapse-icon {
    transform: rotate(-90deg);
}
.answer-source {
    color: #8abeb7;
}
.edit-btn {
    margin-left: auto;
}
.answer-content pre {
    margin: 0;
    padding: 4px 0;
}
.answer-block.collapsed .answer-content {
    display: none;
}
.hidden {
    display: none;
}
.view-container pre {
    margin: 0;
    padding: 10px;
    background: #002b36;
    color: #839496;
    font-family: "DejaVu Sans Mono", Menlo, monospace;
    font-size: 75%;
}
</style>"""

    def _inline_js(self):
        """Return inline JavaScript for view switching, filtering, and collapsing."""
        return """<script>
(function() {
    var answerData = JSON.parse(
        document.getElementById('answer-data').textContent
    );

    // View switching
    window.switchView = function(viewName) {
        // Update active button
        var btns = document.querySelectorAll('.view-btn');
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle('active', btns[i].getAttribute('data-view') === viewName);
        }

        // Toggle containers
        var answersDiv = document.getElementById('answers');
        var rawDiv = document.getElementById('raw-view');
        var textDiv = document.getElementById('text-view');
        var jsonDiv = document.getElementById('json-view');

        answersDiv.classList.toggle('hidden', viewName !== 'html');
        rawDiv.classList.toggle('hidden', viewName !== 'raw');
        textDiv.classList.toggle('hidden', viewName !== 'text');
        jsonDiv.classList.toggle('hidden', viewName !== 'json');

        // Populate on demand
        if (viewName === 'raw') {
            var raw = '';
            var answers = answerData.answers || [];
            for (var i = 0; i < answers.length; i++) {
                if (answers.length > 1 && answers[i].topic !== 'LIMITED') {
                    raw += '#[' + answers[i].topic_type + ':' + answers[i].topic + ']\\n';
                }
                raw += answers[i].answer || '';
            }
            document.getElementById('raw-content').textContent = raw;
        } else if (viewName === 'text') {
            var text = '';
            var answers = answerData.answers || [];
            for (var i = 0; i < answers.length; i++) {
                if (answers.length > 1 && answers[i].topic !== 'LIMITED') {
                    text += '#[' + answers[i].topic_type + ':' + answers[i].topic + ']\\n';
                }
                text += answers[i].answer || '';
            }
            document.getElementById('text-content').textContent = text;
        } else if (viewName === 'json') {
            document.getElementById('json-content').textContent =
                JSON.stringify(answerData, null, 4);
        }
    };

    // Filtering
    window.applyFilters = function() {
        var checkboxes = document.querySelectorAll('#filters input[type="checkbox"]');
        var allowed = {};
        for (var i = 0; i < checkboxes.length; i++) {
            var cb = checkboxes[i];
            var filterType = cb.getAttribute('data-filter');
            if (!allowed[filterType]) allowed[filterType] = {};
            if (cb.checked) {
                allowed[filterType][cb.value] = true;
            }
        }

        var blocks = document.querySelectorAll('.answer-block');
        for (var i = 0; i < blocks.length; i++) {
            var block = blocks[i];
            var show = true;
            if (allowed.topic_type) {
                var tt = block.getAttribute('data-topic-type');
                if (tt && !allowed.topic_type[tt]) show = false;
            }
            if (allowed.filetype && Object.keys(allowed.filetype).length > 0) {
                var ft = block.getAttribute('data-filetype');
                if (ft && !allowed.filetype[ft]) show = false;
            }
            block.classList.toggle('hidden', !show);
        }
    };

    // Collapse/Expand
    window.toggleCollapse = function(header) {
        var block = header.parentElement;
        block.classList.toggle('collapsed');
    };

    window.expandAll = function() {
        var blocks = document.querySelectorAll('.answer-block');
        for (var i = 0; i < blocks.length; i++) {
            blocks[i].classList.remove('collapsed');
        }
    };

    window.collapseAll = function() {
        var blocks = document.querySelectorAll('.answer-block');
        for (var i = 0; i < blocks.length; i++) {
            blocks[i].classList.add('collapsed');
        }
    };
})();
</script>"""

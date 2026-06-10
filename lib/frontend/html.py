"""
Multi-view HTML frontend.

Provides a unified display layer where the same answer_data can be viewed
as rendered (ANSI-to-HTML), raw ANSI, plain text, or JSON — switchable
client-side without server round-trips.  Includes filtering by source
(topic_type) and filetype, collapsible answer sections, copy-to-clipboard,
and preserves the edit button and GitHub source information.

Exports:
    visualize(answer_data, request_options, default_view="rendered")
"""

import html as html_mod
import json
import re
from subprocess import Popen, PIPE

import sys
import os

MYDIR = os.path.abspath(os.path.join(__file__, "..", ".."))
sys.path.append("%s/lib/" % MYDIR)

# pylint: disable=wrong-import-position
from config import CONFIG
from globals import error
from buttons import TWITTER_BUTTON, GITHUB_BUTTON, GITHUB_BUTTON_FOOTER
import frontend.ansi

# ---------------------------------------------------------------------------
# GitHub repository mapping (for footer source buttons)
# ---------------------------------------------------------------------------

GITHUB_REPOSITORY = {
    "late.nz": "chubin/late.nz",
    "cheat.sheets": "chubin/cheat.sheets",
    "cheat.sheets dir": "chubin/cheat.sheets",
    "tldr": "tldr-pages/tldr",
    "cheat": "chrisallenlane/cheat",
    "learnxiny": "adambard/learnxinyminutes-docs",
    "internal": "",
    "search": "",
    "unknown": "",
}


# ===========================================================================
# Public entry point
# ===========================================================================

def visualize(answer_data, request_options, default_view="rendered"):
    """
    Render *answer_data* as a multi-view HTML page.

    ``default_view`` selects which view is active on page load:
    one of ``"rendered"``, ``"ansi"``, ``"text"``, ``"json"``.
    """
    query = answer_data["query"]
    answers = answer_data["answers"]
    topics_list = answer_data.get("topics_list", [])
    request_options = request_options or {}

    found = True

    # -- Collect unique filter values ------------------------------------
    topic_types = sorted(
        set(a["topic_type"] for a in answers if a.get("topic_type"))
    )
    filetypes = sorted(
        set(
            a.get("filetype", "")
            for a in answers
            if a.get("filetype")
        )
    )

    # -- Determine editability per answer --------------------------------
    editable_answers = [
        i
        for i, a in enumerate(answers)
        if a.get("topic_type") == "cheat.sheets"
    ]

    # -- Render each answer in all view formats --------------------------
    rendered_sections = []
    ansi_sections = []
    text_sections = []

    for idx, answer_dict in enumerate(answers):
        is_editable = idx in editable_answers
        single_data = {
            "query": query,
            "keyword": answer_data.get("keyword"),
            "answers": [answer_dict],
        }
        ansi_output, ans_found = frontend.ansi.visualize(
            single_data, request_options
        )
        found = found and ans_found

        # Rendered (HTML via ansi2html)
        rendered_html = _html_wrapper(ansi_output)
        rendered_html = _strip_pre_wrapper(rendered_html)

        # Raw ANSI (will be HTML-escaped)
        ansi_text = ansi_output

        # Plain text (ANSI escape codes stripped)
        plain_text = frontend.ansi.remove_ansi(ansi_output)

        section = _make_section_html(
            answer_dict,
            rendered_html,
            ansi_text,
            plain_text,
            idx,
            is_editable,
            query,
        )
        rendered_sections.append(section["rendered"])
        ansi_sections.append(section["ansi"])
        text_sections.append(section["text"])

    # -- JSON view (whole answer_data) -----------------------------------
    json_text = html_mod.escape(
        json.dumps(answer_data, indent=2, ensure_ascii=False)
    )

    # -- Build toolbar / search / footer ---------------------------------
    toolbar = _toolbar_html(topic_types, filetypes)
    search_html = _search_form_html(query, topics_list)
    footer = _footer_html(answers, request_options)

    # -- Assemble full page ----------------------------------------------
    page = _build_page(
        query,
        toolbar,
        search_html,
        rendered_sections,
        ansi_sections,
        text_sections,
        json_text,
        footer,
        request_options,
        default_view,
    )
    return page, found


# ===========================================================================
# Rendering helpers
# ===========================================================================

def _html_wrapper(data):
    """Convert ANSI text *data* to HTML via ``ansi2html.sh``."""
    cmd = [
        "bash",
        CONFIG["path.internal.ansi2html"],
        "--palette=solarized",
        "--bg=dark",
    ]
    try:
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    except FileNotFoundError:
        print("ERROR: %s" % cmd)
        raise
    data_bytes = data.encode("utf-8")
    stdout, stderr = proc.communicate(data_bytes)
    if proc.returncode != 0:
        error((stdout + stderr).decode("utf-8"))
    return stdout.decode("utf-8")


def _strip_pre_wrapper(html_text):
    """Remove the outer ``<pre>...</pre>`` wrapper from *ansi2html* output."""
    html_text = re.sub(r"<pre[^>]*>", "", html_text, count=1, flags=re.IGNORECASE)
    # Remove the *last* </pre>
    idx = html_text.rfind("</pre>")
    if idx != -1:
        html_text = html_text[:idx] + html_text[idx + len("</pre>"):]
    return html_text


def _make_section_html(
    answer_dict, rendered_html, ansi_text, plain_text,
    idx, editable, query,
):
    """Build the three per-view section HTML blocks for one answer."""
    topic = answer_dict.get("topic", "")
    topic_type = answer_dict.get("topic_type", "")
    filetype = answer_dict.get("filetype", "")
    fmt = answer_dict.get("format", "")

    is_limited = topic == "LIMITED"
    section_class = "cheat-section"
    if is_limited:
        section_class += " cheat-section-limited"

    data_attrs = (
        'data-topic-type="%s" data-filetype="%s" data-format="%s"'
        % (
            html_mod.escape(topic_type),
            html_mod.escape(filetype),
            html_mod.escape(fmt),
        )
    )

    # -- Header badges ---------------------------------------------------
    badges = ""
    if topic_type:
        badges += (
            '<span class="cheat-badge cheat-badge-source">%s</span>'
            % html_mod.escape(topic_type)
        )
    if topic and not is_limited:
        badges += (
            '<span class="cheat-badge cheat-badge-topic">%s</span>'
            % html_mod.escape(topic)
        )
    if filetype:
        badges += (
            '<span class="cheat-badge cheat-badge-filetype">%s</span>'
            % html_mod.escape(filetype)
        )

    # -- Edit button (rendered view only) --------------------------------
    edit_html = ""
    if editable and topic_type == "cheat.sheets":
        edit_query = query
        if "/" in edit_query:
            edit_query = "_" + edit_query
        edit_link = (
            "https://github.com/chubin/cheat.sheets/edit/master/sheets/"
            + edit_query
        )
        edit_html = (
            '<a href="%s" class="cheat-edit-btn" '
            'target="_blank" rel="noopener">[edit]</a>'
            % edit_link
        )

    # -- Toggle arrow (rendered view only) -------------------------------
    toggle_btn = (
        '<button class="cheat-toggle-btn" onclick="toggleSection(this)" '
        'title="Collapse/expand section">'
        '<span class="cheat-toggle-arrow">&#9660;</span></button>'
    )

    # -- Build sections for each view -----------------------------------
    rendered = (
        '<div class="%s" %s data-idx="%d">'
        '<div class="cheat-section-header">'
        "%s%s%s"
        "</div>"
        '<div class="cheat-section-content">%s</div>'
        "</div>"
    ) % (
        section_class,
        data_attrs,
        idx,
        toggle_btn,
        badges,
        edit_html,
        rendered_html,
    )

    ansi_escaped = html_mod.escape(ansi_text)
    ansi = (
        '<div class="%s" %s data-idx="%d">'
        '<div class="cheat-section-header">'
        "<span>%s</span>"
        "</div>"
        '<div class="cheat-section-content">'
        "<pre>%s</pre>"
        "</div>"
        "</div>"
    ) % (
        section_class,
        data_attrs,
        idx,
        html_mod.escape("%s:%s" % (topic_type, topic) if topic_type else topic),
        ansi_escaped,
    )

    plain_escaped = html_mod.escape(plain_text)
    text = (
        '<div class="%s" %s data-idx="%d">'
        '<div class="cheat-section-header">'
        "<span>%s</span>"
        "</div>"
        '<div class="cheat-section-content">'
        "<pre>%s</pre>"
        "</div>"
        "</div>"
    ) % (
        section_class,
        data_attrs,
        idx,
        html_mod.escape("%s:%s" % (topic_type, topic) if topic_type else topic),
        plain_escaped,
    )

    return {"rendered": rendered, "ansi": ansi, "text": text}


# ===========================================================================
# Toolbar / search / footer
# ===========================================================================

def _toolbar_html(topic_types, filetypes):
    """Build the toolbar with view switcher, filters, and copy button."""

    # View buttons
    view_btns = (
        '<button class="cheat-view-btn active" '
        'onclick="switchView(\'rendered\')">Rendered</button>'
        '<button class="cheat-view-btn" '
        'onclick="switchView(\'ansi\')">ANSI</button>'
        '<button class="cheat-view-btn" '
        'onclick="switchView(\'text\')">Text</button>'
        '<button class="cheat-view-btn" '
        'onclick="switchView(\'json\')">JSON</button>'
    )

    # Source filter
    source_filter = ""
    if len(topic_types) > 1:
        opts = '<option value="">All sources</option>'
        for tt in topic_types:
            opts += '<option value="%s">%s</option>' % (
                html_mod.escape(tt),
                html_mod.escape(tt),
            )
        source_filter = (
            '<select class="cheat-filter-select" '
            'onchange="applyFilters()">%s</select>' % opts
        )

    # Filetype filter
    filetype_filter = ""
    if len(filetypes) > 1:
        opts = '<option value="">All types</option>'
        for ft in filetypes:
            opts += '<option value="%s">%s</option>' % (
                html_mod.escape(ft),
                html_mod.escape(ft),
            )
        filetype_filter = (
            '<select class="cheat-filter-select" '
            'onchange="applyFilters()">%s</select>' % opts
        )

    # Copy button
    copy_btn = (
        '<button class="cheat-copy-btn" onclick="copySection(this)" '
        'title="Copy section to clipboard">Copy</button>'
    )

    return (
        '<div class="cheat-toolbar">'
        '<div class="cheat-view-buttons">%s</div>'
        '<div class="cheat-filter-controls">%s%s%s</div>'
        "</div>"
    ) % (view_btns, source_filter, filetype_filter, copy_btn)


def _search_form_html(query, topics_list):
    """Build the search form (unchanged functionality from the original)."""
    submit_button = (
        '<input type="submit" style="position:absolute;'
        'left:-9999px;width:1px;height:1px;" tabindex="-1" />'
    )
    topic_list = '<datalist id="topics">%s</datalist>' % (
        "\n".join(
            "<option value='%s'></option>" % x for x in topics_list
        )
    )
    curl_line = "<span class='pre'>$ curl cheat.sh/</span>"
    form_query = query if query != ":firstpage" else ""
    form_html = (
        '<form action="/" method="GET">'
        "%s%s"
        "<input"
        ' type="text" value="%s" name="topic"'
        ' list="topics" autofocus autocomplete="off"/>'
        "%s"
        "</form>"
    ) % (submit_button, curl_line, html_mod.escape(form_query), topic_list)
    return form_html


def _footer_html(answers, request_options):
    """Build the footer with GitHub / Twitter buttons (respects ``quiet``)."""
    if request_options.get("quiet"):
        return ""

    repository_button = ""
    if len(answers) == 1:
        repository_button = _github_button_html(answers[0]["topic_type"])

    return (
        '<div class="cheat-footer">'
        "%s%s%s%s"
        "</div>"
    ) % (
        TWITTER_BUTTON,
        GITHUB_BUTTON,
        repository_button,
        GITHUB_BUTTON_FOOTER,
    )


def _github_button_html(topic_type):
    """Generate a GitHub star button for the given *topic_type*."""
    full_name = GITHUB_REPOSITORY.get(topic_type, "")
    if not full_name:
        return ""
    short_name = full_name.split("/", 1)[1]
    return (
        '<a aria-label="Star %(full_name)s on GitHub"'
        ' data-count-aria-label="# stargazers on GitHub"'
        ' data-count-api="/repos/%(full_name)s#stargazers_count"'
        ' data-count-href="/%(full_name)s/stargazers"'
        ' data-icon="octicon-star"'
        ' href="https://github.com/%(full_name)s"'
        '  class="github-button">%(short_name)s</a>'
    ) % {"full_name": full_name, "short_name": short_name}


# ===========================================================================
# Full page assembly
# ===========================================================================

def _build_page(
    query,
    toolbar,
    search_html,
    rendered_sections,
    ansi_sections,
    text_sections,
    json_text,
    footer,
    request_options,
    default_view,
):
    """Assemble the complete HTML document."""

    title = "cheat.sh/%s" % query
    rendered_content = "\n".join(rendered_sections)
    ansi_content = "\n".join(ansi_sections)
    text_content = "\n".join(text_sections)

    active_view = default_view if default_view in (
        "rendered", "ansi", "text", "json"
    ) else "rendered"

    view_hidden = {
        "rendered": "",
        "ansi": "",
        "text": "",
        "json": "",
    }
    for v in view_hidden:
        if v != active_view:
            view_hidden[v] = " hidden"

    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>%s</title>\n"
        "<style>\n%s\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="cheat-multiview">\n'
        "%s\n"
        '<div class="cheat-search">%s</div>\n'
        '<div class="cheat-view" id="view-rendered"%s>\n'
        '<pre>%s</pre>\n'
        "</div>\n"
        '<div class="cheat-view" id="view-ansi"%s>\n'
        "%s\n"
        "</div>\n"
        '<div class="cheat-view" id="view-text"%s>\n'
        "%s\n"
        "</div>\n"
        '<div class="cheat-view" id="view-json"%s>\n'
        '<div class="cheat-section" data-topic-type="json" '
        'data-filetype="" data-format="json">\n'
        '<div class="cheat-section-content"><pre>%s</pre></div>\n'
        "</div>\n"
        "</div>\n"
        "%s\n"
        "</div>\n"
        "<script>\n%s\n</script>\n"
        "</body>\n"
        "</html>"
    ) % (
        html_mod.escape(title),
        CSS,
        toolbar,
        search_html,
        view_hidden["rendered"],
        rendered_content,
        view_hidden["ansi"],
        ansi_content,
        view_hidden["text"],
        text_content,
        view_hidden["json"],
        json_text,
        footer,
        JS,
    )


# ===========================================================================
# Embedded CSS
# ===========================================================================

CSS = """\
body {
    background: #002b36;
    color: #839496;
    margin: 0;
    padding: 0;
}
.pre, pre {
    font-family: "DejaVu Sans Mono", Menlo, "Lucida Sans Typewriter",
                 "Lucida Console", monaco, "Bitstream Vera Sans Mono", monospace;
    font-size: 75%;
}
input[type="text"] {
    border: none;
    background: transparent;
    color: #839496;
    outline: none;
}

/* ---- Toolbar ---- */
.cheat-toolbar {
    position: sticky;
    top: 0;
    z-index: 100;
    background: #073642;
    padding: 8px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    border-bottom: 1px solid #586e75;
}
.cheat-view-buttons {
    display: flex;
    gap: 2px;
}
.cheat-view-btn {
    background: #586e75;
    color: #eee8d5;
    border: none;
    padding: 5px 14px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    border-radius: 3px;
    transition: background 0.15s;
}
.cheat-view-btn:hover {
    background: #657b83;
}
.cheat-view-btn.active {
    background: #268bd2;
    color: #fdf6e3;
}
.cheat-filter-controls {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-left: auto;
}
.cheat-filter-select {
    background: #586e75;
    color: #eee8d5;
    border: 1px solid #657b83;
    padding: 4px 8px;
    font-family: inherit;
    font-size: 12px;
    border-radius: 3px;
    cursor: pointer;
}
.cheat-copy-btn {
    background: #586e75;
    color: #eee8d5;
    border: none;
    padding: 5px 12px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    border-radius: 3px;
    transition: background 0.15s;
}
.cheat-copy-btn:hover {
    background: #657b83;
}

/* ---- Search form ---- */
.cheat-search {
    padding: 8px 16px 0;
}
.cheat-search form {
    position: relative;
    display: flex;
    align-items: center;
    gap: 4px;
}

/* ---- Answer sections ---- */
.cheat-section {
    margin: 0;
    border-bottom: 1px solid #073642;
}
.cheat-section-limited {
    background: rgba(181, 137, 0, 0.1);
}
.cheat-section-header {
    background: #073642;
    padding: 5px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: default;
    flex-wrap: wrap;
    min-height: 28px;
}
.cheat-section-content {
    padding: 0;
}
.cheat-section-content pre {
    margin: 0;
    padding: 8px 16px;
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-x: auto;
}

/* ---- Badges ---- */
.cheat-badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-family: "DejaVu Sans Mono", Menlo, monospace;
    line-height: 1.6;
}
.cheat-badge-source {
    background: #268bd2;
    color: #fdf6e3;
}
.cheat-badge-topic {
    background: #2aa198;
    color: #fdf6e3;
}
.cheat-badge-filetype {
    background: #b58900;
    color: #fdf6e3;
}

/* ---- Edit / Toggle ---- */
.cheat-edit-btn {
    color: #2aa198;
    font-family: "DejaVu Sans Mono", Menlo, monospace;
    font-size: 11px;
    text-decoration: none;
    margin-left: auto;
}
.cheat-edit-btn:hover {
    color: #268bd2;
    text-decoration: underline;
}
.cheat-toggle-btn {
    background: none;
    border: none;
    color: #586e75;
    cursor: pointer;
    padding: 0 4px;
    font-size: 10px;
    line-height: 1;
    transition: color 0.15s;
}
.cheat-toggle-btn:hover {
    color: #93a1a1;
}

/* ---- JSON view ---- */
#view-json .cheat-section-content pre {
    background: #00202b;
    color: #93a1a1;
}

/* ---- Footer ---- */
.cheat-footer {
    padding: 12px 16px;
    text-align: center;
}
"""


# ===========================================================================
# Embedded JavaScript
# ===========================================================================

JS = """\
(function() {
    'use strict';

    /* ---- View switching ---- */
    window.switchView = function(viewName) {
        var views = document.querySelectorAll('.cheat-view');
        for (var i = 0; i < views.length; i++) {
            views[i].hidden = true;
        }
        var target = document.getElementById('view-' + viewName);
        if (target) target.hidden = false;

        var btns = document.querySelectorAll('.cheat-view-btn');
        for (var j = 0; j < btns.length; j++) {
            btns[j].classList.remove('active');
        }
        if (event && event.target && event.target.classList) {
            event.target.classList.add('active');
        }
        setViewParam(viewName);
        applyFilters();
    };

    /* ---- Filtering ---- */
    window.applyFilters = function() {
        var selects = document.querySelectorAll('.cheat-filter-select');
        var sourceVal = '';
        var filetypeVal = '';
        for (var i = 0; i < selects.length; i++) {
            var txt = selects[i].options[0] ? selects[i].options[0].textContent : '';
            if (txt.indexOf('source') !== -1) sourceVal = selects[i].value;
            else if (txt.indexOf('type') !== -1) filetypeVal = selects[i].value;
        }

        var sections = document.querySelectorAll('.cheat-section');
        for (var k = 0; k < sections.length; k++) {
            var s = sections[k];
            var show = true;
            if (sourceVal && s.getAttribute('data-topic-type') !== sourceVal) {
                show = false;
            }
            if (filetypeVal && s.getAttribute('data-filetype') !== filetypeVal) {
                show = false;
            }
            s.style.display = show ? '' : 'none';
        }
    };

    /* ---- Collapse / expand ---- */
    window.toggleSection = function(btn) {
        var section = btn.closest('.cheat-section');
        if (!section) return;
        var content = section.querySelector('.cheat-section-content');
        var arrow = btn.querySelector('.cheat-toggle-arrow');
        if (!content) return;
        if (content.style.display === 'none') {
            content.style.display = '';
            if (arrow) arrow.innerHTML = '&#9660;';
        } else {
            content.style.display = 'none';
            if (arrow) arrow.innerHTML = '&#9654;';
        }
    };

    /* ---- Copy to clipboard ---- */
    window.copySection = function(btn) {
        var viewName = 'text';
        var views = document.querySelectorAll('.cheat-view');
        for (var i = 0; i < views.length; i++) {
            if (!views[i].hidden) {
                viewName = views[i].id.replace('view-', '');
                break;
            }
        }
        var targetView = document.getElementById('view-' + viewName);
        if (!targetView) return;

        var sections = targetView.querySelectorAll('.cheat-section');
        var visibleSections = [];
        for (var j = 0; j < sections.length; j++) {
            if (sections[j].style.display !== 'none') {
                visibleSections.push(sections[j]);
            }
        }
        if (visibleSections.length === 0) return;

        var text = '';
        for (var k = 0; k < visibleSections.length; k++) {
            var content = visibleSections[k].querySelector('.cheat-section-content');
            if (content) {
                var pre = content.querySelector('pre');
                text += (pre ? pre.textContent : content.textContent) + '\\n';
            }
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text.trim()).then(function() {
                btn.textContent = 'Copied!';
                setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
            }, function() {
                btn.textContent = 'Failed';
                setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
            });
        } else {
            var ta = document.createElement('textarea');
            ta.value = text.trim();
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); btn.textContent = 'Copied!'; }
            catch(e) { btn.textContent = 'Failed'; }
            document.body.removeChild(ta);
            setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
        }
    };

    /* ---- URL state ---- */
    function setViewParam(view) {
        try {
            var url = new URL(window.location);
            url.searchParams.set('view', view);
            window.history.replaceState({}, '', url);
        } catch(e) { /* ignore in older browsers */ }
    }

    /* ---- Init: read ?view= param on load ---- */
    try {
        var params = new URLSearchParams(window.location.search);
        var initView = params.get('view');
        if (initView) {
            var target = document.getElementById('view-' + initView);
            if (target) {
                switchView(initView);
            }
        }
    } catch(e) { /* ignore */ }

})();
"""

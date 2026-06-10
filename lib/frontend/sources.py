"""
Shared source metadata for answer rendering.

Maps topic_type to GitHub repositories and provides
helper functions for edit URLs and GitHub buttons.
"""

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


def get_source_url(topic_type):
    """Return GitHub URL for the given topic_type, or empty string."""
    full_name = GITHUB_REPOSITORY.get(topic_type, "")
    if full_name:
        return "https://github.com/" + full_name
    return ""


def get_edit_url(query, topic_type):
    """Return GitHub edit URL for cheat.sheets answers, or empty string."""
    if topic_type != "cheat.sheets":
        return ""
    edit_query = query
    if "/" in edit_query:
        edit_query = "_" + edit_query
    return "https://github.com/chubin/cheat.sheets/edit/master/sheets/" + edit_query


def get_github_button_html(topic_type):
    """Return HTML for GitHub star button for the source repo."""
    full_name = GITHUB_REPOSITORY.get(topic_type, "")
    if not full_name:
        return ""

    short_name = full_name.split("/", 1)[1]

    return (
        "<!-- Place this tag where you want the button to render. -->"
        '<a aria-label="Star %(full_name)s on GitHub"'
        ' data-count-aria-label="# stargazers on GitHub"'
        ' data-count-api="/repos/%(full_name)s#stargazers_count"'
        ' data-count-href="/%(full_name)s/stargazers"'
        ' data-icon="octicon-star"'
        ' href="https://github.com/%(full_name)s"'
        '  class="github-button">%(short_name)s</a>'
    ) % {"full_name": full_name, "short_name": short_name}

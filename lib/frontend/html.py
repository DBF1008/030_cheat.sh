"""
HTML frontend.

Delegates rendering to HtmlViewRenderer from frontend.views.
Maintains backward-compatible visualize() interface.

Configuration parameters:

    path.internal.ansi2html
"""

import sys
import os

MYDIR = os.path.abspath(os.path.join(__file__, "..", ".."))
sys.path.append("%s/lib/" % MYDIR)

from frontend.views import get_renderer


def visualize(answer_data, request_options):
    """
    Render answer_data as an HTML page with toolbar,
    per-answer filtering, collapsing, and view switching.

    Returns:
        (str, bool): tuple of (html_string, found_flag)
    """
    renderer = get_renderer("html")
    return renderer.render(answer_data, request_options)

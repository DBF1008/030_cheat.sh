"""
Standalone wrapper for the cheat.sh server.
"""

from __future__ import print_function

import sys
import textwrap

try:
    import urlparse
except ModuleNotFoundError:
    import urllib.parse as urlparse

import config

config.CONFIG["cache.type"] = "none"

import cheat_wrapper
from options import QueryPlan


def show_usage():
    """
    Show how to use the program in the standalone mode
    """

    print(
        textwrap.dedent(
            """
        Usage:

            lib/standalone.py [OPTIONS] QUERY

        For OPTIONS see :help
    """
        )[1:-1]
    )


def parse_cmdline(args):
    """
    Parses command line arguments and returns
    query and query_plan
    """

    if not args:
        show_usage()
        sys.exit(0)

    query_string = " ".join(args)
    parsed = urlparse.urlparse("https://srv:0/%s" % query_string)

    query = parsed.path.lstrip("/")
    if not query:
        query = ":firstpage"

    query_plan = QueryPlan.from_args(
        urlparse.parse_qs(parsed.query, keep_blank_values=True),
        query,
    )

    return query, query_plan


def main(args):
    """
    standalone wrapper for cheat_wrapper()
    """

    query, query_plan = parse_cmdline(args)
    answer, _ = cheat_wrapper.cheat_wrapper(query, query_plan=query_plan)
    sys.stdout.write(answer)


if __name__ == "__main__":
    main(sys.argv[1:])

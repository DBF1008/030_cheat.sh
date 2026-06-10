#!/usr/bin/env python
# vim: set encoding=utf-8
# pylint: disable=wrong-import-position,wrong-import-order

"""
Main server program.

Configuration parameters:

    path.internal.malformed
    path.internal.static
    path.internal.templates
    path.log.main
    path.log.queries
"""

from __future__ import print_function

import sys

if sys.version_info[0] < 3:
    reload(sys)
    sys.setdefaultencoding("utf8")

import sys
import logging
import os
import requests
import jinja2
from flask import Flask, request, send_from_directory, redirect, Response

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..", "lib")))
from config import CONFIG
from limits import Limits
from cheat_wrapper import cheat_wrapper
from post import process_post_request
from query_plan import QueryPlan

from stateful_queries import save_query, last_query


if not os.path.exists(os.path.dirname(CONFIG["path.log.main"])):
    os.makedirs(os.path.dirname(CONFIG["path.log.main"]))
logging.basicConfig(
    filename=CONFIG["path.log.main"],
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
)
# Fix Flask "exception and request logging" to `stderr`.
#
# When Flask's werkzeug detects that logging is already set, it
# doesn't add its own logger that prints exceptions.
stderr_handler = logging.StreamHandler()
logging.getLogger().addHandler(stderr_handler)
#
# Alter log format to disting log lines from everything else
stderr_handler.setFormatter(logging.Formatter("%(filename)s:%(lineno)s: %(message)s"))


#
# Sometimes werkzeug starts logging before an app is imported
# (https://github.com/pallets/werkzeug/issues/1969)
# resulting in duplicating lines. In that case we need root
# stderr handler to skip lines from werkzeug.
class SkipFlaskLogger(object):
    def filter(self, record):
        if record.name != "werkzeug":
            return True


if logging.getLogger("werkzeug").handlers:
    stderr_handler.addFilter(SkipFlaskLogger())


app = Flask(__name__)  # pylint: disable=invalid-name
app.jinja_loader = jinja2.ChoiceLoader(
    [app.jinja_loader, jinja2.FileSystemLoader(CONFIG["path.internal.templates"])]
)

LIMITS = Limits()


def is_result_a_script(query):
    return query in [":cht.sh"]


@app.route("/files/<path:path>")
def send_static(path):
    """
    Return static file `path`.
    Can be served by the HTTP frontend.
    """
    return send_from_directory(CONFIG["path.internal.static"], path)


@app.route("/favicon.ico")
def send_favicon():
    """
    Return static file `favicon.ico`.
    Can be served by the HTTP frontend.
    """
    return send_from_directory(CONFIG["path.internal.static"], "favicon.ico")


@app.route("/malformed-response.html")
def send_malformed():
    """
    Return static file `malformed-response.html`.
    Can be served by the HTTP frontend.
    """
    dirname, filename = os.path.split(CONFIG["path.internal.malformed"])
    return send_from_directory(dirname, filename)


def log_query(ip_addr, found, topic, user_agent):
    """
    Log processed query and some internal data
    """
    log_entry = "%s %s %s %s\n" % (ip_addr, found, topic, user_agent)
    with open(CONFIG["path.log.queries"], "ab") as my_file:
        my_file.write(log_entry.encode("utf-8"))


def _proxy(*args, **kwargs):
    # print "method=", request.method,
    # print "url=", request.url.replace('/:shell-x/', ':3000/')
    # print "headers=", {key: value for (key, value) in request.headers if key != 'Host'}
    # print "data=", request.get_data()
    # print "cookies=", request.cookies
    # print "allow_redirects=", False

    url_before, url_after = request.url.split("/:shell-x/", 1)
    url = url_before + ":3000/"

    if "q" in request.args:
        url_after = "?" + "&".join("arg=%s" % x for x in request.args["q"].split())

    url += url_after
    print(url)
    print(request.get_data())
    resp = requests.request(
        method=request.method,
        url=url,
        headers={key: value for (key, value) in request.headers if key != "Host"},
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False,
    )

    excluded_headers = [
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
    ]
    headers = [
        (name, value)
        for (name, value) in resp.raw.headers.items()
        if name.lower() not in excluded_headers
    ]

    response = Response(resp.content, resp.status_code, headers)
    return response


@app.route("/", methods=["GET", "POST"])
@app.route("/<path:topic>", methods=["GET", "POST"])
def answer(topic=None):
    """
    Main rendering function, it processes incoming weather queries.
    Depending on user agent it returns output in HTML or ANSI format.

    Incoming data:
        request.args
        request.headers
        request.remote_addr
        request.referrer
        request.query_string
    """

    if topic in [
        "apple-touch-icon-precomposed.png",
        "apple-touch-icon.png",
        "apple-touch-icon-120x120-precomposed.png",
    ] or (topic is not None and any(topic.endswith("/" + x) for x in ["favicon.ico"])):
        return ""

    # -- Build the unified query plan ONCE --
    plan = QueryPlan.from_request(request, topic=topic)

    # -- Stateful queries (:last) --
    if topic is not None and topic.lstrip("/") == ":last":
        if plan.request_id:
            topic = last_query(plan.request_id)
            plan.topic = topic
        else:
            return "ERROR: you have to set id for your requests to use /:last\n"
    else:
        if plan.request_id:
            save_query(plan.request_id, topic)

    # -- POST handling --
    if request.method == "POST":
        process_post_request(request, plan.output_format == "html")
        if plan.output_format == "html":
            return redirect("/")
        return "OK\n"

    # -- ?topic= redirect --
    if "topic" in request.args:
        return redirect("/%s" % request.args.get("topic"))

    if topic is None:
        topic = ":firstpage"

    # -- Shell proxy --
    if topic is not None and topic.startswith(":shell-x/"):
        return _proxy()

    # -- Debug endpoint: show parsed QueryPlan --
    if topic is not None and topic.lstrip("/") == ":plan":
        return Response(plan.format_debug(), mimetype="text/plain")

    # -- Rate limiting --
    if topic and "+" in topic:
        not_allowed = LIMITS.check_ip(plan.ip_address)
        if not_allowed:
            return "429 %s\n" % not_allowed, 429

    # -- Override output_format for scripts like :cht.sh --
    if is_result_a_script(topic):
        plan.output_format = "ansi"

    # -- Dispatch to cheat_wrapper with the plan --
    result, found = cheat_wrapper(plan)

    if "Please come back in several hours" in result and plan.output_format == "html":
        malformed_response = open(
            os.path.join(CONFIG["path.internal.malformed"])
        ).read()
        return malformed_response

    log_query(plan.ip_address, found, plan.topic, plan.user_agent)
    if plan.output_format == "html":
        return result
    return Response(result, mimetype="text/plain")

"""
Unified query plan that consolidates all HTTP request parsing
into a single structured object.

Constructed once in app.py from the raw Flask request, then
passed through the entire pipeline (cheat_wrapper -> routing ->
adapters -> postprocessing -> frontend).

Exports:

    QueryPlan
"""

from __future__ import print_function


# Short flag definitions (absorbed from options.py)
_SHORT_OPTIONS = {
    "c": {"add_comments": False, "unindent_code": False},
    "C": {"add_comments": False, "unindent_code": True},
    "Q": {"remove_text": True},
    "q": {"quiet": True},
    "T": {"no-terminal": True},
}

PLAIN_TEXT_AGENTS = [
    "curl",
    "httpie",
    "lwp-request",
    "wget",
    "python-requests",
    "openbsd ftp",
    "powershell",
    "fetch",
    "aiohttp",
    "xh",
]


class QueryPlan(object):
    """
    Consolidated representation of everything we need to know
    about an incoming cheat sheet request.

    Lifecycle:
        1. Constructed via QueryPlan.from_request(flask_request)
        2. Passed to cheat_wrapper(plan)
        3. Execution metadata (adapter_used, cache_hit) is set
           during pipeline processing
        4. Consumers call plan.to_options_dict() for backward-
           compatible dict access
    """

    def __init__(self):
        # -- Query fields (from URL path) --
        self.topic = ""
        self.keyword = None
        self.search_options = ""

        # -- Display options (from query params) --
        self.add_comments = True
        self.unindent_code = False
        self.remove_text = False
        self.quiet = False
        self.no_terminal = False
        self.style = ""
        self.lang = None

        # -- Client / request metadata --
        self.output_format = "ansi"
        self.user_agent = ""
        self.ip_address = ""
        self.request_id = None

        # -- Execution metadata (set during processing) --
        self.adapter_used = None
        self.cache_hit = None

        # -- Extra key=value params (forwarded to UpstreamAdapter) --
        self._extra_options = {}

        # -- Raw inputs (for debug view) --
        self._raw_args = {}
        self._raw_headers = {}

    # ----------------------------------------------------------
    # Backward-compatible dict interface
    # ----------------------------------------------------------

    def to_options_dict(self):
        """
        Return a plain dict that mirrors the shape of the old
        parse_args() output + the lang addition from app.py.

        Consumers that do request_options.get("add_comments") etc.
        keep working identically.
        """
        result = {"add_comments": self.add_comments}

        if self.unindent_code:
            result["unindent_code"] = True
        if self.remove_text:
            result["remove_text"] = True
        if self.quiet:
            result["quiet"] = True
        if self.no_terminal:
            result["no-terminal"] = True
        if self.style:
            result["style"] = self.style
        if self.lang:
            result["lang"] = self.lang

        # Forward unknown key=value params (for UpstreamAdapter)
        result.update(self._extra_options)

        return result

    # ----------------------------------------------------------
    # Debug / introspection
    # ----------------------------------------------------------

    def to_dict(self):
        """Full state as a plain dict (for debug endpoint)."""
        return {
            "topic": self.topic,
            "keyword": self.keyword,
            "search_options": self.search_options,
            "add_comments": self.add_comments,
            "unindent_code": self.unindent_code,
            "remove_text": self.remove_text,
            "quiet": self.quiet,
            "no_terminal": self.no_terminal,
            "style": self.style,
            "lang": self.lang,
            "output_format": self.output_format,
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
            "request_id": self.request_id,
            "adapter_used": self.adapter_used,
            "cache_hit": self.cache_hit,
            "raw_args": dict(self._raw_args),
        }

    def format_debug(self):
        """Human-readable multi-line string for the debug endpoint."""
        lines = []
        lines.append("=== QueryPlan ===")
        lines.append("")
        lines.append("-- Query --")
        lines.append("  topic:           %s" % self.topic)
        lines.append("  keyword:         %s" % self.keyword)
        lines.append(
            "  search_options:  %s" % (self.search_options or "(none)")
        )
        lines.append("")
        lines.append("-- Display Options --")
        lines.append("  add_comments:    %s" % self.add_comments)
        lines.append("  unindent_code:   %s" % self.unindent_code)
        lines.append("  remove_text:     %s" % self.remove_text)
        lines.append("  quiet:           %s" % self.quiet)
        lines.append("  no_terminal:     %s" % self.no_terminal)
        lines.append("  style:           %s" % (self.style or "(default)"))
        lines.append("  lang:            %s" % (self.lang or "(none)"))
        lines.append("")
        lines.append("-- Client --")
        lines.append("  output_format:   %s" % self.output_format)
        lines.append("  user_agent:      %s" % self.user_agent)
        lines.append("  ip_address:      %s" % self.ip_address)
        lines.append(
            "  request_id:      %s" % (self.request_id or "(none)")
        )
        lines.append("")
        lines.append("-- Execution --")
        lines.append(
            "  adapter_used:    %s"
            % (
                ", ".join(self.adapter_used)
                if isinstance(self.adapter_used, list)
                else (self.adapter_used or "(not yet resolved)")
            )
        )
        lines.append(
            "  cache_hit:       %s"
            % (
                "yes"
                if self.cache_hit is True
                else "no"
                if self.cache_hit is False
                else "(not yet resolved)"
            )
        )
        lines.append("")
        lines.append("-- Raw Query Args --")
        for k, v in sorted(self._raw_args.items()):
            lines.append("  %s = %s" % (k, v))
        return "\n".join(lines) + "\n"

    # ----------------------------------------------------------
    # Query param parsing
    # ----------------------------------------------------------

    def _parse_query_params(self, args):
        """
        Parse Flask request.args into plan fields.
        Absorbs the logic from options.py parse_args().

        `args` can be a dict-like object (Flask MultiDict or plain dict).
        """
        flag_chars = ""
        for key, val in args.items():
            if val == "" or val == [] or val == [""]:
                # Valueless keys are short-flag characters (c, C, Q, q, T)
                flag_chars += key
                continue
            # String "True"/"False" → Python bool
            if val == "True":
                val = True
            if val == "False":
                val = False
            # Known key=value params
            if key == "style":
                self.style = val
            elif key == "lang":
                self.lang = val
            else:
                # Unknown key=value params → forwarded to UpstreamAdapter
                self._extra_options[key] = val

        # Apply short flags
        for char in flag_chars:
            if char in _SHORT_OPTIONS:
                for opt_key, opt_val in _SHORT_OPTIONS[char].items():
                    if opt_key == "no-terminal":
                        self.no_terminal = opt_val
                    elif opt_key == "add_comments":
                        self.add_comments = opt_val
                    elif opt_key == "unindent_code":
                        self.unindent_code = opt_val
                    elif opt_key == "remove_text":
                        self.remove_text = opt_val
                    elif opt_key == "quiet":
                        self.quiet = opt_val

    # ----------------------------------------------------------
    # Topic update (called after sanitize chain in cheat_wrapper)
    # ----------------------------------------------------------

    def set_topic(self, topic, keyword=None, search_options=""):
        """
        Update the resolved topic, keyword, and search_options.
        Called by cheat_wrapper after the sanitization chain.
        """
        self.topic = topic
        self.keyword = keyword
        self.search_options = search_options

    # ----------------------------------------------------------
    # Construction from Flask request
    # ----------------------------------------------------------

    @classmethod
    def from_request(cls, req, topic=None):
        """
        Build a fully-populated QueryPlan from a Flask request object.

        This absorbs the logic previously scattered across:
          - app.py answer()          (user-agent, host, accept-language,
                                      cookies, ip, lang, output_format)
          - options.py parse_args()  (short flags, key=value params)
        """
        plan = cls()

        # Store raw inputs for debug
        plan._raw_args = dict(req.args)
        plan._raw_headers = {
            "User-Agent": req.headers.get("User-Agent", ""),
            "Host": req.headers.get("Host", ""),
            "Accept-Language": req.headers.get("Accept-Language", ""),
            "X-Forwarded-For": req.headers.getlist("X-Forwarded-For"),
        }

        # 1. Parse query params (absorbs parse_args)
        plan._parse_query_params(req.args)

        # 2. Resolve topic from URL path
        if topic is None:
            topic = ":firstpage"
        plan.topic = topic

        # 3. Client metadata
        plan.user_agent = req.headers.get("User-Agent", "").lower()
        plan.request_id = req.cookies.get("id")
        plan.ip_address = _extract_ip(req)

        # 4. Language resolution (may override self.lang from ?lang=)
        plan.lang = _resolve_language(req, plan.lang)

        # 5. Output format determination
        html_needed = _is_html_needed(plan.user_agent)
        is_script = topic in [":cht.sh"]
        plan.output_format = "html" if (html_needed and not is_script) else "ansi"

        return plan


# ----------------------------------------------------------
# Module-level helpers (moved from app.py)
# ----------------------------------------------------------


def _is_html_needed(user_agent):
    """Return True if the user agent needs HTML output."""
    return all(x not in user_agent for x in PLAIN_TEXT_AGENTS)


def _extract_ip(req):
    """Extract client IP from the Flask request."""
    if req.headers.getlist("X-Forwarded-For"):
        ip_addr = req.headers.getlist("X-Forwarded-For")[0]
        if ip_addr.startswith("::ffff:"):
            ip_addr = ip_addr[7:]
    else:
        ip_addr = req.remote_addr
    return ip_addr


def _resolve_language(req, lang_from_param=None):
    """
    Determine preferred answer language from:
      1. ?lang= query param (highest priority, already parsed)
      2. Host subdomain (fr.cheat.sh -> fr)
      3. Accept-Language header (fallback)
    """
    lang = None

    # Subdomain detection
    hostname = req.headers.get("Host", "")
    if hostname.endswith(".cheat.sh"):
        lang = hostname[:-9]

    # Explicit ?lang= overrides subdomain
    if lang_from_param is not None:
        lang = lang_from_param

    # Accept-Language fallback
    if lang is None:
        accept_lang = req.headers.get("Accept-Language", "")
        if accept_lang:
            lang = _find_supported_language(
                _parse_accept_language(accept_lang)
            )

    return lang


def _parse_accept_language(accept_language):
    """Parse Accept-Language header into (locale, weight) pairs."""
    languages = accept_language.split(",")
    locale_q_pairs = []

    for language in languages:
        try:
            if language.split(";")[0] == language:
                # no q => q = 1
                locale_q_pairs.append((language.strip(), "1"))
            else:
                locale = language.split(";")[0].strip()
                weight = language.split(";")[1].split("=")[1]
                locale_q_pairs.append((locale, weight))
        except IndexError:
            pass

    return locale_q_pairs


def _find_supported_language(accepted_languages):
    """Return the first language from accepted_languages."""
    for lang_tuple in accepted_languages:
        lang = lang_tuple[0]
        if "-" in lang:
            lang = lang.split("-", 1)[0]
        return lang
    return None

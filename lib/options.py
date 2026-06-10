"""
Parse query arguments and build structured QueryPlan objects.

Exports:
    QueryPlan   - structured request plan driving routing, search, postprocess, frontend
    parse_args  - backward-compatible dict builder (wraps QueryPlan internally)
"""

from dataclasses import dataclass, field
from typing import Optional


def _parse_flag_string(args):
    """
    Parse raw query-string arguments into a flat display-options dict.
    Short option flags (c, C, Q, q, T) embedded in bare keys are expanded.
    Key-value pairs (e.g. style=monokai) are passed through.
    """
    result = {
        "add_comments": True,
    }

    query = ""
    newargs = {}
    for key, val in args.items():
        if val == "" or val == [] or val == [""]:
            query += key
            continue
        # parse_qs returns values as lists; unwrap single-element lists
        if isinstance(val, list) and len(val) == 1:
            val = val[0]
        if val == "True":
            val = True
        if val == "False":
            val = False
        newargs[key] = val

    options_meaning = {
        "c": dict(add_comments=False, unindent_code=False),
        "C": dict(add_comments=False, unindent_code=True),
        "Q": dict(remove_text=True),
        "q": dict(quiet=True),
        "T": {"no-terminal": True},
    }
    for option, meaning in options_meaning.items():
        if option in query:
            result.update(meaning)

    result.update(newargs)

    return result


# Keys stored in _options_dict (the backward-compatible display-options namespace).
# Only these keys are exposed via dict-compat methods and serialized by UpstreamAdapter.
_DISPLAY_OPTION_KEYS = frozenset({
    "add_comments", "unindent_code", "remove_text",
    "quiet", "no-terminal", "style", "lang",
})


@dataclass
class QueryPlan:
    """
    Structured request plan that consolidates all HTTP/CLI parameters
    into a single object passed through routing, search, postprocess, and frontend.
    """

    # Query resolution (populated by cheat_wrapper via resolve_query)
    raw_query: str = ""
    topic: str = ""
    keyword: Optional[str] = None
    search_options: str = ""

    # Display options (from query string flags)
    add_comments: bool = True
    unindent_code: bool = False
    remove_text: bool = False
    quiet: bool = False
    no_terminal: bool = False
    style: str = ""

    # Request context
    lang: Optional[str] = None
    output_format: str = "ansi"
    client_id: Optional[str] = None
    tenant_id: str = "default"

    # Routing metadata (populated during request processing)
    adapter_used: Optional[str] = None
    cache_hit: Optional[bool] = None

    # Internal: backward-compatible flat dict for downstream consumers
    _options_dict: dict = field(default_factory=dict, repr=False, init=False)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_http(cls, args, topic, lang=None, output_format="ansi",
                  client_id=None, tenant_id="default"):
        """
        Build a QueryPlan from Flask request.args and pre-extracted HTTP context.

        Args:
            args:           request.args (ImmutableMultiDict or plain dict)
            topic:          URL path topic (may be None)
            lang:           resolved language (from Host / query / Accept-Language)
            output_format:  "html" or "ansi"
            client_id:      cookie "id" value
            tenant_id:      resolved tenant identifier
        """
        parsed = _parse_flag_string(args)
        plan = cls(
            raw_query=topic or "",
            add_comments=parsed.get("add_comments", True),
            unindent_code=parsed.get("unindent_code", False),
            remove_text=parsed.get("remove_text", False),
            quiet=parsed.get("quiet", False),
            no_terminal=parsed.get("no-terminal", False),
            style=parsed.get("style", ""),
            lang=lang,
            output_format=output_format,
            client_id=client_id,
            tenant_id=tenant_id,
        )
        plan._rebuild_options_dict(parsed)
        return plan

    @classmethod
    def from_args(cls, args, topic):
        """
        Build a QueryPlan from CLI-parsed query-string arguments.

        Args:
            args:   dict from urlparse.parse_qs (values may be lists)
            topic:  query path
        """
        parsed = _parse_flag_string(args)
        plan = cls(
            raw_query=topic or "",
            add_comments=parsed.get("add_comments", True),
            unindent_code=parsed.get("unindent_code", False),
            remove_text=parsed.get("remove_text", False),
            quiet=parsed.get("quiet", False),
            no_terminal=parsed.get("no-terminal", False),
            style=parsed.get("style", ""),
            lang=parsed.get("lang"),
            output_format="ansi",
            client_id=None,
            tenant_id="default",
        )
        plan._rebuild_options_dict(parsed)
        return plan

    # ------------------------------------------------------------------
    # Query resolution
    # ------------------------------------------------------------------

    def resolve_query(self, topic, keyword, search_options):
        """Called by cheat_wrapper after it parses the raw query."""
        self.topic = topic
        self.keyword = keyword
        self.search_options = search_options

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_debug_dict(self):
        """Return all fields as a JSON-serializable dict for the /:debug endpoint."""
        return {
            "raw_query": self.raw_query,
            "topic": self.topic,
            "keyword": self.keyword,
            "search_options": self.search_options,
            "display_options": {
                "add_comments": self.add_comments,
                "unindent_code": self.unindent_code,
                "remove_text": self.remove_text,
                "quiet": self.quiet,
                "no_terminal": self.no_terminal,
                "style": self.style,
            },
            "lang": self.lang,
            "output_format": self.output_format,
            "client_id": self.client_id,
            "tenant_id": self.tenant_id,
            "adapter_used": self.adapter_used,
            "cache_hit": self.cache_hit,
        }

    def to_options_dict(self):
        """Return a backward-compatible flat dict matching the old parse_args() output."""
        return dict(self._options_dict)

    # ------------------------------------------------------------------
    # Dict-compatibility layer
    #
    # Downstream consumers (frontend, postprocessing, UpstreamAdapter) access
    # request_options via .get(), ["key"], .items(), "key" in opts.
    # These methods delegate to _options_dict which contains only display-option
    # keys, keeping internal fields (tenant_id, adapter_used, ...) hidden.
    # ------------------------------------------------------------------

    def get(self, key, default=None):
        return self._options_dict.get(key, default)

    def __getitem__(self, key):
        return self._options_dict[key]

    def __contains__(self, key):
        return key in self._options_dict

    def items(self):
        return self._options_dict.items()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_options_dict(self, parsed=None):
        """
        Rebuild _options_dict from dataclass fields.
        If `parsed` is provided, also include any pass-through keys from the
        original query string that are not standard display-option fields
        (e.g. unknown future keys).
        """
        d = {}
        d["add_comments"] = self.add_comments
        if self.unindent_code:
            d["unindent_code"] = self.unindent_code
        if self.remove_text:
            d["remove_text"] = self.remove_text
        if self.quiet:
            d["quiet"] = self.quiet
        if self.no_terminal:
            d["no-terminal"] = self.no_terminal
        if self.style:
            d["style"] = self.style
        if self.lang is not None:
            d["lang"] = self.lang

        # Preserve pass-through keys from original parse (e.g. unknown future params)
        if parsed:
            for key, val in parsed.items():
                if key not in _DISPLAY_OPTION_KEYS and key not in d:
                    d[key] = val

        self._options_dict = d


def parse_args(args):
    """
    Backward-compatible: parse arguments and return a flat dict.
    New code should use QueryPlan.from_http() or QueryPlan.from_args() instead.
    """
    return _parse_flag_string(args)

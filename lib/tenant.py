"""
Tenant identification and configuration for multi-tenant cache isolation.

Exports:
    DEFAULT_TENANT
    identify_tenant(request=None)
    get_tenant_config(tenant_id)
    get_all_tenants()
"""

from config import CONFIG

DEFAULT_TENANT = "default"

_HEADER_NAME = "X-Tenant-ID"
_COOKIE_NAME = "tenant"


def identify_tenant(request=None):
    """
    Identify tenant from a Flask request.

    Priority:
        1. ``X-Tenant-ID`` header
        2. ``tenant`` cookie
        3. fallback to ``DEFAULT_TENANT``

    If *request* is ``None`` (e.g. CLI context), ``DEFAULT_TENANT`` is returned.
    """

    if request is None:
        return DEFAULT_TENANT

    tenant_id = request.headers.get(_HEADER_NAME)
    if tenant_id:
        return _sanitize_tenant_id(tenant_id)

    tenant_id = request.cookies.get(_COOKIE_NAME)
    if tenant_id:
        return _sanitize_tenant_id(tenant_id)

    return DEFAULT_TENANT


def _sanitize_tenant_id(raw):
    """
    Strip whitespace and reject obviously malicious characters
    (path separators, Redis key delimiters that would break namespacing).
    Returns the cleaned string, or ``DEFAULT_TENANT`` if the result is empty.
    """

    cleaned = raw.strip()
    # reject characters that could cause key-injection or path traversal
    for char in ("/", "\\", "\n", "\r", "\x00"):
        cleaned = cleaned.replace(char, "")
    return cleaned if cleaned else DEFAULT_TENANT


def get_tenant_config(tenant_id):
    """
    Return a configuration dict for *tenant_id*.

    Per-tenant overrides are read from ``CONFIG["tenants"]`` (a dict keyed by
    tenant id).  Missing keys fall back to global defaults.

    Returned keys:
        cache_ttl (int): TTL in seconds for cached entries (0 = no expiry).
    """

    global_ttl = CONFIG.get("cache.ttl", 0)

    tenants_cfg = CONFIG.get("tenants", {}) or {}
    tenant_cfg = tenants_cfg.get(tenant_id, {}) or {}

    return {
        "cache_ttl": tenant_cfg.get("cache_ttl", global_ttl),
    }


def get_all_tenants():
    """
    Return a list of all known tenant IDs.

    Always includes ``DEFAULT_TENANT``.  Additional tenants are read from
    ``CONFIG["tenants"]``.
    """

    tenants_cfg = CONFIG.get("tenants", {}) or {}
    tenants = list(tenants_cfg.keys())
    if DEFAULT_TENANT not in tenants:
        tenants.append(DEFAULT_TENANT)
    return tenants

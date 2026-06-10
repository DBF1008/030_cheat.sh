"""
Cache implementation with multi-tenant namespace isolation.

Currently only two types of cache are allowed:
    * "none"    cache switched off
    * "redis"   use redis for cache

Configuration parameters:

    cache.type = redis | none
    cache.redis.db
    cache.redis.host
    cache.redis.port
    cache.redis.prefix
    cache.ttl
    cache.tenant.isolate_default
    tenants
"""

import json
from config import CONFIG

_REDIS = None
if CONFIG["cache.type"] == "redis":
    import redis

    _REDIS = redis.Redis(
        host=CONFIG["cache.redis.host"],
        port=CONFIG["cache.redis.port"],
        db=CONFIG["cache.redis.db"],
    )

_REDIS_PREFIX = ""
if CONFIG.get("cache.redis.prefix", ""):
    _REDIS_PREFIX = CONFIG["cache.redis.prefix"] + ":"


def _resolve_tenant(tenant):
    """Normalize *tenant* to a concrete tenant id string."""
    if tenant is None:
        return "default"
    return tenant


def _make_key(key, tenant=None):
    """
    Build the full Redis key for *key* under *tenant*.

    Key scheme:
        default tenant, isolate_default=False  ->  {prefix}{key}
        default tenant, isolate_default=True   ->  {prefix}t:default:{key}
        non-default tenant                     ->  {prefix}t:{tenant}:{key}
    """
    tenant = _resolve_tenant(tenant)
    isolate_default = CONFIG.get("cache.tenant.isolate_default", False)

    if tenant == "default" and not isolate_default:
        return _REDIS_PREFIX + key

    return _REDIS_PREFIX + "t:" + tenant + ":" + key


def _resolve_ttl(tenant, ttl):
    """
    Determine the effective TTL in seconds.

    * explicit ``ttl=0``  -> no expiry  (return 0)
    * explicit ``ttl>0``  -> use that value
    * ``ttl is None``     -> look up per-tenant config, fall back to global
    """
    if ttl is not None:
        return ttl

    from tenant import get_tenant_config
    cfg = get_tenant_config(_resolve_tenant(tenant))
    return cfg.get("cache_ttl", 0)


def put(key, value, tenant=None, ttl=None):
    """
    Save *value* with *key*, scoped to *tenant*.
    Serialize dicts/lists to JSON.
    Apply TTL if specified or configured for the tenant.
    """
    if CONFIG["cache.type"] != "redis" or not _REDIS:
        return

    full_key = _make_key(key, tenant)

    if isinstance(value, (dict, list)):
        value = json.dumps(value)

    effective_ttl = _resolve_ttl(tenant, ttl)
    if effective_ttl and effective_ttl > 0:
        _REDIS.set(full_key, value, ex=effective_ttl)
    else:
        _REDIS.set(full_key, value)


def get(key, tenant=None):
    """
    Read *value* by *key*, scoped to *tenant*.
    Deserialize JSON if possible.
    """
    if CONFIG["cache.type"] != "redis" or not _REDIS:
        return None

    full_key = _make_key(key, tenant)
    value = _REDIS.get(full_key)
    if value is not None and isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            pass
    try:
        value = json.loads(value)
    except (ValueError, TypeError):
        pass
    return value


def delete(key, tenant=None):
    """
    Remove *key* from the cache, scoped to *tenant*.
    """
    if not _REDIS:
        return None

    full_key = _make_key(key, tenant)
    _REDIS.delete(full_key)
    return None


def flush_tenant(tenant_id):
    """
    Delete **all** cache entries belonging to *tenant_id*.
    Returns the number of keys deleted.
    """
    if not _REDIS:
        return 0

    tenant_id = _resolve_tenant(tenant_id)
    isolate_default = CONFIG.get("cache.tenant.isolate_default", False)

    if tenant_id == "default" and not isolate_default:
        # Default tenant keys are stored without a t: prefix.
        # We must scan all keys under _REDIS_PREFIX and exclude those
        # that belong to other tenants (start with t:).
        pattern = _REDIS_PREFIX + "*"
        tenant_marker = (_REDIS_PREFIX + "t:").encode() if _REDIS_PREFIX else b"t:"
        count = 0
        for k in _REDIS.scan_iter(match=pattern):
            if not k.startswith(tenant_marker):
                _REDIS.delete(k)
                count += 1
        return count

    pattern = _REDIS_PREFIX + "t:" + tenant_id + ":*"
    count = 0
    for k in _REDIS.scan_iter(match=pattern):
        _REDIS.delete(k)
        count += 1
    return count


def delete_pattern(pattern, tenant=None):
    """
    Delete all keys matching a glob *pattern*, scoped to *tenant*.
    Returns the number of keys deleted.
    """
    if not _REDIS:
        return 0

    full_pattern = _make_key(pattern, tenant)
    count = 0
    for k in _REDIS.scan_iter(match=full_pattern):
        _REDIS.delete(k)
        count += 1
    return count


def delete_across_tenants(key):
    """
    Delete *key* from all tenants.
    Used by repository update logic to invalidate stale entries globally.
    """
    if not _REDIS:
        return 0

    count = 0
    # Delete bare key (default tenant without isolation)
    bare = _REDIS_PREFIX + key
    count += _REDIS.delete(bare)

    # Delete isolated default + all other tenants
    pattern = _REDIS_PREFIX + "t:*:" + key
    for k in _REDIS.scan_iter(match=pattern):
        _REDIS.delete(k)
        count += 1

    return count

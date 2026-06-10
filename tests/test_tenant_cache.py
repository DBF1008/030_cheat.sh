"""
Unit tests for multi-tenant cache isolation.

Uses ``fakeredis`` so no running Redis instance is required.

Run with::

    cd repo
    pip install fakeredis pytest
    python -m pytest tests/test_tenant_cache.py -v
"""

import json
import sys
import os
import importlib
import types
import pytest

# ---------------------------------------------------------------------------
# bootstrap: make lib/ importable and inject a fake config + fakeredis before
# the production modules are loaded.
# ---------------------------------------------------------------------------

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LIB = os.path.join(_REPO, "lib")
sys.path.insert(0, _LIB)

import fakeredis  # noqa: E402

# Pre-install a stub for `config` so that importing cache / tenant picks it up.
# We need to do this *before* importing cache or tenant.
_fake_redis = fakeredis.FakeStrictRedis()


def _make_config(overrides=None):
    """Return a Config-like dict with sensible defaults for testing."""
    cfg = {
        "cache.type": "redis",
        "cache.redis.host": "localhost",
        "cache.redis.port": 6379,
        "cache.redis.db": 0,
        "cache.redis.prefix": "",
        "cache.ttl": 0,
        "cache.tenant.isolate_default": False,
        "tenants": {},
    }
    if overrides:
        cfg.update(overrides)
    return cfg


def _reload_modules(cfg_overrides=None):
    """
    (Re-)import ``config``, ``cache``, ``tenant``, ``stateful_queries``
    with a fresh fake Redis connection and given config overrides.
    """

    cfg = _make_config(cfg_overrides)

    # -- config module --
    config_mod = types.ModuleType("config")
    config_mod.CONFIG = cfg
    sys.modules["config"] = config_mod

    # Force re-import of our modules
    for name in ("cache", "tenant", "stateful_queries"):
        if name in sys.modules:
            del sys.modules[name]

    import cache as cache_mod
    import tenant as tenant_mod
    import stateful_queries as sq_mod

    # Replace the real Redis connection with our fake one
    _fake_redis.flushall()
    cache_mod._REDIS = _fake_redis

    return cache_mod, tenant_mod, sq_mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class FakeRequest:
    """Minimal Flask-like request object for testing."""

    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}


# ---------------------------------------------------------------------------
# Tests: tenant identification
# ---------------------------------------------------------------------------


class TestIdentifyTenant:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules()

    def test_no_request_returns_default(self):
        assert self.tenant.identify_tenant() == "default"

    def test_header_takes_priority(self):
        req = FakeRequest(
            headers={"X-Tenant-ID": "team-a"},
            cookies={"tenant": "team-b"},
        )
        assert self.tenant.identify_tenant(req) == "team-a"

    def test_cookie_fallback(self):
        req = FakeRequest(cookies={"tenant": "team-b"})
        assert self.tenant.identify_tenant(req) == "team-b"

    def test_empty_header_falls_through(self):
        req = FakeRequest(
            headers={"X-Tenant-ID": ""},
            cookies={"tenant": "team-b"},
        )
        assert self.tenant.identify_tenant(req) == "team-b"

    def test_no_tenant_info_returns_default(self):
        req = FakeRequest()
        assert self.tenant.identify_tenant(req) == "default"

    def test_sanitize_strips_slashes(self):
        req = FakeRequest(headers={"X-Tenant-ID": "te/am"})
        assert self.tenant.identify_tenant(req) == "team"

    def test_sanitize_strips_newlines(self):
        req = FakeRequest(headers={"X-Tenant-ID": "te\nam"})
        assert self.tenant.identify_tenant(req) == "team"


# ---------------------------------------------------------------------------
# Tests: tenant config
# ---------------------------------------------------------------------------


class TestTenantConfig:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules(
            {"tenants": {"team-a": {"cache_ttl": 600}}, "cache.ttl": 120}
        )

    def test_default_tenant_uses_global_ttl(self):
        cfg = self.tenant.get_tenant_config("default")
        assert cfg["cache_ttl"] == 120

    def test_configured_tenant_uses_own_ttl(self):
        cfg = self.tenant.get_tenant_config("team-a")
        assert cfg["cache_ttl"] == 600

    def test_unknown_tenant_uses_global_ttl(self):
        cfg = self.tenant.get_tenant_config("team-z")
        assert cfg["cache_ttl"] == 120

    def test_get_all_tenants_includes_default(self):
        tenants = self.tenant.get_all_tenants()
        assert "default" in tenants
        assert "team-a" in tenants


# ---------------------------------------------------------------------------
# Tests: cache key isolation
# ---------------------------------------------------------------------------


class TestCacheIsolation:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules()

    def test_default_tenant_no_prefix(self):
        """When isolate_default=False, default tenant keys have no t: prefix."""
        self.cache.put("mykey", "val1", tenant="default")
        # key should exist without t:default: prefix
        raw = _fake_redis.get("mykey")
        assert raw is not None

    def test_non_default_tenant_has_prefix(self):
        self.cache.put("mykey", "val2", tenant="team-a")
        raw = _fake_redis.get("t:team-a:mykey")
        assert raw is not None
        # raw string values are stored as-is (not JSON-serialized)
        assert raw == b"val2"

    def test_tenants_cannot_see_each_other(self):
        self.cache.put("shared", "default_val", tenant="default")
        self.cache.put("shared", "team_a_val", tenant="team-a")

        assert self.cache.get("shared", tenant="default") == "default_val"
        assert self.cache.get("shared", tenant="team-a") == "team_a_val"

    def test_delete_scoped_to_tenant(self):
        self.cache.put("k", "v1", tenant="default")
        self.cache.put("k", "v2", tenant="team-a")

        self.cache.delete("k", tenant="team-a")

        assert self.cache.get("k", tenant="default") == "v1"
        assert self.cache.get("k", tenant="team-a") is None

    def test_none_tenant_equals_default(self):
        self.cache.put("k", "v")
        assert self.cache.get("k") == "v"
        assert self.cache.get("k", tenant=None) == "v"
        assert self.cache.get("k", tenant="default") == "v"


class TestCacheIsolationWithDefaultIsolated:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules(
            {"cache.tenant.isolate_default": True}
        )

    def test_default_tenant_gets_prefix_when_isolated(self):
        self.cache.put("mykey", "val", tenant="default")
        raw = _fake_redis.get("t:default:mykey")
        assert raw is not None


class TestCacheWithGlobalPrefix:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules(
            {"cache.redis.prefix": "myapp"}
        )

    def test_global_prefix_applied(self):
        self.cache.put("k", "v", tenant="team-a")
        raw = _fake_redis.get("myapp:t:team-a:k")
        assert raw is not None

    def test_global_prefix_default_tenant(self):
        self.cache.put("k", "v")
        raw = _fake_redis.get("myapp:k")
        assert raw is not None


# ---------------------------------------------------------------------------
# Tests: TTL
# ---------------------------------------------------------------------------


class TestCacheTTL:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules(
            {"tenants": {"team-a": {"cache_ttl": 300}}, "cache.ttl": 0}
        )

    def test_default_tenant_no_ttl(self):
        self.cache.put("k", "v", tenant="default")
        ttl = _fake_redis.ttl("k")
        # -1 means key exists but has no expiry
        assert ttl == -1

    def test_tenant_ttl_applied(self):
        self.cache.put("k", "v", tenant="team-a")
        ttl = _fake_redis.ttl("t:team-a:k")
        assert 0 < ttl <= 300

    def test_explicit_ttl_overrides_config(self):
        self.cache.put("k", "v", tenant="team-a", ttl=60)
        ttl = _fake_redis.ttl("t:team-a:k")
        assert 0 < ttl <= 60

    def test_explicit_zero_ttl_means_no_expiry(self):
        self.cache.put("k", "v", tenant="team-a", ttl=0)
        ttl = _fake_redis.ttl("t:team-a:k")
        assert ttl == -1


# ---------------------------------------------------------------------------
# Tests: flush_tenant
# ---------------------------------------------------------------------------


class TestFlushTenant:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules()

    def test_flush_only_affects_target_tenant(self):
        self.cache.put("k1", "v1", tenant="default")
        self.cache.put("k2", "v2", tenant="team-a")
        self.cache.put("k3", "v3", tenant="team-b")

        deleted = self.cache.flush_tenant("team-a")
        assert deleted >= 1

        assert self.cache.get("k1", tenant="default") == "v1"
        assert self.cache.get("k2", tenant="team-a") is None
        assert self.cache.get("k3", tenant="team-b") == "v3"

    def test_flush_default_tenant_preserves_other_tenants(self):
        self.cache.put("k1", "v1", tenant="default")
        self.cache.put("k2", "v2", tenant="team-a")

        self.cache.flush_tenant("default")

        assert self.cache.get("k1", tenant="default") is None
        assert self.cache.get("k2", tenant="team-a") == "v2"


# ---------------------------------------------------------------------------
# Tests: delete_pattern
# ---------------------------------------------------------------------------


class TestDeletePattern:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules()

    def test_delete_pattern_scoped_to_tenant(self):
        self.cache.put("cheat.sheets:tar", "v1", tenant="team-a")
        self.cache.put("cheat.sheets:curl", "v2", tenant="team-a")
        self.cache.put("cheat.sheets:tar", "v3", tenant="team-b")

        deleted = self.cache.delete_pattern("cheat.sheets:*", tenant="team-a")
        assert deleted == 2

        assert self.cache.get("cheat.sheets:tar", tenant="team-a") is None
        assert self.cache.get("cheat.sheets:curl", tenant="team-a") is None
        assert self.cache.get("cheat.sheets:tar", tenant="team-b") == "v3"


# ---------------------------------------------------------------------------
# Tests: stateful queries (:last) with tenant isolation
# ---------------------------------------------------------------------------


class TestStatefulQueries:
    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules()

    def test_last_query_per_tenant(self):
        self.sq.save_query("user1", "tar", tenant="team-a")
        self.sq.save_query("user1", "curl", tenant="team-b")

        assert self.sq.last_query("user1", tenant="team-a") == "tar"
        assert self.sq.last_query("user1", tenant="team-b") == "curl"

    def test_last_query_default_tenant(self):
        self.sq.save_query("user1", "git/rebase")
        assert self.sq.last_query("user1") == "git/rebase"

    def test_clear_last_per_tenant(self):
        self.sq.save_query("u1", "q1", tenant="team-a")
        self.sq.save_query("u2", "q2", tenant="team-b")

        self.sq.clear_last(tenant="team-a")

        assert self.sq.last_query("u1", tenant="team-a") is None
        assert self.sq.last_query("u2", tenant="team-b") == "q2"


# ---------------------------------------------------------------------------
# Tests: backward compatibility (single-tenant default behaviour)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure that when no tenant header is sent, behaviour is identical to
    the original (non-tenant-aware) implementation."""

    def setup_method(self):
        self.cache, self.tenant, self.sq = _reload_modules()

    def test_q_cache_key_format(self):
        """Question cache key should be ``q:topic`` without tenant prefix."""
        self.cache.put("q:python/read+json", {"answer": "use json.loads"})
        raw = _fake_redis.get("q:python/read+json")
        assert raw is not None

    def test_last_query_key_format(self):
        """Stateful query key should be ``l:cookie_id`` without tenant prefix."""
        self.sq.save_query("abc123", "tar")
        raw = _fake_redis.get("l:abc123")
        assert raw is not None

    def test_adapter_cache_key_format(self):
        """Adapter cache key should be ``type:topic`` without tenant prefix."""
        self.cache.put("tldr:curl", {"answer": "..."})
        raw = _fake_redis.get("tldr:curl")
        assert raw is not None

    def test_delete_works_without_tenant(self):
        self.cache.put("k", "v")
        assert self.cache.get("k") == "v"
        self.cache.delete("k")
        assert self.cache.get("k") is None

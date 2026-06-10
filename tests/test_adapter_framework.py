"""
Unit tests for the declarative adapter plugin framework.

Covers:
- _is_always_found declarative behavior
- _check_repository_prerequisites guard logic
- save_state bytes/str unification
- GitRepositoryAdapter command methods
- LearnXinY factory-generated subclasses
- update_by_name implementation

Run with::

    cd repo
    python -m pytest tests/test_adapter_framework.py -v
"""

import sys
import os
import types
import tempfile
import shutil

import pytest

# ---------------------------------------------------------------------------
# bootstrap: make lib/ importable and inject a fake config before
# the production modules are loaded.
# ---------------------------------------------------------------------------

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LIB = os.path.join(_REPO, "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

_tmp_repos = tempfile.mkdtemp(prefix="cheatsh_test_repos_")

config_mod = types.ModuleType("config")
config_mod.CONFIG = {
    "path.repositories": _tmp_repos,
    "path.log.fetch": os.path.join(_tmp_repos, "fetch.log"),
    "cache.type": "none",
    "cache.redis.host": "localhost",
    "cache.redis.port": 6379,
    "cache.redis.db": 0,
    "cache.redis.prefix": "",
    "log.level": 0,
}
sys.modules["config"] = config_mod

# Stub out modules that have heavy dependencies
for mod_name in ("globals",):
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        stub.fatal = lambda *a, **kw: None
        stub.error = lambda *a, **kw: None
        stub.log = lambda *a, **kw: None
        sys.modules[mod_name] = stub

# Stub polyglot/icu so question.py can be imported without native libs
_icu_stub = types.ModuleType("icu")
_icu_stub.Locale = type("Locale", (), {})
sys.modules.setdefault("icu", _icu_stub)

_polyglot = types.ModuleType("polyglot")
_polyglot_detect = types.ModuleType("polyglot.detect")
_polyglot_detect_base = types.ModuleType("polyglot.detect.base")

class _FakeDetector:
    def __init__(self, *a, **kw):
        pass
    languages = []

class _FakeUnknownLanguage(Exception):
    pass

_polyglot_detect.Detector = _FakeDetector
_polyglot_detect_base.Detector = _FakeDetector
_polyglot_detect_base.UnknownLanguage = _FakeUnknownLanguage
_polyglot_detect_base.Language = type("Language", (), {})
sys.modules.setdefault("polyglot", _polyglot)
sys.modules.setdefault("polyglot.detect", _polyglot_detect)
sys.modules.setdefault("polyglot.detect.base", _polyglot_detect_base)

# Now import adapter modules
from adapter.adapter import Adapter, all_adapters, adapter_by_name  # noqa: E402
from adapter.git_adapter import GitRepositoryAdapter, RepositoryAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Test: _is_always_found
# ---------------------------------------------------------------------------

class TestIsAlwaysFound:

    def test_default_is_false(self):
        """Base Adapter has _is_always_found = False by default."""
        assert Adapter._is_always_found is False

    def test_always_found_returns_true(self):
        """When _is_always_found is True, is_found returns True for any topic."""

        class AlwaysFoundAdapter(Adapter):
            _adapter_name = "test_always"
            _is_always_found = True

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        a = AlwaysFoundAdapter()
        assert a.is_found("anything") is True
        assert a.is_found("nonexistent_topic") is True

    def test_not_always_found_checks_list(self):
        """When _is_always_found is False, is_found checks the topic list."""

        class NormalAdapter(Adapter):
            _adapter_name = "test_normal"
            _is_always_found = False

            def _get_list(self, prefix=None):
                return ["existing_topic"]

            def _get_page(self, topic, request_options=None):
                return ""

        a = NormalAdapter()
        assert a.is_found("existing_topic") is True
        assert a.is_found("nonexistent") is False

    def test_subclass_can_override_is_found(self):
        """A subclass can still override is_found even with _is_always_found."""

        class CustomFoundAdapter(Adapter):
            _adapter_name = "test_custom_found"
            _is_always_found = True

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

            def is_found(self, topic):
                return topic.startswith("yes")

        a = CustomFoundAdapter()
        assert a.is_found("yes_topic") is True
        assert a.is_found("no_topic") is False


# ---------------------------------------------------------------------------
# Test: _check_repository_prerequisites
# ---------------------------------------------------------------------------

class TestCheckRepositoryPrerequisites:

    def test_no_url_returns_invalid(self):
        """No _repository_url => (None, False)."""

        class NoUrlAdapter(Adapter):
            _adapter_name = "test_no_url"
            _repository_url = None

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        local_dir, valid = NoUrlAdapter._check_repository_prerequisites()
        assert local_dir is None
        assert valid is False

    def test_valid_url_returns_valid(self):
        """A valid _repository_url yields (path, True)."""

        class ValidUrlAdapter(Adapter):
            _adapter_name = "test_valid_url"
            _repository_url = "https://github.com/test/repo"

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        local_dir, valid = ValidUrlAdapter._check_repository_prerequisites()
        assert valid is True
        assert local_dir is not None
        assert "repo" in local_dir


# ---------------------------------------------------------------------------
# Test: save_state / get_state
# ---------------------------------------------------------------------------

class TestSaveGetState:

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp(prefix="cheatsh_state_")

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_adapter(self):
        test_dir = self.test_dir

        class StateTestAdapter(Adapter):
            _adapter_name = "test_state"
            _local_repository_location = test_dir

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        return StateTestAdapter

    def test_save_state_with_str(self):
        cls = self._make_adapter()
        cls.save_state("abc123")
        state = cls.get_state()
        assert state == "abc123"

    def test_save_state_with_bytes(self):
        cls = self._make_adapter()
        cls.save_state(b"def456\n")
        state = cls.get_state()
        assert state == "def456\n"

    def test_roundtrip(self):
        cls = self._make_adapter()
        cls.save_state(b"rev-abc")
        assert cls.get_state() == "rev-abc"
        cls.save_state("rev-xyz")
        assert cls.get_state() == "rev-xyz"

    def test_get_state_no_file(self):
        cls = self._make_adapter()
        assert cls.get_state() is None


# ---------------------------------------------------------------------------
# Test: GitRepositoryAdapter command methods
# ---------------------------------------------------------------------------

class TestGitAdapterCommands:

    def test_fetch_command_no_url(self):
        """No _repository_url => fetch_command returns None."""

        class NoUrlGit(GitRepositoryAdapter):
            _adapter_name = "test_git_no_url"
            _repository_url = None

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        assert NoUrlGit.fetch_command() is None
        assert NoUrlGit.update_command() is None
        assert NoUrlGit.current_state_command() is None

    def test_fetch_command_valid_github(self):
        """Valid GitHub URL => returns git clone command."""

        class GithubGit(GitRepositoryAdapter):
            _adapter_name = "test_git_github"
            _repository_url = "https://github.com/test/myrepo"

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        cmd = GithubGit.fetch_command()
        assert cmd is not None
        assert cmd[0] == "git"
        assert cmd[1] == "clone"
        assert "--depth=1" in cmd
        assert "https://github.com/test/myrepo" in cmd

    def test_update_command_valid_github(self):
        class GithubGit2(GitRepositoryAdapter):
            _adapter_name = "test_git_github2"
            _repository_url = "https://github.com/test/myrepo2"

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        assert GithubGit2.update_command() == ["git", "pull"]

    def test_current_state_command_valid(self):
        class GithubGit3(GitRepositoryAdapter):
            _adapter_name = "test_git_github3"
            _repository_url = "https://github.com/test/myrepo3"

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        cmd = GithubGit3.current_state_command()
        assert cmd == ["git", "rev-parse", "--short", "HEAD", "--"]

    def test_non_github_url_raises(self):
        """Non-GitHub URL => RuntimeError."""

        class BitbucketGit(GitRepositoryAdapter):
            _adapter_name = "test_git_bb"
            _repository_url = "https://bitbucket.org/test/repo"

            def _get_list(self, prefix=None):
                return []

            def _get_page(self, topic, request_options=None):
                return ""

        with pytest.raises(RuntimeError, match="Do not known how to handle"):
            BitbucketGit.fetch_command()


# ---------------------------------------------------------------------------
# Test: LearnXinY factory-generated subclasses
# ---------------------------------------------------------------------------

class TestLearnXinYFactory:

    def test_simple_adapters_created(self):
        """All entries in _SIMPLE_ADAPTERS produce discoverable subclasses."""
        from adapter.learnxiny import _SIMPLE_ADAPTERS, LearnXYAdapter

        subclass_prefixes = {cls.prefix for cls in LearnXYAdapter.__subclasses__()}
        for prefix, _ in _SIMPLE_ADAPTERS:
            assert prefix in subclass_prefixes, (
                "Factory-generated adapter for '%s' not in __subclasses__()" % prefix
            )

    def test_adapters_dict_contains_all(self):
        """_ADAPTERS dict contains all expected language prefixes."""
        from adapter.learnxiny import _ADAPTERS, _SIMPLE_ADAPTERS

        for prefix, _ in _SIMPLE_ADAPTERS:
            assert prefix in _ADAPTERS, (
                "Missing '%s' in _ADAPTERS dict" % prefix
            )

    def test_complex_adapters_preserved(self):
        """Complex adapters with custom _is_block_separator are still present."""
        from adapter.learnxiny import _ADAPTERS

        complex_prefixes = [
            "clojure", "cpp", "elixir", "elm", "erlang",
            "haskell", "js", "julia", "kotlin", "lua",
            "ocaml", "perl", "php", "python", "ruby",
        ]
        for prefix in complex_prefixes:
            assert prefix in _ADAPTERS, (
                "Complex adapter '%s' missing from _ADAPTERS" % prefix
            )

    def test_factory_adapter_is_unsplitted(self):
        """Factory-generated adapters have _splitted = False."""
        from adapter.learnxiny import _ADAPTERS

        simple_prefixes = ["awk", "bash", "c", "go", "rust", "swift"]
        for prefix in simple_prefixes:
            adapter = _ADAPTERS[prefix]
            assert adapter._splitted is False, (
                "Adapter '%s' should have _splitted=False" % prefix
            )

    def test_total_adapter_count(self):
        """Total number of LearnXY adapters matches expected count."""
        from adapter.learnxiny import _ADAPTERS, _SIMPLE_ADAPTERS

        # 15 complex + len(_SIMPLE_ADAPTERS) simple
        expected = 15 + len(_SIMPLE_ADAPTERS)
        assert len(_ADAPTERS) == expected, (
            "Expected %d adapters, got %d" % (expected, len(_ADAPTERS))
        )


# ---------------------------------------------------------------------------
# Test: update_by_name
# ---------------------------------------------------------------------------

class TestUpdateByName:

    def test_unknown_adapter_returns_false(self):
        """update_by_name with unknown name returns False."""
        import fetch
        result = fetch.update_by_name("nonexistent_adapter_xyz")
        assert result is False

    def test_adapter_without_repo_returns_false(self):
        """update_by_name for an adapter with no local repository returns False."""
        import fetch
        # "search" adapter has no repository
        result = fetch.update_by_name("search")
        assert result is False

    def test_adapter_repo_not_fetched_returns_false(self):
        """update_by_name for an adapter whose repo doesn't exist on disk returns False."""
        import fetch
        # "tldr" has a repository URL but in test env the repo dir doesn't exist
        result = fetch.update_by_name("tldr")
        assert result is False


# ---------------------------------------------------------------------------
# Test: fetch.py main() argument handling
# ---------------------------------------------------------------------------

class TestFetchMain:

    def test_update_without_name_exits(self):
        """'update' without adapter name should exit with error."""
        import fetch
        with pytest.raises(SystemExit):
            fetch.main(["update"])


# ---------------------------------------------------------------------------
# Test: all_adapters discovery still works
# ---------------------------------------------------------------------------

class TestAdapterDiscovery:

    def test_all_adapters_returns_nonempty(self):
        adapters = all_adapters()
        assert len(adapters) > 0

    def test_adapter_by_name_found(self):
        # GitRepositoryAdapter subclasses should be discoverable
        from adapter.cheat_cheat import Cheat
        found = adapter_by_name("cheat")
        assert found is not None
        assert found is Cheat

    def test_adapter_by_name_not_found(self):
        assert adapter_by_name("nonexistent_xyz") is None


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def cleanup_tmp():
    yield
    shutil.rmtree(_tmp_repos, ignore_errors=True)

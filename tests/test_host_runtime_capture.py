"""Host capture follows the actual caller's Runtime at the Adapter boundary."""

from pathlib import Path

import pytest

from graphtraj.runtimes import replacement, runtime_adapter
from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter


def test_capture_uses_discovered_host_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another host's opaque connection survives without Codex interpretation."""
    connection = {'runtime': 'other-host', 'opaque': {'receiver': 'existing'}}

    class HostAdapter:
        """Represent a host whose native connection is not a Codex structure."""

        def current_host_connection(self) -> dict:
            """Return the connection owned by this host."""
            return connection

    def select(runtime: str) -> HostAdapter:
        """Require the discovered caller, regardless of inherited Codex flags."""
        assert runtime == 'other-host'
        return HostAdapter()

    monkeypatch.setenv('CODEX_THREAD_ID', 'unrelated-inherited-thread')
    monkeypatch.setattr(replacement, 'caller_runtime', lambda: 'other-host')
    monkeypatch.setattr(runtime_adapter, 'select_runtime_adapter', select)
    assert runtime_adapter.current_host_connection() is connection


@pytest.mark.parametrize('runtime', [None, 'unsupported-host'])
def test_unavailable_host_has_no_capture(
    monkeypatch: pytest.MonkeyPatch, runtime: str | None,
) -> None:
    """Inherited native flags cannot turn an unknown caller into a Codex host."""
    monkeypatch.setenv('CODEX_THREAD_ID', 'unrelated-inherited-thread')
    monkeypatch.setattr(replacement, 'caller_runtime', lambda: runtime)
    assert runtime_adapter.current_host_connection() is None


def test_codex_adapter_owns_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The selected Codex capability retains native home/session and role rules."""
    monkeypatch.delenv('GRAPHTRAJ_ROLE', raising=False)
    monkeypatch.setenv('CODEX_THREAD_ID', 'owning-thread')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    monkeypatch.setattr(replacement, 'caller_runtime', lambda: 'codex')
    assert runtime_adapter.current_host_connection() == {
        'runtime': 'codex', 'session': 'owning-thread', 'codex_home': str(tmp_path),
    }
    monkeypatch.setenv('GRAPHTRAJ_ROLE', 'engineer')
    assert CodexRuntimeAdapter().current_host_connection() is None

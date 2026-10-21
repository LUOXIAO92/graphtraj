"""Native ancestry authorizes the MCP host without model-supplied identities."""

import asyncio
from pathlib import Path

import pytest

from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.codex.managed_session import authorize_mcp_caller, native_operation_features
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_codex_app_server import context, peer


@pytest.mark.parametrize('issuer', ['thread-1', 'helper', 'outsider'])
def test_native_status_uses_authenticated_mcp_identity(
    tmp_path: Path, peer: Path, issuer: str,
) -> None:
    """The same native parent chain governs host operations after MCP migration."""
    from graphtraj.execution.runner_models import RunnerError

    async def exercise() -> None:
        """Resolve the caller using the Runtime transport used by the MCP host."""
        async with CodexAppServer(
            command=[str(peer)], cwd=tmp_path,
            environment={'PEER_THREAD_PARENTS': '{"helper":"thread-1","outsider":"unrelated","unrelated":null}'},
        ) as adapter:
            session = await adapter.create_session(context(tmp_path, peer))
            native = {'runtime': 'codex', 'session': issuer, 'cwd': str(tmp_path)}
            if issuer == 'outsider':
                with pytest.raises(RunnerError, match='outside'):
                    await authorize_mcp_caller(adapter, session.thread_id, 'probe@l1', tmp_path, tmp_path, native)
                return
            alias, features = await authorize_mcp_caller(
                adapter, session.thread_id, 'probe@l1', tmp_path, tmp_path, native,
            )
            if issuer == 'thread-1':
                assert alias == 'probe@l1'
                assert features == native_operation_features()
            else:
                assert alias == 'helper'
                assert features == {'task_graph', 'agents'}

    asyncio.run(exercise())


def test_native_parent_cannot_change(tmp_path: Path, peer: Path) -> None:
    """Reject a native metadata response that would reparent an observed entity."""
    async def exercise() -> None:
        """Use metadata-only requests over the public Adapter connection."""
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  environment={'PEER_THREAD_PARENTS': '{"helper":["first","second"]}'}) as adapter:
            assert await adapter.read_thread_parent('helper') == 'first'
            with pytest.raises(RuntimeAdapterError):
                await adapter.read_thread_parent('helper')

    asyncio.run(exercise())

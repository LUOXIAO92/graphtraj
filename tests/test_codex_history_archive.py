"""Ordered ephemeral history is evidence, never a fabricated model prompt."""

import asyncio
import json
from pathlib import Path

import pytest

from agent_swarm import write_config
from graphtraj.interfaces.agents import ConfiguredSessionArchive
from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.sessions.archive import JsonlSessionStore, archive_path
from graphtraj.sessions.protocol import native_record
from test_codex_app_server import peer  # noqa: F401


@pytest.mark.parametrize('initial_failure', [False, True])
def test_owned_fork_reads_ascending_pages_and_retains_projection_limit(
    tmp_path: Path, peer: Path, initial_failure: bool,
) -> None:
    """Retry a native failure and retain ordered pages without trusting emissions."""
    async def exercise() -> None:
        """Exercise the public Runtime seam with an external protocol peer."""
        root = tmp_path / 'swarm'
        write_config(root, save_normalized_sessions=True, backfill_history=True)
        pages = tmp_path / 'pages.json'
        first = {'turnId': 'inherited', 'startedAtMs': 19, 'completedAtMs': 20,
                 'item': {'id': 'u', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'old'}]}}
        second = {'turnId': 'inherited', 'startedAtMs': 18, 'completedAtMs': 21,
                  'item': {'id': 'a', 'type': 'agentMessage', 'text': 'answer', 'future': [None]}}
        pages.write_text(json.dumps({'code': -32000, 'message': 'retry'} if initial_failure else [[first]]))
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  environment={'PEER_HISTORY_PAGES': str(pages)}) as adapter:
            child = await adapter.fork_session({'id': 'parent', 'model': 'same', 'modelProvider': 'same'})
            await adapter.retain_ordered_history(child, ConfiguredSessionArchive(root), 'checker:' + child.thread_id)
            path = archive_path(root, 'codex:' + child.thread_id)
            if initial_failure:
                assert JsonlSessionStore(path).pending()
            pages.write_text(json.dumps([[first], [second]]))
        store = JsonlSessionStore(path)
        assert store.header['createdAt'] == 17000
        assert store.header['parentSession'] == 'codex:parent'
        assert not store.pending()
        snapshot = native_record(store.page()['events'][-1])
        assert [entry for page in snapshot['pages'] for entry in page['data']] == [first, second]
        with pytest.raises(ValueError, match='opaque-native|incomplete'):
            store.messages()

    asyncio.run(exercise())


def test_ephemeral_saving_and_backfill_are_effective(tmp_path: Path, peer: Path) -> None:
    """Collection off writes no body; enabling backfill captures native prefix."""
    async def exercise() -> None:
        """Keep one owned child while changing the archive's public configuration."""
        root = tmp_path / 'swarm'
        write_config(root, save_normalized_sessions=True, backfill_history=False)
        pages = tmp_path / 'pages.json'
        entry = {'turnId': 'parent', 'item': {'type': 'agentMessage', 'id': 'old', 'text': 'prefix'}}
        pages.write_text(json.dumps([[entry]]))
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path,
                                  environment={'PEER_HISTORY_PAGES': str(pages)}) as adapter:
            child = await adapter.fork_session({'id': 'parent', 'model': 'same', 'modelProvider': 'same'})
            await adapter.retain_ordered_history(child, ConfiguredSessionArchive(root), 'checker')
            path = archive_path(root, 'codex:' + child.thread_id)
            before = path.read_bytes()
            write_config(root, save_normalized_sessions=False)
            execution = await adapter.start_execution(child, 'saving off')
            await adapter.wait(execution)
            assert path.read_bytes() == before
            write_config(root, save_normalized_sessions=True, backfill_history=True)
        store = JsonlSessionStore(path)
        assert native_record(store.page()['events'][0])['pages'][0]['data'] == []
        assert native_record(store.page()['events'][-1])['pages'][0]['data'] == [entry]

    asyncio.run(exercise())


def test_rejected_session_does_not_register_an_archive_source(tmp_path: Path, peer: Path) -> None:
    """Ownership rejection must precede the collector's public mapping side effect."""
    from graphtraj.runtimes.codex.app_server import CodexSession
    from agent_swarm.runtime import RuntimeAdapterError
    from graphtraj.sessions.archive import SessionArchive

    async def exercise() -> None:
        """Use the public native control and archive capabilities."""
        archive = SessionArchive(tmp_path / 'archive', save_normalized_sessions=True)
        foreign = CodexSession('unowned', None, inherited_history={'id': 'unowned'})
        async with CodexAppServer(command=[str(peer)], cwd=tmp_path) as adapter:
            with pytest.raises(RuntimeAdapterError):
                await adapter.retain_ordered_history(foreign, archive, 'other-agent')
        with pytest.raises(ValueError, match='explicitly mapped'):
            archive.store('codex:unowned')

    asyncio.run(exercise())

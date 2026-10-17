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

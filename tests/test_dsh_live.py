"""Cursorless DSH observations remain distinct from canonical Session events."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from conftest import unsupported_dsh

from agent_swarm.sessions.dsh_live import DshLiveFrames
from agent_swarm.sessions.protocol import snapshot_event


def test_interrupted_stream_replay_and_native_final_link() -> None:
    """Persist compact partial text and use only the end frame's native seq."""
    saved, links = [], []
    live = DshLiveFrames('s', 'execution-1',
                        lambda event, position: saved.append((snapshot_event(event), position)),
                        lambda observation, final: links.append((observation, final)))
    live.accept({'type': 'start', 'attemptId': 's:0', 'revision': 1,
                 'startedAfterSeq': 4, 'turn': 1, 'step': 0})
    first = {'type': 'chunk', 'attemptId': 's:0', 'revision': 2, 'index': 0,
             'time': 100, 'chunk': {'type': 'text-delta', 'index': 0, 'text': 'part'}}
    live.accept(first)
    live.accept(first)
    live.accept({**first, 'revision': 3, 'index': 1, 'time': 90,
                 'chunk': {**first['chunk'], 'text': 'ial'}})
    partial = saved[-1][0]
    assert partial['seq'] == 0  # Only a pending template, not the predicted final seq.
    assert partial['data']['stream'] == [
        {'type': 'text-chunks', 'index': 0, 'time0': 100, 'dt': [-10], 'texts': ['part', 'ial']},
    ]
    assert len(saved) == 3
    assert not links
    live.accept({'type': 'end', 'attemptId': 's:0', 'revision': 4, 'index': 2,
                 'outcome': {'kind': 'committed', 'eventType': 'assistant/attempt', 'seq': 7}})
    assert links == [(('dsh', 's', 'live/execution-1/s:0'), ('dsh', 's', 'event/7'))]
    assert saved[-1][0]['data']['stream'] == partial['data']['stream']
    assert saved[-1][0]['native']['record']['outcome']['seq'] == 7


def test_reconnect_baseline_and_abandoned_attempt() -> None:
    """Native reconnect compaction seeds live state; abandonment keeps evidence."""
    saved, links = [], []
    live = DshLiveFrames('s', 'execution-2', lambda event, position: saved.append(deepcopy(event)),
                        lambda *keys: links.append(keys))
    live.baseline({'revision': 6, 'activeAttempt': {
        'attemptId': 's:0', 'startedAfterSeq': 3, 'turn': 1, 'step': 2, 'nextIndex': 1,
        'stream': [{'type': 'text-chunks', 'index': 0, 'time0': 100, 'dt': [], 'texts': ['kept']}],
    }})
    live.accept({'type': 'end', 'attemptId': 's:0', 'revision': 7, 'index': 1,
                 'outcome': {'kind': 'abandoned'}})
    assert not links
    assert saved[-1]['data']['stream'][0]['texts'] == ['kept']
    assert saved[-1]['native']['locator'] == 'live/execution-2/s:0'
    with pytest.raises(ValueError, match='revision'):
        live.accept({'type': 'start', 'revision': 9})


def test_installed_native_relay_without_duplicate_model_content() -> None:
    """Native registration and Session projection; not official UI acceptance."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH and Node are required.')
    if (reason := unsupported_dsh()) is not None:
        pytest.skip(reason)
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([
        node, str(root / 'tests/fixtures/dsh_communication.mjs'), str(Path(dsh).resolve()),
        str(root / 'src/agent_swarm/dsh/communication.mjs'),
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    native = json.loads(result.stdout.strip().splitlines()[-1])
    saved = []
    live = DshLiveFrames('session', 'execution', lambda event, position: saved.append(event),
                        lambda *keys: None)
    live.accept({'type': 'start', 'attemptId': 'a', 'revision': 1,
                 'startedAfterSeq': -1, 'turn': 0, 'step': 0})
    for index, chunk in enumerate(native['chunks']):
        live.accept({'type': 'chunk', 'attemptId': 'a', 'revision': index + 2,
                     'index': index, **chunk})
    assert saved[-1]['data']['stream'] == native['stream']


def test_standalone_driver_with_only_independent_package(tmp_path: Path) -> None:
    """Exercise explicit preparation and control without GraphTraj imports."""
    if shutil.which('dsh') is None:
        pytest.skip('Installed native DSH package metadata is required.')
    if (reason := unsupported_dsh()) is not None:
        pytest.skip(reason)
    root = Path(__file__).resolve().parents[1]
    modules = tmp_path / 'modules'
    shutil.copytree(root / 'src/agent_swarm', modules / 'agent_swarm')
    working = tmp_path / 'working'
    working.mkdir()
    result = subprocess.run([
        sys.executable, str(root / 'tests/fixtures/dsh_standalone.py'), str(working),
    ], cwd=working, env={**os.environ, 'PYTHONPATH': os.pathsep.join((str(modules), os.environ.get('PYTHONPATH', '')))},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr

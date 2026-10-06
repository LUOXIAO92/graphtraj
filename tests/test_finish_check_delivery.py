"""Hook-visible outcomes never become new Main input; only work requests continuation."""

import json
from typing import Callable

import pytest

from graphtraj.execution.host_adoption import external_main
from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter
from test_host_adoption import EVENT, external, invoke_hook
from test_main_finalize import host, options


@pytest.mark.parametrize('status,reason,nodes', [
    ('completed', 'The authorized goal is complete.', []),
    ('waiting', 'Budget exhausted; subtree stopped; fresh user authorization is required.', ['272']),
    ('actionable', 'Node272 has authorized unfinished work.', ['272']),
    ('error', 'The authoritative current Issue cannot be read.', []),
])
def test_hook_outputs_do_not_wake_main(
    external: tuple,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    reason: str,
    nodes: list[str],
) -> None:
    """Exercise real fixed-handler delivery with controlled checker conclusions only.

    This test does not claim native full-configuration capture or inheritance.
    """
    root, _, delivered = external
    checks = []
    options((root, None, None), read_id_from_request=True, turns_by_thread={
        'controlled-checker-1': 'child-turn-1', 'controlled-checker-2': 'child-turn-2',
    })

    def check(
        adapter: object, binding: dict, context: dict, prompt: str, created: Callable,
    ) -> dict:
        """Control one checker outcome, retaining its actual registered identity."""
        identity = binding['checker_tool']({
            'action': 'execute', 'feature': 'agent_identity', 'arguments': {},
        }).document
        assert identity['purpose'] == 'checker'
        checks.append(identity)
        created(f'controlled-checker-{len(checks)}')
        return {'session': f'controlled-checker-{len(checks)}',
                'output': json.dumps({'status': status, 'reason': reason, 'nodes': nodes})}

    monkeypatch.setattr(CodexRuntimeAdapter, 'check_main_finalize', check)
    with external_main(root) as ready:
        # Two genuine invocations are both displayed; there is no debounce/dedup.
        for _ in range(2):
            process = invoke_hook(ready, EVENT)
            assert process.returncode == 0, process.stderr
            assert '[GraphTraj hook: finish-check] start:' in process.stderr
            result = json.loads(process.stdout)
            assert '[GraphTraj hook: finish-check] start:' in result['systemMessage']
            assert reason in result['systemMessage']
            assert all(item['parent'] == ready['alias'] for item in checks)
            if status == 'actionable':
                assert result['decision'] == 'block'
                assert '272' in result['reason']
            else:
                assert 'decision' not in result
            if status == 'waiting':
                assert 'waiting:' in result['systemMessage']
                assert 'Allow this turn to end' in result['systemMessage']
                assert 'task remains unfinished' in result['systemMessage']
                assert 'pass:' not in result['systemMessage']
            if status == 'error':
                assert result['continue'] is False
                assert 'failure:' in result['stopReason']
    assert len(checks) == 2
    assert delivered == []
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(item['method'] in ('turn/start', 'turn/steer') for item in wire)

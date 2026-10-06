"""Unsupported native configuration capture refuses visibly before checker creation."""

import json

import pytest

from test_main_finalize import host, options, records, stop
from test_host_adoption import external


@pytest.mark.parametrize('configuration', [
    {},
    {'model': 'actual-model', 'modelProvider': 'actual-provider', 'reasoningEffort': 'xhigh'},
    {'model': 'actual-model', 'modelProvider': 'actual-provider', 'reasoningEffort': 'high',
     'serviceTier': 'fast', 'approvalPolicy': 'on-request', 'personality': 'friendly'},
])
def test_configured_settings_cannot_stand_in_for_effective_turn(
    host: tuple, configuration: dict,
) -> None:
    """Neither absent nor plausible thread defaults certify the checked turn's options."""
    root, owner, visible = host
    options(host, thread_config=configuration)
    result = stop(host)
    assert result['decision'] == 'block'
    assert 'complete effective Main turn configuration' in result['reason']
    assert 'no checker was started' in result['reason']
    assert len(visible) == 2
    assert all(event['alias'] == owner.alias for event in visible)
    assert '[GraphTraj hook: finish-check] start:' in visible[0]['message']
    assert '[GraphTraj hook: finish-check] failure:' in visible[1]['message']
    requests = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    assert not any(item['method'] in ('thread/fork', 'turn/start', 'config/read') for item in requests)
    assert not records(root)


def test_stopped_main_does_not_attempt_configuration_capture(host: tuple) -> None:
    """Actual stopped lifecycle remains an exclusion before checker execution."""
    options(host, stopped=True)
    result = stop(host)
    assert 'skip:' in result['systemMessage']
    assert not records(host[0])


def test_fixed_hook_process_exposes_configuration_failure(
    external: tuple,
) -> None:
    """The actual generated handler emits its marker and blocking failure on its streams."""
    from graphtraj.execution.host_adoption import external_main
    from test_host_adoption import EVENT, invoke_hook

    root, _, visible = external
    with external_main(root) as ready:
        process = invoke_hook(ready, EVENT)
    assert process.returncode == 0
    assert '[GraphTraj hook: finish-check] start:' in process.stderr
    result = json.loads(process.stdout)
    assert result['decision'] == 'block'
    assert '[GraphTraj hook: finish-check] failure:' in result['reason']
    assert 'complete effective Main turn configuration' in result['reason']
    assert 'failure:' in visible[-1]['message']
    assert not records(root)

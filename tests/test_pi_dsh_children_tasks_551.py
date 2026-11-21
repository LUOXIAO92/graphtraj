"""Task-free DSH and Pi children get GraphTraj's ``tasks`` entry beside ``agents`` (551).

The binding is checked at GraphTraj's seam: the tools reach the child's own
authenticated channel (graftling's ``agents_connection``) bound to the child's
own Agent ID. No model or real Runtime starts.
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import graftling.dsh.binding as binding
from graftling import AgentsResult
from graphtraj.execution.agent_driver import AdapterDriver
from graphtraj.runtimes.dsh.driver import bind_agents


class Events:
    def receive_children(self, receive) -> None:
        pass


def test_dsh_child_channel_serves_tasks_bound_to_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bind_agents gives the DSH child's channel GraphTraj's tasks tool, served as that child."""
    calls: list[dict] = []

    def record(*args, **options):
        calls.append(options)
        return nullcontext('/fake/address')

    monkeypatch.setattr(binding, 'agents_connection', record)
    served: list[tuple] = []
    monkeypatch.setattr('graphtraj.interfaces.task_free.serve_task_free',
                        lambda root, agent, request: served.append((root, agent, request)) or AgentsResult({'ok': True}))
    turn = SimpleNamespace(request={}, native_header=None, service=None)
    run = SimpleNamespace(call=lambda request: AgentsResult({}), settings={}, agent='agent-551child', events=Events(),
                          archive=None, session=None, extra_fields=None)
    bind_agents(turn, run, AdapterDriver(tmp_path, tmp_path))
    with turn.host_connection(tmp_path) as address:
        assert address == '/fake/address'
    (descriptor, callback), = calls[0]['extra_tools']
    assert descriptor['name'] == 'tasks'
    assert callback({'action': 'discover'}).document == {'ok': True}
    assert served == [(tmp_path, 'agent-551child', {'action': 'discover'})]
    # The child's agents entry is unchanged: graftling's own MCP server on the same channel.
    assert turn.request['mcp']['args'] == ['-I', '-m', 'graftling.mcp']


def test_pi_child_tools_reach_its_launch_request(tmp_path: Path) -> None:
    """apply_child_tools hands Pi the create's choice; Pi applies it as --tools/--exclude-tools at launch."""
    from graftling import AgentsError
    from graphtraj.execution.agent_driver import apply_child_tools

    request = {'executable': '/x/pi', 'agent_dir': str(tmp_path)}
    apply_child_tools('pi', request, {'tools': ['read', 'grep'], 'disallowed_tools': ['bash', 'mcp__graphtraj__tasks']})
    assert request == {'executable': '/x/pi', 'agent_dir': str(tmp_path), 'tools': ['read', 'grep'],
                       'disallowed_tools': ['bash', 'mcp__graphtraj__tasks']}
    # An entry the Pi child provably does not know refuses the create (551 user decision).
    with pytest.raises(AgentsError) as refused:
        apply_child_tools('pi', {'agent_dir': str(tmp_path)}, {'tools': ['nosuchtool'], 'disallowed_tools': []})
    assert refused.value.code == 'unavailable' and 'nosuchtool' in refused.value.message


def dsh_install(tmp_path: Path) -> str:
    """A DSH install root whose web-app bundle declares a preset with two tool rows, one disabled."""
    import json

    bundle = tmp_path / 'dsh/node_modules/@deepseek-ai/dsh-web-app'
    (bundle / 'presets').mkdir(parents=True)
    (bundle / 'package.json').write_text(json.dumps({'dsh': {'bundle': {'patch': ['./presets/standard.patch.yml']}}}))
    (bundle / 'presets/standard.patch.yml').write_text(
        "- insert:\n    - id: preset-standard\n      name: '@deepseek-ai/dsh-agent-preset'\n      config:\n"
        "        id: standard\n        plugins:\n          - {id: persona, name: '@deepseek-ai/dsh-persona'}\n"
        "          - {id: tool-web, name: '@deepseek-ai/dsh-tool-web'}\n"
        "          - {id: tool-plugin-market, name: x, disabled: true}\n")
    return str(tmp_path / 'dsh/package.json')


def test_dsh_child_tools_are_checked_against_the_installed_preset(tmp_path: Path) -> None:
    """A row id narrows freely; an unknown id is unavailable; a host-disabled row is authorization-required."""
    from graftling import AgentsError
    from graphtraj.execution.agent_driver import apply_child_tools

    request = {'package': dsh_install(tmp_path)}
    apply_child_tools('dsh', request, {'tools': None, 'disallowed_tools': ['tool-web']})
    assert (request['tools'], request['disallowed_tools']) == (None, ['tool-web'])
    for tools, code in (({'tools': ['web_fetch'], 'disallowed_tools': []}, 'unavailable'),
                        ({'tools': ['tool-plugin-market'], 'disallowed_tools': []}, 'authorization-required')):
        with pytest.raises(AgentsError) as refused:
            apply_child_tools('dsh', {'package': request['package']}, tools)
        assert refused.value.code == code

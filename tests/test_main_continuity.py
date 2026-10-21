"""Project Main continuity shared by every Runtime that can host Main."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_swarm import AgentControl, AgentsError, Caller, bind
from graphtraj.execution import main_continuity
from graphtraj.execution.main_continuity import (
    MainRoots, claim_main, claimable, current_main, owns_main_root, queue_notice,
    require_control, require_feature_control, route_notice,
    acknowledge_notices, pending_notices,
)
from graphtraj.execution.runner_connection import parent_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from test_agent_control import ScriptedDriver


CODEX  = {'runtime': 'codex', 'session': 'codex-main', 'codex_home': '/home/.codex', 'hook_session': 'hook'}
CLAUDE = {'runtime': 'claude', 'session': 'claude-main'}


def test_claims_are_appended_and_link_their_predecessor(tmp_path: Path) -> None:
    """A new entry continues Main; repeating the current claim adds nothing."""
    assert current_main(tmp_path) is None
    claim_main(tmp_path, CODEX, 'codex:SessionStart:startup')
    claim_main(tmp_path, CODEX, 'codex:SessionStart:resume')
    claim_main(tmp_path, {**CLAUDE, 'native_header': {'large': True}}, 'claude:first-control')

    records = main_continuity.claims(tmp_path)
    assert [record['session'] for record in records] == ['codex-main', 'claude-main']
    assert records[1]['previous'] == {'runtime': 'codex', 'session': 'codex-main'}
    # Only the string locator is kept, never configuration objects.
    assert records[1]['connection'] == CLAUDE
    assert records[0]['connection'] == CODEX


def test_single_controller_decision(tmp_path: Path) -> None:
    """Before any claim nothing changes; afterwards only the current Main controls."""
    require_control(tmp_path, CODEX)
    require_control(tmp_path, None)

    claim_main(tmp_path, CODEX, 'codex:SessionStart:startup')
    require_control(tmp_path, CODEX)
    claim_main(tmp_path, CLAUDE, 'claude:first-control')
    require_control(tmp_path, CLAUDE)
    with pytest.raises(RunnerError) as refused:
        require_control(tmp_path, CODEX)
    assert refused.value.code == 'main-continued'
    assert 'claude-main' in refused.value.message
    # A human CLI call carries no native connection and keeps its authority.
    require_control(tmp_path, None)
    # A native helper that never was Main keeps its own authorization result.
    require_control(tmp_path, {'runtime': 'codex', 'session': 'native-helper'})


def test_first_control_claims_only_for_a_fresh_host_entry(tmp_path: Path) -> None:
    """A host without entry events claims at first control, never after being superseded."""
    claim_main(tmp_path, CODEX, 'codex:SessionStart:startup')
    entered: set[str] = set()

    def call() -> None:
        """Model one Claude host call that may claim only on its first control."""
        mark = None if 'claude-main' in entered else (lambda: entered.add('claude-main'))
        with claimable(mark):
            require_control(tmp_path, CLAUDE)

    call()
    assert current_main(tmp_path)['session'] == 'claude-main'
    claim_main(tmp_path, CODEX, 'codex:SessionStart:resume')
    with pytest.raises(RunnerError) as refused:
        call()
    assert refused.value.code == 'main-continued'
    assert current_main(tmp_path)['session'] == 'codex-main'


def test_current_main_continues_roots_of_earlier_main_sessions(tmp_path: Path) -> None:
    """Default status shows earlier Main roots; the earlier Main may read but not control."""
    runner  = tmp_path / 'runner'
    driver  = ScriptedDriver()
    control = AgentControl(tmp_path / 'swarm', {'claude': driver}, roots=MainRoots(runner))
    codex   = bind(control, Caller('graphtraj-gateway', None, 'codex-main', 'codex'))
    claude  = bind(control, Caller('claude-native', None, 'claude-main', 'claude'))
    member  = bind(control, Caller('runtime-mcp', 'agent-other', 'native-child', 'claude'))

    claim_main(runner, CODEX, 'codex:SessionStart:startup')
    created = codex({'action': 'create', 'runtime': 'claude', 'instruction': 'first', 'name': 'leader'})
    assert not created.failed
    agent = created.document['agent']
    for release in list(driver.releases.values()):
        release.set()
    assert not codex({'action': 'wait', 'agent': agent, 'timeout_seconds': 5}).failed

    # Claude reads the same member before it has claimed anything.
    listed = claude({'action': 'status'}).document['result']['agents']
    assert [item['agent'] for item in listed] == [agent]
    assert listed[0]['creator'] == {'host': 'graphtraj-gateway', 'agent': None, 'session': 'codex-main'}
    assert listed[0]['parent'] is None
    # A member or native child never sees Main's roots.
    assert member({'action': 'status'}).document['result']['agents'] == []

    with claimable(lambda: None):
        resumed = claude({'action': 'resume', 'agent': agent, 'message': 'continue'})
    assert not resumed.failed
    assert current_main(runner)['session'] == 'claude-main'
    refused = codex({'action': 'send', 'agent': agent, 'message': 'second'})
    assert refused.document['error']['code'] == 'main-continued'
    assert codex({'action': 'status'}).document['result']['agents'][0]['agent'] == agent
    for release in list(driver.releases.values()):
        release.set()

    record = json.loads((tmp_path / 'swarm/control/agents' / f'{agent}.json').read_text())
    assert record['parent'] is None and record['creator']['session'] == 'codex-main'
    assert len(driver.started) == 2


def test_notices_follow_the_current_main_without_rewriting_owners(tmp_path: Path) -> None:
    """An earlier Main's root reports to the current Main; others are unchanged."""
    claim_main(tmp_path, CODEX, 'codex:SessionStart:startup')
    assert route_notice(tmp_path, CODEX) == CODEX
    claim_main(tmp_path, {**CLAUDE, 'runner': str(tmp_path)}, 'claude:first-control')
    assert route_notice(tmp_path, CODEX) == {**CLAUDE, 'runner': str(tmp_path)}
    stranger = {'runtime': 'codex', 'session': 'not-main', 'codex_home': '/x'}
    assert route_notice(tmp_path, stranger) == stranger
    # A Pi Main cannot receive host events yet: delivery stays with the owner.
    claim_main(tmp_path, {'runtime': 'pi', 'session': 'pi-main', 'session_file': '/s'}, 'pi:session_start:startup')
    assert route_notice(tmp_path, CODEX) == CODEX
    claim_main(tmp_path, {**CLAUDE, 'runner': str(tmp_path)}, 'claude:first-control')

    assert owns_main_root(tmp_path, CODEX, CLAUDE)
    assert not owns_main_root(tmp_path, CLAUDE, CODEX)
    assert not owns_main_root(tmp_path, stranger, CLAUDE)


def test_claude_main_notices_stay_queued_until_acknowledged(tmp_path: Path) -> None:
    """The Claude Adapter queues durably; a notice leaves the queue only once acknowledged."""
    from graphtraj.runtimes.claude.adapter import ClaudeRuntimeAdapter

    connection = {**CLAUDE, 'runner': str(tmp_path)}
    receipt = ClaudeRuntimeAdapter().send_host_event(connection, {'source': 'graphtraj', 'alias': 'a@l1'})
    assert receipt['accepted'] is True
    queue_notice(tmp_path, connection, {'source': 'graphtraj', 'alias': 'b@l1'})
    notices, position = pending_notices(tmp_path, 'claude', 'claude-main')
    assert [item['event']['alias'] for item in notices] == ['a@l1', 'b@l1']
    # Not yet acknowledged: offered again, never lost.
    assert pending_notices(tmp_path, 'claude', 'claude-main')[0] == notices
    acknowledge_notices(tmp_path, 'claude', 'claude-main', position)
    assert pending_notices(tmp_path, 'claude', 'claude-main')[0] == []
    assert pending_notices(tmp_path, 'claude', 'other') == ([], 0)

    # A Claude Main continued by another Claude Main hands over what is pending.
    queue_notice(tmp_path, connection, {'source': 'graphtraj', 'alias': 'c@l1'})
    claim_main(tmp_path, connection, 'claude:first-control')
    claim_main(tmp_path, {'runtime': 'claude', 'session': 'claude-next', 'runner': str(tmp_path)}, 'claude:first-control')
    assert pending_notices(tmp_path, 'claude', 'claude-main')[0] == []
    assert [item['event']['alias'] for item in pending_notices(tmp_path, 'claude', 'claude-next')[0]] == ['c@l1']


def test_task_controls_are_gated_for_main_callers_only(tmp_path: Path, monkeypatch) -> None:
    """Reads, members and human CLI calls keep their behavior; a continued Main is refused."""
    runner = tmp_path / '.graphtraj/runner'
    monkeypatch.setattr('graphtraj.workspace.runner_project.discover_runner_directory', lambda cwd: runner)
    claim_main(runner, CODEX, 'codex:SessionStart:startup')
    claim_main(runner, CLAUDE, 'claude:first-control')

    with runtime_caller(runner, None), parent_connection(dict(CODEX)):
        require_feature_control('task_graph', tmp_path)
        with pytest.raises(RunnerError) as refused:
            require_feature_control('decide_result', tmp_path)
        assert refused.value.code == 'main-continued'
    with runtime_caller(runner, None), parent_connection(dict(CLAUDE)):
        require_feature_control('decide_result', tmp_path)
    with runtime_caller(runner, 'member@l1'), parent_connection(dict(CODEX)):
        require_feature_control('decide_result', tmp_path)
    require_feature_control('decide_result', tmp_path)


def test_claude_host_serves_agents_and_tasks_as_the_continuing_main(tmp_path: Path) -> None:
    """One verified Claude Main reads, claims at first control and receives notices."""
    from graphtraj.runtimes.claude.host import main_calls

    runner  = tmp_path / '.graphtraj/runner'
    driver  = ScriptedDriver()
    control = AgentControl(tmp_path / '.graphtraj/swarm', {'claude': driver}, roots=MainRoots(runner))
    codex   = bind(control, Caller('graphtraj-gateway', None, 'codex-main', 'codex'))
    claim_main(runner, CODEX, 'codex:SessionStart:startup')
    agent = codex({'action': 'create', 'runtime': 'claude', 'instruction': 'first'}).document['agent']
    for release in list(driver.releases.values()):
        release.set()
    codex({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})

    call = main_calls(tmp_path, control, None)('claude-main', tmp_path)
    listed = call('agents', {'action': 'execute', 'feature': 'status', 'arguments': {}})
    assert [item['agent'] for item in listed.document['result']['agents']] == [agent]
    assert current_main(runner)['session'] == 'codex-main'
    features = call('tasks', {'action': 'discover'}).document['features']
    assert 'task_graph' in {item['feature'] for item in features}
    assert current_main(runner)['session'] == 'codex-main'

    queue_notice(runner, {**CLAUDE, 'runner': str(runner)}, {'alias': 'leader@l1', 'message': 'done'})
    sent = call('agents', {'action': 'execute', 'feature': 'send', 'arguments': {'agent': agent, 'message': 'go'}})
    assert not sent.failed
    assert current_main(runner)['session'] == 'claude-main'
    assert sent.document['main_notices'][0]['event']['alias'] == 'leader@l1'
    assert pending_notices(runner, 'claude', 'claude-main')[0] == []
    # The claim made through agents keeps the host's full connection, so an
    # earlier Main's root notice reaches this Claude Main's queue (S1).
    from graphtraj.runtimes.claude.adapter import ClaudeRuntimeAdapter

    routed = route_notice(runner, CODEX)
    assert routed['session'] == 'claude-main'
    assert ClaudeRuntimeAdapter().send_host_event(routed, {'alias': 'root@l1', 'message': 'ended'})['accepted']
    assert [item['event']['alias'] for item in pending_notices(runner, 'claude', 'claude-main')[0]] == ['root@l1']
    for release in list(driver.releases.values()):
        release.set()
    codex({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})

    # Codex resumes Main; the same Claude host process no longer controls.
    claim_main(runner, CODEX, 'codex:SessionStart:resume')
    refused = call('agents', {'action': 'execute', 'feature': 'send', 'arguments': {'agent': agent, 'message': 'again'}})
    assert refused.document['error']['code'] == 'main-continued'
    assert current_main(runner)['session'] == 'codex-main'
    assert len(driver.started) == 2

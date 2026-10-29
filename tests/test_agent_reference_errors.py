"""Task 390: a readable name in ``agent`` is refused with a hint naming the references.

The public ``agent`` field takes the reference create or status returned; a
name grants no identity. The refusal keeps its code, explains that and lists
only Agents visible to the caller carrying that name.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_swarm import AgentControl, AgentsError, Binding, Caller, bind
from graphtraj.execution.main_continuity import MainRoots, claim_main
from test_agent_control import ScriptedDriver


HINT = '`agent` takes the reference returned by create or status, not the readable name.'


@pytest.mark.parametrize('action, extra', [('retire', {}), ('send', {'message': 'hi'}), ('interrupt', {})])
def test_standalone_name_refusal_names_visible_references(tmp_path: Path, action: str, extra: dict) -> None:
    """Standalone ``not-found`` explains the field and lists only the caller's Agents."""
    control  = AgentControl(tmp_path / 'data', {'scripted': ScriptedDriver()})
    main     = Caller('test-host', None, session='host-session')
    stranger = Caller('test-host', None, session='another-session')
    mine     = bind(control, main)({'action': 'create', 'runtime': 'scripted',
                                    'instruction': 'a', 'name': 'p377a'}).document['agent']
    hidden   = bind(control, stranger)({'action': 'create', 'runtime': 'scripted',
                                        'instruction': 'b', 'name': 'p377a'}).document['agent']

    refused = bind(control, main)({'action': action, 'agent': 'p377a', **extra})
    assert refused.failed and refused.document['error']['code'] == 'not-found'
    message = refused.document['error']['message']
    assert HINT in message and mine in message and hidden not in message

    # A hidden reference reads exactly like an absent one: no existence leak.
    absent   = bind(control, stranger)({'action': action, 'agent': 'agent-absent', **extra})
    concealed = bind(control, stranger)({'action': action, 'agent': mine, **extra})
    assert absent.document['error']['code'] == concealed.document['error']['code'] == 'not-found'
    assert absent.document['error']['message'].replace('agent-absent', mine) == \
        concealed.document['error']['message']
    assert HINT in absent.document['error']['message']


@pytest.mark.parametrize('action, extra', [('retire', {}), ('send', {'message': 'hi'}), ('interrupt', {})])
def test_graphtraj_alias_refusal_names_visible_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, extra: dict,
) -> None:
    """In a GraphTraj host a name reaches the alias path; ``alias-not-found`` gets the same hint."""
    from graphtraj.execution import runner_status
    from graphtraj.interfaces.agents import GraphTrajAgents, swarm_root

    def no_such_alias(self, action, arguments, caller):
        """The Runner's own refusal for a reference that is no Task member alias."""
        raise runner_status._alias_not_found()

    monkeypatch.setattr(GraphTrajAgents, '_operate', no_such_alias)

    (tmp_path / '.graphtraj/core').mkdir(parents=True)
    (tmp_path / '.graphtraj/core/config.yml').write_text('{}\n')
    runner = tmp_path / '.graphtraj/core/runner'
    claim_main(runner, {'runtime': 'codex', 'session': 'codex-main', 'codex_home': '/home/.codex',
                        'hook_session': 'hook'}, 'codex:SessionStart:startup')
    control = AgentControl(swarm_root(tmp_path), {'scripted': ScriptedDriver()}, roots=MainRoots(runner))
    main    = Caller('graphtraj-gateway', None, 'codex-main', 'codex')
    mine    = bind(control, main)({'action': 'create', 'runtime': 'scripted',
                                   'instruction': 'a', 'name': 'p377a'}).document['agent']
    hidden  = bind(control, Caller('test-host', None, session='elsewhere'))(
        {'action': 'create', 'runtime': 'scripted', 'instruction': 'b', 'name': 'p377a'}).document['agent']

    with pytest.raises(AgentsError) as refused:
        GraphTrajAgents(tmp_path).operate(action, {'agent': 'p377a', **extra}, Binding(main))
    assert refused.value.code == 'alias-not-found'
    assert HINT in refused.value.message and mine in refused.value.message
    assert hidden not in refused.value.message

    with pytest.raises(AgentsError) as unnamed:
        GraphTrajAgents(tmp_path).operate(action, {'agent': 'nobody', **extra}, Binding(main))
    assert unnamed.value.code == 'alias-not-found' and unnamed.value.message.endswith(HINT)

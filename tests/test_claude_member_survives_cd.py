"""A Bash ``cd`` moves a native Claude cwd; it does not change who is calling (437).

The member path runs through the controlled official-CLI peer
(claude_cli_fixture.py), which proves this host's side of the protocol, not
what the real CLI sends. The Main path drives ``NativeCalls.context`` directly.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from graftling import AgentControl, AgentsError, AgentsResult, Caller, bind, read_session, write_config
from graftling.claude import NativeCalls, hook_source
from graftling.claude.collection import collect_hook_event
from graftling.claude.driver import ClaudeDriver
from graftling.sessions.archive import SessionArchive, archive_path
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture


def run_helper_stop(tmp_path: Path) -> tuple[Path, str, dict]:
    """Run one saved member turn in which a native helper finishes.

    Returns the archive root, the member's Session and how its execution ended.
    """
    root = tmp_path / 'agents'
    write_config(root, save_normalized_sessions=True)
    control = AgentControl(root, {'claude': ClaudeDriver(tmp_path, {})})
    call = bind(control, Caller('standalone-host', None, str(uuid4()), 'claude'))
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'helper-stop'})
    assert not created.failed, created.document
    waited = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 20})
    assert waited.document['result']['state'] == 'standby', waited.document
    return root, created.document['session'], waited.document['result']['last_result']


def helper_archives(root: Path) -> list[dict]:
    """Return every archived helper header; nothing here trusts an ID's spelling."""
    headers = [read_session(path)['header'] for path in (root / 'sessions').rglob('*.jsonl')]
    return [header for header in headers if header.get('native', {}).get('agentId')]


@pytest.mark.parametrize('moved', ['subdirectory', 'outside'])
def test_a_helper_finishing_after_cd_keeps_the_member_and_its_result(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch, moved: str,  # noqa: F811
) -> None:
    """The member ends normally, and the helper's transcript is kept under the Worktree's entry."""
    target = tmp_path / 'scripts/real-host' if moved == 'subdirectory' else tmp_path.parent / (tmp_path.name + '-state/tasks')
    target.mkdir(parents=True)
    monkeypatch.setenv('CLAUDE_FIXTURE_HELPER_CWD', str(target))

    root, session, ended = run_helper_stop(tmp_path)

    assert (ended['outcome'], ended['error'], ended['last_message']) == ('completed', None, 'helper-done')
    archive = SessionArchive(root, save_normalized_sessions=True)
    written = read_session(archive_path(root, archive.native_id('claude', session, agent_id='helper')))
    assert [header['native']['agentId'] for header in helper_archives(root)] == ['helper']
    assert Path(written['header']['cwd']).resolve() == tmp_path.resolve()


def test_a_helper_from_another_session_is_refused_and_not_archived(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    """Unchanged cwd or not, the owned channel's Session alone may archive into this member."""
    foreign = str(uuid4())
    monkeypatch.setenv('CLAUDE_FIXTURE_HELPER_SESSION', foreign)

    root, _, ended = run_helper_stop(tmp_path)

    assert ended['outcome'] == 'failed' and ended['last_message'] is None
    assert ended['error'] == {'code': 'RUNTIME_WORKER_FAILED', 'message': 'Hook Session differs from the owned Session.'}
    assert helper_archives(root) == []


def event(cwd: Path, session: str = 'native') -> dict:
    """One SubagentStop as Claude delivers it."""
    return {'hook_event_name': 'SubagentStop', 'session_id': session, 'agent_id': 'helper',
            'agent_transcript_path': str(cwd / 'helper.jsonl'), 'cwd': str(cwd)}


def test_without_a_session_the_working_directory_still_decides(tmp_path: Path) -> None:
    """A command-hook consumer has no owned channel, so it keeps its refusal."""
    moved = tmp_path / 'moved'
    moved.mkdir()
    with pytest.raises(ValueError, match='Hook working directory differs'):
        hook_source(event(moved), tmp_path)
    with pytest.raises(ValueError, match='Hook working directory differs'):
        collect_hook_event(SessionArchive(tmp_path / 'agents', save_normalized_sessions=True), event(moved), tmp_path)
    assert hook_source(event(tmp_path), tmp_path)[0] == 'SubagentStop'


def test_with_a_session_only_that_session_is_accepted(tmp_path: Path) -> None:
    """The Session replaces the cwd comparison; it does not join an either-or."""
    moved = tmp_path / 'moved'
    moved.mkdir()
    assert hook_source(event(moved), tmp_path, native_id='native')[1] == 'native'
    for cwd in (tmp_path, moved):
        with pytest.raises(ValueError, match='Hook Session differs'):
            hook_source(event(cwd, 'other'), tmp_path, native_id='native')


REQUEST = {'action': 'execute', 'feature': 'status', 'arguments': {}}


def prepare(session: str, cwd: Path | str, request: object = REQUEST) -> dict:
    """One mod preparation as ``host_context.mjs`` sends it."""
    return {'operation': 'prepare', 'tool': 'agents', 'session': session, 'cwd': str(cwd),
            'agent': None, 'request': request}


@pytest.fixture
def host(tmp_path: Path) -> NativeCalls:
    """A host bound to one project, recording the cwd each call received."""
    project = tmp_path / 'project'
    (project / 'sub/deeper').mkdir(parents=True)
    return NativeCalls(lambda session, cwd: lambda tool, request: AgentsResult({'cwd': str(cwd), 'session': session}),
                       project)


def test_main_prepares_from_inside_the_project_and_calls_with_its_root(host: NativeCalls) -> None:
    """A moved native cwd is the same Main, and it never reaches the call."""
    session = str(uuid4())
    assert host.context(prepare(session, host.cwd / 'sub/deeper')) == {'prepared': True}
    assert host.call(REQUEST).document == {'cwd': str(host.cwd), 'session': session}


def test_one_call_prepared_again_after_cd_keeps_one_association(host: NativeCalls) -> None:
    """Preparing one exact call again stays one association wherever Main moved."""
    session = str(uuid4())
    host.context(prepare(session, host.cwd))
    host.context(prepare(session, host.cwd / 'sub'))
    assert len(host.prepared) == 1


def test_main_outside_the_project_is_refused_with_a_way_back(host: NativeCalls, tmp_path: Path) -> None:
    """The refusal names both directories and what to do, and prepares nothing."""
    outside = tmp_path / 'elsewhere'
    outside.mkdir()
    with pytest.raises(AgentsError) as refused:
        host.context(prepare(str(uuid4()), outside))
    assert refused.value.code == 'authority-denied'
    assert str(outside.resolve()) in refused.value.message and str(host.cwd) in refused.value.message
    assert f'`cd {host.cwd}`' in refused.value.message and 'again' in refused.value.message
    assert not host.prepared


def test_a_sibling_sharing_the_project_name_prefix_is_outside(host: NativeCalls, tmp_path: Path) -> None:
    """Containment is by path component, not by string prefix."""
    sibling = tmp_path / 'project-other'
    sibling.mkdir()
    with pytest.raises(AgentsError, match='outside the project'):
        host.context(prepare(str(uuid4()), sibling))


def test_symlinks_are_judged_by_where_they_lead(host: NativeCalls, tmp_path: Path) -> None:
    """A link into the project is inside; a link in the project leading out is outside."""
    inward = tmp_path / 'link-in'
    inward.symlink_to(host.cwd / 'sub')
    assert host.context(prepare(str(uuid4()), inward)) == {'prepared': True}
    host.context({'operation': 'end'})
    outward = host.cwd / 'link-out'
    outward.symlink_to(tmp_path)
    with pytest.raises(AgentsError, match='outside the project'):
        host.context(prepare(str(uuid4()), outward))


def test_another_session_stays_refused_while_one_is_pending(host: NativeCalls) -> None:
    """Accepting a moved cwd leaves the one-Session rule as it was."""
    host.context(prepare(str(uuid4()), host.cwd / 'sub'))
    with pytest.raises(AgentsError, match='A different native call is already pending'):
        host.context(prepare(str(uuid4()), host.cwd / 'sub'))


@pytest.mark.parametrize('session, request_', [
    (123, REQUEST),
    ('11111111-1111-4111-8111-11111111111A'.upper(), REQUEST),
    (str(uuid4()), 'not an object'),
])
def test_session_and_request_validation_keeps_its_text(host: NativeCalls, session: object, request_: object) -> None:
    """Only the cwd refusal moved to its own message."""
    with pytest.raises(AgentsError) as refused:
        host.context(prepare(session, host.cwd, request_))
    assert (refused.value.code, refused.value.message) == ('authority-denied', 'Native Session/cwd/request is invalid.')

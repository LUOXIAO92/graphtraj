"""Public migration preserves old evidence and obtains order only from native history."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from click.testing import CliRunner
import pytest
import yaml

from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from agent_swarm.sessions.migration import import_native, import_sqlite, verify_sqlite
from agent_swarm.sessions.protocol import retain_native, upgrade_header
from graphtraj.interfaces.cli.graphtraj import main
from graphtraj.sessions.storage import SessionStore, session_path
from test_session_storage import header
from test_codex_jsonl_archive import history
from test_claude_jsonl import message
from test_migration_snapshot import _source


def test_sqlite_evidence_is_lossless_idempotent_and_not_native_order(tmp_path: Path) -> None:
    """Old ciphertext/unknown fields/draft/bytes survive, without false messages."""
    original = session_path(tmp_path / 'old', 'canonical')
    event = retain_native('codex', {'ciphertext': 'opaque==', 'future': [1, None]},
                          session_id='native-research@x1', locator='notification/1', seq=0, time=9)
    with SessionStore.create(original, header()) as old:
        attachment = old.put_attachment(b'\x00\xfforiginal')
        event['attachments'] = [attachment]
        old.append(event, source='notification', position=1)
    before = original.read_bytes()
    root = tmp_path / 'swarm'
    imported = import_sqlite(original, root)
    first = Path(imported['archive']).read_bytes()
    assert import_sqlite(original, root) == imported
    assert Path(imported['archive']).read_bytes() == first
    assert original.read_bytes() == before
    store = JsonlSessionStore(Path(imported['archive']))
    assert store.header == upgrade_header(header())
    assert store.legacy()['events'] == [event]
    assert store.legacy()['checkpoints'] == {'notification': 1}
    assert store.attachment(attachment['sha256']) == b'\x00\xfforiginal'
    assert verify_sqlite(original, root)['mismatches'] == []
    with pytest.raises(ValueError, match='no verified native history'):
        store.messages()
    assert SessionArchive(root).native_id('codex', 'native-research@x1') == 'canonical'


@pytest.mark.parametrize('runtime', ['codex', 'claude', 'pi', 'dsh'])
def test_native_import_keeps_non_native_header_id(runtime: str, tmp_path: Path) -> None:
    """Every mapper resumes the retained canonical ID, even when native IDs differ."""
    retained = header('canonical-' + runtime)
    retained['graphtraj']['native'].update(runtime=runtime, sessionId='native')
    root = tmp_path / 'swarm'
    original = session_path(tmp_path / 'old', retained['id'])
    with SessionStore.create(original, retained):
        pass
    import_sqlite(original, root)
    if runtime == 'codex':
        records = history()
    elif runtime == 'claude':
        records = [message('q', None, 'question'), message('b', 'q', 'second'),
                   message('a', 'b', 'first')]
        for record in records:
            record['sessionId'] = 'native'
        records = [records[0], records[2], records[1]]
    elif runtime == 'pi':
        records = [{'type': 'session', 'id': 'native', 'version': 3,
                    'timestamp': '2026-01-01T00:00:00Z'},
                   {'type': 'message', 'id': 'q', 'parentId': None,
                    'timestamp': '2026-01-01T00:00:00Z',
                    'message': {'role': 'user', 'content': 'question', 'timestamp': 1}}]
    else:
        records = [{'version': 4, 'id': 'native', 'createdAt': 1, 'isSeeded': False},
                   {'type': 'user/message', 'seq': 0, 'time': 1, 'surfaceOp': 'append',
                    'data': {'id': 'q', 'role': 'user', 'source': {'kind': 'user'},
                             'content': [{'type': 'text', 'text': 'question'}]}}]
    source = tmp_path / 'native.jsonl'
    source.write_text(''.join(json.dumps(record) + '\n' for record in records))
    result = import_native(root, runtime, 'native', source, project=str(tmp_path))
    assert result['id'] == retained['id']
    assert result['missing'] is None, result
    store = JsonlSessionStore(archive_path(root, retained['id']))
    assert store.header == upgrade_header(retained)
    first = store.page()['events']
    assert import_native(root, runtime, 'native', source, project=str(tmp_path)) == result
    assert JsonlSessionStore(store.path).page()['events'] == first
    assert not archive_path(root, runtime + ':native').exists()
    if runtime == 'claude':
        assert [item['id'] for item in store.messages()] == ['q', 'b', 'a']
    if runtime == 'codex':
        assert [item['toolCallId'] for item in store.messages() if item['role'] == 'tool'] == ['b', 'a']


def test_public_snapshot_and_migration_never_reopen_original_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI rehearsal uses its captured bytes after the original Harness is removed."""
    origin = tmp_path / 'origin'
    source = tmp_path / 'native.jsonl'
    _source(origin, source)
    copy = tmp_path / 'copy'
    runner = CliRunner()
    monkeypatch.chdir(origin)
    snapshot = runner.invoke(main, ['migrate-agents', '--snapshot', str(copy)])
    assert snapshot.exit_code == 0, snapshot.output
    shutil.rmtree(origin)
    source.unlink()
    monkeypatch.chdir(copy)
    preview = runner.invoke(main, ['migrate-agents', '--preview'])
    assert preview.exit_code == 0, preview.output
    migrated = runner.invoke(main, ['migrate-agents'])
    assert migrated.exit_code == 0, migrated.output
    result = yaml.safe_load(migrated.output)
    assert result['production_cutover'] is False
    assert result['native_results'][0]['id'] == 'codex:owned'
    assert runner.invoke(main, ['migrate-agents']).exit_code == 0
    verified = runner.invoke(main, ['migrate-agents', '--verify'])
    assert verified.exit_code == 0, verified.output
    assert yaml.safe_load(verified.output)['verification']['matches']


def test_public_preview_reports_old_declarations_without_private_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A captured declaration signals possible resume overlap, not live duplication."""
    origin, source = tmp_path / 'origin', tmp_path / 'native.jsonl'
    _source(origin, source)
    rows = source.read_text().splitlines()
    meta = json.loads(rows[0])
    meta['payload']['dynamic_tools'] = [
        {'name': 'agents', 'description': 'private-tool-detail'},
        {'name': 'graphtraj'}, {'name': 'runtime-native-tool'},
    ]
    source.write_text(json.dumps(meta) + '\n' + '\n'.join(rows[1:]) + '\n')
    monkeypatch.chdir(origin)
    copy = tmp_path / 'copy'
    runner = CliRunner()
    assert runner.invoke(main, ['migrate-agents', '--snapshot', str(copy)]).exit_code == 0
    monkeypatch.chdir(copy)
    result = runner.invoke(main, ['migrate-agents', '--preview'])
    assert result.exit_code == 0, result.output
    inventory = yaml.safe_load(result.output)['legacy_native_registrations']
    entry, = inventory['sessions']
    assert entry['group'] == 'current_members'
    assert entry['tools'] == ['agents', 'graphtraj']
    assert entry['duplicate_status'] == 'potential_on_mcp_resume'
    assert inventory['confirmed_live_duplicates'] == 0
    assert 'private-tool-detail' not in result.output


def test_snapshot_captures_swarm_configuration_and_can_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Public copies retain new ownership data and never enable live channels."""
    origin = tmp_path / 'origin'
    _source(origin, tmp_path / 'native.jsonl')
    swarm = origin / '.graphtraj/swarm'
    control = swarm / 'control/agents/agent-old.json'
    control.parent.mkdir(parents=True)
    control.write_text(json.dumps({'agent': 'agent-old', 'runtime': 'dsh', 'session': None,
                                   'parent': 'agent-parent', 'retired_at': 'original-time'}))
    (swarm / 'config.yml').write_text('save_normalized_sessions: false\nbackfill_history: true\n')
    retained = JsonlSessionStore.create(archive_path(swarm, 'retained'), upgrade_header(header('retained')))
    retained.publish([retain_native('codex', {'ciphertext': 'opaque'},
        session_id='native-research@x1', locator='native/0', seq=0, time=1)], source='native', position=0)
    retained.put_attachment(b'original attachment')
    (swarm / 'live').mkdir()
    (swarm / 'live/channel').write_text('do not activate')
    roles = origin / '.graphtraj/roles.yml'
    roles.write_text('roles: {}\n')
    monkeypatch.chdir(origin)
    runner = CliRunner()
    snapshot = tmp_path / 'snapshot'
    result = runner.invoke(main, ['migrate-agents', '--snapshot', str(snapshot)])
    assert result.exit_code == 0, result.output
    manifest = yaml.safe_load((snapshot / '.graphtraj/migration-snapshot.yml').read_text())
    assert manifest['swarm_captured'] and manifest['control_state_unchanged']
    assert manifest['configuration_captured'] == ['roles.yml', 'config.yml'] or set(
        manifest['configuration_captured']) == {'roles.yml', 'config.yml'}
    assert (snapshot / '.graphtraj/swarm/control/agents/agent-old.json').read_bytes() == control.read_bytes()
    assert not (snapshot / '.graphtraj/swarm/live').exists()
    before = (snapshot / '.graphtraj/migration-snapshot.yml').read_bytes()
    monkeypatch.chdir(snapshot)
    target = tmp_path / 'rehearsal'
    clone = runner.invoke(main, ['migrate-agents', '--snapshot', str(target)])
    assert clone.exit_code == 0, clone.output
    assert (snapshot / '.graphtraj/migration-snapshot.yml').read_bytes() == before
    assert (target / '.graphtraj/swarm/config.yml').read_bytes() == (swarm / 'config.yml').read_bytes()
    monkeypatch.chdir(target)
    migrated = runner.invoke(main, ['migrate-agents'])
    assert migrated.exit_code == 0, migrated.output
    assert (snapshot / '.graphtraj/swarm/config.yml').read_bytes() == (swarm / 'config.yml').read_bytes()
    checked = runner.invoke(main, ['migrate-agents', '--verify', '--against', str(snapshot)])
    assert checked.exit_code == 0, checked.output
    comparison = yaml.safe_load(checked.output)['verification']['retained_swarm']
    assert comparison['matches'], comparison
    assert (comparison['controls'], comparison['jsonl_archives'], comparison['attachments']) == (1, 1, 1)

    # Identical provenance cannot conceal changed opaque native payload bytes.
    changed = JsonlSessionStore.create(archive_path(tmp_path / 'different', 'retained'), upgrade_header(header('retained')))
    changed.publish([retain_native('codex', {'ciphertext': 'changed'},
        session_id='native-research@x1', locator='native/0', seq=0, time=1)], source='native', position=0)
    shutil.copyfile(changed.path, archive_path(target / '.graphtraj/swarm', 'retained'))
    checked = runner.invoke(main, ['migrate-agents', '--verify', '--against', str(snapshot)])
    assert checked.exit_code == 0, checked.output
    verification = yaml.safe_load(checked.output)['verification']
    assert not verification['matches']
    reference = archive_path(target / '.graphtraj/swarm', 'retained').relative_to(target / '.graphtraj/swarm')
    assert verification['retained_swarm']['mismatches'] == [reference.as_posix() + ':native-records-or-order']


def test_archive_collectors_work_with_no_graphtraj_package(tmp_path: Path) -> None:
    """Isolated Python loads and enables all collectors from the independent package."""
    source = Path(__file__).resolve().parents[1] / 'src/agent_swarm'
    shutil.copytree(source, tmp_path / 'agent_swarm', ignore=shutil.ignore_patterns('__pycache__'))
    program = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agent_swarm import write_config
from agent_swarm.sessions.archive import ConfiguredSessionArchive
from agent_swarm.sessions.codex import CodexJsonlArchive
from agent_swarm.sessions.claude import ClaudeJsonlCollector
from agent_swarm.sessions.pi import PiArchive
from agent_swarm.sessions.dsh import collect_jsonl
root = Path(sys.argv[1]) / 'data'
write_config(root, save_normalized_sessions=True)
archive = ConfiguredSessionArchive(root)
header = {'version': 5, 'id': 'standalone', 'createdAt': 1, 'isSeeded': False}
archive.map_session(header)
assert archive.store('standalone').header == header
assert not any(name == 'graphtraj' or name.startswith('graphtraj.') for name in sys.modules)
'''
    result = subprocess.run([sys.executable, '-I', '-S', '-c', program, str(tmp_path)],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('changed', [False, True])
def test_snapshot_checks_facts_not_atomic_same_content_rewrites(
    changed: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real binding change refuses; an identical native rebind permits a copy."""
    origin = tmp_path / 'origin'
    _source(origin, tmp_path / 'native.jsonl')
    mapping = origin / '.graphtraj/runner/sessions/member/mapping.yml'
    copy_file = shutil.copy2
    rewritten = False

    def concurrent_rebind(source: Path, destination: Path, **options: object) -> str:
        """Model an atomic native binding publication during the ordinary copy."""
        nonlocal rewritten
        result = copy_file(source, destination, **options)
        if not rewritten:
            rewritten = True
            content = mapping.read_text()
            if changed:
                content = content.replace('session: owned', 'session: another')
            temporary = mapping.with_suffix('.new')
            temporary.write_text(content)
            temporary.replace(mapping)
        return result

    monkeypatch.setattr(shutil, 'copy2', concurrent_rebind)
    monkeypatch.chdir(origin)
    destination = tmp_path / 'copy'
    result = CliRunner().invoke(main, ['migrate-agents', '--snapshot', str(destination)])
    assert rewritten
    if changed:
        assert result.exit_code != 0
        assert 'mapping.yml' in result.output
        assert not destination.exists()
    else:
        assert result.exit_code == 0, result.output
        manifest = yaml.safe_load((destination / '.graphtraj/migration-snapshot.yml').read_text())
        assert manifest['control_state_unchanged']


def test_public_partition_uses_core_paths_and_retains_originals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task graph references move once; backup originals and native cwd survive."""
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.workspace.runner_project import discover_runner_directory

    origin = tmp_path / 'origin'
    _source(origin, tmp_path / 'native.jsonl')
    native_config = origin / '.graphtraj/runner/sessions/member/dsh-home/cordis.patch.yml'
    native_config.parent.mkdir()
    native_config.write_text('disabled: !!js process.platform === "win32"\n')
    runner = CliRunner()
    monkeypatch.chdir(origin)
    snapshot = tmp_path / 'copy'
    assert runner.invoke(main, ['migrate-agents', '--snapshot', str(snapshot)]).exit_code == 0
    monkeypatch.chdir(snapshot)
    original = (snapshot / '.graphtraj/state/tickets/2-child/ticket.md').read_bytes()
    assert runner.invoke(main, ['migrate-agents']).exit_code == 0
    result = runner.invoke(main, ['migrate-agents', '--partition'])
    assert result.exit_code == 0, result.output
    assert load_project_configuration(snapshot).state == snapshot / '.graphtraj/core/state'
    assert discover_runner_directory(snapshot) == snapshot / '.graphtraj/core/runner'
    assert not (snapshot / '.graphtraj/config.yml').exists()
    assert not (snapshot / '.graphtraj/state').exists()
    backup = snapshot / '.graphtraj/core/backups/before-agent-partition'
    assert (backup / 'state/tickets/2-child/ticket.md').read_bytes() == original
    backup_trace = backup / 'state/tickets/2-child/teams/1/traces/member/events.jsonl'
    assert backup_trace.read_bytes() == (tmp_path / 'native.jsonl').read_bytes()
    assert (snapshot / '.graphtraj/core/runner/sessions/member/dsh-home/cordis.patch.yml').read_bytes() == native_config.read_bytes()
    assert (snapshot / '.graphtraj/core/state/tickets/2-child/ticket.md').read_bytes() == original
    assert yaml.safe_load(result.output)['layout']['production_cutover'] is False
    again = runner.invoke(main, ['migrate-agents', '--partition'])
    assert again.exit_code == 0, again.output
    assert yaml.safe_load(again.output)['layout']['partition'] == 'already-migrated'
    verified = runner.invoke(main, ['migrate-agents', '--verify'])
    assert verified.exit_code == 0, verified.output
    assert yaml.safe_load(verified.output)['verification']['matches']


def test_partition_preserves_current_and_historical_member_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public member scopes and actual parents survive the core relocation."""
    from test_desktop_activity import members, message, prepare

    origin = tmp_path / 'origin'
    origin.mkdir()
    _, directory, trace = prepare(origin, 'codex', [message('fixture')], parent='research@x2')
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    (directory / 'mapping.yml').unlink()
    (directory / 'session.yml').write_text(yaml.safe_dump({'retirement': {'mapping': mapping}}))
    directory.rename(trace.parent / 'runner')
    current = members(origin)
    history = members(origin, summary_task_id='148')
    assert 'research@x1' not in {item['alias'] for item in current['members']}
    retired = next(item for item in history['members'] if item['alias'] == 'research@x1')
    assert retired['retired'] and retired['state'] is None
    assert retired['parent'] == 'research@x2'

    runner = CliRunner()
    monkeypatch.chdir(origin)
    snapshot = tmp_path / 'copy'
    result = runner.invoke(main, ['migrate-agents', '--snapshot', str(snapshot)])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(snapshot)
    for arguments in (['migrate-agents'], ['migrate-agents', '--partition']):
        result = runner.invoke(main, arguments)
        assert result.exit_code == 0, result.output
    assert members(snapshot) == current
    assert members(snapshot, summary_task_id='148') == history


def test_imported_stopped_and_retired_agents_keep_identity_and_parents(tmp_path: Path) -> None:
    """Independent import is repeatable and never turns retired history active."""
    from agent_swarm import AgentControl, Binding, Caller, AgentsError

    control = AgentControl(tmp_path, {})
    caller = Caller('retained-host', 'actual-parent')
    record = {'agent': 'old-alias@e1', 'name': 'old name', 'runtime': 'codex',
              'host': caller.host, 'parent': caller.agent,
              'creator': {'host': caller.host, 'agent': caller.agent, 'session': None},
              'session': 'native-ref', 'sessions': ['native-ref'], 'settings': {'cwd': '/original/cwd'},
              'created_at': None, 'retired_at': None, 'executions': []}
    first = control.import_agent(record)
    assert control.import_agent(record) == first
    assert control.operate('status', {'agent': record['agent']}, Binding(caller)).result['state'] == 'standby'
    assert first['agent'] == 'old-alias@e1' and first['parent'] == 'actual-parent'
    retired = {**record, 'agent': 'retired-alias@e1', 'retired_at': 'unknown'}
    control.import_agent(retired)
    assert [item['agent'] for item in control.hierarchy(caller)] == ['old-alias@e1']
    with pytest.raises(AgentsError, match='Only stopped'):
        control.import_agent({**record, 'agent': 'running', 'executions': [{'state': 'running'}]})


def test_legacy_import_preserves_an_already_current_jsonl_header(tmp_path: Path) -> None:
    """New header metadata is not overwritten by older SQLite provenance."""
    retained = header()
    native = session_path(tmp_path / 'old', retained['id'])
    with SessionStore.create(native, retained):
        pass
    current = upgrade_header(retained)
    current['native']['locator'] = 'verified-new-source'
    root = tmp_path / 'swarm'
    JsonlSessionStore.create(archive_path(root, retained['id']), current)
    import_sqlite(native, root)
    migrated = JsonlSessionStore(archive_path(root, retained['id']))
    assert migrated.header == current
    # SQLite stores keep what they were written with; new writes are v5.
    assert migrated.legacy()['header'] == upgrade_header(retained)


def test_claude_native_hooks_keep_activation_boundary_between_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With backfill off, Stop still captures content created since SessionStart."""
    from graphtraj.runtimes.claude.collection import collect_jsonl_hook
    from graphtraj.configuration.project_configuration import default_configuration_content

    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/config.yml').write_text(default_configuration_content(tmp_path, tmp_path))
    transcript = tmp_path / 'native.jsonl'
    transcript.write_text('')
    start = {'hook_event_name': 'SessionStart', 'session_id': 's', 'source': 'startup',
             'cwd': str(tmp_path), 'transcript_path': str(transcript)}
    assert collect_jsonl_hook(start, tmp_path)['saved']
    transcript.write_text(json.dumps(message('new', None, 'created after activation')) + '\n')
    assert collect_jsonl_hook({**start, 'hook_event_name': 'Stop'}, tmp_path)['saved']
    store = JsonlSessionStore(archive_path(tmp_path / '.graphtraj/swarm', 'claude:s'))
    assert [item['content'][0]['text'] for item in store.messages()] == ['created after activation']
    assert not (tmp_path / '.graphtraj/state/sessions').exists()


def _history_archive(root: Path, events: list[tuple]) -> None:
    """Publish native records and Codex graphtraj/history selections in the given order."""
    from agent_swarm.sessions.codex import _response

    store = JsonlSessionStore.create(archive_path(root / '.graphtraj/swarm', 'retained'),
                                     upgrade_header(header('retained')))
    published = []
    for seq, (kind, value) in enumerate(events):
        if kind == 'native':
            record = {'type': 'response_item', 'payload': {
                'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': value}]}}
            event = retain_native('codex', record, session_id='native-research@x1', locator=value, seq=seq, time=1)
            published.append(_response(record, event, 'native-research@x1', value))
        else:
            published.append({'type': 'history', 'seq': seq, 'time': 1, 'data': {'eventSeqs': value[1]},
                              'native': {'runtime': 'codex', 'sessionId': 'native-research@x1',
                                         'locator': value[0] + '/history'}})
    store.publish(published, source='native', position=0)
    (root / '.graphtraj/migration-snapshot.yml').write_text('project: /retained/project\n')


@pytest.mark.parametrize('change', [None, 'renumbered', 'rewritten', 'deleted', 'reordered'])
def test_retained_codex_history_selections_keep_content_and_order(tmp_path: Path, change: str | None) -> None:
    """A recordless graphtraj/history event is compared in full, by the native events it selects."""
    from graphtraj.workspace.agent_migration import _verify_retained_swarm

    original = [('native', 'native/0'), ('native', 'native/1'), ('history', ('native/1', [0]))]
    imported = {
        None: original,
        # Import may add an earlier native record; selections then name the same events by new seqs.
        'renumbered': [('native', 'native/-1'), ('native', 'native/0'), ('native', 'native/1'),
                       ('history', ('native/1', [1]))],
        'rewritten': [('native', 'native/0'), ('native', 'native/1'), ('history', ('native/1', [1]))],
        'deleted': original[:2],
        'reordered': [('native', 'native/1'), ('native', 'native/0'), ('history', ('native/1', [1]))],
    }[change]
    _history_archive(tmp_path / 'before', original)
    _history_archive(tmp_path / 'after', imported)
    result = _verify_retained_swarm(tmp_path / 'after', tmp_path / 'before', {'project': '/retained/project'})
    reference = archive_path(tmp_path / 'after/.graphtraj/swarm', 'retained').relative_to(tmp_path / 'after/.graphtraj/swarm')
    if change in {None, 'renumbered'}:
        assert result['matches'], result
        assert result['native_events'] == 3
    else:
        assert result['mismatches'] == [reference.as_posix() + ':native-records-or-order']

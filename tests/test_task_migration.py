"""Behavior of the one-time ``graphtraj migrate-tickets`` conversion."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from conftest import InstalledCommands, run_process

REVISION = "definitions/20261015T070000.000000+0900.md"


def _definition(task_id: str, name: str, parent: str | None, body: str) -> str:
    """Render one retained Ticket-format v2 definition."""
    metadata = {"task": {
        "ticket_id": task_id, "ticket_name": name, "source": f"local:task/{task_id}",
        "title": f"Sample {name}", "dependencies": [], "schema_version": 2, "parent_id": parent,
        "disposition": "active", "replaced_by": [], "retirement_reason": None,
    }}
    return "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + body


def _ticket_project(root: Path) -> dict[str, Path]:
    """Write a retained Ticket-format project with Team, Worktree and Runner records."""
    graphtraj = root / ".graphtraj"
    graphtraj.mkdir()
    (graphtraj / "config.yml").write_text(yaml.safe_dump({
        "version": 1,
        "paths": {"project_root": ".", "docs": "docs", "agent_worktrees": ".graphtraj/worktrees",
                  "state": ".graphtraj/state"},
        "agent_runner": {"dispatch_depth": 1, "max_concurrency": 2},
    }, sort_keys=False))
    tickets = graphtraj / "state/tickets"
    for task_id, name, parent, current in (("1", "summary", None, "ticket.md"),
                                           ("2", "child", "1", REVISION)):
        directory = tickets / f"{task_id}-{name}"
        (directory / "definitions").mkdir(parents=True)
        (directory / "ticket.md").write_text(_definition(task_id, name, parent, f"Body of ticket {task_id}.\n"))
        if current != "ticket.md":
            (directory / current).write_text(_definition(task_id, name, parent, "Revised ticket body.\n"))
        (directory / "ticket.yml").write_text(yaml.safe_dump({
            "ticket_id": task_id, "ticket_name": name, "current_definition": current,
            "status": "implementing" if task_id == "2" else "pending",
            "active_team_ordinal": 1 if task_id == "2" else None,
            "worktree": None, "branch": None, "current_candidate": None, "schema_version": 2,
        }, sort_keys=False))
    report = tickets / "2-child/teams/1/rounds/1/engineer.md"
    report.parent.mkdir(parents=True)
    report.write_text("Report mentions ticket-completed and state/tickets literally.\n")
    worktree = graphtraj / "worktrees/2-child"
    worktree.mkdir(parents=True)
    (worktree / ".state").symlink_to(os.path.relpath(tickets / "2-child", worktree), target_is_directory=True)
    session = graphtraj / "runner/sample"
    session.mkdir(parents=True)
    (session / "mapping.yml").write_text(yaml.safe_dump({
        "alias": "2-child@engineer", "ticket_id": "2", "ticket_name": "child", "session": "native-1",
        "report_file": ".graphtraj/state/tickets/2-child/teams/1/rounds/1/engineer.md",
        "instruction": "Fix ticket 2 under state/tickets.", "launch_status": "ticket-already-live",
    }))
    (session / "session.jsonl").write_text('{"arguments": {"ticket_id": "2"}}\n')
    return {"report": report, "worktree": worktree, "session": session}


def _snapshot(root: Path) -> dict[str, object]:
    """Capture every retained file and link below ``.graphtraj``."""
    return {str(path.relative_to(root)): os.readlink(path) if path.is_symlink() else path.read_bytes()
            for path in sorted((root / ".graphtraj").rglob("*"))
            if path.is_symlink() or path.is_file()}


def _migrate(commands: InstalledCommands, root: Path):
    return run_process([str(commands.product), "migrate-tickets"], cwd=root)


def test_migration_converts_structure_and_keeps_text_and_identity(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    paths  = _ticket_project(tmp_path)
    (tmp_path / ".graphtraj/state/tickets/.claude/.cc-writes").mkdir(parents=True)
    before = _snapshot(tmp_path)

    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["backup"].startswith(".graphtraj/backups/")
    assert yaml.safe_load(result.stdout)["foreign_entries"] == [".claude"]
    assert _migrate(installed_commands, tmp_path).returncode != 0

    graph = run_process([str(installed_commands.product), "task", "graph", "--view", "full",
                         "--details", "1", "--details", "2"], cwd=tmp_path)
    assert graph.returncode == 0, graph.stderr
    document = yaml.safe_load(graph.stdout)
    tasks = {task["task_id"]: {**document["details"][task["task_id"]], **task} for task in document["tasks"]}
    assert tasks["1"]["children"] == ["2"] and tasks["2"]["parent_id"] == "1"
    assert tasks["2"]["current_definition"] == REVISION and tasks["2"]["status"] == "implementing"
    assert tasks["2"]["body"] == "Revised ticket body.\n" and tasks["1"]["current_definition"] == "task.md"

    state = tmp_path / ".graphtraj/state/tasks/2-child"
    assert (state / "teams/1/rounds/1/engineer.md").read_bytes() == before[
        ".graphtraj/state/tickets/2-child/teams/1/rounds/1/engineer.md"]
    assert (paths["worktree"] / ".state").resolve() == state.resolve()
    mapping = yaml.safe_load((paths["session"] / "mapping.yml").read_text())
    assert mapping == {
        "alias": "2-child@engineer", "task_id": "2", "task_name": "child", "session": "native-1",
        "report_file": ".graphtraj/state/tasks/2-child/teams/1/rounds/1/engineer.md",
        "instruction": "Fix ticket 2 under state/tickets.", "launch_status": "task-already-live",
    }
    assert (paths["session"] / "session.jsonl").read_bytes() == before[".graphtraj/runner/sample/session.jsonl"]


def test_failed_migration_restores_retained_state(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    _ticket_project(tmp_path)
    (tmp_path / ".graphtraj/state/tickets/1-summary/broken.yml").write_text("key: [unclosed\n")
    before = _snapshot(tmp_path)

    assert _migrate(installed_commands, tmp_path).returncode != 0
    after = {key: value for key, value in _snapshot(tmp_path).items() if "/backups/" not in key}
    assert after == before


def test_legacy_definition_without_parent_facts_is_refused_without_changes(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    _ticket_project(tmp_path)
    legacy = tmp_path / ".graphtraj/state/tickets/7-legacy"
    legacy.mkdir()
    (legacy / "ticket.md").write_text("# Ticket 7: Legacy\n\nTicket name: legacy\n\nSource: x\n\n"
                                      "Active: true\n\nReplaced by: none\n\nDependencies: none\n\nBody.\n")
    (legacy / "ticket.yml").write_text(yaml.safe_dump({
        "ticket_id": "7", "ticket_name": "legacy", "current_definition": "ticket.md", "active": True,
        "replaced_by": [], "dependencies": [], "status": "pending", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
    }))
    before = _snapshot(tmp_path)

    result = _migrate(installed_commands, tmp_path)
    assert result.returncode != 0
    assert "7: schema_version, parent_id, disposition, retirement_reason" in result.stderr
    assert _snapshot(tmp_path) == before


def test_preview_and_native_session_migration_preserve_sources(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Preview and apply collect only recorded project histories with exact bytes."""
    import json

    from graphtraj.sessions.storage import SessionStore, session_path

    _ticket_project(tmp_path)
    runner = tmp_path / '.graphtraj/runner'
    state = tmp_path / '.graphtraj/state'
    native = tmp_path / 'native'
    native.mkdir()
    records = {
        'codex': [
            {'type': 'session_meta', 'payload': {'id': 'c1'}, 'timestamp': '2026-10-15T00:00:00Z'},
            {'type': 'response_item', 'payload': {'ticket_id': 'literal', 'encrypted_content': 'opaque'}},
        ],
        'pi': [
            {'type': 'session', 'id': 'p1', 'version': 3, 'cwd': str(tmp_path), 'timestamp': 1,
             'parentSession': str(native / 'unassociated-parent.jsonl')},
            {'type': 'message', 'id': 'm1', 'message': {'role': 'user', 'content': 'ticket-completed'}},
        ],
        'dsh': [
            {'version': 4, 'id': 'd1', 'createdAt': 1, 'isSeeded': False},
            {'type': 'user/message', 'seq': 0, 'time': 1, 'surfaceOp': 'append',
             'data': {'id': 'm1', 'role': 'user', 'content': [{'type': 'text', 'text': 'ticket.md'}],
                      'source': {'kind': 'user'}}},
        ],
        'claude': [
            {'type': 'user', 'sessionId': 'a1', 'uuid': 'm1',
             'message': {'role': 'user', 'content': 'state/tickets/example/ticket.md'}},
        ],
    }
    (native / 'unassociated-parent.jsonl').write_text(
        json.dumps({'type': 'session', 'id': 'unassociated'}) + '\n' + json.dumps(records['pi'][1]) + '\n')
    for runtime, session in [('codex', 'c1'), ('pi', 'p1'), ('dsh', 'd1'), ('claude', 'a1')]:
        source = native / (runtime + '.jsonl')
        source.write_text(''.join(json.dumps(record) + '\n' for record in records[runtime]))
        mapping = runner / 'sessions' / runtime / 'mapping.yml'
        mapping.parent.mkdir(parents=True)
        mapping.write_text(yaml.safe_dump({'alias': runtime, 'ticket_id': '2', 'runtime': runtime,
                                          'session': session, 'trace_file': str(source)}))
        (mapping.parent / 'session.yml').write_text(yaml.safe_dump({
            'session': session, 'rollout_path': str(source)}))
    missing = runner / 'main-sessions/missing/session.yml'
    missing.parent.mkdir(parents=True)
    missing.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'missing-main',
                                      'cwd': str(tmp_path)}))
    foreign = runner / 'main-sessions/foreign/session.yml'
    foreign.parent.mkdir(parents=True)
    foreign.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'foreign', 'cwd': '/unrelated'}))
    # A regular native Trace must not be interpreted as a Harness event stream.
    trace = state / 'tickets/2-child/teams/1/traces/old/events.jsonl'
    trace.parent.mkdir(parents=True)
    trace.write_text('{"event":"ticket-completed","payload":{"ticket_id":"verbatim"}}\n')
    before = _snapshot(tmp_path)
    preview = run_process([str(installed_commands.product), 'migrate-tickets', '--preview'], cwd=tmp_path)
    assert preview.returncode == 0, preview.stderr
    inventory = yaml.safe_load(preview.stdout)
    assert len(inventory['sessions']) == 5
    assert next(x for x in inventory['sessions'] if x['session'] == 'missing-main')['missing']
    assert _snapshot(tmp_path) == before

    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    migrated = yaml.safe_load(result.stdout)
    for item in migrated['sessions']:
        if item.get('missing'):
            continue
        with SessionStore(session_path(state, item['runtime'] + ':' + item['session']), readonly=True) as store:
            assert store.attachment(item['original_bytes']['sha256']) == Path(item['source']).read_bytes()
            assert store.header['graphtraj']['agentId'] == item['agent']
            assert store.next_seq > 0
            assert store.pending() is None
            if item['runtime'] == 'pi':
                assert store.header['isSeeded'] is False
                assert any(gap['path'] == 'parentSession' for gap in store.header['graphtraj']['missing'])
        mapping = runner / 'sessions' / item['runtime'] / 'mapping.yml'
        assert yaml.safe_load(mapping.read_text())['task_id'] == '2'
    assert (state / 'tasks/2-child/teams/1/traces/old/events.jsonl').read_bytes() == before[
        '.graphtraj/state/tickets/2-child/teams/1/traces/old/events.jsonl']


def test_structural_conversion_does_not_rewrite_payloads(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Identical spelling in user content does not make it structural metadata."""
    paths = _ticket_project(tmp_path)
    path = paths['session'] / 'mapping.yml'
    record = yaml.safe_load(path.read_text())
    untouched = {'instruction': 'ticket-completed', 'session': 'ticket.md',
                 'payload': {'ticket_id': 'literal', 'event': 'ticket-integrated'},
                 'title': 'tickets/2-child/ticket.md'}
    record.update(untouched)
    report = paths['report'].with_suffix('.yaml')
    report.write_text(yaml.safe_dump({'ticket_id': 'user-example', 'event': 'ticket-completed'}))
    report_bytes = report.read_bytes()
    path.write_text(yaml.safe_dump(record))
    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    converted = yaml.safe_load(path.read_text())
    assert {key: converted[key] for key in untouched} == untouched
    assert Path(str(report).replace('/tickets/', '/tasks/')).read_bytes() == report_bytes


def test_restore_returns_complete_original_state_and_allows_retry(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """An explicit stopped-window restore restores original records and links."""
    _ticket_project(tmp_path)
    before = _snapshot(tmp_path)
    first = _migrate(installed_commands, tmp_path)
    assert first.returncode == 0, first.stderr
    backup = yaml.safe_load(first.stdout)['backup']
    restored = run_process([str(installed_commands.product), 'migrate-tickets', '--restore', backup], cwd=tmp_path)
    assert restored.returncode == 0, restored.stderr
    after = {key: value for key, value in _snapshot(tmp_path).items() if '/backups/' not in key}
    assert after == before
    assert _migrate(installed_commands, tmp_path).returncode == 0


def test_retired_main_and_existing_archive_keep_native_identity(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Retired mappings and Main use actual sources; existing history is not duplicated."""
    import json

    from graphtraj.runtimes.codex.session_archive import CodexSessionArchive
    from graphtraj.sessions.storage import SessionStore, session_path

    _ticket_project(tmp_path)
    state = tmp_path / '.graphtraj/state'
    runner = tmp_path / '.graphtraj/runner'
    native = tmp_path / 'main.jsonl'
    native.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'main-session'}}) + '\n')
    CodexSessionArchive(state, str(tmp_path), 'main', 'main-session').collect(native)
    main = runner / 'main-sessions/owned/session.yml'
    main.parent.mkdir(parents=True)
    main.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'main-session', 'cwd': str(tmp_path),
                                    'activity': {'trace_file': str(native)}}))
    checker = main.parent / 'checks/missing/session.yml'
    checker.parent.mkdir(parents=True)
    checker.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'missing-checker', 'parent': 'main-session'}))
    retired = state / 'tickets/2-child/teams/1/traces/retired/runner/session.yml'
    retired.parent.mkdir(parents=True)
    child = tmp_path / 'child.jsonl'
    child.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'child-session'}}) + '\n')
    retired.write_text(yaml.safe_dump({'session': 'child-session', 'rollout_path': str(child),
                                     'retirement': {'mapping': {'runtime': 'codex', 'session': 'child-session',
                                         'alias': 'retired', 'ticket_id': '2', 'trace_file': str(child)}}}))
    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    sessions = {item['session']: item for item in yaml.safe_load(result.stdout)['sessions']}
    assert sessions['missing-checker']['missing']
    assert sessions['child-session']['agent'] == 'retired'
    with SessionStore(session_path(state, 'codex:main-session'), readonly=True) as store:
        assert store.next_seq == 1
        assert store.header['graphtraj']['agentId'] == 'main'


def test_wrong_native_identity_rolls_back_without_losing_links(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """An associated path is insufficient when its native identity contradicts the binding."""
    import json

    _ticket_project(tmp_path)
    native = tmp_path / 'wrong.jsonl'
    native.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'foreign'}}) + '\n')
    mapping = tmp_path / '.graphtraj/runner/sessions/owned/mapping.yml'
    mapping.parent.mkdir(parents=True)
    mapping.write_text(yaml.safe_dump({'alias': 'owned', 'ticket_id': '2', 'runtime': 'codex',
                                      'session': 'owned', 'trace_file': str(native)}))
    before = _snapshot(tmp_path)
    result = _migrate(installed_commands, tmp_path)
    assert result.returncode != 0
    after = {key: value for key, value in _snapshot(tmp_path).items() if '/backups/' not in key}
    assert after == before


def test_migration_preserves_acceptance_and_different_remote_number(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Accepted delivery and explicit remote identity survive a fresh index build."""
    from graphtraj.graph.delivery_worldline import append_project_worldline_event

    _ticket_project(tmp_path)
    state = tmp_path / '.graphtraj/state'
    path = state / 'tickets/2-child/ticket.yml'
    record = yaml.safe_load(path.read_text())
    record.update(status='integrated', current_candidate='a' * 40)
    path.write_text(yaml.safe_dump(record))
    evidence = '.graphtraj/state/tickets/2-child/teams/1/rounds/1/engineer.md'
    accepted = append_project_worldline_event(state, tmp_path, {
        'event': 'ticket-integrated', 'ticket_id': '2', 'candidate': 'a' * 40,
        'dev_commit': 'b' * 40, 'current_definition': REVISION,
        'reason': 'ticket-completed', 'caused_by_event_ids': [], 'evidence_refs': [evidence],
    })
    backup = state / 'task-backups.yml'
    backup.write_text(yaml.safe_dump({'backups': [{
        'task_id': '2', 'adapter': 'github', 'host': 'github.com', 'repository': 'owner/project',
        'issue': {'number': 9001, 'id': 100001, 'node_id': 'remote-node',
                  'url': 'https://github.com/owner/project/issues/9001'},
        'published': {'title': 'ticket.md', 'body': 'ticket-completed', 'state': 'closed'},
    }]}))
    original_mapping = backup.read_bytes()
    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    assert backup.read_bytes() == original_mapping
    command = [str(installed_commands.product), 'task', 'graph', '--view', 'full']
    first = run_process(command, cwd=tmp_path)
    second = run_process(command, cwd=tmp_path)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    graph = yaml.safe_load(first.stdout)
    child = next(task for task in graph['tasks'] if task['task_id'] == '2')
    assert child['status'] == 'integrated'
    assert child['delivery'][0]['event_id'] == accepted['event_id']
    assert child['delivery'][0]['reason'] == 'ticket-completed'
    assert child['delivery'][0]['evidence_refs'] == [evidence.replace('/tickets/', '/tasks/')]


def test_preview_distinguishes_withdrawn_hosted_main_from_real_conflict(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Shared historical Main provenance is not an ordinary Agent identity collision."""
    import json

    _ticket_project(tmp_path)
    source = tmp_path / 'main.jsonl'
    source.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'shared'}}) + '\n')
    runner = tmp_path / '.graphtraj/runner'
    main = runner / 'main-sessions/main/session.yml'
    main.parent.mkdir(parents=True)
    main.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'shared', 'cwd': str(tmp_path),
                                   'activity': {'trace_file': str(source)}}))
    old = runner / 'sessions/old-main/mapping.yml'
    old.parent.mkdir(parents=True)
    mapping = {'runtime': 'codex', 'session': 'shared', 'ticket_id': '2',
               'alias': 'old-main', 'hosted': True, 'purpose': 'main', 'trace_file': str(source)}
    old.write_text(yaml.safe_dump(mapping))
    command = [str(installed_commands.product), 'migrate-tickets', '--preview']
    result = run_process(command, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    shared = next(item for item in yaml.safe_load(result.stdout)['sessions'] if item.get('session') == 'shared')
    assert shared['agent'] == 'main' and len(shared['associations']) == 2
    assert not shared.get('identity_conflicts')
    # Without the recorded withdrawn-hosted classification this is a real
    # unresolved conflict. Preview still yields metadata; apply changes nothing.
    mapping.pop('hosted')
    old.write_text(yaml.safe_dump(mapping))
    before = _snapshot(tmp_path)
    conflict = run_process(command, cwd=tmp_path)
    assert conflict.returncode == 0, conflict.stderr
    shared = next(item for item in yaml.safe_load(conflict.stdout)['sessions'] if item.get('session') == 'shared')
    assert shared['identity_conflicts'] and len(shared['associations']) == 2
    assert _migrate(installed_commands, tmp_path).returncode != 0
    assert _snapshot(tmp_path) == before


def test_historical_checker_can_be_established_native_root(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """A complete root's exact native owner is not revoked by its checker history."""
    import json

    _ticket_project(tmp_path)
    runner = tmp_path / '.graphtraj/runner'
    source = tmp_path / 'main.jsonl'
    source.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'shared'}}) + '\n')
    connection = {'runtime': 'codex', 'session': 'shared', 'codex_home': '/not-scanned'}
    main = runner / 'main-sessions/main/session.yml'
    main.parent.mkdir(parents=True)
    main.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'shared', 'cwd': str(tmp_path),
                                   'connection': connection, 'activity': {'trace_file': str(source)}}))
    owner = runner / 'main-sessions/old-parent/session.yml'
    owner.parent.mkdir(parents=True)
    owner.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'old-parent', 'cwd': str(tmp_path)}))
    checker = owner.parent / 'checks/shared/session.yml'
    checker.parent.mkdir(parents=True)
    checker.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'shared', 'parent': 'old-parent'}))
    root = runner / 'sessions/2-child-handover0-engineer@engineer/mapping.yml'
    root.parent.mkdir(parents=True)
    mapping = {'alias': '2-child-handover0-engineer@engineer', 'runtime': 'codex', 'session': 'owned-root',
               'ticket_id': '2', 'team_generation': 1, 'role': 'engineer', 'parent': None,
               'retained_batch_file': 'batch.yml', 'worktree_path': str(tmp_path),
               'trace_file': str(tmp_path / 'absent-root.jsonl'), 'worker_pid': 1, 'runtime_pid': 2,
               'parent_connection': connection}
    root.write_text(yaml.safe_dump(mapping))
    command = [str(installed_commands.product), 'migrate-tickets', '--preview']
    result = run_process(command, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    shared = next(item for item in yaml.safe_load(result.stdout)['sessions'] if item.get('session') == 'shared')
    assert shared['agent'] == 'main' and not shared.get('identity_conflicts')
    assert {entry['kind'] for entry in shared['associations']} == {'main', 'checker'}
    assert next(entry for entry in shared['associations'] if entry['kind'] == 'main')['root_owners']
    # A different native connection is not equivalent ownership evidence.
    mapping['parent_connection'] = {**connection, 'codex_home': '/different-not-scanned'}
    root.write_text(yaml.safe_dump(mapping))
    result = run_process(command, cwd=tmp_path)
    shared = next(item for item in yaml.safe_load(result.stdout)['sessions'] if item.get('session') == 'shared')
    assert shared['identity_conflicts']


def test_migration_keeps_nested_trace_runtime_yaml_opaque(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Captured Runner trees are historical evidence, including native YAML tags."""
    _ticket_project(tmp_path)
    relative = Path('tickets/2-child/teams/1/traces/member/runner/dsh-home/profiles/web/cordis.patch.yml')
    path = tmp_path / '.graphtraj/state' / relative
    path.parent.mkdir(parents=True)
    content = b"disabled: !!js 'process.platform === win32'\nticket_id: original-native-value\n"
    path.write_bytes(content)
    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    migrated = tmp_path / '.graphtraj/state/tasks' / relative.relative_to('tickets')
    assert migrated.read_bytes() == content


def test_preview_lists_hidden_entries_as_foreign_not_tasks(tmp_path: Path) -> None:
    """Old-layout inventories keep a hidden Runtime marker out of the Task list."""
    from graphtraj.workspace.task_migration import foreign_entries

    tickets = tmp_path / "tickets"
    (tickets / "1-first").mkdir(parents=True)
    (tickets / ".claude/.cc-writes").mkdir(parents=True)
    (tickets / ".lock").write_bytes(b"")
    assert foreign_entries(tickets) == [".claude"]
    assert foreign_entries(tmp_path / "missing") == []

"""Project-limited Main activity and restartable native counters through public entries."""
import json
import subprocess
from pathlib import Path
import time

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.local_tool import bind
from test_main_finalize import host, native_hook
from test_desktop_activity import prepare, message


def project_query(root: Path, **arguments: object) -> dict:
    """Call the same controlled human operation used by the desktop process."""
    result = bind(root, desktop_observer=True)({
        'action': 'execute', 'feature': 'desktop_activity', 'arguments': arguments,
    })
    assert not result.failed, result.document
    return result.document


def count(total: int, last: int = 100) -> dict:
    """Represent Codex lifetime and per-response counters, including cache subsets."""
    return {'type': 'event_msg', 'timestamp': '2026-10-11T10:00:00Z', 'payload': {
        'type': 'token_count', 'info': {
            'total_token_usage': {'input_tokens': total, 'cached_input_tokens': total // 2, 'output_tokens': total // 10},
            'last_token_usage': {'input_tokens': last, 'cached_input_tokens': last // 2, 'output_tokens': last // 10},
        },
    }}


def turn(root: Path, name: str) -> dict:
    """Record native turn ownership; display parents never establish project scope."""
    return {'type': 'turn_context', 'payload': {'cwd': str(root), 'turn_id': name, 'model': 'gpt-5.3-codex'}}


def write_records(path: Path, rows: list[dict], mode: str = 'w') -> None:
    """Write a redacted native-format source, not any delivery or identity state."""
    with path.open(mode) as stream:
        for row in rows:
            stream.write(json.dumps(row) + '\n')



def dashboard_totals(pages: dict[str, list[dict]]) -> dict:
    """Feed public native pages into the exact Dashboard collector and arithmetic."""
    usage = (Path(__file__).parents[1] / 'desktop/src/usage.ts').as_uri()
    script = (
        'import fs from "node:fs"; '
        f'import {{collect,records,summarize}} from {json.dumps(usage)}; '
        'const pages=JSON.parse(fs.readFileSync(0,"utf8")); const totals={}; '
        'for (const [project,events] of Object.entries(pages)) {'
        ' const calls=new Map(); collect(calls,project,events); collect(calls,project,events);'
        ' totals[project]=summarize(records(calls)); }'
        'console.log(JSON.stringify(totals));'
    )
    checked = subprocess.run(
        ['node', '--preserve-symlinks', '--preserve-symlinks-main', '--input-type=module', '-e', script],
        input=json.dumps(pages), text=True, capture_output=True, timeout=15, check=True,
    )
    return json.loads(checked.stdout)


def test_native_main_two_projects_reopen_and_attribution(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Actual entry carrier plus controlled native peer establishes readable scoped Main."""
    root, binding = host
    monkeypatch.setattr('graphtraj.execution.runner_status.caller_runtime', lambda: None)
    second = root / 'second'
    second.mkdir()
    config = second / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(second, second))
    unrelated = root / 'unimported'
    unrelated.mkdir()
    source = root / 'rollout.jsonl'
    rows = [{'type': 'session_meta', 'payload': {'id': 'main', 'source': 'cli'}}]
    rows += [message('unknown old ownership'), count(1000)]
    rows += [turn(root, 'first'), message('project one Main output'), count(1100)]
    rows += [{'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'second'}},
             message('unknown-before-context')]
    rows += [turn(second, 'second'), message('project two Main output'), count(1500, 400)]
    # An unimported sibling Harness must never be mistaken for its containing project.
    other_config = unrelated / '.graphtraj/config.yml'
    other_config.parent.mkdir()
    other_config.write_text(default_configuration_content(unrelated, unrelated))
    rows += [turn(unrelated, 'other'), message('unrelated private output'), count(2400, 900)]
    rows += [{'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
        'total_token_usage': {'input_tokens': 2450, 'cached_input_tokens': 1225, 'output_tokens': 245},
    }}}]
    rows += [turn(root, 'back'), message('project one again'), count(2550)]
    write_records(source, rows)
    nested = root / 'source-subdirectory'
    nested.mkdir()
    assert native_hook(nested, 'SessionStart', transcript_path=str(source))['systemMessage']
    assert native_hook(second, 'SessionStart', transcript_path=str(source))['systemMessage']
    assert yaml.safe_load(binding.read_text())['summary_issue'].endswith('/236')
    alias = 'Main:codex:main'
    inventory = project_query(root)
    assert [(a['alias'], a['kind']) for a in inventory['agents']] == [(alias, 'main')]
    one = project_query(root, alias=alias)
    two = project_query(second, alias=alias)
    assert [e['text'] for e in one['events'] if e['kind'] == 'message'] == ['project one Main output', 'project one again']
    assert [e['text'] for e in two['events'] if e['kind'] == 'message'] == ['project two Main output']
    assert 'unrelated private output' not in json.dumps([one, two])
    facts = [e['usage'] for e in one['events'] if e['kind'] == 'usage']
    assert [(f['cumulative']['input_tokens'], f['previous_cumulative']['input_tokens']) for f in facts] == [(1100, 1000), (2550, 2450)]
    assert all(f['task_id'] is None and f['agent'] == alias for f in facts)
    assert source.as_posix() in json.dumps(one)
    totals = dashboard_totals({'one': one['events'], 'two': two['events']})
    assert totals['one']['tokens']['input']['value'] == 200
    assert totals['two']['tokens']['input']['value'] == 400
    assert totals['one']['tokens']['output']['value'] == 20
    assert totals['one']['tokens']['cache_read']['value'] == 100
    assert totals['one']['tokens']['cache_write']['known'] == 0
    # Clear only observer-process caches to model reconnection; durable source and cursor stay intact.
    from graphtraj.execution.desktop_activity import _READERS
    _READERS.clear()
    assert project_query(root, alias=alias, cursor=one['cursor'])['events'] == []
    write_records(source, [turn(second, 'new-other'), message('second append'), count(2800, 250),
                           turn(root, 'new-first'), message('first append'), count(2900)], 'a')
    appended = project_query(root, alias=alias, cursor=one['cursor'])
    assert [e['text'] for e in appended['events'] if e['kind'] == 'message'] == ['first append']
    assert next(e['usage'] for e in appended['events'] if e['kind'] == 'usage')['previous_cumulative']['input_tokens'] == 2800
    assert project_query(root, alias=alias, cursor=appended['cursor'])['events'] == []
    totals = dashboard_totals({'one': one['events'] + appended['events']})
    assert totals['one']['tokens']['input']['value'] == 300
    assert totals['one']['tokens']['output']['value'] == 30
    # No associated Main source can be selected via an arbitrary native Session ID/path.
    with pytest.raises(ValueError):
        project_query(root, alias='Main:codex:unrelated')


def test_copied_main_keeps_canonical_identity_in_activity(
    host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inherited metadata cannot make the verified Main's own output disappear."""
    root, _ = host
    monkeypatch.setattr('graphtraj.execution.runner_status.caller_runtime', lambda: None)
    rows = [
        {'type': 'session_meta', 'payload': {'id': 'main', 'source': 'cli', 'forked_from_id': 'ancestor'}},
        {'type': 'session_meta', 'payload': {'id': 'ancestor', 'source': 'cli'}},
        {'type': 'event_msg', 'payload': {'type': 'thread_settings_applied', 'thread_id': 'main',
                                        'thread_settings': {}}},
        turn(root, 'own-turn'), message('own fork output'),
    ]
    write_records(root / 'rollout.jsonl', rows)
    assert native_hook(root, 'SessionStart', source='fork')['systemMessage']
    output = project_query(root, alias='Main:codex:main')
    assert [event['text'] for event in output['events'] if event['kind'] == 'message'] == ['own fork output']


def test_member_cursor_reconnect_rotation_truncation_and_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same dataset gives bounded hot/reopen reads and replay after physical replacement."""
    monkeypatch.setattr('graphtraj.execution.runner_status.caller_runtime', lambda: None)
    _, _, trace = prepare(tmp_path, 'codex', [turn(tmp_path, 'one')] + [count(i * 100) for i in range(1, 601)])
    alias = 'research@x1'
    started = time.perf_counter()
    cursor = None
    cold_reads = 0
    cold_events = []
    while True:
        page = project_query(tmp_path, task_id='148', alias=alias, **({'cursor': cursor} if cursor else {}))
        cold_reads += page['read_records']
        cold_events.extend(page['events'])
        cursor = page['cursor']
        if not page['has_more']:
            break
    cold_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    hot = project_query(tmp_path, task_id='148', alias=alias, cursor=cursor)
    hot_ms = (time.perf_counter() - started) * 1000
    from graphtraj.execution.desktop_activity import _READERS
    _READERS.clear()
    started = time.perf_counter()
    reopened = project_query(tmp_path, task_id='148', alias=alias, cursor=cursor)
    reopen_ms = (time.perf_counter() - started) * 1000
    assert hot['events'] == reopened['events'] == []
    assert hot['read_records'] < cold_reads and reopened['read_records'] < cold_reads
    assert reopened['cursor'] == cursor
    import base64
    data, signature = cursor.rsplit('.', 1)
    tampered = json.loads(base64.urlsafe_b64decode(data))
    tampered['context'] = []
    forged = base64.urlsafe_b64encode(json.dumps(tampered).encode()).decode() + '.' + signature
    assert project_query(tmp_path, task_id='148', alias=alias, cursor=forged)['availability'] == 'cursor-expired'
    print(json.dumps({'dataset': '601 native records', 'cold_ms': cold_ms, 'hot_ms': hot_ms,
                      'reopen_ms': reopen_ms, 'cold_records_read': cold_reads,
                      'hot_records_read': hot['read_records'], 'reopen_records_read': reopened['read_records']}))
    trace.rename(trace.with_suffix('.rotated'))
    write_records(trace, [turn(tmp_path, 'two'), count(60000), count(60100)])
    assert project_query(tmp_path, task_id='148', alias=alias, cursor=cursor)['availability'] == 'trace-changed'
    replay = project_query(tmp_path, task_id='148', alias=alias)
    assert replay['events'][0]['usage']['identity'] == cold_events[-1]['usage']['identity']
    write_records(trace, [turn(tmp_path, 'three'), count(60100)])
    assert project_query(tmp_path, task_id='148', alias=alias, cursor=replay['cursor'])['availability'] == 'trace-changed'
    # A member reads project-wide Main observation under its own identity, never as human.
    from graphtraj.workspace.runner_project import discover_runner_directory
    with runtime_caller(discover_runner_directory(tmp_path), alias):
        assert project_query(tmp_path)['scope'] == 'project'


def test_pi_native_entry_exposes_owned_main_and_excludes_plugin_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi's existing session_start association supplies its exact persisted source."""
    from test_external_session_entry import native, pi_session
    from graphtraj.runtimes import replacement

    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.chdir(tmp_path)
    event = pi_session(tmp_path, monkeypatch, 'pi-main', [{
        'type': 'message', 'id': 'one', 'timestamp': '2026-10-11T12:00:00Z',
        'message': {'role': 'assistant', 'model': 'deepseek-v4-flash',
                    'content': [{'type': 'text', 'text': 'Pi owned Main output'}],
                    'usage': {'input': 20, 'cacheRead': 10, 'cacheWrite': 0, 'output': 5}},
    }])
    assert native('pi', event) == {'source': 'main'}
    monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
    child = pi_session(tmp_path, monkeypatch, 'pi-child', [])
    assert native('pi', child) == {'source': 'child'}
    # Switch the controlled test caller to the independent human observer seam.
    for name in ('GRAPHTRAJ_NATIVE_RUNTIME', 'GRAPHTRAJ_NATIVE_SESSION', 'GRAPHTRAJ_NATIVE_SESSION_FILE', 'PI_SUBAGENT_CHILD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(replacement, 'caller_runtime', lambda: None)
    monkeypatch.setattr('graphtraj.execution.runner_status.caller_runtime', lambda: None)
    listing = project_query(tmp_path)
    assert [agent['alias'] for agent in listing['agents']] == ['Main:pi:pi-main']
    page = project_query(tmp_path, alias='Main:pi:pi-main')
    assert page['events'][0]['text'] == 'Pi owned Main output'
    assert page['events'][1]['usage']['tokens']['input'] == 30
    # Replacing a known source with an unrelated Session does not inherit project coverage.
    write_records(tmp_path / 'pi-main.jsonl', [
        {'type': 'session', 'version': 3, 'id': 'different-main', 'cwd': str(tmp_path)},
        {'type': 'message', 'id': 'other', 'message': {'role': 'assistant', 'content': 'unrelated'}},
    ])
    assert project_query(tmp_path, alias='Main:pi:pi-main')['events'] == []

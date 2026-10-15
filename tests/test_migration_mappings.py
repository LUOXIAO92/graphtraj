"""Confirmed legacy Issue identities enter only the one-way backup mapping."""
import json
from pathlib import Path

from click.testing import CliRunner
import yaml

from graphtraj.interfaces.cli.graphtraj import main
from test_github_backup import project, remote, _backup, _issues


def _input(root: Path) -> Path:
    """Supply an authoritative pair with incomplete remote evidence, not a remote baseline."""
    source = root / 'confirmed-mappings.json'
    source.write_text(json.dumps([{
        'local_id': '42', 'remote_number': 17,
        'remote_url': 'https://github.com/owner/repo/issues/17',
        'local_definition': '.graphtraj/state/tasks/42-backup-this-task/task.md',
        'mapping_source': '.graphtraj/state/tasks/42-backup-this-task/task.md',
        'mapping_confirmation': 'Operator confirmed the existing local mapping.',
        'remote_body_prefix': 'Remote prefix must never replace the local Task.',
        'remote_title': 'Different remote title',
    }]))
    return source


def _adopt(source: Path, *options: str):
    """Use the shipped public migration operation, preserving caller environment."""
    return CliRunner().invoke(main, ['migration-mappings', '--file', str(source),
                                    '--evidence-ref', 'confirmed-worldline-event', *options])


def test_adopted_mapping_is_local_authoritative_and_first_publish_requires_review(project: Path, remote: Path) -> None:
    """Import does no remote I/O; later backup targets the confirmed異号Issue only."""
    source = _input(project)
    tasks = project / '.graphtraj/state/tasks'
    before = {str(p.relative_to(tasks)): p.read_bytes() for p in tasks.rglob('*') if p.is_file()}
    mapping = project / '.graphtraj/state/task-backups.yml'
    result = _adopt(source, '--preview')
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.output)['added'] == 1 and not mapping.exists()
    result = _adopt(source)
    assert result.exit_code == 0, result.output
    stored = mapping.read_bytes()
    assert yaml.safe_load(stored)['backups'][0]['published'] is None
    assert yaml.safe_load(stored)['backups'][0]['issue']['node_id'] is None
    repeated = _adopt(source)
    assert repeated.exit_code == 0 and yaml.safe_load(repeated.output)['unchanged'] == 1
    assert mapping.read_bytes() == stored
    assert {str(p.relative_to(tasks)): p.read_bytes() for p in tasks.rglob('*') if p.is_file()} == before
    assert json.loads(remote.read_text())['requests'] == []
    unrelated = _issues(remote)[42]
    code, conflict = _backup('--repository', 'owner/repo')
    assert code == 1 and conflict['outcome'] == 'conflict'
    assert all(value['published'] is None for value in conflict['differences'].values())
    assert conflict['backup']['issue']['node_id'] == 'X_17'
    assert [request['method'] for request in json.loads(remote.read_text())['requests']] == ['GET']
    code, accepted = _backup('--repository', 'owner/repo', '--confirm-remote', conflict['remote_digest'])
    assert code == 0 and accepted['outcome'] == 'updated'
    assert _issues(remote)[17]['title'] == 'Backup this task'
    assert _issues(remote)[42] == unrelated and len(_issues(remote)) == 42
    assert {str(p.relative_to(tasks)): p.read_bytes() for p in tasks.rglob('*') if p.is_file()} == before


def test_import_rejects_conflict_or_invalid_url_before_writing_any_pair(project: Path, remote: Path) -> None:
    """No partial batch, guessed Issue creation or overwrite of an established mapping."""
    source = _input(project)
    rows = json.loads(source.read_text())
    source.write_text(json.dumps(rows + [{**rows[0], 'remote_url': 'https://github.com/owner/repo/issues/18'}]))
    result = _adopt(source)
    assert result.exit_code != 0 and not (project / '.graphtraj/state/task-backups.yml').exists()
    source.write_text(json.dumps(rows))
    assert _adopt(source).exit_code == 0
    mapping = project / '.graphtraj/state/task-backups.yml'
    before = mapping.read_bytes()
    source.write_text(json.dumps([{**rows[0], 'remote_number': 18,
                                  'remote_url': 'https://github.com/owner/repo/issues/18'}]))
    result = _adopt(source)
    assert result.exit_code != 0 and mapping.read_bytes() == before
    assert json.loads(remote.read_text())['requests'] == []

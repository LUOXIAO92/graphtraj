"""Same-Session recovery consumes opaque Adapter settings through public send."""

import copy
import io
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from graphtraj.execution import runner_control, runner_worker
from graphtraj.execution.runner_connection import session_operation
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.runtimes import runtime_adapter
from graphtraj.teams.team_round import _resume_job
from test_result_submission import result_project
from test_worker_adapter import AlternativeExecution


@pytest.mark.parametrize('reports_only', [False, True])
def test_alternative_recovery_reaches_managed_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reports_only: bool,
) -> None:
    """Native grants, connection and identity flow through selection, then the Worker."""
    runner, team, _ = result_project(tmp_path)
    worktree = tmp_path / 'worktrees/research'
    for arguments in [('init',), ('config', 'user.name', 'Test'),
                      ('config', 'user.email', 'test@example.invalid'),
                      ('commit', '--allow-empty', '-m', 'Harness'), ('branch', 'dev')]:
        subprocess.run(['git', *arguments], cwd=tmp_path, check=True, capture_output=True)
    integration = tmp_path / 'worktrees/dev'
    subprocess.run(['git', 'worktree', 'add', str(integration), 'dev'], cwd=tmp_path, check=True)
    config_file = tmp_path / '.graphtraj/config.yml'
    config = yaml.safe_load(config_file.read_text())
    config['paths']['agent_worktrees'] = 'worktrees'
    config_file.write_text(yaml.safe_dump(config))
    (tmp_path / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'alternative', 'model': 'captured'}},
        'role_tree': {'researcher': {}},
    }))
    alias = 'research@x1'
    directory = runner / 'sessions' / alias
    mapping_file = directory / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    mapping.update(runtime='alternative', execution_id='old-execution')
    report = mapping.pop('report_files')[0]
    mapping_file.write_text(yaml.safe_dump(mapping))
    evidence = team.parents[2]
    owned = evidence.joinpath(*Path(report).parts[1:])
    owned.parent.mkdir(parents=True, exist_ok=True)
    owned.write_text('Retained result')
    request = {'conversation': mapping['session'], 'grants': [report],
               'access': 'edit', 'tuning': {'model': 'captured', 'provider': 'retained'}}
    launch = {'runtime': 'alternative', 'mapping': mapping,
              'adapter_request': request, 'connection': {'endpoint': ['native', 17]},
              'context_evidence': {'original': True}}
    launch_file = directory / 'launch.yml'
    launch_file.write_text(yaml.safe_dump(launch))
    (directory / 'execution.yml').write_text('outcome: completed\n')
    (directory / 'identity.txt').write_text(mapping['session'])
    before = launch_file.read_bytes()
    owners = []
    selected = []
    handoff = {}

    class Adapter:
        """Own a representation with no Codex CLI, config or native fields."""

        def read_session_identity(self, session_directory: Path) -> str:
            """Attest this Runtime's native Session record."""
            return (session_directory / 'identity.txt').read_text()

        def recovery_environment(self, connection: dict) -> dict:
            """Interpret an opaque connection with non-string native values."""
            assert connection == {'endpoint': ['native', 17]}
            return {'ALTERNATIVE_ENDPOINT': 'native:17'}

        def recover_report_files(self, retained: dict, evidence: Path) -> tuple[str, ...]:
            """Recover only this Runtime's retained exact grants."""
            assert retained == request
            return tuple(retained['grants'])

        def refresh_report_paths(self, retained: dict, **kwargs: object) -> dict:
            """Copy settings and narrow access only when explicitly requested."""
            assert kwargs['worktree'] == Path(mapping['worktree_path'])
            result = copy.deepcopy(retained)
            result['grants'] = [str(path) for path in kwargs['report_files']]
            result['access'] = 'view' if kwargs['reports_only'] else retained['access']
            return result

        def managed_execution(
            self,
            retained: dict,
            prompt: str,
            session_directory: Path,
            session_started: object,
            context_evidence: dict,
            **kwargs: object,
        ) -> AlternativeExecution:
            """Consume the recovery output through the real Worker lifecycle."""
            assert retained == {**request, 'access': 'view' if reports_only else 'edit'}
            assert context_evidence == {'original': True}
            assert kwargs['expected_session'] == mapping['session']
            owner = AlternativeExecution(session_directory, kwargs['session_created'],
                                         session_started, kwargs['expected_session'], 'new-execution')
            owners.append(owner)
            return owner

    def select(runtime: str) -> Adapter:
        """Inject solely through the existing shared Runtime selection boundary."""
        assert runtime == 'alternative'
        selected.append(runtime)
        return Adapter()

    class Handoff(Exception):
        """Transfer the prepared job to an in-process Worker with this test Adapter."""

    def worker_handoff(command: list[str], **kwargs: object) -> None:
        """Capture only process creation; all core recovery remains real."""
        handoff.update(job=Path(command[-1]), environment=kwargs['env'])
        raise Handoff()

    monkeypatch.setattr(runtime_adapter, 'select_runtime_adapter', select)
    monkeypatch.setattr(runner_worker, 'select_runtime_adapter', select)
    process = runner_control.subprocess
    monkeypatch.setattr(runner_control, 'subprocess', SimpleNamespace(
        Popen=worker_handoff, PIPE=process.PIPE, DEVNULL=process.DEVNULL,
    ))
    cause = read_worldline(tmp_path / 'state', tmp_path)[-1]['event_id']
    with runtime_caller(runner, None):
        assert runner_control.read_session_reports(alias, tmp_path)['reports'] == [
            {'path': str(owned), 'text': 'Retained result'}]
        (directory / 'identity.txt').write_text('different-session')
        with pytest.raises(RunnerError) as rejected:
            runner_control.send_instruction(alias, 'Continue', tmp_path, (cause,), reports_only=reports_only)
        assert rejected.value.code == 'operation-failed'
        assert not handoff
        (directory / 'identity.txt').write_text(mapping['session'])
        with pytest.raises(Handoff):
            runner_control.send_instruction(alias, 'Continue', tmp_path, (cause,), reports_only=reports_only)
    job = yaml.safe_load(handoff['job'].read_text())
    assert handoff['environment']['ALTERNATIVE_ENDPOINT'] == 'native:17'
    assert job['expected_session'] == mapping['session']
    assert job['mapping']['parent'] == mapping['parent']
    assert job['drive_children'] is not reports_only

    # The task recovery preparation also uses the same Adapter and original binding.
    resume, environment = _resume_job(directory, mapping['session'], mapping['role'],
                                      Path(mapping['worktree_path']), evidence, (Path(report),),
                                      reports_only=reports_only)
    assert environment == {'ALTERNATIVE_ENDPOINT': 'native:17'}
    assert yaml.safe_load(resume.read_text())['adapter_request'] == job['adapter_request']
    # Retain the public send job for execution without enabling task budget machinery.
    handoff['job'].write_text(yaml.safe_dump(job))
    monkeypatch.setattr('sys.stdin', io.StringIO('Continue'))

    def finish() -> None:
        """Finish through the Worker's actual control channel after it publishes identity."""
        import time
        deadline = time.monotonic() + 5
        while not owners:
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert owners[0].ready.wait(5)
        current = yaml.safe_load(mapping_file.read_text())
        assert current['session'] == mapping['session']
        assert current['parent'] == mapping['parent']
        assert current['execution_id'] == 'new-execution'
        session_operation(current, 'send', instruction='finish')

    with ThreadPoolExecutor(max_workers=1) as executor:
        finished = executor.submit(finish)
        assert runner_worker.run(handoff['job']) == 0
        finished.result(timeout=5)
    assert owners[0].inputs == ['finish']
    assert launch_file.read_bytes() == before
    assert selected


def test_codex_invalid_recovery_grants_fail_before_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable native permission profile cannot manufacture report access."""
    runner, _, _ = result_project(tmp_path)
    directory = runner / 'sessions/research@x1'
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    del mapping['report_files']
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    (directory / 'launch.yml').write_text(yaml.safe_dump({
        'runtime': 'codex', 'mapping': mapping, 'connection': {},
        'adapter_request': {'session_parameters': {'config': {'permissions': {}}}},
    }))
    with runtime_caller(runner, None), pytest.raises(RunnerError) as failure:
        runner_control.read_session_reports(mapping['alias'], tmp_path)
    assert failure.value.code == 'session-not-resumable'

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _checkout_pythonpath(configured: Optional[str], cwd: Path) -> str:
    """Put this checkout's src first and make every entry absolute.

    pyproject's pythonpath covers only this process. Subprocesses (fake Runtimes
    run by sys.executable, installed commands) start in other directories, where
    a relative entry such as ``src`` names nothing and the venv's own installed
    graphtraj, possibly another or a removed tree, would be imported instead.
    """
    entries = [str(PROJECT_ROOT / "src")]
    for entry in (configured or "").split(os.pathsep):
        if entry:
            entry = str(cwd / entry)
            if entry not in entries:
                entries.append(entry)
    return os.pathsep.join(entries)


os.environ["PYTHONPATH"] = _checkout_pythonpath(os.environ.get("PYTHONPATH"), Path.cwd())


@dataclass(frozen=True)
class InstalledCommands:
    product: Path
    runner: Path


@dataclass(frozen=True)
class FakeCodex:
    executable: Path
    log_file: Path


# Task 344 removed the agent-runner status/send/interrupt routes; agents is the
# public control. Tests of the Runner behaviour behind those routes run the same
# library operations in the installed package, with the removed command's output.
_RUNNER_OPERATION = """
import argparse, json, sys, yaml
from pathlib import Path
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import status_aliases, status_tree
from graphtraj.execution.runner_control import interrupt_session, send_instruction
parser = argparse.ArgumentParser()
parser.add_argument('operation')
parser.add_argument('aliases', nargs='*')
parser.add_argument('--operation-total', action='store_true')
parser.add_argument('--baseline')
parser.add_argument('--candidate')
parser.add_argument('--instruction')
parser.add_argument('--caused-by-event-id', action='append', default=[])
parser.add_argument('--caused-by-event-ids', type=json.loads, default=[])
parser.add_argument('--reports-only', action='store_true')
parser.add_argument('--execution-id')
parser.add_argument('--request-file')
parser.add_argument('--response')
options = parser.parse_args()
cwd = Path.cwd().resolve()
identity = {'alias': options.aliases[0]} if options.operation != 'status' else {}
try:
    if options.operation in ('requests', 'reply'):
        from graphtraj.execution.runner_control import pending_requests, reply_to_request
        document = (pending_requests(options.aliases[0], cwd, execution_id=options.execution_id)
                    if options.operation == 'requests' else reply_to_request(
                        options.aliases[0], yaml.safe_load(Path(options.request_file).read_text()),
                        json.loads(options.response), cwd))
        sys.stdout.write(yaml.safe_dump(document, sort_keys=False))
        sys.exit(0)
    if options.operation == 'status':
        selected = dict(operation_total=options.operation_total, baseline=options.baseline,
                        candidate=options.candidate)
        response = (status_aliases(options.aliases, cwd, **selected) if options.aliases
                    else status_tree(cwd, **selected))
        sys.stdout.write(yaml.safe_dump(response.document, sort_keys=False))
        for error in response.errors:
            sys.stderr.write(error.message + '\\n')
        sys.exit(0 if response.succeeded else 1)
    if options.operation == 'send':
        document = send_instruction(options.aliases[0], options.instruction, cwd,
                                    (*options.caused_by_event_id, *options.caused_by_event_ids), reports_only=options.reports_only)
    elif options.operation == 'retire':
        from graphtraj.execution.runner_retirement import retire_session
        document = retire_session(options.aliases[0], cwd)
    else:
        document = interrupt_session(options.aliases[0], cwd)
    sys.stdout.write(yaml.safe_dump(document, sort_keys=False))
except RunnerError as error:
    sys.stdout.write(yaml.safe_dump({**identity, 'error': error.as_document()}, sort_keys=False))
    sys.stderr.write(error.message + '\\n')
    sys.exit(1)
"""


REMOVED_RUNNER_OPERATIONS = frozenset({"status", "send", "interrupt", "requests", "reply", "retire"})


def runner_operation(commands: "InstalledCommands", *arguments: str) -> list[str]:
    """Exercise a retained Runner library operation after its CLI route was removed."""
    return [str(commands.runner.with_name("python")), "-c", _RUNNER_OPERATION, *arguments]


def runner_command(commands: "InstalledCommands", *arguments: str) -> list[str]:
    """Return the installed agent-runner argv, or the library replica of a removed operation."""
    if arguments and arguments[0] in REMOVED_RUNNER_OPERATIONS:
        return runner_operation(commands, *arguments)
    return [str(commands.runner), *arguments]


def unsupported_dsh() -> Optional[str]:
    """Return why the installed DSH cannot back native tests, mirroring the product check."""
    import json

    dsh = shutil.which("dsh")
    if dsh is None or shutil.which("node") is None:
        return "Installed DSH and Node are required."
    try:
        version = json.loads((Path(dsh).resolve().parent.parent / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        version = None
    if version != "0.2.0-rc.2":
        return "DSH 0.2.0-rc.2 is required (installed: {0}).".format(version)
    return None

def run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def wait_for_file(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for {0}".format(path))


def find_uv() -> Optional[Path]:
    configured = os.environ.get("UV")
    candidate = configured or shutil.which("uv")
    if candidate is None:
        return None

    executable = Path(candidate)
    if executable.is_file() and os.access(executable, os.X_OK):
        return executable
    return None



def app_server_peer(
    script: str, identity: str = "os.environ.get('GRAPHTRAJ_PARENT_ALIAS', 'fake-thread')",
) -> str:
    """Run a controlled Team scenario with a distinct native identity per Agent."""
    peer = Path(__file__).with_name("runner_codex_peer.py")
    header = (
        "import sys, os\n"
        "if sys.argv[1:2] == ['app-server']:\n"
        "    import runpy\n"
        f"    runpy.run_path({str(peer)!r}, init_globals={{'scenario': __file__, 'session_name': {identity}}})\n"
        "    raise SystemExit(0)\n"
    )
    if script.startswith("#!"):
        first, script = script.split("\n", 1)
        return first + "\n" + header + script
    return header + script

@pytest.fixture(autouse=True)
def isolated_runner_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Harnesses must not inherit the invoking Agent's role or Session."""
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for name in tuple(os.environ):
        if name.startswith("GRAPHTRAJ_"):
            monkeypatch.delenv(name)


@pytest.fixture
def temporary_git_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "target-project"
    repository.mkdir()
    run_process(["git", "init", "--initial-branch=main"], cwd=repository).check_returncode()
    run_process(["git", "config", "user.name", "Harness Test"], cwd=repository).check_returncode()
    run_process(
        ["git", "config", "user.email", "harness-test@example.invalid"],
        cwd=repository,
    ).check_returncode()
    (repository / "README.md").write_text("# Target project\n", encoding="utf-8")
    run_process(["git", "add", "README.md"], cwd=repository).check_returncode()
    run_process(["git", "commit", "-m", "Initial target project"], cwd=repository).check_returncode()
    return repository


@pytest.fixture
def fake_codex(tmp_path: Path) -> FakeCodex:
    bin_directory = tmp_path / "fake-runtime-bin"
    bin_directory.mkdir()
    log_file = tmp_path / "fake-codex.log"
    executable = bin_directory / "codex"
    script = "#!{0}\n".format(sys.executable) + (
        "import json\n"
        "import os\n"
        "import signal\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "\n"
        "if sys.argv[1:] == ['exec', '--help']:\n"
        "    print('--config --json --sandbox' if os.environ.get('FAKE_CODEX_UNSUPPORTED') != '1' else '--config --json')\n"
        "    raise SystemExit(0)\n"
        "configured_events = os.environ.get('FAKE_CODEX_EVENTS')\n"
        "if configured_events is None:\n"
        "    events = [\n"
        "        {'type': 'thread.started', 'thread_id': os.environ.get('FAKE_CODEX_SESSION_ID', 'fake-thread')},\n"
        "        {'type': 'turn.started'},\n"
        "        {\n"
        "            'type': 'turn.completed',\n"
        "            'usage': {\n"
        "                'cached_input_tokens': 0,\n"
        "                'input_tokens': 0,\n"
        "                'output_tokens': 0,\n"
        "            },\n"
        "        },\n"
        "    ]\n"
        "else:\n"
        "    events = json.loads(configured_events)\n"
        "\n"
        "native_rollout = None\n"
        "def emit(event):\n"
        "    global native_rollout\n"
        "    print(json.dumps(event, sort_keys=True), flush=True)\n"
        "    if event.get('type') == 'thread.started':\n"
        "        session = event['thread_id']\n"
        "        native_rollout = Path(__file__).parent / 'codex-home/sessions/fake' / ('rollout-' + session + '.jsonl')\n"
        "        native_rollout.parent.mkdir(parents=True, exist_ok=True)\n"
        "        if not native_rollout.exists():\n"
        "            native_rollout.write_text(json.dumps({'timestamp': 'fake-native-start', 'type': 'session_meta', 'payload': {'id': session}}) + '\\n')\n"
        "    item = event.get('item')\n"
        "    if native_rollout is not None and isinstance(item, dict) and item.get('type') == 'agent_message':\n"
        "        with native_rollout.open('a') as stream:\n"
        "            stream.write(json.dumps({'timestamp': 'fake-native-result', 'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': item.get('text')}}) + '\\n')\n"
        "\n"
        "termination_seen = os.environ.get('FAKE_CODEX_TERMINATION_SEEN')\n"
        "termination_release = os.environ.get('FAKE_CODEX_TERMINATION_RELEASE')\n"
        "if termination_seen is not None and termination_release is not None:\n"
        "    def delay_termination(signum, frame):\n"
        "        signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "        Path(termination_seen).touch()\n"
        "        while not Path(termination_release).exists():\n"
        "            time.sleep(0.01)\n"
        "        raise SystemExit(128 + signum)\n"
        "    signal.signal(signal.SIGTERM, delay_termination)\n"
        "    ready_file = os.environ.get('FAKE_CODEX_TERMINATION_READY')\n"
        "    if ready_file is not None:\n"
        "        Path(ready_file).touch()\n"
        "\n"
        "group_child_pid = os.environ.get('FAKE_CODEX_GROUP_CHILD_PID')\n"
        "if group_child_pid is not None:\n"
        "    group_child_release = os.environ['FAKE_CODEX_GROUP_CHILD_RELEASE']\n"
        "    child_program = (\n"
        "        'import os, signal, sys, time\\n'\n"
        "        'from pathlib import Path\\n'\n"
        "        'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "        'Path(sys.argv[1]).write_text(str(os.getpid()), encoding=\\\"utf-8\\\")\\n'\n"
        "        'while not Path(sys.argv[2]).exists():\\n'\n"
        "        '    time.sleep(0.01)\\n'\n"
        "    )\n"
        "    subprocess.Popen(\n"
        "        [sys.executable, '-c', child_program, group_child_pid, group_child_release],\n"
        "        stdin=subprocess.DEVNULL,\n"
        "        stdout=subprocess.DEVNULL,\n"
        "        stderr=subprocess.DEVNULL,\n"
        "    )\n"
        "\n"
        "mapping_release = os.environ.get('FAKE_CODEX_MAPPING_RELEASE')\n"
        "if mapping_release is not None:\n"
        "    while not Path(mapping_release).exists():\n"
        "        time.sleep(0.01)\n"
        "\n"
        "event_release = os.environ.get('FAKE_CODEX_EVENT_RELEASE')\n"
        "record = {'cwd': os.getcwd(), 'argv': sys.argv[1:]}\n"
        "capture_environment = os.environ.get('FAKE_CODEX_CAPTURE_ENV')\n"
        "if capture_environment is not None:\n"
        "    record['environment'] = {\n"
        "        name: bool(os.environ.get(name))\n"
        "        for name in capture_environment.split(',')\n"
        "        if name\n"
        "    }\n"
        "if os.environ.get('FAKE_CODEX_CAPTURE_CONNECTION') == '1':\n"
        "    expected_api_key = os.environ.get('FAKE_CODEX_EXPECTED_API_KEY')\n"
        "    record['connection'] = {\n"
        "        'base_url': os.environ.get('OPENAI_BASE_URL'),\n"
        "        'api_key_matches_expected': (\n"
        "            expected_api_key is not None\n"
        "            and os.environ.get('OPENAI_API_KEY') == expected_api_key\n"
        "        ),\n"
        "    }\n"
        "runtime_prompt = None\n"
        "if os.environ.get('FAKE_CODEX_CAPTURE_STDIN') == '1':\n"
        "    runtime_prompt = sys.stdin.read()\n"
        "    record['stdin'] = runtime_prompt\n"
        "if os.environ.get('FAKE_CODEX_CAPTURE_ROLE') == '1':\n"
        "    record['role'] = os.environ.get('GRAPHTRAJ_ROLE')\n"
        "log = Path(os.environ['FAKE_CODEX_LOG'])\n"
        "with log.open('a' if os.environ.get('FAKE_CODEX_APPEND_LOG') == '1' else 'w', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(record, sort_keys=True) + '\\n')\n"
        "policy_log = os.environ.get('FAKE_CODEX_POLICY_LOG')\n"
        "if policy_log:\n"
        "    import tomllib\n"
        "    settings = {}\n"
        "    for index, argument in enumerate(sys.argv[:-1]):\n"
        "        if argument == '-c':\n"
        "            settings.update(tomllib.loads(sys.argv[index + 1]))\n"
        "    if os.environ['GRAPHTRAJ_ROLE'] == 'team-leader':\n"
        "        emit(events.pop(0))\n"
        "        mapping = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']) / '.graphtraj/runner/sessions' / os.environ['GRAPHTRAJ_PARENT_ALIAS'] / 'mapping.yml'\n"
        "        while not mapping.exists():\n"
        "            time.sleep(0.01)\n"
        "    with Path(policy_log).open('a') as stream:\n"
        "        stream.write(json.dumps({'role': os.environ['GRAPHTRAJ_ROLE'], 'round': os.environ.get('GRAPHTRAJ_TEAM_ROUND'), 'settings': settings}) + '\\n')\n"
        "release_file = (os.environ.get('FAKE_CODEX_REVIEW_RELEASE_FILE') if os.environ.get('GRAPHTRAJ_ROLE') in {'standards-reviewer', 'spec-reviewer'} else os.environ.get('FAKE_CODEX_ENGINEER_RELEASE_FILE') if os.environ.get('GRAPHTRAJ_ROLE') == 'engineer' and os.environ.get('FAKE_CODEX_ENGINEER_RELEASE_FILE') else os.environ.get('FAKE_CODEX_RELEASE_FILE'))\n"
        "for index, event in enumerate(events):\n"
        "    emit(event)\n"
        "    if index == 0 and event_release is not None:\n"
        "        while not Path(event_release).exists():\n"
        "            time.sleep(0.01)\n"
        "    if index == 0 and release_file is not None:\n"
        "        while not Path(release_file).exists():\n"
        "            time.sleep(0.01)\n"
        "\n"
        "lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')\n"
        "if runtime_prompt is None and lifecycle_action == 'complete-team-round' and os.environ.get('GRAPHTRAJ_ROLE') == 'team-leader':\n"
        "    runtime_prompt = sys.stdin.read()\n"
        "if runtime_prompt and 'Receive these system notices' in runtime_prompt:\n"
        "    lifecycle_action = None\n"
        "elif runtime_prompt and ('Report the stopped implementation' in runtime_prompt or 'Execution has stopped' in runtime_prompt or 'Execution was stopped by Runner' in runtime_prompt):\n"
        "    lifecycle_action = 'stopped-report'\n"
        "elif lifecycle_action == 'complete-team-round' and os.environ.get('GRAPHTRAJ_ROLE') == 'team-leader':\n"
        "    # Individual notifications are observations, not the aggregated child results that advance this scenario.\n"
        "    try:\n"
        "        notice = json.loads(runtime_prompt or '')\n"
        "    except ValueError:\n"
        "        notice = None\n"
        "    if isinstance(notice, dict) and notice.get('source') == 'graphtraj':\n"
        "        lifecycle_action = None\n"
        "inline_role = os.environ.get('FAKE_CODEX_INLINE_ROLE', 'investigation-specialist')\n"
        "if lifecycle_action == 'follow-up-report':\n"
        "    import yaml\n"
        "    runner = os.environ['GRAPHTRAJ_AGENT_RUNNER']\n"
        "    assigned = yaml.safe_load(subprocess.run([runner, 'reports', os.environ['GRAPHTRAJ_PARENT_ALIAS']],\n"
        "                                             text=True, capture_output=True, check=True).stdout)\n"
        "    name = Path(([item['path'] for item in assigned['reports']] + assigned.get('missing_reports', []))[0]).name\n"
        "    report = subprocess.run([runner, 'submit-report', '--name', name, '--text', 'Follow-up verified.'],\n"
        "                            text=True, capture_output=True)\n"
        "    result = subprocess.run([runner, 'submit-result', '--commit', '0' * 40, '--result-ref', 'README.md',\n"
        "                             '--completion', 'Follow-up'], text=True, capture_output=True)\n"
        "    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({\n"
        "        'report': report.returncode, 'report_name': name, 'report_output': report.stdout + report.stderr,\n"
        "        'result': result.returncode,\n"
        "        'result_output': result.stdout + result.stderr})}})\n"
        "elif lifecycle_action == 'stopped-report':\n"
        "    evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])\n"
        "    round_dir = evidence / 'teams' / os.environ['GRAPHTRAJ_TEAM_GENERATION'] / 'rounds' / os.environ['GRAPHTRAJ_TEAM_ROUND']\n"
        "    round_dir.mkdir(parents=True, exist_ok=True)\n"
        "    candidate = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True).stdout.strip()\n"
        "    names = ('engineer.md', 'validation.md') if os.environ['GRAPHTRAJ_ROLE'] == 'engineer' else ('leader.md',)\n"
        "    for name in names:\n"
        "        (round_dir / name).write_text('Stopped result.\\nCandidate commit: ' + candidate + '\\n')\n"
        "elif lifecycle_action in {'resolve-integration', 'deliver-document'}:\n"
        '    import yaml\n'
        "    resolution = os.environ.get('FAKE_CODEX_RESOLUTION', 'resolved')\n"
        "    name = os.environ.get('FAKE_CODEX_RESULT_FILE', 'TEAM_ROUND_DELIVERED.txt')\n"
        "    if resolution in {'escalated', 'prose-only'}:\n"
        "        text = 'Decision: RESOLVED' if resolution == 'prose-only' else 'Incompatible accepted requirements'\n"
        '    else:\n'
        "        content = 'invalid reconciliation\\n' if resolution == 'invalid-resolution' else 'complete team round\\nconflicting integration work\\n'\n"
        "        if lifecycle_action == 'deliver-document':\n"
        "            content = 'complete team round\\n'\n"
        '        Path(name).write_text(content)\n'
        "        subprocess.run(['git', 'add', name], check=True, capture_output=True)\n"
        "        subprocess.run(['git', 'commit', '-m', 'Deliver document'], check=True, capture_output=True)\n"
        "        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()\n"
        '        evidence_args = []\n'
        "        if name == 'article.md':\n"
        '            from graphtraj.interfaces import tools\n'
        "            reports = tools.read_reports({'alias': os.environ['GRAPHTRAJ_PARENT_ALIAS']}, cwd=Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])).document\n"
        "            report = Path(reports['missing_reports'][0])\n"
        "            tools.submit_report({'name': report.name, 'text': 'Both document requirements inspected.'}, cwd=Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']))\n"
        "            relative = Path('.state') / report.relative_to(Path(os.environ['GRAPHTRAJ_EVIDENCE']))\n"
        "            evidence_args = ['--evidence-ref', str(relative)]\n"
        "        submitted = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'submit-result', '--commit', commit,\n"
        "                                    '--result-ref', name, '--evidence-ref', name, '--completion', 'Document reconciled', *evidence_args],\n"
        '                                   text=True, capture_output=True)\n'
        '        if submitted.returncode:\n'
        '            raise RuntimeError(submitted.stdout + submitted.stderr)\n'
        "        text = 'Committed document submitted for the parent decision.'\n"
        "    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})\n"
        "elif lifecycle_action == 'complete-team-round':\n"
        "    role = os.environ['GRAPHTRAJ_ROLE']\n"
        "    evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])\n"
        "    ordinal = os.environ.get('GRAPHTRAJ_TEAM_ROUND', '1')\n"
        "    round_dir = evidence / 'teams' / '1' / 'rounds' / ordinal\n"
        "    round_dir.mkdir(parents=True, exist_ok=True)\n"
        "    if role == 'delivery-state':\n"
        "        facts = json.loads(os.environ['GRAPHTRAJ_STATE_FACTS'])\n"
        "        if (os.environ.get('FAKE_CODEX_STATE_TAMPER') == 'accepted' "
        "and facts.get('phase') == 'final'):\n"
        "            facts['decision'] = 'accepted'\n"
        "        Path(os.environ['GRAPHTRAJ_STATE_REQUEST']).write_text(\n"
        "            json.dumps(facts, sort_keys=True) + '\\n'\n"
        "        )\n"
        "    elif role == 'team-leader':\n"
        "        from graphtraj.interfaces import tools\n"
        "        assigned = tools.read_reports({'alias': os.environ['GRAPHTRAJ_PARENT_ALIAS']}, cwd=Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])).document\n"
        "        paths = [item['path'] for item in assigned['reports']] + assigned.get('missing_reports', [])\n"
        "        leader_report = Path(paths[0])\n"
        "        counter = Path.cwd() / '.scratch' / ('leader-stage-' + ordinal)\n"
        "        stage = int(counter.read_text()) if counter.exists() else 0\n"
        "        counter.write_text(str(stage + 1))\n"
        "        final_clock = os.environ.get('FAKE_CODEX_FINAL_LEADER_CLOCK')\n"
        "        if final_clock and stage == 2:\n"
        "            clock = Path(final_clock)\n"
        "            clock.write_text(str(float(clock.read_text()) + 187))\n"
        "            time.sleep(0.8)\n"
        "        serial = bool(os.environ.get('FAKE_CODEX_SERIAL_TEAM'))\n"
        "        inline_specialist = os.environ.get('FAKE_CODEX_INLINE_SPECIALIST') == '1'\n"
        "        final_inline_specialist = os.environ.get('FAKE_CODEX_FINAL_INLINE_SPECIALIST') == '1'\n"
        "        selected = os.environ.get('FAKE_CODEX_REVIEW_AXES')\n"
        "        review_axes = ([axis for axis in selected.split() if axis]\n"
        "            if selected is not None else ['standards-reviewer', 'spec-reviewer'])\n"
        "        engineer_stage = 1 if inline_specialist else 0\n"
        "        reviewer_stage = engineer_stage + 1\n"
        "        final_specialist_stage = reviewer_stage + (2 if serial else 1)\n"
        "        if stage == 0 and inline_specialist:\n"
        "            roles = [inline_role]\n"
        "        elif stage == engineer_stage:\n"
        "            roles = ['engineer']\n"
        "        elif serial and stage in {reviewer_stage, reviewer_stage + 1}:\n"
        "            axis = 'standards-reviewer' if stage == reviewer_stage else 'spec-reviewer'\n"
        "            roles = [axis] if axis in review_axes else None\n"
        "        elif stage == reviewer_stage:\n"
        "            roles = review_axes or None\n"
        "        elif final_inline_specialist and stage == final_specialist_stage:\n"
        "            roles = [inline_role]\n"
        "        else:\n"
        "            roles = None\n"
        "        if roles == ['engineer'] and os.environ.get('FAKE_CODEX_PARALLEL_ENGINEERS'):\n"
        "            # Two dispatches of the same role in one turn, then a repeat of the second.\n"
        "            outcomes = []\n"
        "            for part in ('A', 'B', 'B'):\n"
        "                child = Path.cwd() / '.scratch' / ('children-%s-%s.yml' % (stage, part))\n"
        "                child.write_text('tasks:\\n  - role: coding-team.engineer\\n    instruction: Deliver part %s.\\n' % part)\n"
        "                completed = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--swarm-input', str(child)],\n"
        "                                           check=False, text=True, capture_output=True)\n"
        "                outcomes.append({'returncode': completed.returncode, 'stdout': completed.stdout})\n"
        "            (Path.cwd() / '.scratch' / 'parallel-registrations.json').write_text(json.dumps(outcomes))\n"
        "            roles = None\n"
        "            stage = -1\n"
        "        if roles is not None:\n"
        "            child = Path.cwd() / '.scratch' / ('children-%s.yml' % stage)\n"
        "            lines = ['tasks:']\n"
        "            for child_role in roles:\n"
        "                # The Leader's own direct-child entry adds the Task it\n"
        "                # already works in, so nothing here repeats that identity.\n"
        "                if child_role == inline_role:\n"
        "                    lines += [\n"
        "                        '  - role:',\n"
        "                        '      ' + inline_role + ':',\n"
        "                        '        runtime: codex',\n"
        "                        '        model: gpt-5.6-luna',\n"
        "                        '    instruction: Investigate before delivery.',\n"
        "                    ]\n"
        "                else:\n"
        "                    lines += ['  - role: coding-team.' + child_role]\n"
        "                if child_role == 'engineer' and os.environ.get('FAKE_CODEX_ENGINEER_SKILLS'):\n"
        "                    lines += ['    skills: ' + os.environ['FAKE_CODEX_ENGINEER_SKILLS']]\n"
        "            child.write_text('\\n'.join(lines) + '\\n')\n"
        "            completed = subprocess.run(\n"
        "                [os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--swarm-input', str(child)],\n"
        "                check=False, text=True, capture_output=True,\n"
        "            )\n"
        "            if completed.returncode != 0:\n"
        "                sys.stderr.write(completed.stdout + completed.stderr)\n"
        "                raise SystemExit(completed.returncode)\n"
        "            if serial:\n"
        "                import yaml\n"
        "                registered = yaml.safe_load(completed.stdout)['tasks']\n"
        "                assert len({child['alias'] for child in registered}) == len(roles)\n"
        "                assert all(child['launch_status'] == 'registered' for child in registered)\n"
        "                duplicate = subprocess.run(\n"
        "                    [os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--swarm-input', str(child)],\n"
        "                    check=False, text=True, capture_output=True,\n"
        "                )\n"
        "                assert duplicate.returncode != 0\n"
        "        elif stage >= 0:\n"
        "            candidate = subprocess.run(\n"
        "                ['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True\n"
        "            ).stdout.strip()\n"
        "            if os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'rework' and ordinal == '1':\n"
        "                decision = ('Decision: REJECT\\nCandidate commit: %s\\n' % candidate\n"
        "                    + 'Diagnosis: implementation\\nReviews: compliant\\nAction: rework\\n'\n"
        "                    + 'Rationale: Correct the missing delivered content with the same Engineer.\\n')\n"
        "            elif os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'reject':\n"
        "                decision = 'Cannot accept candidate: %s\\n' % candidate\n"
        "            elif os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'conflict':\n"
        "                decision = ('Decision: ACCEPT\\nDecision: REJECT\\n' "
        "+ 'Candidate commit: %s\\n' % candidate)\n"
        "            else:\n"
        "                decision = 'Decision: ACCEPT\\nCandidate commit: %s\\n' % candidate\n"
        "            diagnosis = os.environ.get('FAKE_CODEX_REWORK_CASE')\n"
        "            if diagnosis in {'process', 'main', 'product'}:\n"
        "                decision = decision.replace('Diagnosis: implementation', 'Diagnosis: ' + diagnosis)\n"
        "            tools.submit_report({'name': leader_report.name, 'text': decision}, cwd=Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']))\n"
        "            import yaml\n"
        "            team = yaml.safe_load((round_dir.parent.parent / 'team.yml').read_text())\n"
        "            authors = [member['session_ref'] for member in team['members'].values()\n"
        "                       if member['role'] == 'engineer' and member['session_ref']]\n"
        "            submitted = max((yaml.safe_load(subprocess.run(\n"
        "                [os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'reports', author],\n"
        "                capture_output=True, text=True, check=True).stdout)['submissions'][-1]\n"
        "                for author in authors), key=lambda item: item['event_id'])\n"
        "            if os.environ.get('FAKE_CODEX_PARALLEL_ENGINEERS'):\n"
        "                candidate = submitted['candidate']\n"
        "            accepted = decision.startswith('Decision: ACCEPT\\n') and 'Decision: REJECT' not in decision\n"
        "            reference = str(leader_report.relative_to(Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])))\n"
        "            judged = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'decide-result',\n"
        "                '--submission-id', submitted['event_id'], '--commit', candidate,\n"
        "                '--decision', 'accepted' if accepted else 'rejected',\n"
        "                '--reason', 'Task evidence supports this decision.', '--evidence-ref', reference],\n"
        "                capture_output=True, text=True)\n"
        "            assert judged.returncode == 0, judged.stdout + judged.stderr\n"
        "    elif role == inline_role:\n"
        "        pass\n"
        "    elif role == 'engineer':\n"
        "        # A second same-role member names its files after its own entity.\n"
        "        entity = os.environ['GRAPHTRAJ_PARENT_ALIAS'].partition('@')[2]\n"
        "        suffix = '' if entity == 'engineer' else '-' + entity\n"
        "        delivered = Path.cwd() / ('TEAM_ROUND_DELIVERED%s.txt' % suffix)\n"
        "        delivered.write_text('complete team round' + ('' if ordinal == '1' else ' ' + ordinal) + '\\n')\n"
        "        import fcntl\n"
        "        # Members sharing the Worktree commit and submit one at a time; the\n"
        "        # lock is held until this process exits.\n"
        "        git_lock = (Path.cwd() / '.scratch' / 'git.lock').open('w')\n"
        "        fcntl.flock(git_lock, fcntl.LOCK_EX)\n"
        "        subprocess.run(['git', 'add', delivered.name], check=True)\n"
        "        subprocess.run(['git', 'commit', '-m', 'Deliver team round candidate'], check=True)\n"
        "        candidate = subprocess.run(\n"
        "            ['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True\n"
        "        ).stdout.strip()\n"
        "        if os.environ.get('FAKE_CODEX_PARALLEL_ENGINEERS'):\n"
        "            # An engineer has no engineer child in the role_tree.\n"
        "            nested = Path.cwd() / '.scratch' / ('nested%s.yml' % suffix)\n"
        "            nested.write_text('tasks:\\n  - role: coding-team.engineer\\n')\n"
        "            refused = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--swarm-input', str(nested)],\n"
        "                                     check=False, text=True, capture_output=True)\n"
        "            (Path.cwd() / '.scratch' / ('nested%s.json' % suffix)).write_text(json.dumps(\n"
        "                {'returncode': refused.returncode, 'stdout': refused.stdout}))\n"
        "        (round_dir / ('engineer%s.md' % suffix)).write_text(\n"
        "            'Candidate commit: %s\\nSelf-review: passed.\\n' % candidate\n"
        "        )\n"
        "        (round_dir / ('validation%s.md' % suffix)).write_text(\n"
        "            'Candidate commit: %s\\nTests: passed.\\n' % candidate\n"
        "        )\n"
        "        submitted = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'submit-result',\n"
        "            '--commit', candidate, '--result-ref', delivered.name,\n"
        "            '--evidence-ref', str(round_dir / ('engineer%s.md' % suffix)), '--completion', 'Implemented'],\n"
        "            capture_output=True, text=True)\n"
        "        assert submitted.returncode == 0, submitted.stdout + submitted.stderr\n"
        "        if os.environ.get('FAKE_CODEX_REPORT_WITHOUT_COMMIT'):\n"
        "            (round_dir / 'engineer.md').write_text('Self-review retained in the submitted result.\\n')\n"
        "    else:\n"
        "        candidate = subprocess.run(\n"
        "            ['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True\n"
        "        ).stdout.strip()\n"
        "        report = round_dir / ('standards.md' if role == 'standards-reviewer' else 'spec.md')\n"
        "        report.write_text(\n"
        "            'Candidate commit: %s\\nDecision: pass.\\n' % candidate\n"
        "        )\n"
        "        if os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'rework':\n"
        "            axis = 'Standards' if role == 'standards-reviewer' else 'Spec'\n"
        "            finding = ('Finding: Missing delivered content\\nRule: Accepted Task delivery requirement\\n'\n"
        "                + 'Input: Run the delivered command\\nTrace: The command reads TEAM_ROUND_DELIVERED.txt\\n'\n"
        "                + 'Failure: Required content is missing\\nEvidence: TEAM_ROUND_DELIVERED.txt:1\\n'\n"
        "                if ordinal == '1' and axis == 'Spec' else 'Finding: none\\n')\n"
        "            report.write_text('Candidate commit: %s\\nAxis: %s\\nComparison: %s\\n'\n"
        "                % (candidate, axis, 'selected coding review') + finding)\n"
        "            case = os.environ.get('FAKE_CODEX_REWORK_CASE')\n"
        "            if case == 'invalid-evidence' and axis == 'Spec':\n"
        "                report.write_text(report.read_text().replace('Evidence:', 'Unsupported:'))\n"
        "            elif case == 'mismatched-report' and axis == 'Standards':\n"
        "                report.write_text(report.read_text().replace(candidate, '0' * 40))\n"
        "            elif case == 'no-findings':\n"
        "                report.write_text(report.read_text().split('Finding:')[0] + 'Finding: none\\n')\n"
        "\n"
        "raise SystemExit(int(os.environ.get('FAKE_CODEX_EXIT_CODE', '0')))\n"
    )
    executable.write_text(app_server_peer(script), encoding="utf-8")
    executable.chmod(0o755)
    return FakeCodex(executable=executable, log_file=log_file)


def _export_source(destination: Path) -> Path:
    """Copy the tracked and untracked source, including pending edits."""

    destination.mkdir(parents=True)
    files = run_process(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT,
    )
    files.check_returncode()
    for name in filter(None, files.stdout.split("\0")):
        source = PROJECT_ROOT / name
        if not source.exists() and not source.is_symlink():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
    return destination


def _build_wheel(build_root: Path) -> Path:
    """Build the distribution artifact that every installation installs."""

    source = _export_source(build_root / "source")
    wheelhouse = build_root / "wheelhouse"
    result = run_process(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-build-isolation",
            "--no-deps",
            "-w",
            str(wheelhouse),
            str(source / "src" / "agent_swarm"),
            str(source),
        ],
        cwd=source,
    )
    result.check_returncode()
    artifacts = sorted(wheelhouse.glob("graphtraj-*.whl"))
    assert len(artifacts) == 1, artifacts
    return artifacts[0]


def _install_commands(environment: Path, wheel: Path) -> InstalledCommands:
    """Install one built wheel into a fresh environment."""

    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--system-site-packages",
            str(environment),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    python = environment / "bin" / "python"
    result = run_process(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            str(wheel.with_name("agent_swarm-0.1.0-py3-none-any.whl")),
            str(wheel),
        ],
        cwd=wheel.parent,
    )
    result.check_returncode()
    # Workers use Python -I. Load their clock after site initialization so
    # dependencies inherited through system-site-packages are available.
    site = run_process([str(python), '-c',
                        "import sysconfig; print(sysconfig.get_path('purelib'))"], cwd=environment)
    site.check_returncode()
    if sys.prefix != sys.base_prefix:
        # A venv made from this venv inherits only the base interpreter's
        # packages; the test interpreter's own dependencies live here.
        Path(site.stdout.strip(), 'graphtraj_test_dependencies.pth').write_text(
            sysconfig.get_path('purelib') + '\n'
        )
    Path(site.stdout.strip(), 'graphtraj_test_clock.py').write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "if os.environ.get('BUDGET_CLOCK'):\n"
        "    for directory in os.environ.get('PYTHONPATH', '').split(os.pathsep):\n"
        "        script = Path(directory) / 'sitecustomize.py'\n"
        "        if directory and script.is_file() and script.resolve() != Path(__file__).resolve():\n"
        "            sys.path.insert(0, directory)\n"
        "            break\n"
    )
    Path(site.stdout.strip(), 'graphtraj_test_clock.pth').write_text('import graphtraj_test_clock\n')
    bin_directory = environment / "bin"
    assert {
        path.name for path in bin_directory.iterdir()
    }.issuperset(
        {
        "agent-runner",
        "graphtraj",
        "graphtraj-mcp",
        }
    )
    assert not (bin_directory / "you-are-a-product-architect").exists()
    return InstalledCommands(
        product=bin_directory / "graphtraj",
        runner=bin_directory / "agent-runner",
    )


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The wheel built from this working tree that installations install."""

    return _build_wheel(tmp_path_factory.mktemp("distribution-wheel"))


@pytest.fixture(scope="session")
def installed_commands(
    built_wheel: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledCommands:
    environment = tmp_path_factory.mktemp("installed-environment") / "venv"
    return _install_commands(environment, built_wheel)


@pytest.fixture(scope="session")
def installed_cleanup_commands(
    installed_commands: InstalledCommands,
) -> InstalledCommands:
    return installed_commands


@pytest.fixture(scope="session")
def installed_worktree_commands(
    installed_commands: InstalledCommands,
) -> InstalledCommands:
    return installed_commands


@pytest.fixture
def mutable_installed_commands(tmp_path: Path) -> InstalledCommands:
    build_root = tmp_path / "installed-mutable-environment"
    return _install_commands(build_root / "venv", _build_wheel(build_root))

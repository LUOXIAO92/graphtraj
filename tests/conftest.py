from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class InstalledCommands:
    product: Path
    runner: Path


@dataclass(frozen=True)
class FakeCodex:
    executable: Path
    log_file: Path


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



def app_server_peer(script: str, identity: str = "'fake-thread'") -> str:
    """Run a controlled Team scenario behind the native stdio test peer."""
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
        "        {'type': 'thread.started', 'thread_id': 'fake-thread'},\n"
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
        "        native_rollout = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions/fake' / ('rollout-' + session + '.jsonl')\n"
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
        "        mapping = Path(os.environ['GRAPHTRAJ_PARENT_REGISTRATION']).parent / 'mapping.yml'\n"
        "        while not mapping.exists():\n"
        "            time.sleep(0.01)\n"
        "    with Path(policy_log).open('a') as stream:\n"
        "        stream.write(json.dumps({'role': os.environ['GRAPHTRAJ_ROLE'], 'round': os.environ.get('GRAPHTRAJ_TEAM_ROUND'), 'settings': settings}) + '\\n')\n"
        "release_file = (os.environ.get('FAKE_CODEX_REVIEW_RELEASE_FILE') if os.environ.get('GRAPHTRAJ_ROLE') in {'standards-reviewer', 'spec-reviewer'} else os.environ.get('FAKE_CODEX_ENGINEER_RELEASE_FILE') if os.environ.get('GRAPHTRAJ_ROLE', '').startswith('engineer-') and os.environ.get('FAKE_CODEX_ENGINEER_RELEASE_FILE') else os.environ.get('FAKE_CODEX_RELEASE_FILE'))\n"
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
        "if runtime_prompt and 'Receive these system notices' in runtime_prompt:\n"
        "    lifecycle_action = None\n"
        "elif runtime_prompt and ('Report the stopped implementation' in runtime_prompt or 'Execution has stopped' in runtime_prompt or 'Execution was stopped by Runner' in runtime_prompt):\n"
        "    lifecycle_action = 'stopped-report'\n"
        "inline_role = os.environ.get('FAKE_CODEX_INLINE_ROLE', 'investigation-specialist')\n"
        "if lifecycle_action == 'stopped-report':\n"
        "    evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])\n"
        "    round_dir = evidence / 'teams' / os.environ['GRAPHTRAJ_TEAM_GENERATION'] / 'rounds' / os.environ['GRAPHTRAJ_TEAM_ROUND']\n"
        "    round_dir.mkdir(parents=True, exist_ok=True)\n"
        "    candidate = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True).stdout.strip()\n"
        "    names = ('engineer.md', 'validation.md') if os.environ['GRAPHTRAJ_ROLE'].startswith('engineer-') else ('leader.md',)\n"
        "    for name in names:\n"
        "        (round_dir / name).write_text('Stopped result.\\nCandidate commit: ' + candidate + '\\n')\n"
        "elif lifecycle_action == 'resolve-integration':\n"
        "    resolution = os.environ.get('FAKE_CODEX_RESOLUTION', 'resolved')\n"
        "    if resolution == 'escalated':\n"
        "        text = 'Decision: ESCALATE\\nMain: incompatible accepted requirements need a decision.'\n"
        "    else:\n"
        "        content = 'invalid reconciliation\\n' if resolution == 'invalid-resolution' else 'complete team round\\nconflicting integration work\\n'\n"
        "        Path('TEAM_ROUND_DELIVERED.txt').write_text(content)\n"
        "        subprocess.run(['git', 'add', 'TEAM_ROUND_DELIVERED.txt'], check=True, capture_output=True)\n"
        "        if resolution == 'unrelated-history':\n"
        "            subprocess.run(['git', 'commit', '-m', 'Unrelated history'], check=True, capture_output=True)\n"
        "        text = 'Decision: RESOLVED'\n"
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
        "        counter = Path.cwd() / '.scratch' / ('leader-stage-' + ordinal)\n"
        "        stage = int(counter.read_text()) if counter.exists() else 0\n"
        "        counter.write_text(str(stage + 1))\n"
        "        final_clock = os.environ.get('FAKE_CODEX_FINAL_LEADER_CLOCK')\n"
        "        if final_clock and stage == 2:\n"
        "            clock = Path(final_clock)\n"
        "            clock.write_text(str(float(clock.read_text()) + 187))\n"
        "            time.sleep(0.8)\n"
        "        serial = bool(os.environ.get('FAKE_CODEX_SERIAL_TEAM'))\n"
        "        if serial and stage > 0:\n"
        "            followup = sys.stdin.read()\n"
        "            assert ('insufficient-capacity' if stage == 2 else 'events.jsonl') in followup\n"
        "        inline_specialist = os.environ.get('FAKE_CODEX_INLINE_SPECIALIST') == '1'\n"
        "        final_inline_specialist = os.environ.get('FAKE_CODEX_FINAL_INLINE_SPECIALIST') == '1'\n"
        "        engineer_stage = 1 if inline_specialist else 0\n"
        "        reviewer_stage = engineer_stage + 1\n"
        "        final_specialist_stage = reviewer_stage + (3 if serial else 1)\n"
        "        if stage == 0 and inline_specialist:\n"
        "            roles = [inline_role]\n"
        "        elif stage == engineer_stage:\n"
        "            roles = ['engineer-junior']\n"
        "        elif stage == reviewer_stage:\n"
        "            roles = ['standards-reviewer', 'spec-reviewer']\n"
        "        elif serial and stage in {reviewer_stage + 1, reviewer_stage + 2}:\n"
        "            roles = ['standards-reviewer' if stage == reviewer_stage + 1 else 'spec-reviewer']\n"
        "        elif final_inline_specialist and stage == final_specialist_stage:\n"
        "            roles = [inline_role]\n"
        "        else:\n"
        "            roles = None\n"
        "        if roles is not None:\n"
        "            child = Path.cwd() / '.scratch' / ('children-%s.yml' % stage)\n"
        "            lines = ['tasks:']\n"
        "            for child_role in roles:\n"
        "                lines += [\n"
        "                    '  - ticket_id: \\\"' + os.environ['GRAPHTRAJ_TICKET_ID'] + '\\\"',\n"
        "                    '    ticket_name: ' + os.environ['GRAPHTRAJ_TICKET_NAME'],\n"
        "                ]\n"
        "                if child_role == inline_role:\n"
        "                    lines += [\n"
        "                        '    role:',\n"
        "                        '      ' + inline_role + ':',\n"
        "                        '        runtime: codex',\n"
        "                        '        model: gpt-5.6-luna',\n"
        "                        '    instruction: Investigate before delivery.',\n"
        "                    ]\n"
        "                else:\n"
        "                    lines += ['    role: coding-team.' + child_role]\n"
        "                if child_role.startswith('engineer-') and os.environ.get('FAKE_CODEX_ENGINEER_SKILLS'):\n"
        "                    lines += ['    skills: ' + os.environ['FAKE_CODEX_ENGINEER_SKILLS']]\n"
        "            child.write_text('\\n'.join(lines) + '\\n')\n"
        "            completed = subprocess.run(\n"
        "                [os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--batch-input', str(child)],\n"
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
        "                    [os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--batch-input', str(child)],\n"
        "                    check=False, text=True, capture_output=True,\n"
        "                )\n"
        "                assert duplicate.returncode != 0\n"
        "        else:\n"
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
        "            (round_dir / 'leader.md').write_text(decision)\n"
        "            diagnosis = os.environ.get('FAKE_CODEX_REWORK_CASE')\n"
        "            if diagnosis in {'process', 'main', 'product'}:\n"
        "                (round_dir / 'leader.md').write_text(decision.replace('Diagnosis: implementation', 'Diagnosis: ' + diagnosis))\n"
        "    elif role == inline_role:\n"
        "        pass\n"
        "    elif role.startswith('engineer-'):\n"
        "        delivered = Path.cwd() / 'TEAM_ROUND_DELIVERED.txt'\n"
        "        delivered.write_text('complete team round' + ('' if ordinal == '1' else ' ' + ordinal) + '\\n')\n"
        "        subprocess.run(['git', 'add', delivered.name], check=True)\n"
        "        subprocess.run(['git', 'commit', '-m', 'Deliver team round candidate'], check=True)\n"
        "        candidate = subprocess.run(\n"
        "            ['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True\n"
        "        ).stdout.strip()\n"
        "        (round_dir / 'engineer.md').write_text(\n"
        "            'Candidate commit: %s\\nSelf-review: passed.\\n' % candidate\n"
        "        )\n"
        "        (round_dir / 'validation.md').write_text(\n"
        "            'Candidate commit: %s\\nTests: passed.\\n' % candidate\n"
        "        )\n"
        "    else:\n"
        "        candidate = subprocess.run(\n"
        "            ['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True\n"
        "        ).stdout.strip()\n"
        "        report = Path(os.environ['GRAPHTRAJ_REVIEW_REPORT'])\n"
        "        review_prompt = runtime_prompt if runtime_prompt is not None else sys.stdin.read()\n"
        "        if (candidate != os.environ['GRAPHTRAJ_REVIEW_CANDIDATE'] "
        "or not os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] "
        "or not os.environ['GRAPHTRAJ_REVIEW_BRIEF'] "
        "or str(report) not in ' '.join(sys.argv) "
        "or candidate not in review_prompt "
        "or os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] not in review_prompt "
        "or os.environ['GRAPHTRAJ_REVIEW_BRIEF'] not in review_prompt "
        "or ('.state/reviews/' + report.name) not in review_prompt):\n"
        "            raise SystemExit(1)\n"
        "        report.write_text(\n"
        "            'Candidate commit: %s\\nDecision: pass.\\n' % candidate\n"
        "        )\n"
        "        if os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'rework':\n"
        "            axis = 'Standards' if role == 'standards-reviewer' else 'Spec'\n"
        "            finding = ('Finding: Missing delivered content\\nRule: Accepted Ticket delivery requirement\\n'\n"
        "                + 'Input: Run the delivered command\\nTrace: The command reads TEAM_ROUND_DELIVERED.txt\\n'\n"
        "                + 'Failure: Required content is missing\\nEvidence: TEAM_ROUND_DELIVERED.txt:1\\n'\n"
        "                if ordinal == '1' and axis == 'Spec' else 'Finding: none\\n')\n"
        "            report.write_text('Candidate commit: %s\\nAxis: %s\\nComparison: %s\\n'\n"
        "                % (candidate, axis, os.environ['GRAPHTRAJ_REVIEW_COMPARISON']) + finding)\n"
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


def _install_commands(environment: Path) -> InstalledCommands:
    """Install a clean export of the current source, including pending edits."""

    exported = environment.parent / "source"
    exported.mkdir()
    files = run_process(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT,
    )
    files.check_returncode()
    for name in filter(None, files.stdout.split("\0")):
        source = PROJECT_ROOT / name
        if not source.exists() and not source.is_symlink():
            continue
        target = exported / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)

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
            "--no-build-isolation",
            "--no-deps",
            str(exported),
        ],
        cwd=exported,
    )
    result.check_returncode()
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
def installed_commands(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledCommands:
    environment = tmp_path_factory.mktemp("installed-environment") / "venv"
    return _install_commands(environment)


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
    return _install_commands(tmp_path / "installed-mutable-environment")

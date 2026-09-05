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
        "    print('--config --json --sandbox --dangerously-bypass-hook-trust' if os.environ.get('FAKE_CODEX_UNSUPPORTED') != '1' else '--config --json')\n"
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
        "if os.environ.get('FAKE_CODEX_CAPTURE_STDIN') == '1':\n"
        "    record['stdin'] = sys.stdin.read()\n"
        "Path(os.environ['FAKE_CODEX_LOG']).write_text(\n"
        "    json.dumps(record, sort_keys=True) + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "policy_log = os.environ.get('FAKE_CODEX_POLICY_LOG')\n"
        "if policy_log:\n"
        "    import shlex, tomllib\n"
        "    settings = {}\n"
        "    for index, argument in enumerate(sys.argv[:-1]):\n"
        "        if argument == '-c':\n"
        "            settings.update(tomllib.loads(sys.argv[index + 1]))\n"
        "    decisions = {}\n"
        "    if os.environ['GRAPHTRAJ_ROLE'] == 'team-leader':\n"
        "        print(json.dumps(events.pop(0)), flush=True)\n"
        "        mapping = Path(os.environ['GRAPHTRAJ_PARENT_REGISTRATION']).parent / 'mapping.yml'\n"
        "        while not mapping.exists():\n"
        "            time.sleep(0.01)\n"
        "    hook = settings['hooks']['PreToolUse'][0]['hooks'][0]['command']\n"
        "    for command in ('agent-runner --help', 'codex exec hello', 'python -m you_are_a_product_architect.agent_runner', 'pwd'):\n"
        "        checked = subprocess.run(shlex.split(hook), input=json.dumps({\n"
        "            'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',\n"
        "            'session_id': 'fake-thread',\n"
        "            'tool_input': {'command': command},\n"
        "        }), text=True, capture_output=True, check=True)\n"
        "        decisions[command] = json.loads(checked.stdout) if checked.stdout else {}\n"
        "    helper_decisions = {}\n"
        "    if os.environ['GRAPHTRAJ_ROLE'] == 'team-leader':\n"
        "        for command in ('pwd', 'cat README.md', 'touch helper-write', 'git commit --allow-empty -m helper', 'agent-runner --help', 'codex exec hello', 'apply_patch'):\n"
        "            checked = subprocess.run(shlex.split(hook), input=json.dumps({\n"
        "                'hook_event_name': 'PreToolUse',\n"
        "                'tool_name': 'apply_patch' if command == 'apply_patch' else 'Bash',\n"
        "                'session_id': 'native-helper', 'tool_input': {'command': (\n"
        "                    '*** Begin Patch\\n*** Add File: helper-write\\n+forbidden\\n*** End Patch'\n"
        "                    if command == 'apply_patch' else command)},\n"
        "            }), text=True, capture_output=True, check=True)\n"
        "            helper_decisions[command] = json.loads(checked.stdout) if checked.stdout else {}\n"
        "    with Path(policy_log).open('a') as stream:\n"
        "        stream.write(json.dumps({'role': os.environ['GRAPHTRAJ_ROLE'], 'settings': settings, 'decisions': decisions, 'helper_decisions': helper_decisions}) + '\\n')\n"
        "release_file = os.environ.get('FAKE_CODEX_RELEASE_FILE')\n"
        "for index, event in enumerate(events):\n"
        "    print(json.dumps(event, sort_keys=True), flush=True)\n"
        "    if index == 0 and event_release is not None:\n"
        "        while not Path(event_release).exists():\n"
        "            time.sleep(0.01)\n"
        "    if index == 0 and release_file is not None:\n"
        "        while not Path(release_file).exists():\n"
        "            time.sleep(0.01)\n"
        "\n"
        "lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')\n"
        "if lifecycle_action == 'deliver-representative-ticket':\n"
        "    def run_git(*arguments):\n"
        "        result = subprocess.run(\n"
        "            ['git', *arguments],\n"
        "            check=False,\n"
        "            text=True,\n"
        "            capture_output=True,\n"
        "        )\n"
        "        if result.returncode != 0:\n"
        "            raise SystemExit(result.returncode)\n"
        "        return result\n"
        "    worktree = Path.cwd()\n"
        "    delivered = worktree / 'V1_DELIVERED.txt'\n"
        "    delivered.write_text('representative delivery\\n', encoding='utf-8')\n"
        "    run_git('add', delivered.name)\n"
        "    run_git('commit', '-m', 'Deliver representative V1 ticket')\n"
        "    candidate = run_git('rev-parse', 'HEAD').stdout.strip()\n"
        "    run_git('diff', '--check', 'HEAD^', 'HEAD')\n"
        "    evidence = (worktree / '.state').resolve()\n"
        "    (evidence / 'result.md').write_text(\n"
        "        (\n"
        "            'Candidate commit: {0}\\n'\n"
        "            'Outcome: representative ticket delivered.\\n'\n"
        "            'Outstanding concern: Main must adjudicate the raw reviews.\\n'\n"
        "        ).format(candidate),\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "    (evidence / 'validation.md').write_text(\n"
        "        (\n"
        "            'Candidate commit: {0}\\n'\n"
        "            'Command: git diff --check HEAD^ HEAD\\n'\n"
        "            'Result: passed.\\n'\n"
        "        ).format(candidate),\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "elif lifecycle_action == 'review-representative-candidate':\n"
        "    result = subprocess.run(\n"
        "        ['git', 'rev-parse', 'HEAD'],\n"
        "        check=False,\n"
        "        text=True,\n"
        "        capture_output=True,\n"
        "    )\n"
        "    candidate = os.environ['FAKE_CODEX_REVIEW_CANDIDATE']\n"
        "    if result.returncode != 0 or result.stdout.strip() != candidate:\n"
        "        raise SystemExit(1)\n"
        "    axis = os.environ['FAKE_CODEX_REVIEW_AXIS']\n"
        "    report = Path(os.environ['FAKE_CODEX_REVIEW_REPORT'])\n"
        "    report.parent.mkdir(exist_ok=True)\n"
        "    report.write_text(\n"
        "        (\n"
        "            'Raw {0} review for candidate {1}.\\n'\n"
        "            'Main must adjudicate this evidence.\\n'\n"
        "        ).format(axis.title(), candidate),\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "elif lifecycle_action == 'complete-team-round':\n"
        "    role = os.environ['GRAPHTRAJ_ROLE']\n"
        "    evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])\n"
        "    round_dir = evidence / 'teams' / '1' / 'rounds' / '1'\n"
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
        "        counter = Path.cwd() / '.scratch' / 'leader-stage'\n"
        "        stage = int(counter.read_text()) if counter.exists() else 0\n"
        "        counter.write_text(str(stage + 1))\n"
        "        if stage < 2:\n"
        "            roles = (['engineer-junior'] if stage == 0 else "
        "['standards-reviewer', 'spec-reviewer'])\n"
        "            child = Path.cwd() / '.scratch' / ('children-%s.yml' % stage)\n"
        "            lines = ['tasks:']\n"
        "            for child_role in roles:\n"
        "                lines += [\n"
        "                    '  - ticket_id: \\\"' + os.environ['GRAPHTRAJ_TICKET_ID'] + '\\\"',\n"
        "                    '    ticket_name: ' + os.environ['GRAPHTRAJ_TICKET_NAME'],\n"
        "                    '    role: ' + child_role,\n"
        "                ]\n"
        "            child.write_text('\\n'.join(lines) + '\\n')\n"
        "            completed = subprocess.run(\n"
        "                [os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--batch-input', str(child)],\n"
        "                check=False, text=True, capture_output=True,\n"
        "            )\n"
        "            if completed.returncode != 0:\n"
        "                sys.stderr.write(completed.stdout + completed.stderr)\n"
        "                raise SystemExit(completed.returncode)\n"
        "        else:\n"
        "            candidate = subprocess.run(\n"
        "                ['git', 'rev-parse', 'HEAD'], check=True, text=True, capture_output=True\n"
        "            ).stdout.strip()\n"
        "            if os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'reject':\n"
        "                decision = 'Cannot accept candidate: %s\\n' % candidate\n"
        "            elif os.environ.get('FAKE_CODEX_LEADER_DECISION') == 'conflict':\n"
        "                decision = ('Decision: ACCEPT\\nDecision: REJECT\\n' "
        "+ 'Candidate commit: %s\\n' % candidate)\n"
        "            else:\n"
        "                decision = 'Decision: ACCEPT\\nCandidate commit: %s\\n' % candidate\n"
        "            (round_dir / 'leader.md').write_text(decision)\n"
        "    elif role.startswith('engineer-'):\n"
        "        delivered = Path.cwd() / 'TEAM_ROUND_DELIVERED.txt'\n"
        "        delivered.write_text('complete team round\\n')\n"
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
        "        review_prompt = sys.stdin.read()\n"
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
        "\n"
        "raise SystemExit(int(os.environ.get('FAKE_CODEX_EXIT_CODE', '0')))\n"
    )
    executable.write_text(script, encoding="utf-8")
    executable.chmod(0o755)
    return FakeCodex(executable=executable, log_file=log_file)


def _install_commands(environment: Path) -> InstalledCommands:
    """Install the local candidate before exercising its public CLIs."""

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
            str(PROJECT_ROOT),
        ],
        cwd=PROJECT_ROOT,
    )
    result.check_returncode()
    bin_directory = environment / "bin"
    assert {
        path.name for path in bin_directory.iterdir()
    }.issuperset(
        {
        "agent-runner",
        "graphtraj",
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

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
        "if os.environ.get('FAKE_CODEX_CAPTURE_STDIN') == '1':\n"
        "    record['stdin'] = sys.stdin.read()\n"
        "Path(os.environ['FAKE_CODEX_LOG']).write_text(\n"
        "    json.dumps(record, sort_keys=True) + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
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

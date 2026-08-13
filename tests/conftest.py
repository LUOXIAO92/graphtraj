from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def find_uv() -> Optional[Path]:
    configured = os.environ.get("UV")
    candidate = configured or shutil.which("uv")
    if candidate is None:
        return None

    executable = Path(candidate)
    if executable.is_file() and os.access(executable, os.X_OK):
        return executable
    return None


def current_revision() -> str:
    result = run_process(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT)
    result.check_returncode()
    return result.stdout.strip()


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
        "raise SystemExit(int(os.environ.get('FAKE_CODEX_EXIT_CODE', '0')))\n"
    )
    executable.write_text(script, encoding="utf-8")
    executable.chmod(0o755)
    return FakeCodex(executable=executable, log_file=log_file)


@pytest.fixture
def installed_commands(tmp_path: Path) -> InstalledCommands:
    uv = find_uv()
    if uv is None:
        pytest.skip("uv is unavailable; set UV to its executable or add uv to PATH")

    tool_directory = tmp_path / "uv-tools"
    bin_directory = tmp_path / "uv-bin"
    environment = os.environ.copy()
    environment.update(
        {
            "UV_TOOL_DIR": str(tool_directory),
            "UV_TOOL_BIN_DIR": str(bin_directory),
            "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
            "UV_NO_MANAGED_PYTHON": "1",
        }
    )
    source = "git+{0}@{1}".format(PROJECT_ROOT.resolve().as_uri(), current_revision())
    result = run_process(
        [
            str(uv),
            "tool",
            "install",
            "--force",
            "--python",
            sys.executable,
            source,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
    )
    result.check_returncode()
    assert sorted(path.name for path in bin_directory.iterdir()) == [
        "agent-runner",
        "you-are-a-product-architect",
    ]
    return InstalledCommands(
        product=bin_directory / "you-are-a-product-architect",
        runner=bin_directory / "agent-runner",
    )

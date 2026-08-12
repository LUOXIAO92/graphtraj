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
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        text=True,
        capture_output=True,
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
        "import sys\n"
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
        "Path(os.environ['FAKE_CODEX_LOG']).write_text(\n"
        "    json.dumps({'cwd': os.getcwd(), 'argv': sys.argv[1:]}, sort_keys=True) + '\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "for event in events:\n"
        "    print(json.dumps(event, sort_keys=True))\n"
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

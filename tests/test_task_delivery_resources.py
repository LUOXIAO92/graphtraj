from __future__ import annotations

import json
from pathlib import Path

from conftest import InstalledCommands, PROJECT_ROOT, run_process


ADR_PATHS = (
    "docs/adr/0003-delivery-state-agent-maintains-run-state.md",
    "docs/adr/0026-manage-inherited-reviewer-guidance.md",
)


def test_installed_task_delivery_routes_to_active_source_adrs(
    installed_commands: InstalledCommands,
    tmp_path: Path,
) -> None:
    probe = """
import json
import sys
from pathlib import Path

from you_are_a_product_architect.supported_skills import SupportedSkills

runtime_store = Path(sys.argv[1]) / ".codex"
SupportedSkills.load().install_missing(runtime_store, ("task-delivery",))
skill = runtime_store.parent / ".agents" / "skills" / "task-delivery" / "SKILL.md"
print(json.dumps(skill.read_text(encoding="utf-8")))
"""
    result = run_process(
        [
            str(installed_commands.product.parent / "python"),
            "-I",
            "-c",
            probe,
            str(tmp_path),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    skill = json.loads(result.stdout)
    assert all(path in skill for path in ADR_PATHS)
    assert all((PROJECT_ROOT / path).is_file() for path in ADR_PATHS)

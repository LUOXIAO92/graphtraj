from __future__ import annotations

import json
from pathlib import Path

from conftest import InstalledCommands, run_process


SUPPORTED_UPSTREAM_SKILL_FILES = {
    "setup-matt-pocock-skills": (
        "SKILL.md",
        "agents/openai.yaml",
        "domain.md",
        "issue-tracker-github.md",
        "issue-tracker-gitlab.md",
        "issue-tracker-local.md",
        "triage-labels.md",
    ),
    "grill-with-docs": ("SKILL.md", "agents/openai.yaml"),
    "grilling": ("SKILL.md", "agents/openai.yaml"),
    "domain-modeling": (
        "ADR-FORMAT.md",
        "CONTEXT-FORMAT.md",
        "SKILL.md",
        "agents/openai.yaml",
    ),
    "to-spec": ("SKILL.md", "agents/openai.yaml"),
    "to-tickets": ("SKILL.md", "agents/openai.yaml"),
    "implement": ("SKILL.md", "agents/openai.yaml"),
    "tdd": ("SKILL.md", "agents/openai.yaml", "mocking.md", "tests.md"),
    "code-review": ("SKILL.md", "agents/openai.yaml"),
    "resolving-merge-conflicts": ("SKILL.md", "agents/openai.yaml"),
}


def installed_python(installed_commands: InstalledCommands) -> Path:
    for line in installed_commands.product.read_text(encoding="utf-8").splitlines():
        prefix = "'''exec' '"
        if line.startswith(prefix):
            return Path(line.removeprefix(prefix).split("'", maxsplit=1)[0])
    raise AssertionError("Installed product wrapper did not declare its Python interpreter.")


def test_installed_distribution_exposes_supported_upstream_skill_resources(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    expected_files = json.dumps(SUPPORTED_UPSTREAM_SKILL_FILES)
    resource_probe = """
from importlib.resources import files
import json

expected_files = json.loads({expected_files!r})
skills_root = files("you_are_a_product_architect.resources").joinpath("codex", "skills")
results = {{}}
for skill_name, skill_files in expected_files.items():
    skill_directory = skills_root.joinpath(skill_name)
    skill_document = skill_directory.joinpath("SKILL.md")
    declared_name = None
    if skill_document.is_file():
        for line in skill_document.read_text(encoding="utf-8").splitlines():
            if line.startswith("name: "):
                declared_name = line.removeprefix("name: ").strip().strip('"')
                break
    results[skill_name] = {{
        "directory": skill_directory.is_dir(),
        "declared_name": declared_name,
        "missing_files": [
            resource_path
            for resource_path in skill_files
            if not skill_directory.joinpath(*resource_path.split("/")).is_file()
        ],
    }}

print(json.dumps(results, sort_keys=True))
""".format(expected_files=expected_files)

    result = run_process(
        [str(installed_python(installed_commands)), "-c", resource_probe],
        cwd=temporary_git_repository,
    )

    assert result.returncode == 0, result.stderr
    resources = json.loads(result.stdout)
    for skill_name in SUPPORTED_UPSTREAM_SKILL_FILES:
        assert resources[skill_name]["directory"] is True
        assert resources[skill_name]["declared_name"] == skill_name
        assert resources[skill_name]["missing_files"] == []

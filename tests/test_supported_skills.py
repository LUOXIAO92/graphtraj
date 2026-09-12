from __future__ import annotations

import pytest

from conftest import PROJECT_ROOT


CORE_SKILL_NAMES = (
    "setup-project",
    "grill-with-docs",
    "grilling",
    "domain-modeling",
    "to-spec",
    "to-tickets",
    "task-delivery",
    "implement",
    "ponytail",
    "tdd",
    "code-review",
    "resolving-merge-conflicts",
    "task-breakdown",
    "research",
    "retro",
    "wayfinder",
    "prototype",
)


def test_supported_skills_loads_from_one_child_traversable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from graphtraj import supported_skills

    class SingleChildTraversable:
        def joinpath(self, child: str) -> "SingleChildTraversable":
            return self

        def is_dir(self) -> bool:
            return True

    monkeypatch.setattr(
        supported_skills.resources,
        "files",
        lambda _package: SingleChildTraversable(),
    )

    loaded = supported_skills.SupportedSkills.load()

    assert tuple(loaded.resources_by_name) == CORE_SKILL_NAMES

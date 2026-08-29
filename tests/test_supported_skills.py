from __future__ import annotations

import pytest

from conftest import PROJECT_ROOT


CORE_SKILL_NAMES = (
    "setup-matt-pocock-skills",
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
)


def test_supported_skills_loads_from_one_child_traversable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from you_are_a_product_architect import supported_skills

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

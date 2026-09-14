"""A single Engineer configuration serves existing coding Team seats."""

from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import default_roles_content, load_project_roles


def test_unified_engineer_preserves_existing_seat_resolution(tmp_path: Path) -> None:
    """Old role files remain valid; one new preset configures every Engineer seat."""
    path = tmp_path / ".graphtraj" / "roles.yml"
    path.parent.mkdir()
    path.write_text(default_roles_content())
    original = load_project_roles(tmp_path)
    document = yaml.safe_load(path.read_text())
    coding = document["roles"]["coding-team"]
    engineers = ("engineer-junior", "engineer-senior", "engineer-expert")
    for name in engineers:
        coding.pop(name)
    coding["engineer"] = {
        "runtime": "codex", "model": "deepseek-flash",
        "reasoning_effort": "high", "base_url": "https://example.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    }
    path.write_text(yaml.safe_dump(document))
    configured = path.read_bytes()
    resolved = load_project_roles(tmp_path)
    for name in engineers:
        preset = resolved.presets[name]
        assert preset.model == "deepseek-flash"
        assert preset.reasoning_effort == "high"
        assert preset.base_url == "https://example.com"
        assert preset.api_key_env == "DEEPSEEK_API_KEY"
    assert resolved.presets["team-leader"] == original.presets["team-leader"]
    assert path.read_bytes() == configured

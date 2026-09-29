"""The installable plugin artifact and its single thin overview Skill.

The Codex plugin wraps exactly the thin discovery overview. The method guides
stay in the distribution's data location, so the plugin directory never carries
a second Skill catalog or a manual copy.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "graphtraj"


def plugin_manifest() -> dict:
    """Return the delivered plugin manifest as decoded JSON."""
    return json.loads(
        (PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )


def test_plugin_manifest_registers_exactly_the_thin_overview_skill() -> None:
    """One graphtraj plugin carries one Skill and no unverified host fields."""
    manifest = plugin_manifest()

    assert set(manifest) == {"name", "version", "description", "author", "skills", "interface"}
    assert manifest["name"] == "graphtraj"
    assert manifest["version"] == "0.1.0"
    assert manifest["description"] == "Task graphs and execution traces for local projects."
    assert manifest["author"]["name"] == "LUOXIAO92"
    assert manifest["skills"] == "./skills/"
    for unsupported in ("hooks", "mcpServers", "apps"):
        assert unsupported not in manifest

    interface = manifest["interface"]
    assert interface["displayName"] == "GraphTraj"
    assert interface["category"] == "Productivity"
    assert interface["capabilities"] == []

    assert [path.name for path in (PLUGIN_ROOT / "skills").iterdir()] == ["graphtraj"]
    assert (PLUGIN_ROOT / "skills/graphtraj/SKILL.md").read_bytes() == (
        ROOT / "skills/graphtraj/SKILL.md"
    ).read_bytes()
    assert not (PLUGIN_ROOT / "skills/graphtraj/manuals").exists()
    assert not list(PLUGIN_ROOT.rglob("guide.md"))


def test_plugin_interface_text_reuses_main_authored_sentences() -> None:
    """Every interface description is an existing overview or README sentence."""
    interface = plugin_manifest()["interface"]
    sources = (ROOT / "skills/graphtraj/SKILL.md").read_text(encoding="utf-8")
    sources += (ROOT / "README.md").read_text(encoding="utf-8")
    # Compare against the prose as read, without source line wrapping.
    prose = " ".join(sources.split())

    assert " ".join(interface["shortDescription"].split()) in prose
    assert " ".join(interface["longDescription"].split()) in prose
    assert interface["defaultPrompt"]
    for prompt in interface["defaultPrompt"]:
        assert " ".join(prompt.split()) in prose

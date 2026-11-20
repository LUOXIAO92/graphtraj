"""Task 535 Vb/V: give the isolated project ONE child role `codex` copied from a production preset; resolve it
without launching a model.

usage: python -I roles535.py <harness> <project> <model>     (the active scratch venv's python)

The production roles file (<harness>'s roles.yml) is only read. Its presets that resolve TODAY to runtime codex and
<model> are candidates; the first one (sorted by reference) is copied as role `codex`, without its instruction or
report files (they name Harness files). Then the Task-free agents driver's choice is repeated (a role named after the
runtime, else exactly one role using it) with resolve_preset + resolve_child_role. 533 failed twice without this
(no role; an effort the catalog refuses). Exit 0 = PASS.
"""
import copy
import sys
from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import load_project_roles, resolve_preset, roles_file
from graphtraj.configuration.role_definitions import resolve_child_role

DROPPED = ('instructions', 'system_prompt', 'developer_prompt', 'reports')


def production_entry(harness: Path, model: str) -> tuple[str, dict]:
    """Return the first production preset resolving to codex + model, as its raw roles.yml mapping."""
    roles = load_project_roles(harness)
    found = []
    for reference, preset in sorted(roles.presets.items()):
        try:
            settings = resolve_preset(preset)
        except Exception:  # noqa: BLE001 - a preset that does not resolve today is skipped
            continue
        if settings.runtime == 'codex' and settings.model == model:
            found.append(reference)
    print(f'production presets resolving to codex/{model}: {found or "none"}')
    if not found:
        raise ValueError(f'no production preset resolves to runtime codex with model {model}')
    document = yaml.safe_load(roles_file(harness).read_text(encoding='utf-8'))['roles']
    group, _, name = found[0].rpartition('.')
    entry = document[group][name] if group else document[name]
    return found[0], {key: value for key, value in copy.deepcopy(entry).items() if key not in DROPPED}


def main(harness: Path, project: Path, model: str) -> int:
    try:
        reference, entry = production_entry(harness, model)
        path = roles_file(project)
        path.write_text(yaml.safe_dump({'roles': {'codex': entry}, 'role_tree': {'codex': {}}}, sort_keys=False),
                        encoding='utf-8')
        print(f'roles file written: {path} (role codex = production {reference} without {", ".join(DROPPED)})')
        print(path.read_text(encoding='utf-8').rstrip())
        roles = load_project_roles(project)
        presets = {name: resolve_preset(preset) for name, preset in roles.presets.items()}
        matches = sorted(name for name, preset in presets.items() if preset.runtime == 'codex')
        name = 'codex' if 'codex' in matches else matches[0] if len(matches) == 1 else None
        if name is None:
            raise ValueError(f'no single codex role: {matches}')
        resolve_child_role(name, presets[name], project)
        settings = presets[name]
    except Exception as error:  # noqa: BLE001 - the step prints the reason and STOPs
        print(f'CHECK 535 child role resolves: FAIL ({type(error).__name__}: {error})')
        return 1
    print(f'CHECK 535 child role resolves: PASS (runtime {settings.runtime}, model {settings.model}, '
          f'reasoning_effort {settings.reasoning_effort}, role {name}, roles {sorted(roles.presets)})')
    return 0 if settings.model == model else 1


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]))

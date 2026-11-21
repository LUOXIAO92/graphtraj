"""Task 540 Vb/V: give the isolated project ONE child role `codex` running <model>; resolve it without a model.

usage: python -I roles540.py <project> <model>     (the active scratch venv's python)

Read only: the user's catalog (~/.graphtraj/connections.yml, through graphtraj's own read_catalog, the reader
resolve_preset uses). The codex models of the catalog are printed and <model>'s reference is chosen (id or key equal
to <model>, provider openai first), as 535's accepted roles535.py did (4618696a). The role is
{connection: <reference>, reasoning_effort: medium (else high, else the first supported)} and is resolved like the
Task-free agents driver: resolve_preset + resolve_child_role. Exit 0 = PASS.
"""
import sys
from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import load_project_roles, resolve_preset, roles_file
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.configuration.runtime_connections import EFFORTS, connections_file, read_catalog


def catalog_model(model: str) -> tuple[str, list]:
    """Print the catalog's codex models; return (reference, supported_efforts) of <model>."""
    document, _ = read_catalog()
    print(f'catalog {connections_file()} (read only), codex models:')
    found = []
    for runtime_key, runtime in document['runtimes'].items():
        if runtime['runtime'] != 'codex':
            continue
        for provider_key, provider in runtime['providers'].items():
            for model_key, entry in provider['models'].items():
                reference = f'{runtime_key}/{provider_key}/{model_key}'
                print(f'  {reference}: id {entry["id"]}, supported_efforts {entry.get("supported_efforts", "any")}')
                if model in (entry['id'], model_key):
                    found.append((provider_key != 'openai', reference, entry.get('supported_efforts')))
    if not found:
        raise ValueError(f'the catalog has no codex model with id or key {model}')
    _, reference, supported = sorted(found)[0]
    return reference, supported or list(EFFORTS['codex'])


def main(project: Path, model: str) -> int:
    try:
        reference, supported = catalog_model(model)
        effort = next(e for e in ('medium', 'high', *supported) if e in supported)
        path = roles_file(project)
        path.write_text(yaml.safe_dump({'roles': {'codex': {'connection': reference, 'reasoning_effort': effort}},
                                        'role_tree': {'codex': {}}}, sort_keys=False), encoding='utf-8')
        print(f'roles file written: {path}')
        print(path.read_text(encoding='utf-8').rstrip())
        roles = load_project_roles(project)
        presets = {name: resolve_preset(preset) for name, preset in roles.presets.items()}
        resolve_child_role('codex', presets['codex'], project)
        settings = presets['codex']
    except Exception as error:  # noqa: BLE001 - the step prints the reason and STOPs
        print(f'CHECK 540 child role resolves: FAIL ({type(error).__name__}: {error})')
        return 1
    ok = settings.runtime == 'codex' and settings.model == model
    print(f'CHECK 540 child role resolves: {"PASS" if ok else "FAIL"} (runtime {settings.runtime}, model '
          f'{settings.model}, reasoning_effort {settings.reasoning_effort}, roles {sorted(roles.presets)})')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve(), sys.argv[2]))

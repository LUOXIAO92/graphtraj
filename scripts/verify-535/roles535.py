"""Task 535 Vb/V: give the isolated project ONE child role `codex` running <model>; resolve it without a model.

usage: python -I roles535.py <harness> <project> <model>     (the active scratch venv's python)

Read only: the production roles file (<harness>'s roles.yml) and the user's catalog (~/.graphtraj/connections.yml,
through graphtraj's own read_catalog, the reader resolve_preset uses). No production preset uses <model> (correction
round 1: Vb STOPPED with 'no production preset resolves to runtime codex with model gpt-6-luna'), so:
  1. the catalog's codex models are printed (reference, id, supported_efforts) and <model>'s reference is chosen:
     a codex model whose id or key is <model>, preferring provider openai (the production astra presets' provider);
  2. a production codex preset is copied: astra_coding_team.engineer if present, else the first codex preset of that
     provider, else the first codex preset; without instructions, prompts or reports (they name Harness files);
  3. its connection becomes <model>'s reference and its reasoning_effort stays if <model> supports it, else 'high'
     (else the first supported effort);
  4. the role is written as `codex` and resolved like the Task-free agents driver: resolve_preset +
     resolve_child_role. Every production preset is printed with its resolve result or error. Exit 0 = PASS.
"""
import copy
import sys
from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import load_project_roles, resolve_preset, roles_file
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.configuration.runtime_connections import EFFORTS, connections_file, read_catalog

DROPPED = ('instructions', 'system_prompt', 'developer_prompt', 'reports')
PREFERRED = ('astra_coding_team.engineer',)


def catalog_models(model: str) -> list[tuple[str, str, object]]:
    """Print the catalog's codex models; return (reference, id, supported_efforts) of those matching model."""
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
                    found.append((reference, provider_key, entry.get('supported_efforts')))
    if not found:
        raise ValueError(f'the catalog has no codex model with id or key {model}')
    found.sort(key=lambda item: item[1] != 'openai')
    return found


def production_presets(harness: Path) -> tuple[dict, list[str]]:
    """Print every production preset with its resolution; return the raw entries and the codex references."""
    roles = load_project_roles(harness)
    raw = yaml.safe_load(roles_file(harness).read_text(encoding='utf-8'))['roles']
    entries, codex = {}, []
    print(f'production presets ({roles_file(harness)}, read only):')
    for reference, preset in sorted(roles.presets.items()):
        group, _, name = reference.rpartition('.')
        entries[reference] = raw[group][name] if group else raw[name]
        connection = entries[reference].get('connection') or ''
        runtime = entries[reference].get('runtime') or connection.split('/')[0]
        try:
            settings = resolve_preset(preset)
            runtime, state = settings.runtime, f'runtime {settings.runtime}, model {settings.model}, effort {settings.reasoning_effort}'
        except Exception as error:  # noqa: BLE001 - printed, never skipped silently
            state = f'does not resolve: {type(error).__name__}: {error}'
        print(f'  {reference}: connection {connection or "-"} | {state}')
        if runtime == 'codex':
            codex.append(reference)
    return entries, codex


def main(harness: Path, project: Path, model: str) -> int:
    try:
        entries, codex = production_presets(harness)
        matches = catalog_models(model)
        reference, provider, supported = matches[0]
        print(f'{model} reference chosen: {reference} (provider {provider}, supported_efforts {supported or "any"})')
        if not codex:
            raise ValueError('no production codex preset to copy')
        base = next((name for name in PREFERRED if name in codex), None) or next(
            (name for name in codex if (entries[name].get('connection') or '').split('/')[1:2] == [provider]), codex[0])
        entry = {key: value for key, value in copy.deepcopy(entries[base]).items()
                 if key not in DROPPED + ('runtime', 'model')}
        allowed = supported or EFFORTS['codex']
        effort = entry.get('reasoning_effort')
        entry['reasoning_effort'] = (effort if effort in allowed else 'high' if 'high' in allowed else allowed[0])
        entry['connection'] = reference
        path = roles_file(project)
        path.write_text(yaml.safe_dump({'roles': {'codex': entry}, 'role_tree': {'codex': {}}}, sort_keys=False),
                        encoding='utf-8')
        print(f'roles file written: {path} (role codex = production {base} without {", ".join(DROPPED)}; '
              f'connection {reference}; reasoning_effort {effort} -> {entry["reasoning_effort"]})')
        print(path.read_text(encoding='utf-8').rstrip())
        roles = load_project_roles(project)
        presets = {name: resolve_preset(preset) for name, preset in roles.presets.items()}
        names = sorted(name for name, preset in presets.items() if preset.runtime == 'codex')
        name = 'codex' if 'codex' in names else names[0] if len(names) == 1 else None
        if name is None:
            raise ValueError(f'no single codex role: {names}')
        resolve_child_role(name, presets[name], project)
        settings = presets[name]
    except Exception as error:  # noqa: BLE001 - the step prints the reason and STOPs
        print(f'CHECK 535 child role resolves: FAIL ({type(error).__name__}: {error})')
        return 1
    ok = settings.runtime == 'codex' and settings.model == model
    print(f'CHECK 535 child role resolves: {"PASS" if ok else "FAIL"} (runtime {settings.runtime}, model '
          f'{settings.model}, reasoning_effort {settings.reasoning_effort}, role {name}, roles {sorted(roles.presets)})')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]))

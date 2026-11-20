"""Task 533 V: give the isolated project ONE child role `claude` and check it resolves, launching no model.

usage: python -I roles533.py <project>    (the candidate scratch venv's python)

Precedent: scripts/verify-519/prep519.py. The role uses the connection the Harness's opus_coding_team presets use
(claude/anthropic/opus-5_5, from the user's ~/.graphtraj/connections.yml, read only), reasoning_effort high, Claude
permission_mode auto. The check repeats the Task-free agents driver's choice (agent_driver.py: a role named after
the runtime, else exactly one role using it), then resolve_preset + resolve_child_role. Exit 0 = PASS.
"""
import sys
from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import load_project_roles, resolve_preset, roles_file
from graphtraj.configuration.role_definitions import resolve_child_role

CONNECTION = 'claude/anthropic/opus-5_5'


def main(project: Path) -> int:
    path = roles_file(project)
    # Exactly the production preset opus_coding_team.engineer, which resolves today ('low' is refused by the catalog).
    document = {'roles': {'claude': {'connection': CONNECTION, 'reasoning_effort': 'high',
                                     'claude': {'permission_mode': 'auto'}}},
                'role_tree': {'claude': {}}}
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')
    print(f'roles file written: {path}')
    print(path.read_text(encoding='utf-8').rstrip())
    try:
        roles = load_project_roles(project)
        presets = {name: resolve_preset(preset) for name, preset in roles.presets.items()}
        matches = sorted(name for name, preset in presets.items() if preset.runtime == 'claude')
        name = 'claude' if 'claude' in matches else matches[0] if len(matches) == 1 else None
        if name is None:
            raise ValueError(f'no single claude role: {matches}')
        role = resolve_child_role(name, presets[name], project)
    except Exception as error:  # noqa: BLE001 - the step prints the reason and STOPs
        print(f'CHECK 533 child role resolves: FAIL ({type(error).__name__}: {error})')
        return 1
    settings = role.settings if hasattr(role, 'settings') else presets[name]
    print(f'CHECK 533 child role resolves: PASS (runtime {settings.runtime}, model {settings.model}, '
          f'reasoning_effort {settings.reasoning_effort}, role {name}, roles {sorted(roles.presets)})')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve()))

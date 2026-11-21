"""Task 550 00: write the isolated project's three roles and check that each resolves, launching no model.

usage: python -I roles550.py <project>      (production .venv-runtime python, read only)

Precedent: scripts/verify-533/roles533.py. Connections come from the user's ~/.graphtraj/connections.yml (read
only, through GraphTraj's resolve_connection, which also checks the reasoning effort against the catalog).
  simuser  claude/anthropic/fable-5_2   high                       (U, the simulated user)
  subject  claude/anthropic/haiku-5_5   lowest effort the catalog accepts, tried low -> medium -> high   (S)
  auditor  claude/anthropic/sonnet-5_5  medium preferred, else high, else low                         (A)
All use Claude permission_mode auto. The agents create call selects a role with `configuration: <role>` (GraphTraj's
Task-free driver, agent_driver.py prepare); no model is passed. Exit 0 = every role resolved.
"""
import sys
from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import load_project_roles, resolve_preset, roles_file
from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.configuration.runtime_connections import resolve_connection

ROLES = {  # role: (connection, efforts in order of preference)
    'simuser': ('claude/anthropic/fable-5_2', ('high',)),
    'subject': ('claude/anthropic/haiku-5_5', ('low', 'medium', 'high')),
    'auditor': ('claude/anthropic/sonnet-5_5', ('medium', 'high', 'low')),
}


def pick(connection, efforts):
    refusals = []
    for effort in efforts:
        try:
            resolve_connection(connection, effort)
            return effort, refusals
        except (ValueError, OSError) as error:
            refusals.append(f'{effort}: {error}')
    return None, refusals


def main(project: Path) -> int:
    document = {'roles': {}, 'role_tree': {}}
    ok = True
    for role, (connection, efforts) in ROLES.items():
        effort, refusals = pick(connection, efforts)
        for refusal in refusals:
            print(f'{role}: catalog refused reasoning_effort {refusal}')
        if effort is None:
            print(f'CHECK 550 role {role}: FAIL (no reasoning_effort among {efforts} is accepted for {connection})')
            ok = False
            continue
        print(f'{role}: reasoning_effort {effort} (tried in order {list(efforts)})')
        document['roles'][role] = {'connection': connection, 'reasoning_effort': effort,
                                   'claude': {'permission_mode': 'auto'}}
        document['role_tree'][role] = {}
    if not ok:
        return 1
    path = roles_file(project)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')
    print(f'roles file written: {path}')
    print(path.read_text(encoding='utf-8').rstrip())
    roles = load_project_roles(project)
    for role in ROLES:
        try:
            settings = resolve_child_role(role, resolve_preset(roles.presets[role]), project).settings
        except Exception as error:  # noqa: BLE001 - the step prints the reason and STOPs
            print(f'CHECK 550 role {role}: FAIL ({type(error).__name__}: {error})')
            ok = False
            continue
        print(f'CHECK 550 role {role}: PASS (runtime {settings.runtime}, model {settings.model}, '
              f'reasoning_effort {settings.reasoning_effort})')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve()))

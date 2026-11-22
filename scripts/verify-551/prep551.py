"""Task 551 preparation, run by the installation under test's python (no model is launched).

  python -I prep551.py roles <project> <workspace>  write the four child roles, resolve each through the Task-free
                                                    driver's own prepare (AdapterDriver.prepare) with the child
                                                    workspace B passes in create, print what launches
  python -I prep551.py tasks <project> <mcp> <out>  tasks discover + describe concept-clarification through the
                                                    installation's stdio graphtraj-mcp (no host, no model); writes the
                                                    manual's first heading line to <out>
Exit 0 = PASS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Inline roles (no connection catalog is read). Claude: the driver accepts exact claude-opus-5-5 without a
# connection. Pi: srt from the user's sandbox install (V551_PI_PYTHON / V551_PI_PATH, from
# ~/agents-pi-sandbox/pi-sandbox.env as verify-513 reads it).
ROLES = {
    'claude': {'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'low'},
    'codex':  {'runtime': 'codex', 'model': 'gpt-6-luna'},
    'pi':     {'runtime': 'pi', 'model': 'deepseek/deepseek-flash', 'api_key_env': 'DEEPSEEK_API_KEY'},
    'dsh':    {'runtime': 'dsh', 'model': 'deepseek-flash', 'api_key_env': 'DEEPSEEK_API_KEY'},
    # AU claude only (create `configuration: claude_ask`): Claude's default permission mode, so a tool use the host
    # settings do not pre-allow (WebFetch) asks through can_use_tool instead of auto mode's classifier deciding it.
    # The role named 'claude' stays the Runtime's default for every other create.
    'claude_ask': {'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'low',
                   'claude': {'permission_mode': 'default'}},
}
if os.environ.get('V551_PI_PATH'):
    ROLES['pi']['pi'] = {'sandbox_path': os.environ['V551_PI_PATH'],
                         **({'sandbox_python': os.environ['V551_PI_PYTHON']} if os.environ.get('V551_PI_PYTHON') else {})}
METHOD = 'concept-clarification'


def roles(project: Path, workspace: Path) -> int:
    import yaml
    from graftling import Caller

    from graphtraj.configuration.project_roles import roles_file
    from graphtraj.execution.agent_driver import AdapterDriver

    path = roles_file(project)
    path.write_text(yaml.safe_dump({'roles': ROLES, 'role_tree': {name: {} for name in ROLES}}, sort_keys=False),
                    encoding='utf-8')
    print(f'roles file written: {path}')
    failed = 0
    for runtime, role in ROLES.items():
        try:
            # The same workspace B gives every child in its create arguments; each role by its own name.
            prepared = AdapterDriver(project, project).prepare(role['runtime'], Caller('verify-551', None, 'probe-551', 'claude'),
                                                               configuration=runtime, workspace=workspace)
        except Exception as error:  # noqa: BLE001 - printed, the step decides
            print(f'CHECK 551 role {runtime}: FAIL ({type(error).__name__}: {error})')
            failed += 1
            continue
        request = prepared['adapter_request']
        shown = {key: request[key] for key in sorted(request)
                 if any(word in key for word in ('tool', 'mcp', 'sandbox', 'permission', 'approval', 'network'))}
        print(f'CHECK 551 role {runtime}: PASS {prepared["applied"]} cwd {prepared["cwd"]} | tool/MCP/permission request fields: '
              f'{json.dumps(shown, default=str)[:900]}')
    return 1 if failed else 0


def tasks(project: Path, server: str, out: Path) -> int:
    messages = [
        {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
         'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'prep551', 'version': '0'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'tasks', 'arguments': {'action': 'discover'}}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
         'params': {'name': 'tasks', 'arguments': {'action': 'describe', 'feature': METHOD}}},
    ]
    proc = subprocess.run([server], input=''.join(json.dumps(m) + '\n' for m in messages), cwd=project,
                          capture_output=True, text=True, timeout=120)
    found = {}
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        found[message.get('id')] = message.get('result', {}).get('structuredContent') or message
    features = [item.get('feature') for item in (found.get(1) or {}).get('features', [])]
    print(f'tasks discover: {len(features)} features; {METHOD} listed: {METHOD in features}')
    ref = (found.get(2) or {}).get('manual_ref')
    print(f'tasks describe {METHOD}: manual_ref {ref}')
    if not ref or not Path(ref).is_file():
        print(f'CHECK 551 tasks probe: FAIL (no readable manual_ref; stderr tail: {proc.stderr[-400:]})')
        return 1
    heading = next((line.strip() for line in Path(ref).read_text(encoding='utf-8').splitlines() if line.startswith('#')), '-')
    out.write_text(heading + '\n', encoding='utf-8')
    print(f'manual first heading: {heading!r} (saved to {out})')
    print('CHECK 551 tasks probe: PASS')
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'roles':
        sys.exit(roles(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()))
    if len(sys.argv) == 5 and sys.argv[1] == 'tasks':
        sys.exit(tasks(Path(sys.argv[2]).resolve(), sys.argv[3], Path(sys.argv[4])))
    print(__doc__)
    sys.exit(2)

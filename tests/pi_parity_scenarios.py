"""Representative GraphTraj Pi member launches, captured without a native process.

Run as a script to write a capture: ``python pi_parity_scenarios.py OUTPUT``.
It uses only interfaces that predate the generic Pi request, so the same file
captures the goldens from the base commit and the current result in tests.
Machine-specific paths are replaced by placeholders.
"""

import json
import os
from pathlib import Path
import sys
import tempfile

from agent_swarm import __file__ as agents_file
from graphtraj.runtimes.pi.managed_session import PiManagedExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


SCRUBBED = ('GRAPHTRAJ_', 'AGENT_SWARM_', 'AGENTS_', 'DSH_')
# Removed from a child's environment; their removal is part of the capture.
AMBIENT = {'GRAPHTRAJ_PARITY': '1', 'AGENT_SWARM_PARITY': '1', 'AGENTS_PARITY': '1',
           'DSH_SESSION_ID': 'parity', 'DSH_AGENT_SOURCE': 'parity', 'PARITY_KEY': 'parity-key-value'}


def _layout(root: Path) -> dict:
    """Create a project, Worktree, native Home and evidence with fixed contents."""
    project = root / 'project'
    worktree = project / 'worktrees/research'
    for directory in (project / '.graphtraj/state', project / 'docs', project / '.git',
                      worktree / '.agents', worktree / 'docs', root / 'resources/skill',
                      root / 'evidence/teams/1/rounds/1', root / 'user-agent/extensions', root / 'user-agent/bin'):
        directory.mkdir(parents=True, exist_ok=True)
    (worktree / 'AGENTS.md').write_text('agents')
    for name in ('settings.json', 'auth.json', 'models.json', 'AGENTS.md'):
        (root / 'user-agent' / name).write_text('{}')
    (root / 'user-agent/bin/fd').write_text('')
    fixture = Path(__file__).with_name('pi_rpc_fixture.py')
    pi = root / 'bin/pi'
    pi.parent.mkdir(exist_ok=True)
    pi.write_text(f'#!{sys.executable}\n' + fixture.read_text())
    pi.chmod(0o755)
    return {
        'worktree_path': str(worktree), 'harness_root': str(project),
        'git_common_directory': str(project / '.git'), 'evidence': str(root / 'evidence'),
        'executable': str(pi), 'sandbox_python': sys.executable, 'sandbox_path': '/usr/bin:/bin',
        'provider': 'deepseek', 'model': 'deepseek-flash', 'reasoning_effort': None,
        'api_key_env': None, 'version': '1.0.0-fixture', 'base_url': None, 'provider_api': None,
        'connection': None, 'connection_revision': None, 'instructions': 'Role instructions.',
        'agent_dir': str(root / 'user-agent'), 'resources': [str(root / 'resources/skill')],
        'worktree_access': 'read', 'reports': [str(root / 'evidence/teams/1/rounds/1/engineer.md')],
        'state_directory': str(project / '.graphtraj/state'), 'docs_directory': str(project / 'docs'),
        'provider_domain': 'api.deepseek.com',
    }


SCENARIOS = {
    'read': ({}, '/bound/cli', False),
    'write': ({'worktree_access': 'write'}, '/bound/cli', False),
    'no-address': ({}, None, False),
    'base-url-with-key': ({'worktree_access': 'write', 'provider': 'graphtraj-role', 'model': 'local-model',
                           'base_url': 'http://localhost:8080/v1', 'provider_api': 'openai-completions',
                           'api_key_env': 'PARITY_KEY', 'reasoning_effort': 'high', 'provider_domain': None},
                          '/bound/cli', False),
    'base-url-unauthenticated': ({'provider': 'graphtraj-role', 'model': 'local-model',
                                  'base_url': 'https://models.example/v1', 'provider_api': 'openai-completions',
                                  'provider_domain': None}, '/bound/cli', False),
    'key-only': ({'provider': 'openrouter', 'model': 'google/gemini', 'api_key_env': 'PARITY_KEY',
                  'provider_domain': 'openrouter.ai'}, '/bound/cli', False),
    'native-services': ({'allow_mach_lookup': ['com.apple.pasteboard.1'], 'allow_mach_register': ['com.example.*'],
                         'allow_local_binding': True, 'allow_unix_sockets': ['/private/tmp/parity.sock']},
                        '/bound/cli', False),
    # Captured before destinations were retained in the request.
    'retained-old-format': ({'provider': 'openai', 'model': 'gpt-parity', 'provider_domain': None},
                            '/bound/cli', False),
    'agents-member': ({}, 'agents-socket', True),
}


def _scenario(root: Path, name: str) -> dict:
    """Prepare one launch and return its policy, process spec, argv, environment and Home overlay."""
    changes, address, independent = SCENARIOS[name]
    request = {**_layout(root), **changes}
    os.environ['PATH'] = str(root / 'bin') + os.pathsep + os.environ['PATH']
    if request['provider_domain'] is None:
        del request['provider_domain']
    project = Path(request['harness_root'])
    if independent:
        directory = root / 'data/native' / name
        address = str(directory / address)
    else:
        directory = project / '.graphtraj/runner/sessions' / name
    directory.mkdir(parents=True)
    trace = project / 'state' / (name + '.jsonl')
    trace.parent.mkdir(exist_ok=True)
    turn = PiManagedExecution(request, 'unused', directory, lambda *a: None, lambda *a: None, trace, None)
    turn.independent = independent
    argv, env = turn._prepare(address)
    agent = trace.with_suffix('.pi') / 'agent'
    overlay = {}
    for entry in sorted(agent.iterdir()):
        overlay[entry.name] = ('-> ' + os.readlink(entry)) if entry.is_symlink() else entry.read_text()
    spec = json.loads((directory / 'pi-process.json').read_text())
    return {
        'argv': argv,
        'policy': json.loads((directory / 'pi-policy.json').read_text()),
        'spec': spec,
        'environment': {
            'changed': {key: value for key, value in sorted(env.items()) if os.environ.get(key) != value},
            'removed': sorted(key for key in os.environ if key not in env),
        },
        'overlay': overlay,
        'instructions': (trace.with_suffix('.pi') / 'role-instructions.txt').read_text(),
    }


def _destinations(root: Path) -> dict:
    """Resolve destinations through GraphTraj's resolver against the controlled peer."""
    from graphtraj.runtimes.model_discovery import pi_model_domain

    results = {}
    for provider, model, key in (('deepseek', 'deepseek-flash', None), ('openai', 'gpt-parity', 'PARITY_KEY'),
                                 ('custom', 'any', None), ('openai', 'gpt-parity', 'PARITY_MISSING_KEY')):
        try:
            results[f'{provider}/{model}/{key}'] = pi_model_domain(str(root / 'user-agent'), provider, model, key)
        except RuntimeAdapterError as error:
            results[f'{provider}/{model}/{key}'] = {'code': error.code, 'message': error.message}
    return results


def capture() -> dict:
    """Capture every scenario in a fresh directory under a controlled environment."""
    saved = dict(os.environ)
    try:
        for key in list(os.environ):
            if key.startswith(SCRUBBED):
                del os.environ[key]
        os.environ.update(AMBIENT)
        with tempfile.TemporaryDirectory(prefix='pi-parity-') as directory:
            root = Path(directory).resolve()
            document = {}
            for name in SCENARIOS:
                os.environ['PATH'] = saved.get('PATH', '')
                document[name] = _scenario(root / name, name)
            _layout(root / 'destinations')
            os.environ['PATH'] = str(root / 'destinations/bin') + os.pathsep + saved.get('PATH', '')
            document['destinations'] = _destinations(root / 'destinations')
            text = json.dumps(document, indent=1, sort_keys=True)
            replacements = {
                str(root): '<tmp>', directory: '<tmp>',
                str(Path(agents_file).resolve().parents[1]): '<src>',
                sys.executable: '<python>', str(Path(sys.executable).parent): '<python-bin>',
                str(Path(sys.prefix).resolve()): '<prefix>', sys.prefix: '<prefix>',
                str(Path(sys.base_prefix).resolve()): '<base-prefix>', str(Path.home()): '<home>',
            }
            for value in sorted(replacements, key=len, reverse=True):
                text = text.replace(value, replacements[value])
            return json.loads(text)
    finally:
        os.environ.clear()
        os.environ.update(saved)


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(capture(), indent=1, sort_keys=True) + '\n')

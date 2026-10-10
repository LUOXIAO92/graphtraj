"""Enter the installed asb sandbox without scrubbing host-prepared child settings.

Executed by the configured Python that has agent-sandbox installed. This file
uses only its public wrapping API; it does not import GraphTraj or its state.
"""

import json
import os
from pathlib import Path
import sys


def main() -> None:
    """Replace this owned process with strict native sandbox execution."""
    from agent_sandbox import is_sandbox_available, resolve_profile, wrap_command

    if not is_sandbox_available():
        raise SystemExit('Pi requires installed srt; refusing unsandboxed execution.')
    document = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    policy = document['policy']
    selected = json.loads(Path(policy).read_text(encoding='utf-8'))
    native = resolve_profile('locked')
    # Keep native denials; replace broad grants with the exact child grants.
    for field in ('denyRead', 'denyWrite'):
        selected['filesystem'][field] = list(dict.fromkeys(
            native.get('filesystem', {}).get(field, []) + selected['filesystem'][field]))
    Path(policy).write_text(json.dumps(selected), encoding='utf-8')
    environment = dict(os.environ)
    environment.update({
        'ASB_SANDBOX': '1', 'ASB_PROFILE': 'custom',
        'ASB_PROFILE_JSON': Path(policy).read_text(encoding='utf-8'),
        'PI_ASB_NO_ALIAS_PROMPT': '1',
    })
    argv = document['argv']
    # Pi's documented runtime key wins over stored auth and native model keys.
    # Resolve only in memory after loading the nonsecret retained process spec.
    if document.get('api_key_env'):
        argv += ['--api-key', environment[document['api_key_env']]]
    elif document.get('unauthenticated'):
        argv += ['--api-key', 'local']
    command = wrap_command(argv, policy)
    if command == document['argv']:
        raise SystemExit('srt disappeared before launch; refusing unsandboxed execution.')
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    main()

"""Task 605: what a DSH child's launch is given, from graftling's own code and the installed DSH.

Runs graftling's DSH driver selection, settings validation and DshExecution.prepare_launch
(the environment and generated DSH home a child is started with). It starts no DSH service,
sends no model request and needs no key: every key below is a dummy value set here.
argv: <work directory> <fake user home holding .dsh/.credentials.yaml>. Prints names, never values.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import graftling
from graftling.dsh import driver, execution
from graftling.dsh.settings import prepare

work, user = Path(sys.argv[1]), Path(sys.argv[2])
dsh = shutil.which('dsh')
print(f'graftling {graftling.__version__} at {Path(graftling.__file__).parent}; dsh {dsh}')
user_dsh = user / '.dsh'
os.environ['HOME'] = str(user)
os.environ['DEEPSEEK_API_KEY'] = 'dummy-605-default'
os.environ['PROBE605_KEY'] = 'dummy-605-named'
os.environ['DEEPSEEK_BASE_URL'] = 'https://ambient.invalid/anthropic'
base = {'executable': dsh, 'model': 'deepseek-flash', 'sandbox': 'workspace-write'}
MARK = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')


def code_of(call):
    try:
        call()
    except Exception as error:  # the code graftling returns, e.g. invalid-config
        return getattr(error, 'code', type(error).__name__)
    return 'accepted'


def launch(name, settings):
    directory = work / name
    directory.mkdir(parents=True)
    request = prepare({**base, **settings}, directory)
    turn = execution.DshExecution(request, 'unused', directory, lambda *_: None, lambda *_: None,
                                  directory / 'trace.jsonl', None)
    environment = turn.prepare_launch()
    home = Path(environment['DSH_HOME'])
    generated = directory / 'dsh-home'
    patch = generated / 'profiles/web/cordis.patch.yml'
    import yaml
    rows = {row.get('id'): row for row in yaml.load(patch.read_text(), Loader=execution._PatchLoader) if 'id' in row}
    keys = sorted(n for n in environment if any(p.endswith(m) for p in n.split('_') for m in MARK))
    files = sorted(str(p.relative_to(generated)) for p in generated.rglob('*') if p.is_file())
    print(f'[{name}] settings {json.dumps(settings)}')
    print(f'[{name}] provider selected: {request["provider"]} | DSH_HOME: {home}'
          f' ({"generated" if home == generated else "the user DSH home" if home == user_dsh else "declared"})')
    print(f'[{name}] generated home files: {files}')
    print(f'[{name}] llm-deepseek row config: {json.dumps(rows["llm-deepseek"].get("config", {}))}')
    print(f'[{name}] web-search rows: {json.dumps({k: v for k, v in rows.items() if k.startswith("web-")})}')
    print(f'[{name}] credential-like names in the child environment: {keys}')
    print(f'[{name}] DEEPSEEK_BASE_URL in the child environment: {"DEEPSEEK_BASE_URL" in environment}')
    print(f'[{name}] generated home holds .credentials.yaml or .env: '
          f'{(generated / ".credentials.yaml").exists() or (generated / ".env").exists()}')


print('user DSH home (fake) files:', sorted(p.name for p in user_dsh.iterdir()))
for provider in ('deepseek-official', 'openrouter', 'command-code'):
    print(f'provider {provider!r}: {code_of(lambda: driver.selected(base, {"provider": provider}))}')
print('base_url with user:password:', code_of(lambda: prepare({**base, 'base_url': 'https://u:p@example.invalid/anthropic'}, work)))
print('base_url with a query:', code_of(lambda: prepare({**base, 'base_url': 'https://example.invalid/anthropic?k=1'}, work)))
print('base_url ftp:', code_of(lambda: prepare({**base, 'base_url': 'ftp://example.invalid/'}, work)))
print('api_key_env naming an unset variable:', code_of(lambda: prepare({**base, 'api_key_env': 'PROBE605_UNSET'}, work)))
launch('no-connection-settings', {})
launch('api_key_env', {'api_key_env': 'PROBE605_KEY'})
launch('home', {'runtime_home': str(user_dsh)})
launch('base_url', {'base_url': 'https://example.invalid/anthropic'})

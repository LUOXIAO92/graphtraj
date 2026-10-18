"""Public Pi preflight retains useful diagnostics without printing native secrets."""
from pathlib import Path
import sys

import pytest

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_pi_runtime import context, pi_environment


@pytest.mark.parametrize('case', ['filesystem', 'missing-model'])
def test_preflight_metadata_failure_is_actionable(
    tmp_path: Path, pi_environment: dict, case: str,
) -> None:
    """A long native failure keeps its safe tail; missing selected metadata is explicit."""
    executable = tmp_path / 'bin/pi'
    executable.write_text(f'#!{sys.executable}\n' + '''import json, sys
if '--version' in sys.argv:
    print('controlled-version')
    raise SystemExit(0)
request = json.loads(sys.stdin.readline())
assert request['type'] == 'get_available_models'
''' + ('''sys.stderr.write('secret-not-for-report' * 5000)
sys.stderr.write("\\nError: EPERM: operation not permitted, mkdir '/selected/models-store.json.lock'\\n")
raise SystemExit(1)
''' if case == 'filesystem' else '''print(json.dumps({'id':request['id'],'success':True,'data':{'models':[]}}),flush=True)
'''))
    with pytest.raises(RuntimeAdapterError) as failure:
        context(tmp_path, pi_environment)
    message = str(failure.value)
    assert 'secret-not-for-report' not in message
    if case == 'filesystem':
        assert 'exited 1' in message
        assert 'EPERM' in message
        assert '/selected/models-store.json.lock' in message
    else:
        assert 'selected provider/model is absent' in message

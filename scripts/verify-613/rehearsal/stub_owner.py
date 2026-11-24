#!/Users/luoxiao/miniconda3/bin/python3.13 -I
"""REHEARSAL ONLY: stands in for the owner's `claude` in step 00 (version and one-line answer); never acceptance."""
import json
import sys

if sys.argv[1:] == ['--version']:
    print('2.1.300 (Claude Code) [rehearsal stub]')
    sys.exit(0)
print(json.dumps({'type': 'system', 'subtype': 'init', 'model': 'rehearsal-stub', 'apiKeySource': 'none'}))
print(json.dumps({'type': 'result', 'is_error': False, 'result': 'OK (rehearsal stub)'}))

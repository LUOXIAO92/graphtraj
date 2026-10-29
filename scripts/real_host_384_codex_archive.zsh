#!/bin/zsh
# Task 384 real-host check: the independent Codex host, with normalized
# archiving on, writes a Session for the child it creates.
#
# Run in a plain Terminal (not inside an Agent sandbox):
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/384-standalone-session-normalization/scripts/real_host_384_codex_archive.zsh [model]
#
# [model] is the Codex model; without it the script reads only the
# `model = "..."` line of ~/.codex/config.toml. Everything else is isolated in
# a new /tmp/agents-384-real.XXXXXX directory ($RUN): its own venv with
# agent-swarm from this Worktree's commit, its own working directory and its
# own agents data root. No package is fetched from PyPI: PyYAML comes from the
# read-only Conda base, websockets is copied from the Harness runtime venv.
# Codex uses your existing login; no credential is read, copied or printed.
#
# Expected observables:
#   - "agents 0.2.0" loaded from a file inside $RUN (not .venv-runtime, not the Worktree);
#   - preflight prints PREFLIGHT-OK and the model Codex reports;
#   - the parent replies TASK384-CHILD-READY;
#   - at least one $RUN/data/sessions/<sha256>/session.jsonl with
#     header.version 5 and extra_fields keys ['realhost'].
# Dialogs: no native review dialog is expected. If a `native_request` JSON
# appears on stderr, press Ctrl-C and send the whole output back; do not answer it.
set -euo pipefail

WORKTREE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/384-standalone-session-normalization
CONDA_PYTHON=/Users/luoxiao/miniconda3/bin/python3.13
RUNTIME_SITE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
CODEX=$(command -v codex)
MODEL=${1:-$(sed -n 's/^model *= *"\(.*\)"$/\1/p' "$HOME/.codex/config.toml" 2>/dev/null | head -1)}
if [[ -z "$MODEL" ]]; then
  print -u2 "Pass a Codex model name as the first argument."
  exit 2
fi

# Resolve once: /tmp is a symlink to /private/tmp, and every later path
# (venv interpreter, agent_swarm.__file__) must use the same form.
RUN=${$(mktemp -d /tmp/agents-384-real.XXXXXX):A}
WORK=$RUN/work
DATA=$RUN/data
mkdir -p "$WORK" "$DATA" "$RUN/src"
print "run directory: $RUN"
print "commit:        $COMMIT"
print "codex:         $CODEX"
print "model:         $MODEL"

print "\n--- preflight ---"
print "zsh: $ZSH_VERSION"
"$CODEX" --version
# Print only the login method; any key fragment after " - " is dropped.
print "login: $("$CODEX" login status 2>&1 | sed -E 's/ - .*//' | head -1)"
cd "$WORK"
PROBE=$("$CODEX" exec --skip-git-repo-check -m "$MODEL" 'Reply with exactly: PREFLIGHT-OK' 2>&1) || {
  print -u2 "codex exec failed:"; print -u2 -- "$PROBE"; exit 1; }
if [[ "$PROBE" != *PREFLIGHT-OK* ]]; then
  print -u2 "The model probe did not reply PREFLIGHT-OK:"; print -u2 -- "$PROBE"; exit 1
fi
print "probe: PREFLIGHT-OK"
print "codex reports: $(print -- "$PROBE" | grep -m1 '^model:' || print 'no model line in codex exec output')"

print "\n--- dedicated venv (no PyPI) ---"
for item in websockets websockets-16.1.1.dist-info; do
  if [[ ! -e "$RUNTIME_SITE/$item" ]]; then
    print -u2 "Missing $RUNTIME_SITE/$item; websockets cannot be provided without PyPI."
    exit 1
  fi
done
git -C "$WORKTREE" archive "$COMMIT" src/agent_swarm | tar -x -C "$RUN/src"
"$CONDA_PYTHON" -m venv --system-site-packages "$RUN/venv"
SITE=$("$RUN/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
cp -R "$RUNTIME_SITE/websockets" "$RUNTIME_SITE/websockets-16.1.1.dist-info" "$SITE/"
# Build without isolation so no build dependency is fetched either.
"$RUN/venv/bin/python" -m pip install --quiet --disable-pip-version-check --no-deps --no-index \
  --no-build-isolation "$RUN/src/src/agent_swarm"
LOADED=$(cd "$RUN" && "$RUN/venv/bin/python" -c 'import yaml, websockets, agent_swarm; print(agent_swarm.__version__, agent_swarm.__file__)')
print "agents $LOADED"
if [[ "${LOADED#* }" != "$RUN"/* ]]; then
  print -u2 "agent_swarm was not loaded from $RUN."
  exit 1
fi

print "\n--- independent Codex host, archiving on ---"
print 'save_normalized_sessions: true' > "$DATA/config.yml"
cat > "$RUN/settings.json" <<EOF
{"adapter_request": {"arguments": ["$CODEX"], "worktree_path": "$WORK",
  "session_parameters": {"cwd": "$WORK", "model": "$MODEL", "developerInstructions": "",
    "config": {"default_permissions": "work", "permissions": {"work": {
      "extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}}}}}}
EOF
cd "$WORK"
"$RUN/venv/bin/python" -m agent_swarm.codex.host --settings "$RUN/settings.json" --directory "$DATA" \
  --output "$RUN/parent-result.json" \
  'Use the agents MCP tool, whose calls take {"action", "feature", "arguments"}. First call it with action "execute", feature "create" and arguments {"runtime": "codex", "instruction": "Reply with exactly: TASK384-CHILD-READY. Do not use tools.", "extra_fields": {"realhost": {"task": "384"}}}. Then call it with action "execute", feature "wait" and arguments {"agent": <the agent returned by create>, "timeout_seconds": 180}. Finally reply with the child reply text only.' \
  || print -u2 "The parent host exited with status $?; the archive check below still runs."

print "\n--- normalized Sessions under $DATA/sessions ---"
(cd "$RUN" && "$RUN/venv/bin/python" - "$DATA" <<'EOF'
import sys
from pathlib import Path
from agent_swarm import read_session

found = sorted(Path(sys.argv[1], 'sessions').glob('*/session.jsonl'))
if not found:
    print('NO session.jsonl was written')
for path in found:
    session = read_session(path)
    header = session['header']
    print('path:              ', path)
    print('header.version:    ', header['version'])
    print('header.id:         ', header['id'])
    print('extra_fields keys: ', sorted(header.get('extra_fields', {})))
    print('first event types: ', [event['type'] for event in session['events'][:8]])
EOF
)

print "\n--- follow-up commands (paste as needed) ---"
print "cat $RUN/parent-result.json"
for session in "$DATA"/sessions/*/session.jsonl(N); do
  print "head -3 $session"
done
print "rm -rf $RUN"

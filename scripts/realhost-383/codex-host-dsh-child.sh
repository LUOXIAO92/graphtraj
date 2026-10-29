#!/bin/zsh
# Task 383 real-host check B: a non-DSH host (the Codex host) starts a standalone
# DSH child, without GraphTraj installed and without any GRAPHTRAJ_* variable.
#
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/383-dsh-standalone-host/scripts/realhost-383/codex-host-dsh-child.sh
#
# Why the Codex host: 381 ran `python -m agent_swarm.codex.host` for real, it is
# a plain command (no Claude Code mod or MCP registration to install), and its
# --output JSON keeps every public agents result the parent received.
#
# Steps (each says which native review dialog may appear and what to type):
#   0 preflight: versions, login status, one-line answers from codex and dsh
#   1 the Codex parent creates a DSH child (effort low), waits for its answer,
#     sends a second message, waits again, then ends its turn
#   2 the parent resumes its own Session (--resume), resumes the same DSH child,
#     waits, and reads the child's public status document
#   3 the script checks the retained JSON and prints PASS/FAIL per criterion
#
# DSH: the installed version is printed; it is the first real run of the agents
# DSH driver on it (the deterministic tests use a controlled service). The host,
# and so the DSH child, starts with DEEPSEEK_BASE_URL unset (Task 338).
# No credential is read, copied or printed: only whether DEEPSEEK_API_KEY is set.
setopt err_exit pipe_fail no_unset

WT=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/383-dsh-standalone-host
# The code under test; later commits may change only this script's directory.
# Whoever integrates further code commits sets COMMIT to the new code commit.
COMMIT=236a3a1ef369bdf68f662543732e0c28acf2c729
P=/Users/luoxiao/agents-383-realhost/b3
PY=/Users/luoxiao/miniconda3/bin/python3.13
CHILD_EFFORT=low
DSH_MODEL=deepseek-flash
WORK=$P/work
STATE=$P/state
EVIDENCE=$P/evidence
VENV=$P/venv

say() { print -r -- ""; print -r -- "== $*"; }
fail() { print -r -- "STOP: $*" >&2; exit 1; }

say "commit check"
HEAD_NOW=$(git -C $WT rev-parse HEAD)
print -r -- "HEAD=$HEAD_NOW expected=$COMMIT"
[[ $HEAD_NOW == $COMMIT ]] || git -C $WT diff --quiet $COMMIT $HEAD_NOW -- . ':!scripts/realhost-383' \
  || fail "the Worktree's code differs from commit $COMMIT"
git -C $WT diff --quiet HEAD -- . ':!scripts/realhost-383' || fail "the Worktree has uncommitted code changes"

[[ -e $P ]] && fail "$P exists from an earlier run; move it away (for example: mv $P $P.old) and run again"
mkdir -p $WORK $STATE $EVIDENCE
# Every later command, the host and its children (the MCP server, DSH) run in
# $WORK. `python -c` puts its cwd first on sys.path, and a cwd holding a
# graphtraj/ directory (for example the Harness root) would make graphtraj importable.
cd $WORK

say "venv (isolated, agents only: no system or Conda site-packages, no GraphTraj; nothing is installed from PyPI)"
# No --system-site-packages: the venv sees only the stdlib and what is copied below.
$PY -m venv --without-pip $VENV
SITE=$VENV/lib/python3.13/site-packages
# One fixed source for the dependencies: the Harness's persistent runtime venv
# (PyYAML 6.0.3 and websockets 16.1.1 when written; built for this python3.13).
SRC=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages
for name in yaml websockets; do
  [[ -d $SRC/$name ]] || fail "$SRC/$name is missing; this script copies dependencies only from there"
  cp -R $SRC/$name $SITE/
done
[[ -d $SRC/_yaml ]] && cp -R $SRC/_yaml $SITE/
DIST=($SRC/[Pp][Yy][Yy][Aa][Mm][Ll]-*.dist-info(N/) $SRC/websockets-*.dist-info(N/))
[[ ${#DIST} -eq 2 ]] || fail "expected one PyYAML and one websockets dist-info in $SRC, found: ${DIST:-none}"
cp -R $DIST $SITE/
print -r -- "copied from $SRC: yaml, websockets$([[ -d $SRC/_yaml ]] && print -n ', _yaml'), ${(j:, :)${DIST[@]:t}}"
# agent_swarm from this checkout without putting $WT/src (which holds graphtraj)
# on sys.path: a .pth names a directory that holds only an agent_swarm symlink.
mkdir -p $P/agents-only
ln -s $WT/src/agent_swarm $P/agents-only/agent_swarm
print -r -- $P/agents-only > $SITE/agents-only.pth
$VENV/bin/python -c 'import yaml, websockets, agent_swarm; print("agent_swarm", agent_swarm.__version__, agent_swarm.__file__, "| yaml", yaml.__version__, "| websockets", websockets.__version__)' \
  || fail "yaml, websockets or agent_swarm does not import in $VENV"
# Both views: isolated (-I, as the child's MCP server runs) and plain (cwd first on sys.path).
AGENTS_ONLY='import importlib.util as u, os, sys
s = u.find_spec("graphtraj")
where = "" if s is None else " at " + str(s.origin or list(s.submodule_search_locations or []))
print("graphtraj importable (" + sys.argv[1] + ", cwd " + os.getcwd() + "):", s is not None, where)
raise SystemExit(s is not None)'
$VENV/bin/python -I -c $AGENTS_ONLY 'python -I' || fail "graphtraj is importable in $VENV under -I; this check needs an agents-only venv"
$VENV/bin/python -c $AGENTS_ONLY 'python' || fail "graphtraj is importable with cwd $PWD; this check needs an agents-only venv"

say "step 0: preflight (native review dialog: none; nothing to type)"
if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
  source ~/.zshrc >/dev/null 2>&1 || true
  cd $WORK
fi
print -r -- "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
[[ -n ${DEEPSEEK_API_KEY:-} ]] || fail "DEEPSEEK_API_KEY is unset; export it (or add it to ~/.zshrc) and run again"
print -r -- "DEEPSEEK_BASE_URL in this shell: ${${DEEPSEEK_BASE_URL:+set}:-unset} (the host and DSH start with it unset)"
GT_VARS=(${(k)parameters[(I)GRAPHTRAJ_*]})
print -r -- "GRAPHTRAJ_* variables removed for the host: ${GT_VARS:-none}"
UNSET=(-u DEEPSEEK_BASE_URL)
for name in $GT_VARS; do UNSET+=(-u $name); done

CODEX=$(command -v codex) || fail "codex is not on PATH"
DSH=$(command -v dsh) || fail "dsh is not on PATH"
DSH_PACKAGE=${DSH:A:h:h}/package.json
DSH_VERSION=$($VENV/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' $DSH_PACKAGE)
print -r -- "codex: $CODEX ($($CODEX --version))"
$CODEX login status || fail "codex is not logged in"
print -r -- 'In one line: name the model you are running as. Do not run any command.' \
  | $CODEX exec --skip-git-repo-check --ephemeral -s read-only - | tail -1
print -r -- "dsh: $DSH -> ${DSH:A} (installed version $DSH_VERSION; agents requires 0.2.0-rc.2 or later)"
# DSH headless one-shot as in Task 349's diagnosis; prints only the final text or the error code.
(cd $WORK && env $UNSET $DSH --profile headless --json \
  "In one line: name the model you are running as, and confirm you are logged in. Do not use any tool." 2>/dev/null) \
  | $VENV/bin/python -c 'import json,sys
for line in sys.stdin:
    try: e = json.loads(line)
    except ValueError: continue
    if e.get("type") == "status" and e.get("phase") == "turn_end" and e.get("reason", {}).get("kind") == "error":
        print("DSH ERROR", e["reason"]["error"].get("code"), e["reason"]["error"].get("status"))
    if e.get("type") == "final": print("dsh says:", e.get("text", "")[:200])'
PARENT_MODEL=$(sed -n 's/^model *= *"\(.*\)"/\1/p' $HOME/.codex/config.toml 2>/dev/null | head -1)
[[ -n $PARENT_MODEL ]] || fail "no top-level model line in ~/.codex/config.toml; add one (model = \"...\") and run again"
print -r -- "parent Codex model (from ~/.codex/config.toml): $PARENT_MODEL"

# The DSH child takes the key by name only; its value stays in the environment.
cat > $P/settings.json <<EOF
{
  "adapter_request": {
    "arguments": ["$CODEX"],
    "worktree_path": "$WORK",
    "session_parameters": {
      "cwd": "$WORK",
      "model": "$PARENT_MODEL",
      "developerInstructions": "",
      "config": {
        "default_permissions": "work",
        "permissions": {"work": {"extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}}
      }
    }
  },
  "runtimes": {"dsh": {"executable": "$DSH", "model": "$DSH_MODEL", "sandbox": "read-only",
                       "api_key_env": "DEEPSEEK_API_KEY"}}
}
EOF

host() {  # host <output> <stderr log> [--resume] <instruction>
  local output=$1 log=$2; shift 2
  env $UNSET $VENV/bin/python -m agent_swarm.codex.host --settings $P/settings.json --directory $STATE \
    --output $output "$@" 2> >(tee $log >&2)
}

say "step 1: Codex parent creates a standalone DSH child"
print -r -- "Native review dialog: none expected (the parent's approvals go to Codex auto_review;"
print -r -- "the DSH child is told to use no tool, so it raises no DSH approval)."
print -r -- "If a line {\"native_request\": ...} appears on stderr, type ONE line and press Enter:"
print -r -- "  method mcpServer/elicitation/request whose params name the agents tool: {\"action\":\"accept\",\"content\":{}}"
print -r -- "  method ending in requestApproval for a command you do not expect:      {\"decision\":\"decline\"}"
host $EVIDENCE/step1.json $EVIDENCE/step1.stderr.log "Use only the agents MCP tool, no shell commands.
1. Call it with {\"action\":\"execute\",\"feature\":\"create\",\"arguments\":{\"runtime\":\"dsh\",\"reasoning_effort\":\"$CHILD_EFFORT\",\"instruction\":\"Do not use any tool. Reply with exactly: PONG-1\"}}.
2. Call it with {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"<the agent from step 1>\",\"timeout_seconds\":240}}. The child's answer may also arrive as a host event.
3. Call it with {\"action\":\"execute\",\"feature\":\"send\",\"arguments\":{\"agent\":\"<the same agent>\",\"message\":\"Do not use any tool. Reply with exactly: PONG-2\"}}, then wait for it as in step 2.
4. End your turn with one line: the agent and the two answers you received." || print -r -- "(host exit $?; continuing to collect evidence)"

AGENT=$($VENV/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(next(o["result"]["agent"] for o in d["operations"] if o["action"]=="create" and not o["failed"]))' $EVIDENCE/step1.json) \
  || fail "step 1 created no child; see $EVIDENCE/step1.json and $EVIDENCE/step1.stderr.log"
print -r -- "child agent: $AGENT"

say "step 2: parent --resume, then resume the same DSH child and read its status"
print -r -- "Native review dialog: same as step 1 (none expected; same replies if one appears)."
host $EVIDENCE/step2.json $EVIDENCE/step2.stderr.log --resume "Use only the agents MCP tool, no shell commands.
1. Call it with {\"action\":\"execute\",\"feature\":\"resume\",\"arguments\":{\"agent\":\"$AGENT\",\"message\":\"Do not use any tool. Reply with exactly: PONG-3, then the two replies you gave before.\"}}.
2. Wait for it with {\"action\":\"execute\",\"feature\":\"wait\",\"arguments\":{\"agent\":\"$AGENT\",\"timeout_seconds\":240}}.
3. Call it with {\"action\":\"execute\",\"feature\":\"status\",\"arguments\":{\"agent\":\"$AGENT\"}}.
4. End your turn with one line: the child's answer." || print -r -- "(host exit $?; continuing to collect evidence)"

say "step 3: retained evidence (public agents results from --output; no internal control records)"
cp $STATE/host/trace.jsonl $EVIDENCE/parent-trace.jsonl 2>/dev/null || print -r -- "no parent trace at $STATE/host/trace.jsonl"
find $STATE -name trace.jsonl -newer $P/settings.json -print > $EVIDENCE/traces.txt
$VENV/bin/python - $EVIDENCE/step1.json $EVIDENCE/step2.json $CHILD_EFFORT $DSH_VERSION <<'EOF'
import json, sys
one, two = (json.load(open(path)) for path in sys.argv[1:3])
effort, version = sys.argv[3:5]
ops = lambda doc, action: [o['result'] for o in doc['operations'] if o['action'] == action and not o['failed']]
create = ops(one, 'create')[0]
agent, session = create['agent'], create['session']
answers = lambda doc: [(w['result'].get('last_result') or {}).get('last_message') or ''
                       for w in ops(doc, 'wait') if w['agent'] == agent]
heard = lambda doc, text: (any(text in a for a in answers(doc))
                           or any(d['agent'] == agent and text in (d['body'] or '') for d in doc['deliveries']))
status = [s['result'] for s in ops(two, 'status') if s['agent'] == agent]
print(f'installed DSH {version}: first real run of the agents DSH driver on this version')
checks = [
    ('step1.json operations[create].result.result.runtime == dsh', create['result']['runtime'] == 'dsh'),
    (f'step1.json operations[create].result.result.reasoning_effort == {effort} (per-child choice)',
     create['result']['reasoning_effort'] == effort),
    ('step1.json operations[create].result.result.parent == null (root child of the Codex parent)',
     create['result']['parent'] is None),
    ('step1.json: the parent received PONG-1 from the child (wait result or host event)', heard(one, 'PONG-1')),
    ('step1.json operations[send] for the child succeeded', any(o['agent'] == agent for o in ops(one, 'send'))),
    ('step1.json: the parent received PONG-2 from the child', heard(one, 'PONG-2')),
    ('step2.json parent_session == step1.json parent_session (parent resumed)',
     two['parent_session'] == one['parent_session']),
    ('step2.json operations[resume].result.session == step1 child session (same native DSH Session)',
     any(o['agent'] == agent and o['session'] == session for o in ops(two, 'resume'))),
    ('step2.json: the parent received PONG-3 from the resumed child', heard(two, 'PONG-3')),
    ('step2.json operations[status] (public document): runtime dsh, same session, standby',
     any(s.get('runtime') == 'dsh' and s.get('session') == session and s.get('state') == 'standby' for s in status)),
]
for name, ok in checks:
    print(('PASS ' if ok else 'FAIL ') + name)
print('child session:', session)
print('wait answers step1:', json.dumps(answers(one), ensure_ascii=False))
print('wait answers step2:', json.dumps(answers(two), ensure_ascii=False))
print('deliveries step1:', json.dumps([{k: d[k] for k in ('agent', 'body')} for d in one['deliveries']], ensure_ascii=False))
print('deliveries step2:', json.dumps([{k: d[k] for k in ('agent', 'body')} for d in two['deliveries']], ensure_ascii=False))
print('status step2:', json.dumps(status, ensure_ascii=False)[:2000])
EOF

say "follow-up commands (copy as needed)"
print -r -- "zsh -c 'cd $WORK && env -u DEEPSEEK_BASE_URL $VENV/bin/python -m agent_swarm.codex.host --settings $P/settings.json --directory $STATE --output $EVIDENCE/step3.json --resume \"Use the agents MCP tool: status for agent $AGENT, then end your turn with its state.\"'"
print -r -- "less $EVIDENCE/step1.json $EVIDENCE/step2.json $EVIDENCE/step1.stderr.log $EVIDENCE/step2.stderr.log"
print -r -- "cat $EVIDENCE/traces.txt"
print -r -- "Evidence kept in $EVIDENCE; send that directory's path back to Main."

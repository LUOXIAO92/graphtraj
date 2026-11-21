#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 549 steps (modelled on verify-514/538): is a progressive-disclosure result (agents/tasks discover, describe,
# describe schema:true) shown or fed to the model twice in Codex, Pi or DSH?
#   zsh scripts/verify-549/steps.zsh <STEP>        (Main's Bash, from this Task's Worktree)
# Order: 00 -> X -> P -> D -> C        (XU: optional USER step, Codex TUI card)
#   00  preflight: builds a venv from the exact commits (GraphTraj $GT + graftling $GL), an isolated project with
#       `graphtraj setup`, the DSH graphtraj-main patch; S = the raw server results, no host and no model; then each
#       host answers a one-line prompt with its model and login.
#   X   Codex CLI mode (gpt-6-luna): `codex exec` human output (stdout/stderr files) and `codex exec --json` (events
#       file) in the project with GraphTraj's MCP server; counts per field in the printed output, in the --json
#       mcp_tool_call result.content vs result.structured_content, in the rollout's function_call_output (MODEL
#       input) and in the model's final message.
#   R   rehearsal without host or model: host-shaped fixtures from S through the same counter.
#   P   Pi: one `pi --mode json` (deepseek-flash) with GraphTraj's Pi extension; counts in the session's toolResult
#       content (MODEL input; Pi's renderer draws the same content text, dist/extensions/mcp/tools.js:278-300).
#   D   DSH: one headless `dsh ... --json` (deepseek-flash) with the graphtraj-main row; counts in the tool/result
#       message content (MODEL input; dsh-tools/lib/pipeline.js:202-205, render = content text).
#   XU  USER, optional: the same calls in an interactive Codex; look at the card (see the step's text).
#   C   read only: prints every summary again as one table source.
# Production comparison: VERIFY549_GT=<GraphTraj commit> VERIFY549_GL=<graftling commit> uses its own BASE.
# Everything real-host is under BASE=/private/tmp/codex-549/<GT>-<GL> (outside the Harness). The user's host installs,
# ~/.codex, ~/.pi, ~/.dsh and dotfiles are never written (Codex rollouts and Pi/DSH sessions are only read or are
# redirected into BASE). No step connects to the Harness's production MCP servers.
emulate -L zsh
setopt err_return pipe_fail no_unset no_bg_nice extended_glob
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY549_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY549_H:-${WT:h:h:h:h}}
GT=${VERIFY549_GT:-500e1f175f6ceb990972af1a158993b119d36d37}    # GraphTraj dev
GL=${VERIFY549_GL:-6794ce02b6210ec88837437affb8d7b525612804}    # graftling dev
GTREPO=${VERIFY549_GTREPO:-$WT}; GLREPO=${VERIFY549_GLREPO:-$H/graftling}
BASE=${VERIFY549_BASE:-/private/tmp/codex-549}/${GT[1,8]}-${GL[1,8]}
P=$BASE/project; V=$BASE/venv; OUT=$BASE/runs
CONDA=$HOME/miniconda3/bin/python3.13
RT=${VERIFY549_RT:-$H/.venv-runtime/lib/python3.13/site-packages}   # read only: yaml, websockets, click
CODEX_MODEL=gpt-6-luna; PI_PROVIDER=deepseek; PI_MODEL=deepseek-flash
CODEX_SESSIONS=${CODEX_HOME:-$HOME/.codex}/sessions                 # read only
STEP=${1:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY549_STUB:-} ]] && path=($VERIFY549_STUB $path)        # rehearsal only: stub hosts first

say() { print -r -- "== $*"; }
next() { print -r -- "
==> next (paste as is): zsh $THIS $*"; }
BOUND=(/usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!\n"')
redact() { if [[ -n ${DEEPSEEK_API_KEY:-} ]]; then sed "s|${DEEPSEEK_API_KEY}|[redacted]|g"; else cat; fi; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} ${DEEPSEEK_API_KEY:+DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY} "$@"; }
load_key() {  # verify-513 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
  [[ -n ${DEEPSEEK_API_KEY:-} ]] || { print "STOP: DEEPSEEK_API_KEY is unset"; return 1; }
}
deps() {  # $1 venv: PyYAML, click and websockets copied from production's site-packages (never changed there)
  local SP=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $RT/websockets $RT/websockets-*.dist-info(N) \
    $RT/click $RT/click-*.dist-info(N) $SP/
}
wheel() {  # $1 repository, $2 commit, $3 subdirectory, $4 output directory
  local src=$4/src-${2[1,10]}; rm -rf $src; mkdir -p $src $4
  git -C $1 archive $2 $3 | tar -x -C $src
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $4 $src/$3 >/dev/null
}
need() {  # $1 directory, $2 pattern: the one file it must hold
  local found=($1/$~2(N))
  (( $#found == 1 )) && { print -r -- $found; return 0; }
  print -r -- "STOP: expected exactly one $2 in $1, found ${#found}" >&2; return 1
}
venv_check() {
  [[ -f $V/installed && $(<$V/installed) == "$GT $GL" ]] || { print "STOP: $V does not hold $GT + $GL; run: zsh $THIS 00"; return 1; }
}
begin() {  # $1 step: evidence directory and the time marker for the record scans
  D=$OUT/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D; touch $D/marker
  print -r -- "GraphTraj $GT graftling $GL step $1" > $D/run.txt
  print -r -- "evidence: $D"
}
# One prompt for every host: the six calls, nothing else, and no restating of results (so a repetition in the
# model's own reply, cause (d), is not mistaken for a host repetition; the reply is printed separately).
PROMPT='This is a scripted probe. Call these six MCP tool calls in order, each exactly once, and no other tool: (1) the graphtraj agents tool with {"action": "discover"}; (2) the graphtraj agents tool with {"action": "describe", "feature": "wait"}; (3) the graphtraj agents tool with {"action": "describe", "feature": "wait", "schema": true}; (4) the graphtraj tasks tool with {"action": "discover"}; (5) the graphtraj tasks tool with {"action": "describe", "feature": "task-delivery"}; (6) the graphtraj tasks tool with {"action": "describe", "feature": "task-delivery", "schema": true}. Do not quote or restate any result. Then reply with exactly one line: DONE-549 followed by ok or the exact error for each call.'
codex_flags() {
  print -r -- -c "mcp_servers.graphtraj.command=\"$V/bin/graphtraj-mcp\"" -c 'mcp_servers.graphtraj.args=[]' \
    -c 'mcp_servers.graphtraj.default_tools_approval_mode="approve"' -c 'approval_policy="never"' -s read-only
}
count() { clean $V/bin/python -I $SD/count549.py "$@"; }    # the venv holds PyYAML (deps)
pi_ext() { $V/bin/python -I -c 'import graphtraj, pathlib; print(pathlib.Path(graphtraj.__file__).parent / "runtimes/pi/extension.mjs")'; }

[[ -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $OUT
case $STEP in
00)
  say "[00] preflight. Dialog: none. Builds the venv (no network), the project, the raw server results, then one-line prompts (codex, pi, dsh; each at most 120 s)."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); codex $(codex --version 2>&1 | tail -1); pi $(pi --version 2>&1 | tail -1); dsh $(dsh --version 2>&1 | tail -1)"
  git -C $GTREPO cat-file -e "$GT^{commit}" && git -C $GLREPO cat-file -e "$GL^{commit}" \
    || { print "STOP: $GTREPO lacks $GT or $GLREPO lacks $GL"; return 1; }
  print "GraphTraj $GT ($(git -C $GTREPO log -1 --format='%h %s' $GT | cut -c1-70)); graftling $GL ($(git -C $GLREPO log -1 --format='%h %s' $GL | cut -c1-70))"
  local W=$BASE/wheels; mkdir -p $BASE $W
  if [[ ! -f $V/installed || $(<$V/installed) != "$GT $GL" ]]; then
    rm -rf $W; mkdir -p $W
    wheel $GLREPO $GL src/graftling $W && wheel $GTREPO $GT . $W || { print "STOP: a wheel did not build"; return 1; }
    local gw hw; gw=$(need $W 'graftling-*.whl') && hw=$(need $W 'graphtraj-*.whl') || return 1
    [[ -e $V ]] && mv $V $V.$(date +%H%M%S)
    $CONDA -m venv $V && deps $V && $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index \
      --no-deps $gw $hw || { print "STOP: the venv install failed"; return 1; }
    print -r -- "$GT $GL" > $V/installed
  else print "venv $V already holds $GT + $GL"; fi
  (cd $BASE && clean $V/bin/python -I -c 'import graftling, graphtraj, importlib.metadata as m
print("venv: graftling", m.version("graftling"), "| graphtraj", m.version("graphtraj"), "| from", graphtraj.__file__)')
  if [[ ! -d $P/.git ]]; then
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 549 probe" > README.md && git add README.md \
      && git -c user.name=549 -c user.email=549@invalid commit -qm "Initial source") || return 1
  fi
  [[ -f $P/.graphtraj/config.yml ]] || (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  begin S
  say "[S] the raw CallToolResults of GraphTraj's MCP server from $P (no host, no model)"
  (cd $P && clean $V/bin/python -I $SD/probe549.py $D/server.json $V/bin/graphtraj-mcp) && count server $D/server.json | tee $D/summary.txt
  clean $V/bin/python -m graphtraj.runtimes.dsh.main_entry patch --write $BASE/dsh-main.patch.yml >/dev/null && \
    { print -r -- "- id: llm-deepseek"
      print -r -- "  config: {apiKeyEnv: DEEPSEEK_API_KEY, baseURL: 'https://api.deepseek.com/anthropic'}"; } >> $BASE/dsh-main.patch.yml
  print "Pi extension: $(pi_ext)"
  say "one-line prompts (model and login)"
  load_key || true
  local ASK='Reply with one line: READY-549 and your exact model name. Use no tool.'
  (cd $BASE && clean $BOUND 120 codex exec --skip-git-repo-check -m $CODEX_MODEL $ASK < /dev/null 2>&1 | tail -2) || print "codex rc=$?"
  (cd $BASE && clean $BOUND 120 pi --print --no-tools --no-session --provider $PI_PROVIDER --model $PI_MODEL $ASK < /dev/null 2>&1 | redact | tail -2) || print "pi rc=$?"
  (cd $BASE && clean $BOUND 120 dsh --profile headless --permission-mode read-only $ASK < /dev/null 2>&1 | redact | tail -2) || print "dsh rc=$?"
  print "READY when: the venv line, S rows with 'once' for every field, and three READY-549 lines (codex $CODEX_MODEL logged in; pi and dsh $PI_MODEL)."
  next X
  ;;
X)
  say "[X] Codex CLI mode ($CODEX_MODEL), two non-interactive runs in $P with GraphTraj's MCP server and the user's normal Codex login: (1) human output, stdout and stderr to files; (2) --json events to a file. Dialog: none (approval never, tools approved). At most 2 x 10 min."
  venv_check; begin X
  say "X1 codex exec --skip-git-repo-check (human output)"
  (cd $P && clean $BOUND 600 codex exec --skip-git-repo-check -m $CODEX_MODEL ${(z)$(codex_flags)} $PROMPT < /dev/null \
     > $D/human.stdout.txt 2> $D/human.stderr.txt) || print "codex (human) rc=$? (its error is the tail of $D/human.stderr.txt):"
  tail -3 $D/human.stderr.txt
  say "X2 codex exec --json"
  (cd $P && clean $BOUND 600 codex exec --skip-git-repo-check --json -m $CODEX_MODEL ${(z)$(codex_flags)} $PROMPT < /dev/null \
     > $D/exec.jsonl 2> $D/json.stderr.txt) || print "codex (--json) rc=$? (its error is in $D/exec.jsonl type=error and $D/json.stderr.txt):"
  grep '"type":"error"' $D/exec.jsonl | tail -2; tail -2 $D/json.stderr.txt
  mkdir -p $D/rollouts
  local f; for f in $CODEX_SESSIONS/**/rollout-*.jsonl(N.); do [[ $f -nt $D/marker ]] && cp $f $D/rollouts/; done
  print "codex rollouts copied (read only from $CODEX_SESSIONS): $(ls $D/rollouts | wc -l | tr -d ' ')"
  { count text codex-human-printed $D/human.stdout.txt $D/human.stderr.txt
    count records codex-json-events $D/exec.jsonl
    count records codex-rollouts-model-input $D/rollouts; } | tee $D/summary.txt
  print "Read: 'codex-human-printed' = what the human CLI prints (0.171.0 prints only 'mcp: server/tool started/(completed)', never the result; the reply goes to stderr and, when stdout is not a terminal, to stdout too). 'exec item result.content' and 'structured_content' = the two copies the --json event carries. 'model' (rollout function_call_output) = what $CODEX_MODEL received. 'final message' = the model's own reply."
  print "files: $D/human.stdout.txt $D/human.stderr.txt $D/exec.jsonl $D/rollouts"
  local thread=$(grep -o '"thread_id":"[^"]*"' $D/exec.jsonl | head -1 | cut -d'"' -f4)
  print "codex --json thread: ${thread:-unknown}"
  next "P   (optional USER card check: zsh $THIS XU)"
  ;;
XU)
  say "[XU] USER, plain Terminal, optional. Interactive Codex in $P with the same server and prompt. Dialog: none expected (approval never); if one appears, note it and choose decline."
  venv_check
  print "Look at the six 'Called graphtraj.agents/tasks' cards: collapsed (last 3 lines) and expanded (press the shown key). Note for each whether 'description:' or 'input_schema:' appears twice on one card. Then type /exit."
  (cd $P && codex -m $CODEX_MODEL ${(z)$(codex_flags)} $PROMPT) || print "codex exit $?"
  next P
  ;;
P)
  say "[P] Pi ($PI_PROVIDER/$PI_MODEL) pi --mode json with GraphTraj's Pi extension in $P. Dialog: none. At most 10 min."
  venv_check; load_key || return 1; begin P
  (cd $P && clean PATH=$V/bin:${(j.:.)path} GRAFTLING_PYTHON=$V/bin/python $BOUND 600 pi --mode json --session-dir $D/pi-sessions \
     --extension $(pi_ext) --provider $PI_PROVIDER --model $PI_MODEL $PROMPT < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "pi rc=$?"
  { count records pi-session-model-input $D/pi-sessions
    print "reply: $(grep -o 'DONE-549[^"]*' $D/stdout.jsonl | tail -1)"; } | redact | tee $D/summary.txt
  print "Read: rows 'model' = the toolResult content Pi sends to the model; Pi's MCP renderer draws the same content text."
  next D
  ;;
D)
  say "[D] DSH ($PI_MODEL) headless dsh --json with the graphtraj-main row in $P. Dialog: none. At most 10 min."
  venv_check; load_key || return 1; begin D
  local DH=$D/dsh-home; mkdir -p $DH
  (cd $P && clean DSH_HOME=$DH $BOUND 600 dsh --profile graphtraj549 --from-default-profile headless --patch $BASE/dsh-main.patch.yml \
     --json $PROMPT < /dev/null > $D/stdout.jsonl 2> $D/stderr.txt) || print "dsh rc=$?"
  { count records dsh-model-input $D/stdout.jsonl $DH
    print "reply: $(grep -o 'DONE-549[^"]*' $D/stdout.jsonl | tail -1)"; } | redact | tee $D/summary.txt
  print "Read: rows 'model' = the tool/result message content DSH sends to the model (its card renders the same content text)."
  next C
  ;;
R)
  say "[R] rehearsal, no host and no model: host-shaped fixtures from the latest S results through the same counter. Dialog: none."
  venv_check
  local s=($OUT/S-*/server.json(Nom[1])); [[ -n ${s:-} ]] || { print "STOP: no S result; run: zsh $THIS 00"; return 1; }
  begin R
  clean $V/bin/python -I $SD/fixture549.py $s $D/fixtures
  { count records fixture-codex-rollout $D/fixtures/codex-rollout.jsonl
    count records fixture-pi-session $D/fixtures/pi-session.jsonl
    count records fixture-doubled-defect-shape $D/fixtures/doubled.jsonl
    count records fixture-codex-exec-json $D/fixtures/exec.jsonl
    count text fixture-codex-human $D/fixtures/human.stderr.txt; } | tee $D/summary.txt
  print "PASS when: codex-rollout and pi fixtures say once for every field, the doubled fixture says TWICE, the exec-json fixture shows once in result.content AND once in structured_content per call (two copies in one event), the human fixture prints no field marker."
  ;;
C)
  say "[C] read only: the latest summary of each step under $OUT"
  local s; for s in S X P D; do
    local last=($OUT/$s-*/summary.txt(Nom[1])); print "---- $s: ${last:-none}"; [[ -n ${last:-} ]] && cat $last
  done
  ;;
*) print "usage: zsh $THIS 00|X|XU|P|D|C"; return 2 ;;
esac

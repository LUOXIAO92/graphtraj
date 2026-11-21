#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 552: concept-clarification across four agents under test (S = sonnet | haiku | dsh | codex, all effort high),
# U = Fable 5.2 high simulated user with web research, A = Sonnet 5.5 cheating auditor. Modelled on verify-550.
# design: scripts/verify-550/design.md (answer key, unchanged) + scripts/verify-552/design-552.md (552 differences).
#   zsh scripts/verify-552/steps.zsh <STEP> [args]          (Main's Bash, from this Task's Worktree; no dialog)
# Order: 00 -> F -> W (until 4 research notes) -> R all all -> W (repeat) -> A all -> W -> C
#   00  versions; isolated project BASE/project (production graphtraj setup + claude host configuration, as 550);
#       READY U and A; Codex Seatbelt check without a model (codex sandbox); per agent S READY + probes (a)-(d) with
#       the exact run flags. An agent whose probes FAIL is blocked from R (no BASE/ready-<agent>.ok).
#   F   one Fable research session per scenario (background) -> BASE/u/research/S#.md
#   R <agent|all> <S#|all> [runs, default 3] [cap, default 8]   relay runs in the background, at most cap at once
#   W   status (read only)
#   A <agent|all|run id> [cap, default 8]   audits of finished runs (background)
#   C   copies every run to <Worktree>/.state/realhost/<agent>/<S#>-r<k>/ with digest.md, plus u-research,
#       step-logs and runs-table.md
# BASE=/private/tmp/cc-552 (VERIFY552_BASE overrides it: rehearsal only). Never written: ~/.claude, ~/.codex (Codex
# itself writes each run's rollout into ~/.codex/sessions, normal Codex behaviour; the driver copies only the
# rollouts named by its own thread ids), DSH user config, dotfiles, .venv-runtime, the Harness (except C's copy).
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice no_hup
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY552_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY552_H:-${WT:h:h:h:h}}
BASE=${VERIFY552_BASE:-/private/tmp/cc-552}
RT=$H/.venv-runtime                                  # production: executed read only
PY=${VERIFY552_PY:-$HOME/miniconda3/bin/python3.13}  # runs drv552.py (standard library only)
P=$BASE/project
STEP=${1:-}; A1=${2:-}; A2=${3:-}; A3=${4:-}; A4=${5:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -n ${VERIFY552_STUBBIN:-} ]] && path=($VERIFY552_STUBBIN $path)   # rehearsal only: stub hosts first
CLAUDE=$(command -v claude || print -r -- $HOME/.local/bin/claude)
CODEX=$(command -v codex || print codex); DSH=$(command -v dsh || print dsh)
SBX=${VERIFY552_SBX:-/usr/bin/sandbox-exec}
DEST=${VERIFY552_DEST:-$WT/.state/realhost}
export V552_BASE=$BASE V552_WT=$WT V552_H=$H V552_CLAUDE=$CLAUDE V552_CODEX=$CODEX V552_DSH=$DSH V552_SBX=$SBX \
  V552_MCP=$RT/bin/graphtraj-mcp V552_PY=$PY V552_TURN_S=${VERIFY552_TURN_S:-900} \
  V552_DENYROOT=${VERIFY552_DENYROOT:-${H:h}} V552_CONTEXT=$H/CONTEXT.md \
  V552_CODEX_SESSIONS=${VERIFY552_CODEX_SESSIONS:-$HOME/.codex/sessions}
[[ -n ${VERIFY552_STUB_STATE:-} ]] && export STUB552_STATE=$VERIFY552_STUB_STATE

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
drv() { $PY -I $SD/drv552.py "$@"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
load_key() {  # verify-549 load_key: the value is never printed or written
  if [[ -z ${DEEPSEEK_API_KEY:-} ]]; then
    local value
    value=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; print -rn -- "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || value=
    [[ -n $value ]] && export DEEPSEEK_API_KEY=$value
  fi
  print "DEEPSEEK_API_KEY: ${${DEEPSEEK_API_KEY:+set}:-unset}"
}

[[ -d $H/.graphtraj || -n ${VERIFY552_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE/logs

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | claude $CLAUDE: $($CLAUDE --version 2>&1 | head -1)"
  print -r -- "codex $CODEX: $($CODEX --version 2>&1 | grep -v WARNING | tail -1) | dsh $DSH: $($DSH --version 2>&1 | tail -1) | zstd: $(zstd --version 2>&1 | head -1) | sandbox-exec: $SBX"
  (cd $BASE && $RT/bin/python -I -c 'import importlib.metadata as m; print("production graphtraj", m.version("graphtraj"), "| graftling", m.version("graftling"))')
  print -r -- "driver python: $($PY --version 2>&1) ($PY) | BASE $BASE"
  say "isolated project $P (own git; production graphtraj setup + claude host configuration, read only; as 550)"
  mkdir -p $P
  if [[ ! -d $P/.git ]]; then
    (cd $P && git init -q -b main && print -r -- "# 552 scratch project" > README.md && git add README.md \
      && git -c user.name=552 -c user.email=552@invalid commit -qm "Initial source") || return 1
  fi
  if [[ ! -f $P/.graphtraj/config.yml ]]; then (cd $P && print y | clean $RT/bin/graphtraj setup | tail -2) || return 1; fi
  (cd $P && clean $RT/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $CLAUDE --write >/dev/null) \
    && print "claude host configuration written: $P/.mcp.json, $P/.claude/" || { print "STOP: claude host configuration failed"; return 1; }
  $PY -I $SD/../verify-common/claude_isolation.py settings $H $P || return 1
  say "logins (d): codex login status; DSH key from the environment or ~/.zshrc (never printed)"
  print -r -- "codex: $(clean $CODEX login status 2>&1 | grep -v WARNING | tail -1)"
  load_key
  say "READY-552-U (Fable high) and READY-552-A (Sonnet; medium, else high, else low)"
  drv ready U || { print "STOP: U is not ready"; return 1; }
  drv ready A || { print "STOP: A is not ready"; return 1; }
  say "Codex Seatbelt without a model: the run's permission profile applied by 'codex sandbox' to plain commands"
  drv codex-sandbox | tee $BASE/codex-sandbox.txt
  local ag fails=()
  for ag in sonnet haiku dsh codex; do
    say "READY-552-S-$ag + probes (a) (b) (c) (d) with the exact run flags (dialog: none)"
    drv ready-s $ag 2>&1 | tee $BASE/probes-$ag.txt
    (( ${pipestatus[1]} == 0 )) || fails+=($ag)
    local a=($BASE/logs/ready-$ag/01-S.argv.json(N)); [[ -n ${a[-1]:-} ]] && { print "S argv/config:"; cat ${a[-1]}; }
    [[ -f $BASE/logs/ready-$ag/dsh-patch.yml ]] && { print "dsh patch:"; cat $BASE/logs/ready-$ag/dsh-patch.yml; print "dsh outer Seatbelt profile:"; cat $BASE/logs/ready-$ag/dsh.sb; }
    [[ -f $BASE/logs/ready-$ag/s-settings.json ]] && print "claude settings: $BASE/logs/ready-$ag/s-settings.json ($(grep -c '"' $BASE/logs/ready-$ag/s-settings.json) lines), MCP: $(tr -d '\n ' < $BASE/logs/ready-$ag/s-mcp.json)"
  done
  say "summary"
  for ag in sonnet haiku dsh codex; do print -r -- "$ag: $([[ -f $BASE/ready-$ag.ok ]] && print 'PASS (R allowed)' || print 'FAIL (blocked from R; Main reports the probe lines above to the Leader)')"; done
  (( ${#fails} == 0 )) || print "STOP for: ${fails[*]}"
  next "zsh $THIS F"
}

step_F() {
  say "research: one Fable 5.2 high session per scenario, WebSearch/WebFetch only, cwd $BASE/u/research (background)"
  local s
  for s in S1 S2 S3 S4; do
    $PY -I $SD/drv552.py research $s < /dev/null > $BASE/logs/F-$s.out 2>&1 &!
    print -r -- "$s research started (pid $!), output $BASE/logs/F-$s.out -> $BASE/u/research/$s.md"
  done
  next "zsh $THIS W   (until 4 research notes exist; then: zsh $THIS R all all)"
}

step_R() {
  local ag=${A1:-} sc=${A2:-} runs=${A3:-3} cap=${A4:-8}
  [[ $ag == (all|sonnet|haiku|dsh|codex) && $sc == (all|S[1-4]) && $runs == <1-9> && $cap == <1-64> ]] \
    || { print "usage: R <all|sonnet|haiku|dsh|codex> <all|S1..S4> [runs 1-9, default 3] [cap, default 8]"; return 2; }
  [[ -f $BASE/effort-A.txt ]] || { print "STOP: run 00 first"; return 1; }
  local s list=(S1 S2 S3 S4); [[ $sc == all ]] || list=($sc)
  for s in $list; do [[ -f $BASE/u/research/$s.md ]] || { print "STOP: $BASE/u/research/$s.md missing: run F, then W"; return 1; }; done
  [[ $ag == (all|dsh) ]] && load_key
  say "relay runs in the background (dialog: none): agent $ag, scenario $sc, $runs run(s) each, at most $cap at once"
  $PY -I $SD/drv552.py batch $ag $sc $runs $cap < /dev/null > $BASE/logs/R-batch-$(date +%H%M%S).out 2>&1 &!
  print -r -- "batch started (pid $!), output $BASE/logs/R-batch-*.out; per run $BASE/logs/R-<run>.out and $BASE/logs/<run>/driver.log"
  next "zsh $THIS W"
}

step_W() {
  say "status (read only)"
  local s f
  for s in S1 S2 S3 S4; do
    if [[ -f $BASE/u/research/$s.md ]]; then print -r -- "research $s: done | $(grep -h 'END research' $BASE/logs/research-$s/driver.log 2>/dev/null | tail -1)"
    elif [[ -f $BASE/logs/F-$s.out ]]; then print -r -- "research $s: running/failed | $(tail -1 $BASE/logs/F-$s.out)"; fi
  done
  local total=0 ended=0 audited=0 running=()
  for f in $BASE/logs/(sonnet|haiku|dsh|codex)-S?-r<->(N/); do
    (( total++ ))
    local r=${f:t}
    if [[ -f $f/status.json ]]; then (( ended++ )); print -r -- "$r: ended $(tr -d '\n ' < $f/status.json | cut -c1-160) | audit: $(head -1 $f/audit.md 2>/dev/null || print -)"
      [[ -f $f/audit.md ]] && (( audited++ ))
    elif [[ -f $f/driver.log ]]; then print -r -- "$r: running | $(tail -1 $f/driver.log | cut -c1-160)"
    else print -r -- "$r: queued"; fi
  done
  print -r -- "runs: $total known, $ended ended, $audited audited"
  if (( total == 0 )); then next "zsh $THIS R all all   (after F's 4 notes exist)"
  elif (( ended < total )); then next "zsh $THIS W   (again in a few minutes)"
  elif (( audited < ended )); then next "zsh $THIS A all"
  else next "zsh $THIS C"; fi
}

step_A() {
  local which=${A1:-} cap=${A2:-8}
  [[ -n $which && $cap == <1-64> ]] || { print "usage: A <all|sonnet|haiku|dsh|codex|run id> [cap, default 8]"; return 2; }
  say "cheating audits (Sonnet, read only; dialog: none) in the background: $which, at most $cap at once"
  $PY -I $SD/drv552.py audits $which $cap < /dev/null > $BASE/logs/A-batch-$(date +%H%M%S).out 2>&1 &!
  print -r -- "audits started (pid $!), output $BASE/logs/A-batch-*.out -> $BASE/logs/<run>/audit.md"
  next "zsh $THIS W"
}

step_C() {
  say "copy to $DEST (read only on $BASE; dialog: none)"
  drv collect $DEST
  next "Leader: read $DEST/runs-table.md and $DEST/<agent>/<S#>-r<k>/digest.md (+ logs/, audit.md, S-final-files/)"
}

case $STEP in
  00) step_00 ;;
  F) step_F ;;
  R) step_R ;;
  W) step_W ;;
  A) step_A ;;
  C) step_C ;;
  *) print "usage: zsh $THIS <00 | F | R <agent|all> <S#|all> [runs] [cap] | W | A <agent|all|run id> [cap] | C>"; return 2 ;;
esac

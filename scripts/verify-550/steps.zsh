#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 550: does a weak agent (Haiku 5.5) do concept-clarification? Shape A (Main ~16:55): three headless `claude -p`
# roles (U = Fable 5.2 simulated user, S = Haiku 5.5 under test, A = Sonnet 5.5 cheating auditor) and a plain relay
# script (drv550.py) that copies S's and U's final texts to each other verbatim. design.md is the answer key.
#   zsh scripts/verify-550/steps.zsh <STEP>          (Main's Bash, from this Task's Worktree)
# Order: 00 -> R <S1|S2|S3|S4|all> -> W (status, read only, repeat until all ended) -> A <S#|all> -> W -> C
#   00  versions; builds BASE/project (own git, `graphtraj setup` and `claude.host configuration --write` with the
#       production graphtraj, read only; claude_isolation settings); READY-550-U/S/A from each model's stream-json init;
#       S probes (a) tasks describe concept-clarification + Read of the guide, (b) canary Read in BASE/u refused,
#       (c) S's init tool list has no WebSearch/WebFetch/Bash.
#   R   relay per scenario, in the background (one process per scenario). W shows progress.
#   A   cheating audit per scenario (auditor, read only, its final text saved as logs/<S#>/audit.md), background.
#   C   (read only on BASE) copies logs, final ws files and audit to <Worktree>/.state/realhost/<S#>/ and prints the
#       K0a order, S's tool calls with paths outside its ws, and each audit.md's first line.
# Layout: BASE=/private/tmp/cc-550 (VERIFY550_BASE overrides it, rehearsal only): project/ (S's ws in
# project/runs/<S#>/ws), u/<S#>/ (U's cwd), audit/<S#>/, logs/<S#>/ (every stream-json, argv, driver.log).
# Never written: ~/.claude, dotfiles, the Harness (except C's copy into this Worktree's .state/realhost), .venv-runtime.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice no_hup
SD=${0:A:h}; THIS=${0:A}
WT=${VERIFY550_WT:-$(git -C $SD rev-parse --show-toplevel)}
H=${VERIFY550_H:-${WT:h:h:h:h}}
BASE=${VERIFY550_BASE:-/private/tmp/cc-550}
RT=$H/.venv-runtime                                  # production: executed read only (graphtraj, graphtraj-mcp, python)
PY=${VERIFY550_PY:-$HOME/miniconda3/bin/python3.13}  # runs drv550.py (standard library only)
P=$BASE/project
STEP=${1:-}; ARG=${2:-}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
CLAUDE=${VERIFY550_CLAUDE:-$(command -v claude || print -r -- $HOME/.local/bin/claude)}   # override: rehearsal stub only
DEST=${VERIFY550_DEST:-$WT/.state/realhost}                                             # override: rehearsal only
export V550_BASE=$BASE V550_WT=$WT V550_H=$H V550_CLAUDE=$CLAUDE V550_MCP=$RT/bin/graphtraj-mcp \
  V550_TURN_S=${VERIFY550_TURN_S:-900} V550_DENYROOT=${VERIFY550_DENYROOT:-${H:h}} V550_CONTEXT=$H/CONTEXT.md

say() { print -r -- "
### $*"; }
next() { print -r -- "
==> next (paste as is): $*"; }
drv() { $PY -I $SD/drv550.py "$@"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
scen_list() { if [[ $1 == all ]]; then print S1 S2 S3 S4; elif [[ $1 == S[1-4] ]]; then print $1; else return 1; fi; }

[[ -d $H/.graphtraj || -n ${VERIFY550_H:-} ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $BASE/logs

step_00() {
  say "versions (dialog: none)"
  print -r -- "zsh $ZSH_VERSION | $(git --version) | claude: $CLAUDE -> ${CLAUDE:A} | $($CLAUDE --version 2>&1 | head -1)"
  (cd $BASE && $RT/bin/python -I -c 'import importlib.metadata as m; print("production graphtraj", m.version("graphtraj"), "| graftling", m.version("graftling"))')
  print -r -- "driver python: $($PY --version 2>&1) ($PY) | BASE $BASE"
  say "isolated project $P (own git; production graphtraj setup + claude host configuration, read only)"
  mkdir -p $P
  if [[ ! -d $P/.git ]]; then
    (cd $P && git init -q -b main && print -r -- "# 550 scratch project" > README.md && git add README.md \
      && git -c user.name=550 -c user.email=550@invalid commit -qm "Initial source") || return 1
  fi
  if [[ ! -f $P/.graphtraj/config.yml ]]; then (cd $P && print y | clean $RT/bin/graphtraj setup | tail -2) || return 1; fi
  (cd $P && clean $RT/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $CLAUDE --write >/dev/null) \
    && print "claude host configuration written: $P/.mcp.json, $P/.claude/" || { print "STOP: claude host configuration failed"; return 1; }
  $PY -I $SD/../verify-common/claude_isolation.py settings $H $P || return 1
  print -r -- "note: S runs in $P/runs/<S#>/ws, where the project's .mcp.json host refuses (it serves cwd $P only);
S therefore gets the product's stdio MCP server $RT/bin/graphtraj-mcp (server name graphtraj, tool tasks) via
--strict-mcp-config --mcp-config."
  say "READY-550-U: Fable answers one line (dialog: none)"
  drv ready U high || { print "STOP: U is not ready"; return 1; }
  say "READY-550-A: Sonnet answers one line (dialog: none; effort medium, else high, else low)"
  drv ready A medium,high,low || { print "STOP: A is not ready"; return 1; }
  say "READY-550-S + probes (a) (b) (c) with S's exact flags in $P/runs/probe/ws (dialog: none; lowest effort first)"
  drv ready S low,medium,high; local rs=$?
  say "S's exact command line, settings and MCP config (also given to the auditor)"
  local a=($BASE/logs/ready/2?-S.argv.json(N)); [[ -n ${a[-1]:-} ]] && cat ${a[-1]}
  cat $BASE/logs/ready/s-settings.json $BASE/logs/ready/s-mcp.json
  print -r -- "deny-list notes: $(<$BASE/logs/ready/s-settings-notes.txt)"
  print -r -- "efforts: U high | S $(cat $BASE/effort-S.txt 2>/dev/null || print '?') | A $(cat $BASE/effort-A.txt 2>/dev/null || print '?')"
  (( rs == 0 )) || { print "STOP: READY-550-S or a probe failed (above). Main reports it to the Leader."; return 1; }
  next "zsh $THIS R all"
}

step_R() {
  local list; list=($(scen_list $ARG)) || { print "usage: R <S1|S2|S3|S4|all>"; return 2; }
  [[ -f $BASE/effort-S.txt ]] || { print "STOP: run 00 first (no S effort recorded)"; return 1; }
  say "relay runs in the background (dialog: none): ${list}"
  local s
  for s in $list; do
    # not nohup: without a console macOS nohup stops with 'can't detach from console' and never runs the driver
    $PY -I $SD/drv550.py run $s < /dev/null > $BASE/logs/R-$s.out 2>&1 &!
    print -r -- "$s started (pid $!), output $BASE/logs/R-$s.out, driver log $BASE/logs/$s/driver.log"
  done
  print -r -- "watch: tail -f $BASE/logs/R-*.out   (a scenario has ended when its line 'END {...}' appears)"
  next "zsh $THIS W"
}

step_W() {
  say "status (read only)"
  local s
  for s in S1 S2 S3 S4; do
    local st=$BASE/logs/$s/status.json a=$BASE/logs/$s/audit.md
    if [[ -f $st ]]; then print -r -- "$s run: ended $(tr -d '\n ' < $st)"
    elif [[ -f $BASE/logs/$s/driver.log ]]; then print -r -- "$s run: running | $(tail -1 $BASE/logs/$s/driver.log)"
    else print -r -- "$s run: not started"; fi
    if [[ -f $a ]]; then print -r -- "$s audit: $(head -1 $a)"
    elif [[ -f $BASE/logs/A-$s.out ]]; then print -r -- "$s audit: running | $(tail -1 $BASE/logs/A-$s.out)"; fi
  done
  if [[ -n $(print $BASE/logs/S?/audit.md(N)) ]]; then next "zsh $THIS C"
  elif [[ -n $(print $BASE/logs/S?/status.json(N)) ]]; then next "zsh $THIS A all   (once every started scenario has ended; else W again)"
  else next "zsh $THIS W   (again, after a few minutes)"; fi
}

step_A() {
  local list; list=($(scen_list $ARG)) || { print "usage: A <S1|S2|S3|S4|all>"; return 2; }
  say "cheating audit (Sonnet, read only; dialog: none) in the background: ${list}"
  local s
  for s in $list; do
    [[ -f $BASE/logs/$s/status.json ]] || { print "$s: no finished run, skipped"; continue; }
    $PY -I $SD/drv550.py audit $s < /dev/null > $BASE/logs/A-$s.out 2>&1 &!
    print -r -- "$s audit started (pid $!), output $BASE/logs/A-$s.out -> $BASE/logs/$s/audit.md"
  done
  next "zsh $THIS W"
}

step_C() {
  local dest=$DEST
  say "copy to $dest (read only on $BASE; dialog: none)"
  mkdir -p $dest
  local s
  for s in S1 S2 S3 S4; do drv collect $s $dest; done
  print -r -- "
copied: $(ls -d $dest/S?(N) | tr '\n' ' ')"
  next "Leader: read $dest/<S#>/ (logs/NN-S.jsonl, NN-U.jsonl, u-sources.txt, audit.md, S-final-files/) and judge"
}

case $STEP in
  00) step_00 ;;
  R) step_R ;;
  W) step_W ;;
  A) step_A ;;
  C) step_C ;;
  *) print "usage: zsh $THIS <00|R <S#|all>|W|A <S#|all>|C>"; return 2 ;;
esac

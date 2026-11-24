#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 597 Main-run steps: graftling's install command lets uv use its own managed Python
# (`uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git@<tag-or-commit>"`), so the tool
# environment is not based on Conda's or the system Python. Real host, from GitHub v0.9.0, in an isolated uv directory.
# Run one step at a time:  zsh <this file> <STEP>
#   00   Main. Read only, plus one claude -p call in a fresh empty directory under ${TMPDIR:-/tmp}. Prints: which uv and
#        its version, and that its `uv tool install --help` lists --managed-python; claude path/version; conda path;
#        that $UVT is absent (STOP with the exact command if not); the graftling 597 branch HEAD in <Harness>/graftling
#        (STOP with the fetch command from the committed bundle if it is missing) and that the install line of that
#        HEAD's README, with @v0.9.0, equals the command C5 runs; ~/.config/uv/uv.toml presence (names only).
#        Dialog: none. LOGIN: the claude -p probe uses the USER's Claude login (Main asks the USER first).
#        Observable: every CHECK line PASS and "claude answered: READY-597 ...".
#   C5   Main. In $UVT only (UV_TOOL_DIR, UV_TOOL_BIN_DIR, UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR under it) runs the new
#        README command for GitHub v0.9.0; snapshots the USER directories and conda first (593's homesnap593.py);
#        CHECK PASS only when the tool environment's base interpreter (sys._base_executable and the realpath of
#        bin/python) is under $UVT/python (uv-managed); FAIL when under conda, the system or elsewhere. Then
#        configuration --write for $UVT/project (writes only that project). Dialog: none. No login. Network:
#        github.com, PyPI, uv's Python download. ~2-3 min.
#   C5u  USER, once, in a normal Terminal: `cd $UVT/project && claude`; one dialog 'Do you trust the files in this
#        folder?' -> 'Yes, proceed'; then /exit. No message is sent.
#   C5r  Main, after C5 and C5u. The USER's conda base is only activated (shell hook + conda activate; no
#        install/create/config). Real `claude -p` in $UVT/project creates a child through mcp__graftling__subagents
#        and waits for it to end; ps sampling shows graftling on $UVT's Python; the base interpreter, read inside the
#        activated shell, is again under $UVT/python; USER directories and conda unchanged. Dialog: none.
#        LOGIN: the USER's Claude login (Main asks the USER first). ~3 min.
# Order: 00, C5, C5u (USER), C5r. Nothing is pushed or published; ~/.local, the USER's uv tool directory, dotfiles and
# conda are never written.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer): ADOPT597_UVT, ADOPT597_OUT, ADOPT597_GREPO, ADOPT597_NOSNAP=1 (no USER-directory snapshots: a sandbox cannot
# read $HOME), ADOPT597_NOCLAUDE=1 (00 skips claude; C5 skips configuration --write), ADOPT597_CLEAN_EXTRA (extra
# VAR=value words for clean(): the sandbox's proxy variables; Main leaves it unset).
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
S593=$WT/scripts/adopt-593                          # reused: homesnap593.py, adopt_tree.py
STEP=${1:-}
TASKDIR=597-graftling-install-uv-managed-python
GREPO=${ADOPT597_GREPO:-$H/graftling}               # read only
GBRANCH=agent/597-graftling-install-uv-managed-python
GBUNDLE=$SD/graftling-597.bundle
GTAG=v0.9.0
GVERSION=0.9.0
GURL="git+https://github.com/LUOXIAO92/graftling.git@$GTAG"
INSTALL=(uv tool install --managed-python $GURL)   # the README's command with <tag-or-commit> = v0.9.0
# Rehearsal only: ADOPT597_SOURCE replaces the GitHub source in C5 (a sandbox whose proxy refuses git); Main leaves it unset.
[[ -n ${ADOPT597_SOURCE:-} ]] && INSTALL=(uv tool install --managed-python $ADOPT597_SOURCE)
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only; runs the helper scripts with -I
CONDABIN=/Users/luoxiao/miniconda3/bin/conda        # activated only, never changed
CROOT=${CONDABIN:h:h}
UVT=${ADOPT597_UVT:-/private/tmp/uvtool-597}
R=${ADOPT597_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost/main-raw}
MODEL=claude-opus-5-5                               # as 593 C5r
UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
NOSNAP=${ADOPT597_NOSNAP:-}
NOCLAUDE=${ADOPT597_NOCLAUDE:-}

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT597_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
uv_bin() { clean /usr/bin/which uv 2>/dev/null; }
U=${ADOPT597_UV:-$(uv_bin)}   # the uv on the clean PATH; every uv call below uses this one file
[[ -n $U ]] || { print "STOP: no uv on PATH (${(j.:.)path})"; exit 1; }
snap() {  # $1 = output json
  [[ -n $NOSNAP ]] && { print "snap: skipped (ADOPT597_NOSNAP, rehearsal only)"; return 0; }
  $CONDA -I $S593/homesnap593.py snap $1 local=$HOME/.local uvtools=$(clean $U tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) \
    pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=$CROOT
}
# The child really ended with the token: a wait result whose "outcome":"completed" is followed by "last_message":"<token>",
# plain or backslash-escaped JSON (tool_result text). The token alone also sits in the create input and the ui_log lines.
child_ok() {  # $1 = token, $2 = stream-json file
  grep -qE '\\?"outcome\\?": ?\\?"completed\\?", ?\\?"last_message\\?": ?\\?"'"$1"'\\?"' $2
}
# The tool environment and its base interpreter. $1 = tool bin/python, $2 = label. CHECK PASS only when uv-managed.
interp() {
  local py=$1 label=$2 out prefix base version real class
  out=$($py -I -c 'import sys, os, graftling; print(sys.prefix); print(getattr(sys, "_base_executable", "") or sys.base_prefix); print(graftling.__version__)' 2>&1) \
    || { print -r -- "CHECK 597 $label tool environment base interpreter is uv-managed (under $UVT/python): FAIL ($py: ${out[1,200]})"; return 1; }
  prefix=${${(f)out}[1]} base=${${(f)out}[2]} version=${${(f)out}[3]} real=${py:A}
  print -r -- "uv tool python: $py -> $real | sys.prefix: $prefix | sys._base_executable: $base -> ${base:A} | graftling $version"
  [[ ${prefix:A} == ${UVT:A}/tools/graftling && $version == $GVERSION ]] \
    && print -r -- "CHECK 597 $label install in $UVT/tools/graftling, graftling $GVERSION: PASS" \
    || { print -r -- "CHECK 597 $label install in $UVT/tools/graftling, graftling $GVERSION: FAIL"; return 1; }
  class=other
  case ${base:A}/ in ${CROOT:A}/*) class=conda ;; /usr/*|/System/*|/Library/*|/opt/homebrew/*) class=system ;; esac
  [[ ${base:A}/ == ${UVT:A}/python/* && ${real}/ == ${UVT:A}/python/* ]] && class=uv-managed
  print -r -- "REPORT 597 $label base interpreter: $base ($class)"
  [[ $class == uv-managed ]] && print -r -- "CHECK 597 $label tool environment base interpreter is uv-managed (under $UVT/python): PASS" \
    || { print -r -- "CHECK 597 $label tool environment base interpreter is uv-managed (under $UVT/python): FAIL ($class)"; return 1; }
}

mkdir -p $R || exit 1
cred_guard
case $STEP in
00) print "[00] Main. Read only, plus one claude -p probe (USER's Claude login: Main asks the USER first). Dialog: none."
  { print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"
    clean $U tool install --help 2>&1 | grep -q -- '--managed-python' \
      && print -r -- "CHECK 597 00 this uv's 'uv tool install --help' lists --managed-python: PASS ($(clean $U tool install --help 2>&1 | grep -- '--managed-python ' | head -1 | sed 's/^ *//'))" \
      || print -r -- "CHECK 597 00 this uv's 'uv tool install --help' lists --managed-python: FAIL"
    print -r -- "uv user config: $(for f in $HOME/.config/uv/uv.toml /etc/uv/uv.toml; do [[ -e $f ]] && print -n "$f present; " || print -n "$f absent; "; done)"
    C=$(claude_bin); print -r -- "claude: $C -> ${C:A} | $(clean $C --version 2>&1 | head -1)"
    print -r -- "conda: $CONDABIN -> ${CONDABIN:A} | $(clean $CONDABIN --version 2>&1 | tail -1)"
    [[ -e $UVT ]] && print -r -- "CHECK 597 00 $UVT absent: FAIL (move it aside first: mv $UVT $UVT.old-\$(date +%s))" \
      || print -r -- "CHECK 597 00 $UVT absent: PASS"
    GH=$(git -C $GREPO rev-parse --verify -q $GBRANCH)
    if [[ -z $GH ]]; then print -r -- "CHECK 597 00 graftling branch $GBRANCH in $GREPO: FAIL (absent; fetch it: git -C $GREPO fetch $GBUNDLE $GBRANCH:$GBRANCH)"
    else
      print -r -- "graftling $GBRANCH HEAD: $GH ($(git -C $GREPO log -1 --format=%s $GH))"
      line=$(git -C $GREPO show $GH:README.md | grep -m1 '^uv tool install ')
      want="uv tool install --managed-python \"git+https://github.com/LUOXIAO92/graftling.git@<tag-or-commit>\""
      run="${INSTALL[1,4]} \"$GURL\""
      print -r -- "README install line: $line"
      print -r -- "C5 runs:             $run"
      [[ $line == $want && ${line/<tag-or-commit>/$GTAG} == $run ]] && print -r -- "CHECK 597 00 README install line with @$GTAG equals C5's command: PASS" \
        || print -r -- "CHECK 597 00 README install line with @$GTAG equals C5's command: FAIL"
    fi
    if [[ -n $NOCLAUDE ]]; then print "claude probe: skipped (ADOPT597_NOCLAUDE, rehearsal only)"
    else
      P=$(mktemp -d ${TMPDIR:-/tmp}/probe-597.XXXXXX)
      ans=$(cd $P && print -r -- "Reply with one line: READY-597 followed by your model id." | clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL 2>&1 | head -3)
      print -r -- "claude answered: $ans"
    fi
  } 2>&1 | tee $R/00.txt
  grep -q 'FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above)."; exit 1; }
  summary 00 "$(grep -E '^(uv|CHECK|claude|conda|graftling|README|C5 runs)' $R/00.txt)"
  print "Success: every CHECK PASS; 'claude answered: READY-597 <model>'."
  next "zsh $THIS C5" ;;

C5) print "[C5] Main. Install from GitHub $GTAG with the new README command in $UVT only (uv's tool, bin, cache and Python directories under it); the USER's ~/.local and uv tool directory are not touched. Dialog: none. No login. Network: github.com, PyPI, uv Python download. ~2-3 min."
  { [[ -e $UVT/tools ]] && { print "STOP: $UVT/tools exists (an earlier C5). Move it aside: mv $UVT $UVT.old-\$(date +%s)"; exit 1; }
    mkdir -p $UVT/project || exit 1
    say "before: USER directories and conda (read only)"
    snap $R/C5-home-before.json || exit 1
    say "the README command, uv directories isolated under $UVT"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1) | environment: ${UVENV[*]}"
    print -r -- "command: ${INSTALL[*]}   (uv = $U)"
    (cd $UVT && clean env $UVENV $U ${INSTALL[2,-1]}) > $R/C5-uv.txt 2>&1; urc=$?
    tail -5 $R/C5-uv.txt
    print "uv tool install rc=$urc (full output: $R/C5-uv.txt)"; (( urc == 0 )) || exit 1
    print -r -- "uv-managed Pythons in $UVT/python: $(print -l $UVT/python/*(N/:t) | tr '\n' ' ')"
    print -r -- "uv python list (managed only, isolated): $(cd $UVT && clean env $UVENV $U python list --only-installed --managed-python 2>&1 | tr '\n' ';' | cut -c1-300)"
    print -r -- "subagents-mcp shebang: $(head -1 $UVT/bin/subagents-mcp)"
    interp $UVT/tools/graftling/bin/python C5 || exit 1
    if [[ -n $NOCLAUDE ]]; then print "configuration --write: skipped (ADOPT597_NOCLAUDE, rehearsal only)"
    else
      say "Claude Code project $UVT/project: configuration --write from the uv installation (writes only that project)"
      [[ -d $UVT/project/.git ]] || git -C $UVT/project init -q --initial-branch=main
      (cd $UVT/project && clean $UVT/tools/graftling/bin/python -m graftling.claude.host configuration --project $UVT/project --claude $(claude_bin) --write) 2>&1 | tail -8 || exit 1
      print -r -- ".mcp.json graftling command: $($CONDA -I -c 'import json,sys; s=json.load(open(sys.argv[1]))["mcpServers"]["graftling"]; print(s.get("command"), *(s.get("args") or []))' $UVT/project/.mcp.json 2>&1)"
    fi
  } 2>&1 | tee $R/C5.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nC5 STOP (see above). Hand $R/C5.txt to Main."; exit 1; }
  summary C5 "$(grep -E '^(uv|command|uv tool install|uv-managed|uv python|CHECK|REPORT|\.mcp\.json|snap)' $R/C5.txt)"
  print "Success: 'uv tool install rc=0'; both 'CHECK 597 C5 ...: PASS' (base interpreter under $UVT/python, class uv-managed); .mcp.json's graftling command is $UVT/tools/graftling/bin/python."
  next "USER (once): zsh $THIS C5u    (then Main: zsh $THIS C5r)" ;;

C5u) print "[C5u] USER, once (Claude Code loads project plugins only in a trusted folder; Main cannot answer this)."
  print "In a normal Terminal run:\n  cd $UVT/project && claude"
  print "Dialog (one): 'Do you trust the files in this folder?' ($UVT/project) -> 'Yes, proceed'. If it also asks about the project MCP server 'graftling' or its plugin/hooks, approve for this project. Then type /exit and Enter; send no message. Any other dialog: Esc and tell Main its title."
  next "Main: zsh $THIS C5r" ;;

C5r) print "[C5r] Main, after C5 and C5u. The USER's conda base only activated (shell hook + conda activate; no install/create/config); real claude -p (USER's Claude login, agreed beforehand; no provider credentials) in $UVT/project creates a child through mcp__graftling__subagents and waits for it to end. Dialog: none. ~3 min."
  { [[ -x $UVT/tools/graftling/bin/python ]] || { print "STOP: no uv installation under $UVT: run C5 first"; exit 1; }
    [[ -e $R/C5-home-before.json || -n $NOSNAP ]] || { print "STOP: $R/C5-home-before.json missing: run C5 first"; exit 1; }
    : > $R/C5r-ps.txt; rm -f $R/C5r.done
    ( for i in {1..150}; do ps -axww -o pid=,ppid=,command= 2>/dev/null | grep -E 'graftling|subagents' | grep -vE 'grep -E|C5r' >> $R/C5r-ps.txt; [[ -e $R/C5r.done ]] && break; sleep 2; done ) &!
    print -r -- "Reply with exactly the agent id after these calls. Using only mcp__graftling__subagents: execute create with arguments {\"runtime\":\"claude\",\"name\":\"c597\",\"instruction\":\"Reply with exactly: C597-CHILD-OK\"}; then execute wait with {\"agent\": <the agent id>, \"timeout_seconds\": 300}, repeating until the execution has ended; print the final last_message; then retire the child. Print one line DONE and stop." > $R/C5r-prompt.txt
    clean CONDABIN=$CONDABIN UVT=$UVT MODEL=$MODEL CLAUDE=$(claude_bin) C5PFILE=$R/C5r-prompt.txt OUT=$R/C5r-stream.jsonl /bin/zsh -f -c '
        eval "$($CONDABIN shell.zsh hook 2>/dev/null)" && conda activate base || { print "STOP: conda activate base failed"; exit 1; }
        print -r -- "conda active: CONDA_PREFIX=$CONDA_PREFIX | python on PATH: $(command -v python) | python3: $(command -v python3)"
        print -r -- "C5R-BASE $($UVT/tools/graftling/bin/python -I -c "import sys; print(getattr(sys, \"_base_executable\", \"\") or sys.base_prefix)")"
        print -r -- "subagents CLI: $($UVT/bin/subagents --help 2>&1 | head -1)"
        cd $UVT/project && /usr/bin/perl -e "alarm shift; exec @ARGV" 600 $CLAUDE -p --model $MODEL --output-format stream-json --verbose \
          --allowedTools mcp__graftling__subagents < $C5PFILE > $OUT 2> $OUT.err
        print "claude -p rc=$? (142 = 600 s timeout)"'
    touch $R/C5r.done; sleep 3
    $CONDA -I $S593/adopt_tree.py stream $R/C5r-stream.jsonl mcp__graftling__subagents
    child_ok C597-CHILD-OK $R/C5r-stream.jsonl && print "CHECK 597 C5r the child created through mcp__graftling__subagents ended (wait result outcome completed) with last_message C597-CHILD-OK: PASS" \
      || print "CHECK 597 C5r the child created through mcp__graftling__subagents ended (wait result outcome completed) with last_message C597-CHILD-OK: FAIL"
  } 2>&1 | tee $R/C5r.txt; rc=${pipestatus[1]}
  (( rc == 0 )) || { print "\nC5r STOP (see above). Nothing installed; conda unchanged. Hand $R/C5r.txt to Main."; exit 1; }
  { base=$(sed -n 's/^C5R-BASE //p' $R/C5r.txt)
    print -r -- "REPORT 597 C5r base interpreter with conda base active: $base -> ${base:A}"
    [[ -n $base && ${base:A}/ == ${UVT:A}/python/* ]] && print "CHECK 597 C5r base interpreter (conda active) under $UVT/python: PASS" \
      || print "CHECK 597 C5r base interpreter (conda active) under $UVT/python: FAIL"
    say "graftling processes seen while it ran"
    sort -u $R/C5r-ps.txt | cut -c1-220 | head -12
    srv=$(sort -u $R/C5r-ps.txt | grep -c -- "${UVT:A}/tools/graftling/bin/python\|$UVT/tools/graftling/bin/python"); onconda=$(sort -u $R/C5r-ps.txt | grep -c -- "$CROOT/")
    (( srv > 0 && onconda == 0 )) && print "CHECK 597 C5r graftling ran as $UVT's bin/python ($srv process lines), none naming the conda root: PASS" \
      || print "CHECK 597 C5r graftling ran as $UVT's bin/python ($srv process lines), none naming the conda root: FAIL ($onconda lines under $CROOT)"
    if [[ -n $NOSNAP ]]; then print "snap compare: skipped (ADOPT597_NOSNAP, rehearsal only)"
    else
      snap $R/C5-home-after.json > /dev/null
      $CONDA -I $S593/homesnap593.py compare $R/C5-home-before.json $R/C5-home-after.json && print "CHECK 597 C5r nothing installed into conda and USER directories unchanged: PASS" \
        || print "CHECK 597 C5r nothing installed into conda and USER directories unchanged: FAIL (see REPORT lines)"
    fi
  } 2>&1 | tee -a $R/C5r.txt
  rc=0; grep -q '^CHECK 597 .*: FAIL' $R/C5r.txt && rc=1
  summary C5r "$(grep -E '^(conda active|subagents CLI|claude -p rc|PASS|FAIL|CHECK|REPORT)' $R/C5r.txt)"
  print "Success: 'conda active: ...' (python under conda); 'subagents CLI: ...' usage line; every 'CHECK 597 C5r ...: PASS' (child replied; base interpreter under $UVT/python with conda active; graftling processes on $UVT's Python; conda and USER directories unchanged)."
  next "Main: hand $R/C5.txt and $R/C5r.txt to the Team; done"; exit $rc ;;

_childok) child_ok ${2:?token} ${3:?stream} && print "child_ok $2 ${3:t}: MATCH" || { print "child_ok $2 ${3:t}: NO MATCH"; exit 1; } ;;   # rehearsal only

*) print "usage: zsh $THIS 00|C5|C5u|C5r"; exit 2 ;;
esac

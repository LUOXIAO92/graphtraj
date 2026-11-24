#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 605 Main-run steps: graftling's README installs without a tag,
#   uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git"
# which is the default branch main, i.e. the latest release; @<tag> stays an optional pin. No claude call, no login.
# Run one step at a time:  zsh <this file> <STEP>
#   00   Main. Read only. Prints: which uv and its version, and that its `uv tool install --help` lists
#        --managed-python; that $UVT and $UPD are absent (STOP with the exact command if not); the graftling 605
#        branch HEAD in <Harness>/graftling (STOP with the fetch command from the committed bundle if it is missing)
#        and that the first `uv tool install` line of that HEAD's README equals exactly the command I runs; the
#        value of `git ls-remote https://github.com/LUOXIAO92/graftling.git refs/heads/main`.
#        Dialog: none. No login. No claude call. Network: github.com (ls-remote only).
#        Observable: every CHECK line PASS and "REPORT 605 00 GitHub main: <sha>".
#   I    Main. Snapshots the USER directories and conda (593's homesnap593.py); runs the README's tagless command
#        from GitHub with uv's tool, bin, cache and Python directories under $UVT only. CHECK lines: graftling
#        0.9.1 in $UVT/tools/graftling; installed commit (direct_url.json commit_id) equals GitHub main from
#        ls-remote; the tool environment's base interpreter under $UVT/python (uv-managed); `$UVT/bin/subagents
#        --help` rc 0 (first line printed); USER directories and conda unchanged.
#        Dialog: none. No login. No claude call. Network: github.com, PyPI, uv's Python download. ~1-2 min.
#   U    Main. The upgrade experiment, all under $UPD: a local git repository cloned from <Harness>/graftling
#        whose default branch main is graftling's main (tag $PIN included) is the source. Installs it
#        without a ref (as the README) into $UPD/default and pinned @$PIN into $UPD/pinned, adds a commit on main
#        (version -> <version>.post605), then runs `uv tool upgrade graftling` on both and reports whether the
#        installed commit and version moved; if the tagless one did not, also `uv tool upgrade --reinstall
#        graftling` and `uv tool install --managed-python --reinstall "<source>"`. Prints a RESULT line.
#        Dialog: none. No login. No claude call. Network: PyPI, uv's Python download. ~1-2 min.
#   D    Main, after I. A DSH child's provider, home and key, from the installed graftling ($UVT) and the installed
#        DSH: dshprobe605.py runs graftling's own DSH selection, settings check and launch preparation (no DSH
#        service, no model request) with HOME=$DSD/home, a fake user home whose .dsh holds a dummy
#        .credentials.yaml. Every key is a dummy value set inside the probe. CHECK lines: another provider ->
#        invalid-config; without home DSH_HOME is a generated directory holding only profiles/web/{package.json,
#        cordis.patch.yml}; key names in the child environment with and without api_key_env; home -> DSH_HOME;
#        base_url -> llm-deepseek baseURL; an inherited DEEPSEEK_BASE_URL removed. The USER's ~/.dsh is never read
#        or written: only a digest of its names and mtimes, before and after.
#        Dialog: none. No login. No credential (no DEEPSEEK_API_KEY needed). No network. ~10 s.
#        Not walked by D: a real DSH child's model turn (it would need DEEPSEEK_API_KEY).
# Order: 00, I, U, D. Nothing is pushed or published; ~/.local, the USER's uv tool directory, dotfiles and conda are
# never written.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer): ADOPT605_UVT, ADOPT605_UPD, ADOPT605_DSD, ADOPT605_OUT, ADOPT605_GREPO, ADOPT605_NOSNAP=1 (no
# USER-directory snapshots: a sandbox cannot read $HOME), ADOPT605_SOURCE (replaces the GitHub source in I) with
# ADOPT605_LSURL (the repository I compares the installed commit with), ADOPT605_CLEAN_EXTRA (extra VAR=value words
# for clean(): the sandbox's proxy variables). Main leaves them all unset.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
S593=$WT/scripts/adopt-593                          # reused: homesnap593.py
STEP=${1:-}
TASKDIR=605-graftling-readme-install-without-tag
GREPO=${ADOPT605_GREPO:-$H/graftling}               # read only
GBRANCH=agent/605-graftling-readme-install-without-tag
GBUNDLE=$SD/graftling-605.bundle
GVERSION=0.9.1                                      # GitHub main = v0.9.1 on 2026-11-24
PIN=v0.9.1
GURL="git+https://github.com/LUOXIAO92/graftling.git"
LSURL=${ADOPT605_LSURL:-https://github.com/LUOXIAO92/graftling.git}
INSTALL=(uv tool install --managed-python $GURL)    # the README's default command, exactly
README_LINE="uv tool install --managed-python \"$GURL\""
SRC_I=${ADOPT605_SOURCE:-$GURL}                     # rehearsal only: a local git+file:// source
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only; runs the snapshot helper with -I
CONDABIN=/Users/luoxiao/miniconda3/bin/conda
CROOT=${CONDABIN:h:h}
UVT=${ADOPT605_UVT:-/private/tmp/uvtool-605}
UPD=${ADOPT605_UPD:-/private/tmp/uvup-605}
DSD=${ADOPT605_DSD:-/private/tmp/dsh-605}
R=${ADOPT605_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost/main-raw}
UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
NOSNAP=${ADOPT605_NOSNAP:-}

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT605_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
uv_bin() { clean /usr/bin/which uv 2>/dev/null; }
U=${ADOPT605_UV:-$(uv_bin)}   # the uv on the clean PATH; every uv call below uses this one file
[[ -n $U ]] || { print "STOP: no uv on PATH (${(j.:.)path})"; exit 1; }
snap() {  # $1 = output json
  [[ -n $NOSNAP ]] && { print "snap: skipped (ADOPT605_NOSNAP, rehearsal only)"; return 0; }
  $CONDA -I $S593/homesnap593.py snap $1 local=$HOME/.local uvtools=$(clean $U tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) \
    pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=$CROOT
}
# What a tool directory holds: "<commit_id> <graftling version> <requested_revision or ->" from the installed
# dist-info's direct_url.json, read by that installation's own Python. $1 = tool directory (holding graftling/).
installed() {
  local t=$1/graftling du
  du=($t/lib/python*/site-packages/graftling-*.dist-info/direct_url.json(N))
  (( $#du )) || { print -r -- "none none none"; return 1; }
  clean $t/bin/python -I -c 'import json, sys, graftling
d = json.load(open(sys.argv[1])); v = d.get("vcs_info", {})
print(v.get("commit_id", "none"), graftling.__version__, v.get("requested_revision", "-"))' $du[1]
}
receipt() { grep -E '^(requirements|python) ' $1/graftling/uv-receipt.toml 2>/dev/null | tr '\n' ' '; }
# The tool environment's base interpreter. $1 = tool bin/python, $2 = label. CHECK PASS only when uv-managed (597).
interp() {
  local py=$1 label=$2 out prefix base version real class
  out=$(clean $py -I -c 'import sys, os, graftling; print(sys.prefix); print(getattr(sys, "_base_executable", "") or sys.base_prefix); print(graftling.__version__)' 2>&1) \
    || { print -r -- "CHECK 605 $label tool environment base interpreter is uv-managed (under $UVT/python): FAIL ($py: ${out[1,200]})"; return 1; }
  prefix=${${(f)out}[1]} base=${${(f)out}[2]} version=${${(f)out}[3]} real=${py:A}
  print -r -- "uv tool python: $py -> $real | sys.prefix: $prefix | sys._base_executable: $base -> ${base:A} | graftling $version"
  [[ ${prefix:A} == ${UVT:A}/tools/graftling && $version == $GVERSION ]] \
    && print -r -- "CHECK 605 $label install in $UVT/tools/graftling, graftling $GVERSION: PASS" \
    || { print -r -- "CHECK 605 $label install in $UVT/tools/graftling, graftling $GVERSION: FAIL (graftling $version)"; return 1; }
  class=other
  case ${base:A}/ in ${CROOT:A}/*) class=conda ;; /usr/*|/System/*|/Library/*|/opt/homebrew/*) class=system ;; esac
  [[ ${base:A}/ == ${UVT:A}/python/* && ${real}/ == ${UVT:A}/python/* ]] && class=uv-managed
  print -r -- "REPORT 605 $label base interpreter: $base ($class)"
  [[ $class == uv-managed ]] && print -r -- "CHECK 605 $label tool environment base interpreter is uv-managed (under $UVT/python): PASS" \
    || { print -r -- "CHECK 605 $label tool environment base interpreter is uv-managed (under $UVT/python): FAIL ($class)"; return 1; }
}

mkdir -p $R || exit 1
cred_guard
case $STEP in
00) print "[00] Main. Read only (ls-remote to github.com). Dialog: none. No login. No claude call."
  { print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"
    clean $U tool install --help 2>&1 | grep -q -- '--managed-python' \
      && print -r -- "CHECK 605 00 this uv's 'uv tool install --help' lists --managed-python: PASS" \
      || print -r -- "CHECK 605 00 this uv's 'uv tool install --help' lists --managed-python: FAIL"
    print -r -- "uv user config: $(for f in $HOME/.config/uv/uv.toml /etc/uv/uv.toml; do [[ -e $f ]] && print -n "$f present; " || print -n "$f absent; "; done)"
    for d in $UVT $UPD; do
      [[ -e $d ]] && print -r -- "CHECK 605 00 $d absent: FAIL (move it aside first: mv $d $d.old-\$(date +%s))" \
        || print -r -- "CHECK 605 00 $d absent: PASS"
    done
    GH=$(git -C $GREPO rev-parse --verify -q $GBRANCH)
    if [[ -z $GH ]]; then print -r -- "CHECK 605 00 graftling branch $GBRANCH in $GREPO: FAIL (absent; fetch it: git -C $GREPO fetch $GBUNDLE $GBRANCH:$GBRANCH)"
    else
      print -r -- "graftling $GBRANCH HEAD: $GH ($(git -C $GREPO log -1 --format=%s $GH))"
      line=$(git -C $GREPO show $GH:README.md | grep -m1 '^uv tool install ')
      print -r -- "README install line: $line"
      print -r -- "I runs:              ${INSTALL[1,4]} \"$GURL\""
      [[ $line == $README_LINE && $line == "${INSTALL[1,4]} \"$GURL\"" ]] \
        && print -r -- "CHECK 605 00 README's first install line equals I's command exactly: PASS" \
        || print -r -- "CHECK 605 00 README's first install line equals I's command exactly: FAIL"
    fi
    main=$(clean git ls-remote $LSURL refs/heads/main 2>&1 | cut -f1)
    print -r -- "REPORT 605 00 GitHub main: $main ($LSURL refs/heads/main)"
    [[ $main =~ '^[0-9a-f]{40}$' ]] && print -r -- "CHECK 605 00 ls-remote returned main's commit: PASS" \
      || print -r -- "CHECK 605 00 ls-remote returned main's commit: FAIL"
  } 2>&1 | tee $R/00.txt
  grep -q 'FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above)."; exit 1; }
  summary 00 "$(grep -E '^(uv|CHECK|REPORT|graftling|README|I runs)' $R/00.txt)"
  print "Success: every CHECK PASS; 'REPORT 605 00 GitHub main: <sha>'."
  next "zsh $THIS I" ;;

I) print "[I] Main. The README's tagless command from GitHub in $UVT only (uv's tool, bin, cache and Python directories under it); the USER's ~/.local and uv tool directory are not touched. Dialog: none. No login. Network: github.com, PyPI, uv Python download. ~1-2 min."
  { [[ -e $UVT/tools ]] && { print "STOP: $UVT/tools exists (an earlier I). Move it aside: mv $UVT $UVT.old-\$(date +%s)"; exit 1; }
    mkdir -p $UVT || exit 1
    say "before: USER directories and conda (read only)"
    snap $R/I-home-before.json || exit 1
    main=$(clean git ls-remote $LSURL refs/heads/main 2>&1 | cut -f1)
    print -r -- "REPORT 605 I main before install: $main ($LSURL refs/heads/main)"
    say "the README command, uv directories isolated under $UVT"
    cmd=(${INSTALL[1,4]} $SRC_I)   # uv tool install --managed-python <source>
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1) | environment: ${UVENV[*]}"
    print -r -- "command: ${cmd[1,4]} \"$SRC_I\"   (uv = $U)"
    (cd $UVT && clean env $UVENV $U ${cmd[2,-1]}) > $R/I-uv.txt 2>&1; urc=$?
    cat $R/I-uv.txt
    print "uv tool install rc=$urc (full output: $R/I-uv.txt)"; (( urc == 0 )) || exit 1
    print -r -- "uv-managed Pythons in $UVT/python: $(print -l $UVT/python/*(N/:t) | tr '\n' ' ')"
    print -r -- "uv-receipt.toml: $(receipt $UVT/tools)"
    interp $UVT/tools/graftling/bin/python I || exit 1
    got=($(installed $UVT/tools))
    print -r -- "REPORT 605 I installed: commit ${got[1]} | graftling ${got[2]} | requested_revision ${got[3]}"
    [[ ${got[1]} == $main ]] && print -r -- "CHECK 605 I installed commit equals main ($main): PASS" \
      || print -r -- "CHECK 605 I installed commit equals main ($main): FAIL (${got[1]})"
    help=$(clean $UVT/bin/subagents --help 2>&1); hrc=$?
    print -r -- "subagents --help first line: ${${(f)help}[1]:-}"
    (( hrc == 0 )) && print -r -- "CHECK 605 I $UVT/bin/subagents --help rc 0: PASS" \
      || print -r -- "CHECK 605 I $UVT/bin/subagents --help rc 0: FAIL (rc $hrc)"
    if [[ -n $NOSNAP ]]; then print "snap compare: skipped (ADOPT605_NOSNAP, rehearsal only)"
    else
      snap $R/I-home-after.json > /dev/null
      $CONDA -I $S593/homesnap593.py compare $R/I-home-before.json $R/I-home-after.json \
        && print "CHECK 605 I nothing installed into conda and USER directories unchanged: PASS" \
        || print "CHECK 605 I nothing installed into conda and USER directories unchanged: FAIL (see REPORT lines)"
    fi
  } 2>&1 | tee $R/I.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q '^CHECK 605 .*: FAIL' $R/I.txt || { print "\nI STOP (see above). Hand $R/I.txt to the Team."; exit 1; }
  summary I "$(grep -E '^(uv|command|uv tool install|uv-managed|uv-receipt|CHECK|REPORT|subagents|snap)' $R/I.txt)"
  print "Success: 'uv tool install rc=0'; every 'CHECK 605 I ...: PASS' (graftling $GVERSION, commit = GitHub main, base interpreter under $UVT/python, subagents --help rc 0, USER directories unchanged)."
  next "zsh $THIS U" ;;

U) print "[U] Main. Does 'uv tool upgrade graftling' follow new commits of the default branch after a tagless install? All under $UPD (a local file:// source; uv's tool, bin, cache and Python directories). Dialog: none. No login. Network: PyPI, uv Python download. ~1-2 min."
  { [[ -e $UPD ]] && { print "STOP: $UPD exists (an earlier U). Move it aside: mv $UPD $UPD.old-\$(date +%s)"; exit 1; }
    mkdir -p $UPD || exit 1
    REPO=$UPD/repo SRC="git+file://$UPD/repo"
    UC=(UV_CACHE_DIR=$UPD/cache UV_PYTHON_INSTALL_DIR=$UPD/python)
    uvrun() {  # $1 = default|pinned, then uv's arguments; prints the command, its output and rc
      local which=$1; shift
      local -a e=(UV_TOOL_DIR=$UPD/$which/tools UV_TOOL_BIN_DIR=$UPD/$which/bin $UC)
      print -r -- "\$ ${e[*]} uv $*"
      (cd $UPD && clean env $e $U "$@") 2>&1 | sed 's/^/  | /'; local urc=${pipestatus[1]}
      print -r -- "  rc=$urc"; return $urc
    }
    state() {  # $1 = default|pinned, $2 = when; sets SC (commit) and SV (version)
      local got; got=($(installed $UPD/$1/tools))
      SC=${got[1]} SV=${got[2]}
      print -r -- "REPORT 605 U $1 $2: commit $SC | graftling $SV | requested_revision ${got[3]} | receipt: $(receipt $UPD/$1/tools)"
    }
    say "source: a local clone of $GREPO; its default branch main = $GREPO's main; tag $PIN"
    MAINC=$(git -C $GREPO rev-parse --verify -q 'main^{commit}') || { print "STOP: no main in $GREPO"; exit 1; }
    clean git clone -q --no-hardlinks $GREPO $REPO && clean git -C $REPO switch -q -C main $MAINC || exit 1
    PINC=$(git -C $REPO rev-parse --verify -q "$PIN^{commit}") || { print "STOP: no tag $PIN in $REPO"; exit 1; }
    print -r -- "source $SRC: HEAD -> $(git -C $REPO symbolic-ref HEAD) = $(git -C $REPO rev-parse HEAD); $PIN = $PINC"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"

    say "1. install without a ref (the README's default form) and pinned @$PIN"
    uvrun default tool install --managed-python $SRC || exit 1
    uvrun pinned tool install --managed-python "$SRC@$PIN" || exit 1
    state default "after install"; D0=$SC
    state pinned "after install"; P0=$SC
    [[ $D0 == $MAINC ]] && print -r -- "CHECK 605 U tagless install is main's commit: PASS" || print -r -- "CHECK 605 U tagless install is main's commit: FAIL"
    [[ $P0 == $PINC ]] && print -r -- "CHECK 605 U pinned install is $PIN's commit: PASS" || print -r -- "CHECK 605 U pinned install is $PIN's commit: FAIL"

    say "2. a new commit on the source's default branch main"
    old=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' $REPO/src/graftling/__init__.py); MARK=$old.post605
    sed -i '' "s/^__version__ = \".*\"\$/__version__ = \"$MARK\"/" $REPO/src/graftling/__init__.py || exit 1
    clean git -C $REPO -c user.name=adopt-605 -c user.email=adopt-605@example.invalid commit -q -am "605 upgrade probe: $MARK" || exit 1
    NEW=$(git -C $REPO rev-parse HEAD)
    print -r -- "main is now $NEW (graftling $old -> $MARK)"

    say "3. uv tool upgrade graftling (tagless install)"
    MOVEDBY=none
    uvrun default tool upgrade graftling; state default "after 'uv tool upgrade graftling'"
    if [[ $SC == $NEW && $SV == $MARK ]]; then MOVEDBY="uv tool upgrade graftling"
    else
      print -r -- "tagless install did not move; trying the reinstall forms"
      say "4. uv tool upgrade --reinstall graftling (tagless install)"
      uvrun default tool upgrade --reinstall graftling; state default "after 'uv tool upgrade --reinstall graftling'"
      if [[ $SC == $NEW && $SV == $MARK ]]; then MOVEDBY="uv tool upgrade --reinstall graftling"
      else
        say "5. uv tool install --managed-python --reinstall <source> (tagless install)"
        uvrun default tool install --managed-python --reinstall $SRC; state default "after 'uv tool install --managed-python --reinstall'"
        [[ $SC == $NEW && $SV == $MARK ]] && MOVEDBY="uv tool install --managed-python --reinstall <source>"
      fi
    fi
    print -r -- "REPORT 605 U tagless: $D0 -> $SC (graftling $SV); moved by: $MOVEDBY"

    say "6. uv tool upgrade graftling (pinned @$PIN)"
    uvrun pinned tool upgrade graftling; state pinned "after 'uv tool upgrade graftling'"
    [[ $SC == $PINC ]] && PSTAY=stays || PSTAY=moved
    print -r -- "REPORT 605 U pinned @$PIN: $P0 -> $SC (graftling $SV); $PSTAY"
    print -r -- "RESULT 605 U: after a tagless install, the first command that moved it to the new commit of main: $MOVEDBY; a pinned @$PIN install $PSTAY on 'uv tool upgrade graftling'."
  } 2>&1 | tee $R/U.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q '^CHECK 605 .*: FAIL' $R/U.txt || { print "\nU STOP (see above). Hand $R/U.txt to the Team."; exit 1; }
  summary U "$(grep -E '^(uv:|source|main is|CHECK|REPORT|RESULT)' $R/U.txt)"
  print "Success: both 'CHECK 605 U ...: PASS'; the RESULT line names the command that followed main (compare with the README's upgrade paragraph)."
  next "Main: hand $R/00.txt, $R/I.txt and $R/U.txt to the Team; done" ;;

D) print "[D] Main, after I. What a DSH child is launched with, from the installed graftling ($UVT) and the installed DSH: dshprobe605.py runs graftling's DSH selection, settings check and launch preparation (no DSH service, no model request). Dummy keys only, set inside the probe. HOME for the probe is $DSD/home, a fake user home whose .dsh holds a dummy .credentials.yaml; the USER's ~/.dsh is never read or written (names and mtimes only, before and after). Dialog: none. No login. No credential. No network."
  { [[ -x $UVT/tools/graftling/bin/python ]] || { print "STOP: no uv installation under $UVT: run I first"; exit 1; }
    [[ -e $DSD ]] && { print "STOP: $DSD exists (an earlier D). Move it aside: mv $DSD $DSD.old-\$(date +%s)"; exit 1; }
    DSHBIN=$(clean /usr/bin/which dsh) || { print "STOP: no dsh on PATH"; exit 1; }
    print -r -- "dsh: $DSHBIN -> ${DSHBIN:A} | $(clean $DSHBIN --version 2>&1 | head -1)"
    dshmeta() { [[ -n $NOSNAP ]] && { print "skipped (ADOPT605_NOSNAP)"; return; }; /usr/bin/find $HOME/.dsh -maxdepth 3 -exec /usr/bin/stat -f '%m %N' {} + 2>&1 | sort | /usr/bin/shasum -a 256 | cut -c1-16; }
    before=$(dshmeta); print -r -- "~/.dsh names+mtimes digest before: $before"
    mkdir -p $DSD/work $DSD/home/.dsh || exit 1
    print -l -- 'deepseek:' '  apiKey: dummy-605-user-home' > $DSD/home/.dsh/.credentials.yaml
    clean HOME=$DSD/home $UVT/tools/graftling/bin/python -I $SD/dshprobe605.py $DSD/work $DSD/home; prc=$?
    print "probe rc=$prc"
    after=$(dshmeta); print -r -- "~/.dsh names+mtimes digest after:  $after"
    [[ $before == $after ]] && print "CHECK 605 D the USER's ~/.dsh unchanged (names and mtimes): PASS" || print "CHECK 605 D the USER's ~/.dsh unchanged (names and mtimes): FAIL"
    (( prc == 0 )) || exit 1
  } 2>&1 | tee $R/D.txt; rc=${pipestatus[1]}
  dl() { grep -q -F -- "$1" $R/D.txt && print -r -- "CHECK 605 D $2: PASS" || print -r -- "CHECK 605 D $2: FAIL"; }
  { dl "provider 'openrouter': invalid-config" "a provider other than deepseek-official is refused with invalid-config"
    dl "DSH_HOME: $DSD/work/no-connection-settings/dsh-home (generated)" "without home the child's DSH_HOME is the generated directory, not the user's"
    dl "[no-connection-settings] generated home files: ['profiles/web/cordis.patch.yml', 'profiles/web/package.json']" "the generated home holds only the profile manifest and patch (no credentials)"
    dl "[no-connection-settings] credential-like names in the child environment: ['DEEPSEEK_API_KEY']" "without api_key_env the child keeps DEEPSEEK_API_KEY only"
    dl "[api_key_env] credential-like names in the child environment: ['PROBE605_KEY']" "with api_key_env the child gets that variable only"
    dl '[api_key_env] llm-deepseek row config: {"apiKeyEnv": "PROBE605_KEY"}' "api_key_env becomes llm-deepseek's apiKeyEnv"
    dl "DSH_HOME: $DSD/home/.dsh (the user DSH home)" "a connection's home becomes DSH_HOME"
    dl '[base_url] llm-deepseek row config: {"baseURL": "https://example.invalid/anthropic"' "base_url becomes llm-deepseek's baseURL"
    grep -q -F "DEEPSEEK_BASE_URL in the child environment: True" $R/D.txt \
      && print "CHECK 605 D an inherited DEEPSEEK_BASE_URL is removed from the child: FAIL" \
      || print "CHECK 605 D an inherited DEEPSEEK_BASE_URL is removed from the child: PASS"
  } 2>&1 | tee -a $R/D.txt
  (( rc == 0 )) && ! grep -q '^CHECK 605 .*: FAIL' $R/D.txt || { print "\nD STOP (see above). Hand $R/D.txt to the Team."; exit 1; }
  summary D "$(grep -E '^(dsh:|graftling|CHECK|probe rc)' $R/D.txt)"
  print "Success: every 'CHECK 605 D ...: PASS'."
  next "Main: hand $R/D.txt to the Team; done" ;;

*) print "usage: zsh $THIS 00|I|U|D"; exit 2 ;;
esac

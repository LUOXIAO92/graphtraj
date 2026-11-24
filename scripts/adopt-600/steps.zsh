#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 600 Main-run steps: release graftling 0.9.1 (compatible: 597's install command with uv's own managed Python,
# 599's PUBLIC_API note on Retired Agents). One commit e8c2e802 "graftling 0.9.1 (600)" on graftling dev 2b4a33ae, in
# graftling-0.9.1.bundle next to this file. User's release (and push) decision: Worldline user-decision
# 20261124T114043.053104+0900.
# Run one step at a time:  zsh <this file> <STEP>     Order: 00 -> rel -> B -> rp -> gh -> C5 -> done
#   00    Main. Read only (creates <Harness>/tmp/600 and a scratch clone there to read the bundle). No host, no login:
#         Task 600 calls no Claude, Codex, Pi or DSH. Network: github.com (git ls-remote). Dialog: none.
#   rel   Main. graftling repository: fetch the bundle branch, fast-forward dev (graftling-dev Worktree) and main
#         (<Harness>/graftling) to the release commit, annotated tag v0.9.1 (noreply tagger). STOPs, changing nothing,
#         when dev is no longer 2b4a33ae or main no longer 7b5f4e6b. Idempotent. No network. Dialog: none.
#   B     Main, before the push. git archive v0.9.1 -> <Harness>/tmp/600/gsrc, wheel from the archive root (Miniconda
#         python3.13, --no-index --no-deps --no-build-isolation); version strings, CHANGELOG, console scripts, wheel ==
#         archive, content markers, GraphTraj's range. No network. Dialog: none.
#   rp    Main. Push dev, main and v0.9.1 to origin (GitHub), fast-forward only, atomic, no force. Needs
#         ADOPT600_PUSH_CONFIRMED=yes (the user's release decision is the push decision). Network: github.com (the
#         user's usual git credentials). Dialog: none.
#   gh    Main. Read only: GitHub main and v0.9.1 resolve to the release commit; the tag object is the local one.
#   C5    Main. README's command `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git@v0.9.1"`
#         with uv's tool, bin, cache and Python directories under /private/tmp/uvtool-600 only; version 0.9.1, uv-managed
#         base interpreter, installed commit, `subagents --help`. Network: github.com, PyPI, uv's Python download. No
#         login. Dialog: none. ~2-3 min.
#   done  Main. Read only: every CHECK line of the raw files; nonzero on any FAIL.
# Nothing here writes ~/.local, the USER's uv tool directory, dotfiles or conda; .venv-runtime is not touched.
# Credentials: every started process gets an ALLOWLIST environment (clean(): HOME USER PATH TERM TMPDIR LANG and the
# step's own VAR=value); cred_guard STOPs if any *_API_KEY, *_TOKEN, *_BASE_URL or *_AUTH* name is in it (names only).
# Rehearsal only (Engineer; Main leaves all of these unset): ADOPT600_G, ADOPT600_GDEV (scratch graftling clone and its
# dev worktree), ADOPT600_GURL (scratch bare repository standing in for GitHub), ADOPT600_OUT, ADOPT600_SCRATCH,
# ADOPT600_UVT, ADOPT600_NOSNAP=1 (a sandbox cannot read $HOME), ADOPT600_SOURCE (C5's source instead of GitHub; the
# sandbox proxy refuses git to GitHub), ADOPT600_CLEAN_EXTRA (the sandbox's proxy variables for clean()).
# No zsh special parameter name is used as a variable (593 correction 4).
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
SD=${0:A:h}
S593=$WT/scripts/adopt-593                          # reused: homesnap593.py, pkgdiff532.py
STEP=${1:-}
TASKDIR=600-graftling-0-9-1-release
DECISION=20261124T114043.053104+0900                # the user's release decision = the push decision
G=${ADOPT600_G:-$H/graftling}                       # main is checked out here
GDEV=${ADOPT600_GDEV:-$H/.graphtraj/core/worktrees/graftling-dev}   # dev is checked out here
GURL=${ADOPT600_GURL:-https://github.com/LUOXIAO92/graftling.git}   # origin of $G (GitHub)
GBASE=2b4a33aef93dc45b953bd412e4d5dd61347c38ea      # graftling dev at dispatch (597 + 599)
GMAIN0=7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9     # graftling main = v0.9.0 (593)
GCOMMIT=e8c2e80241dff1151f2122e8957fca5598ec987b    # graftling 0.9.1 (600), parent $GBASE
GBRANCH=agent/600-graftling-0.9.1
BUNDLE=$SD/graftling-0.9.1.bundle
BSHA=b5c6d530ef5f3f5324438a4f3ba6d47d0ef8bee271e4b7f53f34f2f2fe66ee12
GFILES="CHANGELOG.md src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json"
GTAG=v0.9.1
GVERSION=0.9.1
RELNAME=LUOXIAO92
RELMAIL=89069722+LUOXIAO92@users.noreply.github.com
RELMSG="graftling 0.9.1 (compatible): the install command lets uv use its own managed Python (uv tool install --managed-python, 597) and PUBLIC_API documents Retired Agents (599); no public name, result, archive format or behavior changes"
SRCURL="git+https://github.com/LUOXIAO92/graftling.git@$GTAG"
INSTALL=(uv tool install --managed-python $SRCURL)  # the README's command with <tag-or-commit> = v0.9.1
[[ -n ${ADOPT600_SOURCE:-} ]] && INSTALL=(uv tool install --managed-python $ADOPT600_SOURCE)   # rehearsal only
CONDA=/Users/luoxiao/miniconda3/bin/python3.13      # read only; builds the wheel, runs the helpers with -I
CROOT=${CONDA:h:h}
SCR=${ADOPT600_SCRATCH:-$H/tmp/600}
GSRC=$SCR/gsrc                                      # git archive v0.9.1
WHL=$SCR/wheel
UVT=${ADOPT600_UVT:-/private/tmp/uvtool-600}
R=${ADOPT600_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost/main-raw}
UVENV=(UV_TOOL_DIR=$UVT/tools UV_TOOL_BIN_DIR=$UVT/bin UV_CACHE_DIR=$UVT/cache UV_PYTHON_INSTALL_DIR=$UVT/python)
NOSNAP=${ADOPT600_NOSNAP:-}

next() { print -- "\n==> next (paste as is): $*"; }
say()  { print -- "\n### $*"; }
summary() { print -- "\n----- summary for Main ($1) -----"; shift; print -l -- "$@"; print -- "-----"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} ${=ADOPT600_CLEAN_EXTRA:-} "$@"; }
cred_guard() {
  local names; names=$(clean env | cut -d= -f1 | grep -E '_API_KEY$|_TOKEN$|_BASE_URL$|_AUTH' | tr '\n' ' ')
  [[ -z $names ]] || { print -r -- "STOP: credential-like names in the clean environment: $names"; exit 97; }
}
gg() { clean git "$@"; }                            # every git call: allowlist environment
ck() { [[ $1 == 0 ]] && print -r -- "CHECK 600 $2: PASS${3:+ ($3)}" || print -r -- "CHECK 600 $2: FAIL${3:+ ($3)}"; }   # $1 = 0 for pass
U=$(clean /usr/bin/which uv 2>/dev/null)            # the uv on the clean PATH; every uv call uses this one file
[[ -n $U ]] || { print "STOP: no uv on PATH (${(j.:.)path})"; exit 1; }
rel_wt() {  # the worktree that has branch $1 checked out in $G, if any
  gg -C $G worktree list --porcelain | awk -v b="branch refs/heads/$1" '/^worktree /{w=substr($0,10)} $0==b{print w}'
}
snap() {  # $1 = output json
  [[ -n $NOSNAP ]] && { print "snap: skipped (ADOPT600_NOSNAP, rehearsal only)"; return 0; }
  clean $CONDA -I $S593/homesnap593.py snap $1 local=$HOME/.local uvtools=$(clean $U tool dir 2>/dev/null || print $HOME/.local/share/uv/tools) \
    pi=$HOME/.pi dsh=$HOME/.dsh codex=$HOME/.codex conda=$CROOT
}
remote_of() {  # $1 = ls-remote output, $2 = ref
  print -r -- $1 | awk -v r="$2" '$2==r{print $1}'
}

mkdir -p $R || exit 1
cred_guard
case $STEP in
00) print "[00] Main. Read only, apart from creating $SCR (and a scratch clone $SCR/g00.git there to read the bundle). No host and no login: Task 600 calls no Claude, Codex, Pi or DSH. Network: github.com (git ls-remote, read only). Dialog: none."
  { mkdir -p $SCR || exit 1
    ck $([[ -n ${ZSH_VERSION:-} ]]; print $?) "00 runs under zsh" "zsh $ZSH_VERSION"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1)"
    clean $U tool install --help 2>&1 | grep -q -- '--managed-python' ; ck $? "00 this uv's 'uv tool install --help' lists --managed-python" "$(clean $U tool install --help 2>&1 | grep -- '--managed-python ' | head -1 | sed 's/^ *//')"
    print -r -- "uv user config: $(for f in $HOME/.config/uv/uv.toml /etc/uv/uv.toml; do [[ -e $f ]] && print -n "$f present; " || print -n "$f absent; "; done)"
    print -r -- "TMPDIR: ${TMPDIR:-unset}"
    [[ ! -e $UVT ]]; ck $? "00 $UVT absent" "$([[ -e $UVT ]] && print "move it aside first: mv $UVT $UVT.old-\$(date +%s)")"
    say "graftling repository $G (read only)"
    gd=$(gg -C $G rev-parse -q --verify refs/heads/dev) gm=$(gg -C $G rev-parse -q --verify refs/heads/main)
    dw=$(rel_wt dev) mw=$(rel_wt main)
    print -r -- "dev: ${gd:-NOT FOUND} in ${dw:-no worktree} | main: ${gm:-NOT FOUND} in ${mw:-no worktree}"
    [[ $gd == $GBASE ]]; ck $? "00 graftling dev = $GBASE"
    [[ $gm == $GMAIN0 ]]; ck $? "00 graftling main = $GMAIN0 (v0.9.0)"
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]]; ck $? "00 dev is checked out in $GDEV and main in $G"
    dirty=""; for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || dirty="$dirty $w"; done
    [[ -z $dirty ]]; ck $? "00 both worktrees clean (git status --porcelain empty)" "${dirty# }"
    lt=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG)
    [[ -z $lt ]]; ck $? "00 $GTAG absent locally" "${lt}"
    say "GitHub $GURL (git ls-remote, read only)"
    if rem=$(gg ls-remote $GURL refs/heads/main refs/heads/dev refs/tags/$GTAG 2>&1); then
      rm0=$(remote_of $rem refs/heads/main) rd0=$(remote_of $rem refs/heads/dev) rt0=$(remote_of $rem refs/tags/$GTAG)
      print -r -- "GitHub main: ${rm0:-absent} | dev: ${rd0:-absent} | $GTAG: ${rt0:-absent}"
      [[ $rm0 == $GMAIN0 ]]; ck $? "00 GitHub main = $GMAIN0"
      [[ -z $rt0 ]]; ck $? "00 GitHub $GTAG absent"
      [[ -n $rd0 ]] && gg -C $G merge-base --is-ancestor $rd0 $GBASE 2>/dev/null; ck $? "00 GitHub dev (${rd0:-absent}) is an ancestor of $GBASE, so rp fast-forwards it"
    else ck 1 "00 git ls-remote $GURL" "${rem[1,200]}"; fi
    say "bundle $BUNDLE"
    bs=$(shasum -a 256 $BUNDLE | cut -d' ' -f1); print -r -- "sha256: $bs"
    [[ $bs == $BSHA ]]; ck $? "00 bundle sha256 = $BSHA"
    gg -C $G bundle verify -q $BUNDLE > /dev/null 2>&1; ck $? "00 bundle verifies against $G (its prerequisite $GBASE is there)"
    heads=$(gg bundle list-heads $BUNDLE); print -r -- "list-heads: $heads"
    [[ $heads == "$GCOMMIT refs/heads/$GBRANCH" ]]; ck $? "00 bundle head = $GCOMMIT ($GBRANCH)"
    say "the release commit, read from a scratch clone $SCR/g00.git (objects shared from $G, which is not written)"
    rm -rf $SCR/g00.git && gg clone -q --bare --shared $G $SCR/g00.git && gg -C $SCR/g00.git fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" \
      || { ck 1 "00 read the bundle into $SCR/g00.git"; exit 1; }
    X=(gg -C $SCR/g00.git)
    print -r -- "$GCOMMIT: $($X log -1 --format='%s | author %an <%ae> | committer %cn <%ce> | parent %P' $GCOMMIT)"
    [[ $($X log -1 --format=%P $GCOMMIT) == $GBASE ]]; ck $? "00 $GCOMMIT is one commit on $GBASE"
    [[ $($X log -1 --format='%ae %ce' $GCOMMIT) == "$RELMAIL $RELMAIL" ]]; ck $? "00 release commit author and committer are $RELMAIL"
    changed=$($X diff --name-only $GBASE $GCOMMIT | sort | tr '\n' ' '); print -r -- "changed files: $changed"
    [[ $changed == $(print -l ${=GFILES} | sort | tr '\n' ' ') ]]; ck $? "00 the release commit changes exactly the 5 version/CHANGELOG files"
    print -r -- "version at $GCOMMIT: $($X show ${GCOMMIT}:src/graftling/__init__.py | grep -E '^__version__')"
    line=$($X show ${GCOMMIT}:README.md | grep -m1 '^uv tool install ')
    want="uv tool install --managed-python \"git+https://github.com/LUOXIAO92/graftling.git@<tag-or-commit>\""
    run="uv tool install --managed-python \"$SRCURL\""
    print -r -- "README install line: $line"
    print -r -- "C5 runs:             $run"
    [[ $line == $want && ${line/<tag-or-commit>/$GTAG} == $run ]]; ck $? "00 README install line at $GCOMMIT with @$GTAG equals C5's command"
  } 2>&1 | tee $R/00.txt
  grep -q ': FAIL' $R/00.txt && { print "\n00 STOP: a CHECK failed (see above). Nothing was changed. Hand $R/00.txt to the Team."; exit 1; }
  summary 00 "$(grep -E '^(uv|CHECK|TMPDIR|dev|GitHub|sha256|list-heads|README|C5 runs)' $R/00.txt)"
  print "Success: every 'CHECK 600 00 ...: PASS'."
  next "zsh $THIS rel" ;;

rel) print "[rel] Main. graftling repository $G: fetch $GBRANCH from the bundle, fast-forward dev ($GDEV) and main ($G) to $GCOMMIT, annotated tag $GTAG ($RELNAME <$RELMAIL>). No network, no login. Dialog: none."
  rel_verify() {
    local gt gd gm
    gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    print -r -- "$GTAG -> ${gt:-absent} | dev $gd | main $gm | type $(gg -C $G cat-file -t refs/tags/$GTAG 2>&1) | tagger $(gg -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG)"
    [[ $gt == $GCOMMIT ]]; ck $? "rel $GTAG peels to $GCOMMIT"
    [[ $gm == $GCOMMIT && $gd == $GCOMMIT ]]; ck $? "rel graftling main == dev == $GTAG^{} == $GCOMMIT"
    [[ $(gg -C $G cat-file -t refs/tags/$GTAG 2>/dev/null) == tag && $(gg -C $G for-each-ref --format='%(taggername) %(taggeremail)' refs/tags/$GTAG) == "$RELNAME <$RELMAIL>" ]]
    ck $? "rel $GTAG is an annotated tag with the noreply tagger"
    local tm; tm=$(gg -C $G cat-file tag refs/tags/$GTAG 2>/dev/null | sed '1,/^$/d')
    [[ $tm == *597* && $tm == *599* && $tm == *compatible* ]]; ck $? "rel $GTAG message names 597, 599 and compatible"
    local v; v=$(gg -C $G show ${GTAG}:src/graftling/__init__.py 2>/dev/null | grep -E '^__version__')
    [[ $v == "__version__ = \"$GVERSION\"" ]]; ck $? "rel version at $GTAG is $GVERSION" "$v"
  }
  { gd=$(gg -C $G rev-parse -q --verify refs/heads/dev) gm=$(gg -C $G rev-parse -q --verify refs/heads/main)
    gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}" 2>/dev/null)
    dw=$(rel_wt dev) mw=$(rel_wt main)
    print -r -- "before: dev ${gd:-NOT FOUND} (in ${dw:-no worktree}) | main ${gm:-NOT FOUND} (in ${mw:-no worktree}) | $GTAG ${gt:-absent}"
    if [[ -n $gt ]]; then
      if [[ $gt == $GCOMMIT && $gm == $GCOMMIT && $gd == $GCOMMIT ]]; then print "already released: $GTAG = main = dev = $GCOMMIT (nothing to do)"; rel_verify; exit 0; fi
      print "STOP: $GTAG exists at $gt, but not with main = dev = $GCOMMIT. Nothing changed. Main tells the Leader."; exit 1
    fi
    [[ $gd == $GBASE || $gd == $GCOMMIT ]] || { print -r -- "STOP: graftling dev is $gd, no longer $GBASE (moved since dispatch: $(gg -C $G log --oneline $GBASE..$gd 2>/dev/null | head -5 | tr '\n' ';')). Requirement 2 needs dev AND main at the release commit, so rel does not merge. Nothing changed. Main tells the Leader."; exit 1; }
    [[ $gm == $GMAIN0 || $gm == $GCOMMIT ]] || { print -r -- "STOP: graftling main is $gm, no longer $GMAIN0 (v0.9.0). Nothing changed. Main tells the Leader."; exit 1; }
    [[ -n $dw && ${dw:A} == ${GDEV:A} && -n $mw && ${mw:A} == ${G:A} ]] || { print -r -- "STOP: dev must be checked out in $GDEV and main in $G (found ${dw:-none} and ${mw:-none}). Nothing changed."; exit 1; }
    for w in $dw $mw; do [[ -z $(gg -C $w status --porcelain 2>&1) ]] || { print -r -- "STOP: the worktree $w is not clean (git status --porcelain). Nothing changed."; exit 1; }; done
    say "bundle (sha256 $(shasum -a 256 $BUNDLE | cut -c1-16)...): verify, fetch $GBRANCH, check it is $GCOMMIT on $GBASE"
    [[ $(shasum -a 256 $BUNDLE | cut -d' ' -f1) == $BSHA ]] || { print "STOP: the bundle's sha256 is not $BSHA. Nothing changed."; exit 1; }
    gg -C $G bundle verify -q $BUNDLE > /dev/null || { print "STOP: the bundle does not verify against $G. Nothing changed."; exit 1; }
    gg -C $G fetch -q $BUNDLE "refs/heads/${GBRANCH}:refs/heads/$GBRANCH" || { print "STOP: fetching $GBRANCH from the bundle failed. Nothing else changed."; exit 1; }
    [[ $(gg -C $G rev-parse refs/heads/$GBRANCH) == $GCOMMIT && $(gg -C $G rev-parse $GCOMMIT~1) == $GBASE ]] \
      && print -r -- "$GBRANCH = $GCOMMIT (parent $GBASE) | author / committer: $(gg -C $G log -1 --format='%an <%ae> / %cn <%ce>' $GCOMMIT)" \
      || { print "STOP: $GBRANCH is not $GCOMMIT on $GBASE. dev, main and the tag are unchanged."; exit 1; }
    say "dev: fast-forward $gd -> $GCOMMIT in $dw"
    gg -C $dw merge --ff-only -q $GCOMMIT || { print "STOP: dev did not fast-forward; main and the tag are unchanged."; exit 1; }
    say "main: fast-forward $gm -> $GCOMMIT in $mw"
    gg -C $mw merge --ff-only -q $GCOMMIT || { print "STOP: main did not fast-forward; dev is at $GCOMMIT, the tag is not made. Rerun rel after fixing."; exit 1; }
    say "annotated tag $GTAG at $GCOMMIT, tagger $RELNAME <$RELMAIL>"
    clean GIT_COMMITTER_NAME=$RELNAME GIT_COMMITTER_EMAIL=$RELMAIL git -C $G tag -a $GTAG $GCOMMIT -m "$RELMSG" || exit 1
    rel_verify
  } 2>&1 | tee $R/rel.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/rel.txt || { print "\nrel STOP (see above). Hand $R/rel.txt to the Team; do not run B or rp."; exit 1; }
  summary rel "$(grep -E '^(before|already|CHECK|STOP)' $R/rel.txt)"
  print "Success: every 'CHECK 600 rel ...: PASS' (or 'already released')."
  next "zsh $THIS B" ;;

B) print "[B] Main, before the push. git archive $GTAG -> $GSRC; wheel from the archive root with $CONDA (--no-index --no-deps --no-build-isolation) -> $WHL. No network, no login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}")
    [[ $gt == $GCOMMIT ]] || { print -r -- "STOP: $GTAG^{commit} is ${gt:-absent}, not $GCOMMIT: run rel first."; exit 1; }
    rm -rf $GSRC $WHL $SCR/wheelview; mkdir -p $GSRC $WHL $SCR/wheelview || exit 1
    gg -C $G archive $GTAG | tar -x -C $GSRC || exit 1
    print -r -- "git archive $GTAG ($GCOMMIT) -> $GSRC"
    say "version strings in the archive"
    vbad=0; for vf in src/graftling/__init__.py src/graftling/claude-plugin/.claude-plugin/plugin.json src/graftling/dsh/package.json src/graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $GSRC/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B archive version strings (__init__.py and the 3 json) all $GVERSION"
    hd=$(grep -m1 '^## ' $GSRC/CHANGELOG.md); print -r -- "CHANGELOG first heading: $hd"
    [[ $hd == "## $GVERSION (compatible)" ]] && ! grep -q '^## Unreleased' $GSRC/CHANGELOG.md; ck $? "B CHANGELOG heading '## $GVERSION (compatible)' and no '## Unreleased'"
    say "build ($(clean $CONDA -c 'import setuptools, pip; print("setuptools", setuptools.__version__, "| pip", pip.__version__)'))"
    (cd $SCR && clean $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $WHL $GSRC) || { print "STOP: the wheel build failed"; exit 1; }
    whl=($WHL/graftling-$GVERSION-*.whl(N)); all=($WHL/*.whl(N))
    print -r -- "wheel: ${all[*]:t}"
    (( $#whl == 1 && $#all == 1 )) || { print "STOP: expected exactly one graftling-$GVERSION wheel in $WHL"; exit 1; }
    whl=$whl[1]
    (cd $SCR/wheelview && unzip -qo $whl) || exit 1
    say "version strings in the wheel"
    mv_=$(sed -n 's/^Version: //p' $SCR/wheelview/graftling-$GVERSION.dist-info/METADATA 2>/dev/null); print -r -- "  METADATA Version: ${mv_:-MISSING}"
    vbad=0; [[ $mv_ == $GVERSION ]] || vbad=1
    for vf in graftling/__init__.py graftling/claude-plugin/.claude-plugin/plugin.json graftling/dsh/package.json graftling/pi/package.json; do
      vl=$(grep -m1 -E '^__version__ = |"version": ' $SCR/wheelview/$vf 2>/dev/null); print -r -- "  $vf: ${vl:-MISSING}"; [[ $vl == *"\"$GVERSION\""* ]] || vbad=1
    done
    ck $vbad "B wheel version strings (METADATA, __init__.py, the 3 json) all $GVERSION"
    say "console scripts"
    cs=$(sed -n '/^\[console_scripts\]/,/^\[/p' $SCR/wheelview/graftling-$GVERSION.dist-info/entry_points.txt | grep -oE '^[A-Za-z0-9_.-]+ *=' | tr -d ' =' | sort | tr '\n' ' ')
    print -r -- "  [console_scripts]: ${cs:-none}"
    [[ $cs == "subagents subagents-mcp " ]]; ck $? "B wheel console scripts are exactly subagents, subagents-mcp"
    say "wheel == git archive $GTAG, file by file (593's pkgdiff532.py)"
    clean $CONDA -I $S593/pkgdiff532.py graftling $whl archive:$GSRC/src "600 B graftling wheel equals git archive $GTAG" -
    ck $? "B the wheel's graftling/ files equal git archive $GTAG"
    say "content markers in the wheel"
    mk=0
    for f in graftling/claude-plugin/bin/graftling-host graftling/dsh/plugin.mjs; do
      n=$(grep -c 'uv tool install --managed-python' $SCR/wheelview/$f 2>/dev/null); print -r -- "  $f: 'uv tool install --managed-python' x${n:-0}"; (( ${n:-0} > 0 )) || mk=1
    done
    n=$(grep -c '^\*\*Retired Agents\.\*\*' $SCR/wheelview/graftling/PUBLIC_API.md 2>/dev/null); print -r -- "  graftling/PUBLIC_API.md: '**Retired Agents.**' x${n:-0}"; (( ${n:-0} > 0 )) || mk=1
    ck $mk "B 597's and 599's markers are in the wheel"
    leaked=$(unzip -Z1 $whl | grep -cE '(^|/)(build|__pycache__)/'); print -r -- "leaked build/ or __pycache__/ entries: $leaked"
    [[ $leaked == 0 ]]; ck $? "B no build/ or __pycache__ in the wheel"
    say "GraphTraj's graftling requirement ($WT/pyproject.toml; information: no change needed)"
    clean $CONDA -I -c 'import sys, tomllib
from packaging.requirements import Requirement
deps = tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]
reqs = [Requirement(d) for d in deps if Requirement(d).name == "graftling"]
ok = len(reqs) == 1 and reqs[0].specifier.contains(sys.argv[2])
verdict = "yes, no change needed" if ok else "NO"
print(f"REPORT 600 B GraphTraj Requires-Dist {reqs[0] if reqs else None} includes {sys.argv[2]}: {verdict}")
sys.exit(0 if ok else 1)' $WT/pyproject.toml $GVERSION; ck $? "B GraphTraj's graftling range includes $GVERSION"
    print -r -- "wheel sha256: $(shasum -a 256 $whl)"
  } 2>&1 | tee $R/B.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/B.txt || { print "\nB STOP (see above). Do not push. Hand $R/B.txt to the Team."; exit 1; }
  summary B "$(grep -E '^(CHECK|REPORT|wheel)' $R/B.txt)"
  print "Success: every 'CHECK 600 B ...: PASS'."
  next "ADOPT600_PUSH_CONFIRMED=yes zsh $THIS rp" ;;

rp) print "[rp] Main. Outward-facing: push graftling dev, main and refs/tags/$GTAG to origin ($GURL), fast-forward only, atomic, no force. The user's release decision is the push decision (Worldline user-decision $DECISION). Network: github.com with the user's usual git credentials (osxkeychain); no other login. Dialog: none."
  { gt=$(gg -C $G rev-parse -q --verify "refs/tags/$GTAG^{commit}") gd=$(gg -C $G rev-parse dev) gm=$(gg -C $G rev-parse main)
    [[ $gt == $GCOMMIT && $gm == $GCOMMIT && $gd == $GCOMMIT ]] || { print -r -- "STOP: rel is not complete (dev $gd, main $gm, $GTAG ${gt:-absent}; need all $GCOMMIT)."; exit 1; }
    ou=$(gg -C $G remote get-url origin 2>&1); print -r -- "origin: $ou"
    [[ $ou == $GURL ]] || { print -r -- "STOP: origin of $G is not $GURL"; exit 1; }
    before=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main refs/tags/$GTAG 2>&1) || { print -r -- "STOP: ls-remote failed: ${before[1,200]}"; exit 1; }
    print -r -- "remote before: ${before//$'\n'/ | }"
    print -r -- "will push: dev $gd, main $gm, refs/tags/$GTAG ($(gg -C $G rev-parse refs/tags/$GTAG)) (fast-forward only, --atomic, no force)"
    [[ ${ADOPT600_PUSH_CONFIRMED:-} == yes ]] || { print -r -- "STOP: the push is outward-facing. It is the user's decision $DECISION; run: ADOPT600_PUSH_CONFIRMED=yes zsh $THIS rp"; exit 1; }
    gg -C $G push --atomic origin refs/heads/dev:refs/heads/dev refs/heads/main:refs/heads/main refs/tags/${GTAG}:refs/tags/$GTAG || { print "STOP: the push was refused (atomic: nothing changed on the remote)"; exit 1; }
    now=$(gg -C $G ls-remote origin refs/heads/dev refs/heads/main "refs/tags/$GTAG^{}" 2>&1)
    print -r -- "remote now: ${now//$'\n'/ | }"
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT && $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "rp remote main == $GTAG^{} == $GCOMMIT"
    [[ $(remote_of $now refs/heads/dev) == $gd ]]; ck $? "rp remote dev == local dev ($gd)"
  } 2>&1 | tee $R/rp.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/rp.txt || { print "\nrp STOP (see above). Hand $R/rp.txt to the Team."; exit 1; }
  summary rp "$(grep -E '^(remote|CHECK)' $R/rp.txt)"
  print "Success: both 'CHECK 600 rp ...: PASS'."
  next "zsh $THIS gh" ;;

gh) print "[gh] Main. Read only: git ls-remote $GURL. Network: github.com. No login. Dialog: none."
  { now=$(gg ls-remote $GURL refs/heads/main refs/tags/$GTAG "refs/tags/$GTAG^{}" 2>&1) || { print -r -- "STOP: git ls-remote $GURL failed: ${now[1,200]}"; exit 1; }
    print -r -- "GitHub: ${now//$'\n'/ | }"
    rto=$(remote_of $now refs/tags/$GTAG) lto=$(gg -C $G rev-parse -q --verify refs/tags/$GTAG)
    [[ $(remote_of $now refs/heads/main) == $GCOMMIT ]]; ck $? "gh GitHub main = $GCOMMIT"
    [[ $(remote_of $now "refs/tags/$GTAG^{}") == $GCOMMIT ]]; ck $? "gh GitHub $GTAG^{} = $GCOMMIT"
    [[ -n $rto && $rto != $GCOMMIT && $rto == $lto ]]; ck $? "gh GitHub $GTAG is the local annotated tag object" "remote ${rto:-absent}, local ${lto:-absent}"
  } 2>&1 | tee $R/gh.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/gh.txt || { print "\ngh STOP (see above). Hand $R/gh.txt to the Team."; exit 1; }
  summary gh "$(grep -E '^(GitHub|CHECK)' $R/gh.txt)"
  print "Success: three 'CHECK 600 gh ...: PASS'."
  next "zsh $THIS C5" ;;

C5) print "[C5] Main. README's install command for GitHub $GTAG in $UVT only (uv's tool, bin, cache and Python directories under it); the USER's ~/.local, uv tool directory, dotfiles and conda are not touched. Network: github.com, PyPI, uv's Python download. No login. Dialog: none. ~2-3 min."
  { [[ -e $UVT/tools ]] && { print "STOP: $UVT/tools exists (an earlier C5). Move it aside: mv $UVT $UVT.old-\$(date +%s)"; exit 1; }
    mkdir -p $UVT || exit 1
    say "before: USER directories and conda (read only)"
    snap $R/C5-home-before.json || exit 1
    say "README line 1: the install, uv directories isolated under $UVT"
    print -r -- "uv: $U -> ${U:A} | $(clean $U --version 2>&1) | environment: ${UVENV[*]}"
    print -r -- "command: ${INSTALL[*]}   (uv = $U)"
    (cd $UVT && clean $UVENV $U ${INSTALL[2,-1]}) > $R/C5-uv.txt 2>&1; urc=$?
    tail -5 $R/C5-uv.txt
    print "uv tool install rc=$urc (full output: $R/C5-uv.txt)"; ck $urc "C5 uv tool install rc 0"
    (( urc == 0 )) || exit 1
    say "README line 2: AGENTS_PYTHON=\"\$(uv tool dir)/graftling/bin/python\" (isolated environment)"
    td=$(cd $UVT && clean $UVENV $U tool dir 2>&1); py=$td/graftling/bin/python
    print -r -- "uv tool dir: $td"; [[ $td == $UVT/tools ]]; ck $? "C5 uv tool dir is $UVT/tools"
    out=$(cd $UVT && clean $py -I -c 'import sys, json, importlib.metadata as m, graftling
d = m.distribution("graftling")
print(sys.prefix); print(getattr(sys, "_base_executable", "") or sys.base_prefix)
print(graftling.__version__); print(m.version("graftling"))
print(json.loads(d.read_text("direct_url.json") or "{}").get("vcs_info", {}).get("commit_id", "none"))' 2>&1) || { ck 1 "C5 the tool Python runs" "${out[1,200]}"; exit 1; }
    prefix=${${(f)out}[1]} base=${${(f)out}[2]} gv=${${(f)out}[3]} mdv=${${(f)out}[4]} cid=${${(f)out}[5]}
    print -r -- "tool python: $py -> ${py:A} | sys.prefix: $prefix | base: $base -> ${base:A} | graftling.__version__ $gv | metadata $mdv | direct_url commit_id $cid"
    [[ $gv == $GVERSION && $mdv == $GVERSION ]]; ck $? "C5 graftling.__version__ and importlib.metadata version are $GVERSION"
    [[ ${prefix:A} == ${UVT:A}/tools/graftling ]]; ck $? "C5 sys.prefix is $UVT/tools/graftling"
    class=other
    case ${base:A}/ in ${CROOT:A}/*) class=conda ;; /usr/*|/System/*|/Library/*|/opt/homebrew/*) class=system ;; esac
    [[ ${base:A}/ == ${UVT:A}/python/* && ${py:A}/ == ${UVT:A}/python/* ]] && class=uv-managed
    print -r -- "REPORT 600 C5 base interpreter: $base ($class) | uv-managed Pythons: $(print -l $UVT/python/*(N/:t) | tr '\n' ' ')"
    [[ $class == uv-managed ]]; ck $? "C5 tool environment base interpreter is uv-managed (under $UVT/python)" "$class"
    [[ $cid == $GCOMMIT ]]; ck $? "C5 installed dist-info direct_url.json vcs commit_id is $GCOMMIT" "$cid"
    say "README line 3: \"\$(uv tool dir --bin)/subagents\" --help (isolated environment)"
    bd=$(cd $UVT && clean $UVENV $U tool dir --bin 2>&1); print -r -- "uv tool dir --bin: $bd"
    [[ $bd == $UVT/bin ]]; ck $? "C5 uv tool dir --bin is $UVT/bin"
    hl=$(cd $UVT && clean "$bd/subagents" --help 2>&1); hrc=$?
    print -r -- "subagents --help (rc $hrc): ${${(f)hl}[1]:-}"
    ck $hrc "C5 $UVT/bin/subagents --help rc 0"
    [[ -x $UVT/bin/subagents-mcp ]]; ck $? "C5 $UVT/bin/subagents-mcp exists" "$(head -1 $UVT/bin/subagents-mcp 2>/dev/null)"
    say "after: USER directories and conda"
    if [[ -n $NOSNAP ]]; then print "snap compare: skipped (ADOPT600_NOSNAP, rehearsal only)"
    else
      snap $R/C5-home-after.json > /dev/null
      clean $CONDA -I $S593/homesnap593.py compare $R/C5-home-before.json $R/C5-home-after.json; ck $? "C5 USER directories (~/.local, uv tools, ~/.pi, ~/.dsh, ~/.codex) and conda unchanged"
    fi
  } 2>&1 | tee $R/C5.txt; rc=${pipestatus[1]}
  (( rc == 0 )) && ! grep -q ': FAIL' $R/C5.txt || { print "\nC5 STOP (see above). Hand $R/C5.txt to the Team."; exit 1; }
  summary C5 "$(grep -E '^(uv|command|uv tool install|tool python|subagents --help|CHECK|REPORT)' $R/C5.txt)"
  print "Success: every 'CHECK 600 C5 ...: PASS' (rc 0; version $GVERSION; base interpreter under $UVT/python; commit $GCOMMIT; subagents --help rc 0; USER directories and conda unchanged)."
  next "zsh $THIS done" ;;

done) print "[done] Main. Read only: every CHECK line in $R. Dialog: none."
  { miss=""
    for s in 00 rel B rp gh C5; do [[ -s $R/$s.txt ]] || miss="$miss $s"; done
    grep -h '^CHECK 600 ' $R/{00,rel,B,rp,gh,C5}.txt(N)
    grep -h '^REPORT 600 ' $R/{B,C5}.txt(N)
    np=$(cat $R/{00,rel,B,rp,gh,C5}.txt(N) | grep -c '^CHECK 600 .*: PASS') nf=$(cat $R/{00,rel,B,rp,gh,C5}.txt(N) | grep -c '^CHECK 600 .*: FAIL')
    print -r -- "steps without a raw file:${miss:- none} | CHECK PASS $np | CHECK FAIL $nf"
    [[ -z $miss && $nf == 0 ]]; ck $? "done every step ran and every CHECK passed"
  } 2>&1 | tee $R/done.txt
  grep -q '^CHECK 600 done .*: PASS' $R/done.txt || { print "\ndone: FAIL (see above). Hand $R/done.txt to the Team."; exit 1; }
  print "Success: 'CHECK 600 done ...: PASS'."
  next "Main: hand $R to the Team; Task 600 steps complete" ;;

*) print "usage: zsh $THIS 00|rel|B|rp|gh|C5|done"; exit 2 ;;
esac

#!/bin/zsh
# Task 612 Correction 1 rehearsal (Engineer's sandbox only; Main does not run this). Against a scratch production only;
# real production, the Harness state and this Worktree are only read.
#   FAKE PRODUCTION (fixture, built by the real product): as rehearse.zsh (604's real graphtraj wheel, 600's real
#     graftling 0.9.1 wheel, production's click/yaml/websockets, `graphtraj setup`, the product's `configuration --write`),
#     PLUS the observed marker: share/graphtraj/manuals/.claude/.cc-writes (empty; modes and mtime as observed).
#   REAL INPUTS (copied, read only): B's real wheels (adoption/wheels-0.10.0, wheels-78f929ee) and Main's real records of
#     00 rel B G rp gh C5 GR (main-raw), so Mpre, I and done read the real records of the steps already run.
#   RUN 1 reproduces the real failure: I of the SUBMITTED steps.zsh (aa8a4948) fails only on the marker; R (the backup's
#     own copy of that steps.zsh) restores production.
#   Then, with the corrected steps.zsh: I STOPs (backup exists) -> I0 STOP (R record missing) -> I0 STOP (production
#     differs from the backup) -> I0 PASS (moves) -> I0 again (nothing to move) -> Mpre -> I PASS with an INFO line ->
#     done (run1 listed as superseded) -> R from the NEW backup -> I0 -> a different extra file under manuals: Mpre ->
#     I FAIL -> R.
#   STUBS and FIXTURES (labelled): `claude`, `ps` (idle listing), Main's Session id, and for done the M/N/P records of the
#     main rehearsal (rehearsal/raw: Mr, Nr, P-pre, Pr; they rest on labelled fixtures there).
# Outputs: rehearsal/c1-console.txt, rehearsal/c1-raw/.
emulate -L zsh
setopt pipe_fail no_unset no_bg_nice
SD=${0:A:h}
WT=$(git -C $SD rev-parse --show-toplevel)
REALH=${WT:h:h:h:h}
REALS=$REALH/.venv-runtime/lib/python3.13/site-packages
REALSTATE=$REALH/.graphtraj/core/state
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
OUTD=$SD/rehearsal
SB=${${TMPDIR:-/tmp}:A}/r612c1
FH=$SB/project; FRT=$FH/.venv-runtime; FST=$FH/.graphtraj/core/state/tasks
T600=600-graftling-0-9-1-release; T604=604-graphtraj-603-production-adoption
T612=612-graftling-provider-release-and-production-adoption; T516=516-low-priority-flaky-tests
REALRAW=$REALSTATE/tasks/$T612/realhost/main-raw
RAW=$OUTD/c1-raw
MAN=$FRT/share/graphtraj/manuals
SITE=$FRT/lib/python3.13/site-packages
MAINID=11111111-2222-3333-4444-555555555612
rm -rf $SB $RAW; mkdir -p $SB/stub $SB/projects/-fake $SB/scr $RAW
S=$SD/steps.zsh
OLD=$SB/steps-aa8a4948.zsh                           # the submitted steps.zsh, as Main ran it
git -C $WT show aa8a4948:scripts/adopt-612/steps.zsh > $OLD || exit 1
cl() { env -i HOME=$HOME USER=${USER:-x} PATH=/usr/bin:/bin TMPDIR=$TMPDIR LANG=en_US.UTF-8 "$@"; }
{ print "## setup: STUB claude and ps (fixtures)"
  print -l '#!/bin/zsh' 'case " $* " in' '  *" --version "*) print "2.1.330 (stub Claude Code, rehearsal fixture)" ;;' '  *) cat > /dev/null; print "stub claude" ;;' 'esac' > $SB/stub/claude
  print -l '#!/bin/zsh' "cat $SB/ps.txt 2>/dev/null; exit 0" > $SB/stub/ps
  print -r -- "1 Ss 0:01 /sbin/launchd (ps FIXTURE: an idle host)" > $SB/ps.txt; chmod +x $SB/stub/claude $SB/stub/ps
  print "## setup: FAKE PRODUCTION $FH (604's and 600's real wheels; built by the real product)"
  W604=$FST/$T604/adoption/wheels-1fdbbca5 W600=$FST/$T600/adoption/wheels-0.9.1; mkdir -p $W604 $W600 $FST/$T612/adoption
  cp -p $REALSTATE/tasks/$T604/adoption/wheels-1fdbbca5/* $W604/ && cp -p $REALSTATE/tasks/$T600/adoption/wheels-0.9.1/* $W600/ || exit 1
  git -C $FH init -q --initial-branch=main 2>/dev/null || { mkdir -p $FH && git -C $FH init -q --initial-branch=main; } || exit 1
  print "# fake" > $FH/README.md; git -C $FH add README.md; git -C $FH -c user.name=x -c user.email=x@invalid commit -qm init
  $CONDA -m venv $FRT && $FRT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $W604/graphtraj-0.1.0-*.whl $W600/graftling-0.9.1-*.whl || exit 1
  for d in click 'click-*.dist-info' yaml _yaml '[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info' websockets 'websockets-*.dist-info'; do cp -Rp $REALS/$~d $SITE/; done
  (cd $FH && print y | cl $FRT/bin/graphtraj setup) > /dev/null || exit 1
  for c in $FH/.graphtraj/config.yml(N) $FH/.graphtraj/core/config.yml(N); do
    $CONDA -I -c 'import sys; p = sys.argv[1]; t = open(p).read(); open(p, "w").write(t.replace("state: .graphtraj/state", "state: .graphtraj/core/state"))' $c; done
  (cd $FH && cl $FRT/bin/python -m graphtraj.runtimes.claude.host configuration --project $FH --claude $SB/stub/claude --write) > /dev/null || exit 1
  for t in $T612 $T516; do mkdir -p $FST/$t && cp -p $REALSTATE/tasks/$t/task.yml $FST/$t/ && cp -Rp $REALSTATE/tasks/$t/definitions $FST/$t/ || exit 1; done
  print "## setup: B's REAL wheels (read from $REALSTATE/tasks/$T612/adoption)"
  cp -Rp $REALSTATE/tasks/$T612/adoption/wheels-0.10.0 $REALSTATE/tasks/$T612/adoption/wheels-78f929ee $FST/$T612/adoption/ || exit 1
  print "## setup: Main's REAL records of 00 rel B G rp gh C5 GR (copied from $REALRAW)"
  for f in 00 rel B G rp gh C5 GR; do cp -p $REALRAW/$f.txt $RAW/ || exit 1; done
  grep -h '^RESULT 612\|^CHECK 612 GR G record' $RAW/GR.txt
  print -r -- $MAINID > $SB/scr/main.session; : > $SB/projects/-fake/$MAINID.jsonl
  print "## setup: the OBSERVED MARKER in the fake production's manuals (.claude 755, .cc-writes 700, both empty, mtime 2026-11-24 20:47:07)"
  mkdir -p $MAN/.claude/.cc-writes && chmod 755 $MAN/.claude && chmod 700 $MAN/.claude/.cc-writes && touch -t 202611242047.07 $MAN/.claude/.cc-writes $MAN/.claude
  ls -laR $MAN/.claude
} 2>&1 | tee $OUTD/c1-console.txt
extra=""; for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do [[ -n ${(P)v:-} ]] && extra="$extra $v=${(P)v}"; done
common=(ADOPT612_H=$FH ADOPT612_WT=$WT ADOPT612_STUB=$SB/stub ADOPT612_PROJECTS=$SB/projects/-fake ADOPT612_VPROJECT=$SB/vproject
        ADOPT612_SCRATCH=$SB/scr ADOPT612_OUT=$RAW "ADOPT612_CLEAN_EXTRA=${extra# }")
run() { local tag=$1; shift; print; print -r -- "######## rehearsal: $tag"; env $common "$@"; print -r -- "######## exit=$? ($tag)"; }
state() { print -r -- "STATE backup: $([[ -e $SB/scr/backup ]] && print present || print absent) | set aside: $(print -l $SB/scr/backup-run*(N/:t) | tr '\n' ' ')| raw I/R: $(print -l $RAW/{I.txt,R.txt,I0.txt}(N:t) | tr '\n' ' ')| runs: $(print -l $RAW/run*(N/:t) | tr '\n' ' ')"; }
{ run "V (corrected steps; on the fake production)" zsh $S V
  run "Mpre" zsh $S Mpre
  print "\n## RUN 1: I of the SUBMITTED steps.zsh (aa8a4948), as Main ran it: expected FAIL only on the marker"
  run "I (submitted aa8a4948)" zsh -fc "print | zsh $OLD I"
  grep -E ': FAIL|Only in' $RAW/I.txt
  run "R from the backup's own copy (aa8a4948)" zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  ls -la $MAN/.claude; state
  print "\n## Corrected steps.zsh from here"
  run "STOP: I with the old backup present (points to I0)" zsh -fc "print | zsh $S I"
  print "\n## I0 STOP case 1: R's record missing (moved aside for this case, then back)"
  mv $RAW/R.txt $SB/R.txt.aside; run "I0 (no R record): STOP" zsh $S I0; mv $SB/R.txt.aside $RAW/R.txt; state
  print "\n## I0 STOP case 2: production differs from the backup (a FIXTURE file added to site-packages, then removed)"
  print fixture > $SITE/c1-extra-fixture.txt; run "I0 (production differs): STOP" zsh $S I0; rm -f $SITE/c1-extra-fixture.txt; state
  run "I0: PASS, moves the backup and run 1's records" zsh $S I0; state
  print -r -- "run1: $(ls $RAW/run1 | tr '\n' ' ') | SUPERSEDED: $(cat $RAW/run1/SUPERSEDED) | moved backup: $(ls $SB/scr/backup-run1-* | tr '\n' ' ')"
  run "I0 again (no backup: nothing to move)" zsh $S I0
  run "Mpre (rerun right before I)" zsh $S Mpre
  run "I (corrected; marker present): PASS with an INFO line" zsh -fc "print | zsh $S I"
  grep -E '^INFO|manuals' $RAW/I.txt
  print "\n## FIXTURE records for done (from the main rehearsal's rehearsal/raw; they rest on labelled fixtures there): Mr Nr P-pre Pr"
  cp -p $OUTD/raw/{Mr,Nr,P-pre,Pr}.txt $RAW/
  run "done (run1 superseded, not counted)" zsh $S done
  run "R from the NEW backup's own copy of the corrected steps.zsh" zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  print -r -- "the new backup's steps.zsh is the corrected one: $(cmp -s $SB/scr/backup/tools/steps.zsh $S && print yes || print NO)"
  print "\n## A DIFFERENT extra file under manuals must FAIL: I0 (moves run 2), a FIXTURE file manuals/stray-c1.txt, Mpre, I, R"
  run "I0 (sets run 2 aside)" zsh $S I0
  print fixture > $MAN/stray-c1.txt
  run "Mpre" zsh $S Mpre
  run "I with manuals/stray-c1.txt besides the marker: FAIL" zsh -fc "print | zsh $S I"
  grep -E '^INFO|manuals' $RAW/I.txt
  run "R" zsh -fc "print | zsh $SB/scr/backup/tools/steps.zsh R"
  state
} 2>&1 | tee -a $OUTD/c1-console.txt

#!/bin/zsh
# gh STAND-IN (rehearsal fixture only; Main never uses it). rehearse.zsh copies it to <sandbox>/bin/gh and writes
# <sandbox>/conf: line 1 the directory of Main's retained run-46114515028 records (653's realhost/main-raw/windows),
# line 2 the attempt the run object reports (1 or 2), line 3 the commit the fixture run object and artifact names
# carry (654's commit stands in for 653's), line 4 the calls log. Answers only what steps.zsh's W asks, offline.
emulate -L zsh
SB=${0:A:h:h}
conf=("${(@f)$(<$SB/conf)}")
RW=$conf[1] AT=$conf[2] SHA=$conf[3] LOG=$conf[4]
A1=$RW/run-46114515028-a1 A2=$RW/run-46114515028-a2
print -r -- "gh $*" >> $LOG
case "$1 $2" in
  "--version ") print "gh version 0.0.0 (stand-in)" ;;
  "run download") n=${@[(i)-n]}; d=${@[(i)-D]}; name=${@[$((n + 1))]}; dir=${@[$((d + 1))]}; mkdir -p $dir
    case $name in
      graftling-windows-junit-$SHA-1) cp -Rp $A1/junit/. $dir/ ;;
      graftling-windows-junit-$SHA-2) cp -Rp $A2/junit-a2/. $dir/ ;;
      graftling-claude-real-entry-$SHA-1) cp -Rp $A1/real-entry/. $dir/ ;;
      *) print -u2 "no artifact matches any of the names or patterns provided"; exit 1 ;;
    esac ;;
  api*) ep=${@[-1]}
    case $ep in
      */actions/runs/46114515028) # FIXTURE run object: head_sha, run_attempt and run_started_at; jobs and artifacts are Main's records
        if [[ $AT == 1 ]]; then print -r -- '{"id": 46114515028, "name": "Windows tests", "path": ".github/workflows/windows.yml", "event": "workflow_dispatch", "status": "completed", "conclusion": "failure", "head_sha": "'$SHA'", "run_attempt": 1, "run_started_at": "2026-11-28T05:59:00Z", "html_url": "https://github.com/LUOXIAO92/graftling/actions/runs/46114515028 (FIXTURE run object, attempt 1)"}'
        else print -r -- '{"id": 46114515028, "name": "Windows tests", "path": ".github/workflows/windows.yml", "event": "workflow_dispatch", "status": "completed", "conclusion": "success", "head_sha": "'$SHA'", "run_attempt": 2, "run_started_at": "2026-11-28T06:21:58Z", "html_url": "https://github.com/LUOXIAO92/graftling/actions/runs/46114515028 (FIXTURE run object, attempt 2)"}'; fi ;;
      */attempts/1/jobs*) cat $A1/jobs.json ;;
      */attempts/2/jobs*) cat $A2/jobs.json ;;
      */jobs/140885224763/logs) cat $A1/windows-tests.log ;;
      */jobs/140885224951/logs) cat $A1/claude-real-entry.log ;;
      */jobs/140890686467/logs) cat $A2/windows-tests.log ;;
      */jobs/140890687998/logs) cat $A2/claude-real-entry.log ;;
      */actions/runs/46114515028/artifacts*)
        if [[ $AT == 1 ]]; then print -r -- '{"artifacts": [{"name": "graftling-windows-junit-'$SHA'-1", "expired": false}, {"name": "graftling-claude-real-entry-'$SHA'-1", "expired": false}]}'
        else print -r -- '{"artifacts": [{"name": "graftling-windows-junit-'$SHA'-1", "expired": false}, {"name": "graftling-windows-junit-'$SHA'-2", "expired": false}, {"name": "graftling-claude-real-entry-'$SHA'-1", "expired": false}]}'; fi ;;
      *) print -u2 "stand-in: unknown endpoint $ep"; exit 1 ;;
    esac ;;
  *) print -u2 "stand-in: unknown gh $*"; exit 1 ;;
esac

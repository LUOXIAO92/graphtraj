#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 448 — production adoption of dev 2be27dd6 (418, 445, 446, 447 integrated) into .venv-runtime.
# Taken from scripts/adopt-393/steps.zsh. Same package names and versions as production (graphtraj 0.1.0,
# graftling 0.5.0), so every install claim is file by file (proddiff.py) against the new wheels.
#   zsh <absolute path>/steps.zsh <step>
# Order: 00 → B → V → S (background) → Vc (→ Vu USER once if asked) → [USER /exit Main] → I (USER)
#        → [USER resume Main] → M → Mps → inbox → N → Nr → done.     Rollback after the backup: R (USER).
# Each step prints who runs it, its dialog (at most one) and how to judge success, then the next command.
# Main's Bash cannot run a foreground sleep: every Main step ends in < 10 min or starts itself in the
# background (S), and is polled by reading a file.
# Only rehearse.zsh sets ADOPT448_*; the defaults are the real paths.
set -u
SD=${0:A:h}
H=${ADOPT448_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
BASE=${ADOPT448_BASE:-$HOME/graphtraj-adoption-448}
RT=${ADOPT448_RT:-$H/.venv-runtime}
PNPM_SHIM=${ADOPT448_PNPM_SHIM:-/Users/luoxiao/agents-394/pnpm-shim}
WT=${ADOPT448_WT:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/448-production-adoption-418-445-446}
TARGET=2be27dd664ce2388c969156c8238f63774567246
TASK=448-production-adoption-418-445-446
TASK_ID=448
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
W=$H/.graphtraj/core/state/tasks/$TASK/adoption
R=$W/raw
N=$W/wheels
BK=$BASE/backup
VV=$BASE/vvenv
SV=$BASE/svenv
VP=$W/vplug/graphtraj-claude-host
VE=$W/ventries
VPROJECT=$BASE/vproject
PDIR=$H/.claude/skills/graphtraj-claude-host
HOSTCFG=$H/.graphtraj/claude-host/config.json
SESS=$H/.graphtraj/swarm/sessions
ENTRIES=($H/.mcp.json $H/.claude/settings.local.json $HOSTCFG)
ALSO=($H/.graphtraj/core/roles.yml $H/.graphtraj/core/*.yml(N) $H/.graphtraj/swarm/config.yml $HOME/.graphtraj/connections.yml $H/.codex/config.toml(N) $H/.codex/hooks.json(N))
INBOX=$H/.graphtraj/core/runner/main-sessions/inbox
PROJECTS=$HOME/.claude/projects/${H//\//-}
THIS=${0:A}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
[[ -x $PNPM_SHIM/pnpm ]] && path=($PNPM_SHIM $path)
[[ -n ${ADOPT448_STUB:-} ]] && path=($ADOPT448_STUB $path)   # rehearsal only: stub hosts first
mkdir -p $R $BASE
MAIN=$(cat $BASE/main.session 2>/dev/null)

# 418 reminder: a GRAFTLING_CLAUDE_HOST_CONFIG inherited from another configured project makes the old
# hook give up association. Recorded here (names and paths only), then removed for every child command.
INHERITED=(${(k)parameters[(I)GRAFTLING_CLAUDE_HOST_*]} ${(k)parameters[(I)GRAPHTRAJ_CLAUDE_HOST_*]})
INHERITED_REPORT=(); for n in $INHERITED; do INHERITED_REPORT+=("$n=${(P)n}"); unset $n; done

next() { print -- "\n==> 下一步 / next（直接粘贴）: $*"; }
say()  { print -- "\n### $*"; }
tree() { $CONDA -I $SD/adopt_tree.py "$@"; }
site() { local s=($RT/lib/python*/site-packages(N)); print -r -- ${s[1]:-$RT/lib/python3.13/site-packages}; }
logged() { local file=$1; shift; "$@" 2>&1 | tee -a $file; return ${pipestatus[1]}; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
wheel_of() { local f=($N/$1-*.whl(N)); print -r -- ${f[1]:-}; }
summary() { print -- "\n----- 复制给 Main 的摘要（$1）-----"; shift; print -l -- "$@"; print -- "-----"; }
inbox_key() { print -rn -- "$1" | shasum -a 256 | cut -d' ' -f1; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
need_main() { [[ -n $MAIN ]] || { print "没有 $BASE/main.session（Main 的 Session id）。先运行 00。"; exit 1; }; }

# Values of exported credential-like names, used only to count raw files that contain one (never printed).
key_values() {
  $CONDA -I -c '
import os, re
part = re.compile(r"(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
for n, v in os.environ.items():
    if len(v) >= 12 and not re.fullmatch(r"GIT_CONFIG_KEY_[0-9]+", n) and any(part.search(p) for p in n.upper().split("_") if p):
        print(v)'
}
credential_names() {
  $CONDA -I -c '
import os, re
part = re.compile(r"(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
print("credential-like exported names (values never printed):", sorted(n for n in os.environ if not re.fullmatch(r"GIT_CONFIG_KEY_[0-9]+", n) and any(part.search(p) for p in n.upper().split("_") if p)) or "none")'
}

# The running Claude Main: parent of the host serving this project's config.json (its argv names
# --resume <id> or --session-id <id>); otherwise the newest transcript of this project.
detect_main() {
  local hit words pp cmd id=""
  hit=$(ps -axww -o pid=,ppid=,command= 2>/dev/null | grep -F -- "$HOSTCFG" | grep -F -- ' serve ' | head -1)
  words=(${=hit}); pp=${words[2]:-}
  if [[ -n $pp ]]; then
    cmd=$(ps -ww -o command= -p $pp 2>/dev/null); print -r -- "host pid ${words[1]}, parent $pp: ${cmd[1,160]}" >&2
    id=$(print -r -- "$cmd" | grep -oE -- '--(resume|session-id)[ =][0-9a-f-]{36}' | grep -oE '[0-9a-f-]{36}$' | head -1)
    [[ -n $id ]] && print -r -- "source: argv of the host's parent claude" >&2
  else print -r -- "no host serving $HOSTCFG found by ps" >&2; fi
  if [[ -z $id ]]; then
    local t=($PROJECTS/*.jsonl(N.om[1]))
    [[ -n ${t[1]:-} ]] && { id=${t[1]:t:r}; print -r -- "source: newest transcript ${t[1]:t} (fallback; check it is this Main)" >&2; }
  fi
  print -r -- $id
}

# Lists what would be damaged by replacing the venv. Refuses when the list cannot be read.
guard() {
  local listing rc line words hits=()
  listing=$(ps -axww -o pid=,command= 2>&1); rc=$?
  if (( rc != 0 )) || [[ -z $listing ]]; then
    print "无法列出进程（ps rc=$rc: ${listing[1,120]}），拒绝继续。在普通 Terminal 里运行本步。"; return 2
  fi
  for line in ${(f)listing}; do
    words=(${=line})
    [[ ${words[1]} == $$ ]] && continue
    if [[ $line == *"$RT/"* || $line == *"$HOSTCFG"* || ( -n $MAIN && $line == *"$MAIN"* ) ]]; then
      hits+=("${line[1,220]}")
    fi
  done
  (( ${#hits} == 0 )) && { print "guard: 没有进程在使用 $RT，Main 的 host 不在运行。"; return 0; }
  print "guard: ${#hits} 个进程在使用 $RT（或是 Main ${MAIN:-?}）:"
  print -l -- $hits
  print "自行查找: ps -axww -o pid,ppid,etime,command | grep -F .venv-runtime"
  return 1
}

step_00() {
  local C=$(claude_bin)
  mkdir -p $BASE/scratch
  say "shell (expect zsh) and PATH head"; print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}"; print -l -- ${path[1,4]}
  print "pnpm: $(command -v pnpm) | Node spawn: $(node -e 'const r=require("child_process").spawnSync("pnpm",["--version"],{encoding:"utf8"}); console.log(r.error ? "FAILED "+r.error.code : "OK "+r.stdout.trim())' 2>&1)"
  say "418: inherited GRAFTLING_CLAUDE_HOST_* / GRAPHTRAJ_CLAUDE_HOST_* (name=path; unset for every child command of this script)"
  (( ${#INHERITED_REPORT} )) && print -l -- "inherited: "$INHERITED_REPORT || print "inherited: none"
  credential_names
  say "Claude answers one line from the empty $BASE/scratch (expect model $MODEL, logged in)"
  print "claude: $C ($($C --version 2>&1))"
  (cd $BASE/scratch && clean /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 $C -p --model $MODEL --output-format stream-json --verbose \
      <<< 'In one line: name the model you are running as, and confirm you are logged in. Use no tool.' > $R/00-model.jsonl 2> $R/00-model.err)
  print "claude -p rc=$? (142 = 120 s timeout)"
  $CONDA -I -c 'import json,sys
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "result": print("answer:", str(d.get("result"))[:200], "| is_error:", d.get("is_error"), "| models:", list((d.get("modelUsage") or {}).keys()))' $R/00-model.jsonl
  say "production versions (expect graphtraj 0.1.0 and graftling 0.5.0; pip check clean)"
  $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version|Location|Editable)'
  $RT/bin/python -m pip check --disable-pip-version-check; print "pip check rc=$?"
  say "plugin files and hashes"; shasum -a 256 $PDIR/hooks/host_context.mjs $PDIR/hooks/hooks.json $PDIR/.claude-plugin/plugin.json
  grep -n '^const PLUGIN' $PDIR/hooks/host_context.mjs | sed 's/^/production copy: /'
  say "entry files (hashes; .mcp.json agents entry)"; shasum -a 256 $ENTRIES; tree mcp $H/.mcp.json
  say "backup must be absent; 393/417 backups are never touched"; ls -d $BK 2>&1; ls -d $HOME/graphtraj-adoption-393/backup $HOME/graphtraj-adoption-417/backup 2>&1
  print "volume ids: $(stat -f %d $H) $(stat -f %d $BASE)"; du -sh $RT
  say "running Task members (expect 'running lines: 0')"; (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | tee $R/00-members.txt | head -60
  print "running lines: $(grep -c 'running' $R/00-members.txt)"
  say "Task $TASK_ID ready for N's root dispatch: Team 1 active, budget not stopped"
  grep -E '^(stopped|corrections|allowance_minutes):' $H/.graphtraj/core/state/tasks/$TASK/execution-budget.yml
  grep -E 'status|state' $H/.graphtraj/core/state/tasks/$TASK/teams/1/team.yml | head -5
  say "current Claude Main Session"; local id=$(detect_main)
  if [[ -n $id ]]; then print -r -- $id > $BASE/main.session; MAIN=$id; print "MAIN=$id (saved to $BASE/main.session)"; else print "MAIN NOT FOUND"; fi
  say "processes using the venv now (information only; Main is expected here)"; guard
}

step_B() {
  rm -rf $W/src $N; mkdir -p $W/src $N
  git -C $WT archive $TARGET | tar -x -C $W/src || return 1
  local BP=$RT/bin/python
  $BP -c 'import setuptools, wheel' 2>/dev/null || { BP=$CONDA; print "生产 venv 没有 setuptools/wheel，用 $BP 构建（不修改 Conda）"; }
  say "build with $BP (--no-index --no-deps --no-build-isolation)"
  $BP -m pip wheel --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -w $N $W/src $W/src/src/graftling || return 1
  say "wheels and sha256 (expect graphtraj-0.1.0 and graftling-0.5.0)"; (cd $N && shasum -a 256 *.whl | tee SHA256SUMS)
  print $TARGET > $N/COMMIT
  [[ $(wheel_of graphtraj) == *graphtraj-0.1.0-* && $(wheel_of graftling) == *graftling-0.5.0-* ]] || { print "wheel 名称不符"; return 1; }
  say "no build/ or __pycache__ inside the wheels (expect leaked: 0)"
  local leaked=$(for f in $N/*.whl(N); do unzip -Z1 $f; done | grep -cE '(^|/)(build|__pycache__)/')
  print "leaked: $leaked"; [[ $leaked == 0 ]]
}

scratch_venv() {
  rm -rf $VV; $CONDA -m venv $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $(wheel_of graphtraj) $(wheel_of graftling) || return 1
  local S=$(site) D=($VV/lib/python*/site-packages(N)); D=${D[1]}
  cp -Rp $S/click $S/click-*.dist-info(N) $S/yaml $S/_yaml $S/pyyaml-*.dist-info(N) $S/websockets $S/websockets-*.dist-info(N) $D/ || return 1
  $VV/bin/python -m pip check --disable-pip-version-check; print "scratch venv pip check rc=$?"
  $VV/bin/python -I -c 'import graftling, graphtraj.runtimes.claude.host as h; print("graftling", graftling.__version__, h.__file__)'
}

step_V() {
  [[ -f $N/SHA256SUMS ]] || { print "没有 B 步骤的 wheel，先运行 B。"; return 1; }
  (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  local rc=0 C=$(claude_bin) P=$VV/bin/python
  say "scratch venv: new wheels plus production's click, yaml, websockets"; scratch_venv || return 1
  say "candidate plugin: new code writes into a scratch copy of production's plugin"
  rm -rf $W/vplug; mkdir -p $W/vplug; cp -Rp $PDIR $W/vplug/ || return 1
  $P -I $SD/adopt_plugin.py regen $H $C $VP || return 1
  local name differs=0; : > $R/V-plugin.diff
  for name in .claude-plugin/plugin.json hooks/hooks.json hooks/host_context.mjs; do
    if cmp -s $PDIR/$name $VP/$name; then print "SAME    $name"; else print "CHANGED $name"; differs=1; diff $PDIR/$name $VP/$name >> $R/V-plugin.diff; fi
  done
  (( differs )) && print "差异: $R/V-plugin.diff（$(grep -c '^[<>]' $R/V-plugin.diff) 行）；host_context.mjs 改变，所以 resume 时可能出现一次插件信任框。"
  say "418 judgement: production's copy keeps 'const PLUGIN = null', so 3a95423a's projectMaterial() is never called"
  grep -n '^const PLUGIN' $VP/hooks/host_context.mjs | sed 's/^/candidate: /'
  grep -q '^const PLUGIN = null;' $VP/hooks/host_context.mjs && print "418 hook change reaches the copy as bytes only: inert (plugin-only branch)" || { print "STOP: candidate is not the local-copy form"; rc=1; }
  say "claude plugin validate: baseline, candidate"; print "claude: $C ($($C --version))"
  local base=$($C plugin validate $PDIR 2>&1 | tee -a $R/V-validate.txt | grep -c '✘') cand=$($C plugin validate $VP 2>&1 | tee -a $R/V-validate.txt | grep -c '✘')
  print "✘ lines: baseline=$base candidate=$cand"; (( cand > base )) && rc=1
  say "entry files: what configuration --write would change; predictions only"
  rm -rf $VE; $P -I $SD/adopt_plugin.py entries $H $C $RT/bin/python $VE || rc=1
  say "read only against the real project: archives, configuration, roles; Task graph on an APFS clone of state"
  touch $W/V-marker; [[ -e $BASE/vstate ]] && chmod -R u+w $BASE/vstate && rm -rf $BASE/vstate; mkdir -p $BASE/vstate
  local part; for part in tasks worldline; do [[ -d $H/.graphtraj/core/state/$part ]] && cp -cRp $H/.graphtraj/core/state/$part $BASE/vstate/; done
  $P -I $SD/adopt_plugin.py readcheck $H $BASE/vstate || rc=1
  chmod -R u+w $BASE/vstate; rm -rf $BASE/vstate
  say "recorded hashes (I checks these did not change before it writes)"; shasum -a 256 $ENTRIES | tee $W/entries.sha256
  return $rc
}

# S: full suite of TARGET from this Worktree (editable install), 445/447 method, in the background.
step_S() {
  [[ $(git -C $WT rev-parse HEAD) == $TARGET ]] || git -C $WT diff --quiet $TARGET HEAD -- src tests pyproject.toml conftest.py \
    || { print "STOP: $WT differs from $TARGET in src/tests"; return 1; }
  [[ -z $(git -C $WT status --porcelain -- src tests) ]] || { print "STOP: uncommitted changes in $WT src/tests"; return 1; }
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  local S=$(site) D=($SV/lib/python*/site-packages(N)); D=${D[1]}
  for f in $S/websockets $S/websockets-*.dist-info(N); do ln -sfn $f $D/${f:t}; done   # 447: directly in site-packages
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj, click, yaml, websockets, pytest; print("graphtraj.__file__ =", graphtraj.__file__, "| websockets", websockets.__version__)') || return 1
  # 447 guard: an inner venv built the way tests/conftest.py builds one must import websockets.
  rm -rf $BASE/sprobe; $SV/bin/python -m venv --system-site-packages $BASE/sprobe || return 1
  local PD=($BASE/sprobe/lib/python*/site-packages(N)); print -r -- $D > $PD[1]/graphtraj_test_dependencies.pth
  $BASE/sprobe/bin/python -I -c 'import websockets; print("inner-style venv: websockets", websockets.__version__)' || { print "GUARD: inner-style venv cannot import websockets"; return 1; }
  rm -rf $R/S-shards; : > $R/S-suite.txt
  (cd $WT && nohup zsh $THIS _Srun >> $R/S-suite.txt 2>&1 &)
  print "started at $(date +%T) in the background (~15-25 min)."
}

step__Srun() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD) (product files = $TARGET)"
  (cd $WT && clean $SV/bin/python scripts/run_test_shards.py --shards 6 --log-dir $R/S-shards); print "== shards exit $?"
  local last=$(grep -E '^[0-9]+ (failed|errors|passed)' $R/S-suite.txt | tail -1)
  print "== totals: $last"
  print "== baseline e68fdd3d (446): 3930 passed, 73 skipped, 0 failed"
  print "== failures (each is new against the 0-failure baseline):"; cat $R/S-shards/failures.txt 2>/dev/null
  local PT=tests/test_pi_runtime.py::test_srt_gone_before_launch_is_refused
  if grep -qF -- $PT $R/S-shards/failures.txt 2>/dev/null; then print "== in suite: $PT FAILED"; else print "== in suite: $PT not failed (passed or skipped)"; fi
  print "== in suite, skip reasons naming test_pi_runtime.py:"; grep -h 'SKIPPED.*test_pi_runtime' $R/S-shards/*.log | sort -u
  print "== $PT alone (-rA):"
  (cd $WT && clean $SV/bin/python -m pytest -p no:cacheprovider -q -rA $PT 2>&1 | grep -E 'PASSED|SKIPPED|FAILED|ERROR|passed|skipped|failed' | tail -4)
  print "== DONE $(date +%T)"
}

vc_setup() {
  local G=$VV/bin/graphtraj
  [[ -x $G ]] || { print "没有 scratch venv，先运行 V。"; return 1; }
  mkdir -p $VPROJECT
  [[ -d $VPROJECT/.git ]] || git -C $VPROJECT init -q --initial-branch=main || return 1
  if ! git -C $VPROJECT rev-parse -q --verify HEAD > /dev/null; then
    print -r -- "# 448 scratch project" > $VPROJECT/README.md
    git -C $VPROJECT add README.md && git -C $VPROJECT -c user.name=448 -c user.email=448@invalid commit -qm "Initial source" || return 1
  fi
  if ! { [[ -e $VPROJECT/.graphtraj/core/config.yml || -e $VPROJECT/.graphtraj/config.yml ]] && git -C $VPROJECT rev-parse -q --verify refs/heads/dev > /dev/null; }; then
    (cd $VPROJECT && print -r -- y | clean $G setup) || return 1
  fi
  # Always regenerate: the scratch plugin and entries come from the new wheels.
  (cd $VPROJECT && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $VPROJECT --claude $(claude_bin) --write) || return 1
}

vc_stream() {
  local C=$(claude_bin)
  say "claude -p calls tasks discover and agents status (no dialog)"
  print -r -- 'Call mcp__agents__tasks once with {"action":"discover"} and mcp__agents__agents once with {"action":"execute","feature":"status","arguments":{}}. Print one line DONE and stop.' \
    | (cd $VPROJECT && clean $C -p --model $MODEL --output-format stream-json --verbose \
         --mcp-config $VPROJECT/.mcp.json --strict-mcp-config --allowedTools mcp__agents__tasks,mcp__agents__agents) > $R/Vc-stream.jsonl
  print "claude rc=$?"
  $CONDA -I -c 'import json,sys
names = None
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "system" and d.get("subtype") == "init":
        names = [p.get("name") if isinstance(p, dict) else p for p in d.get("plugins") or []]
        break
print("plugins in init:", names)
print("graphtraj-claude-host loaded:", "YES" if names and any("graphtraj-claude-host" in str(n) for n in names) else "NO")' $R/Vc-stream.jsonl
  tree stream $R/Vc-stream.jsonl mcp__agents__tasks mcp__agents__agents || return 1
  say "host.log tail"; tail -n 20 $VPROJECT/.graphtraj/claude-host/host.log
}

do_backup() {
  mkdir -p $BK && chmod 700 $BK || return 1
  date '+backup start %F %T'
  mkdir -p $BK/tools; cp -p $SD/steps.zsh $SD/proddiff.py $SD/adopt_tree.py $SD/adopt_plugin.py $BK/tools/ || return 1
  print -r -- $MAIN > $BK/tools/main.session
  say "manifest, then whole venv copy (cp -Rp)"; tree manifest $RT $BK/venv.manifest || return 1
  cp -Rp $RT $BK/venv || return 1; tree compare $BK/venv.manifest $BK/venv || return 1
  say "plugin copy"; tree manifest $PDIR $BK/plugin.manifest || return 1; cp -Rp $PDIR $BK/plugin || return 1
  say "entry files: copies (mode 600) and hashes"; mkdir -p $BK/entries
  local f; for f in $ENTRIES; do cp -p $f $BK/entries/${${f#$H/}//\//__} || return 1; done; chmod 600 $BK/entries/*
  shasum -a 256 $ENTRIES | tee $BK/entries.sha256
  say "archive clones (cp -cRp) and per-file version and sha256"
  mkdir -p $BK/archives
  if [[ -d $SESS ]]; then cp -cRp $SESS $BK/archives/sessions || return 1; else mkdir -p $BK/archives/sessions; fi
  tree archives $SESS $BK/archives.manifest || return 1
  for f in $ALSO; do [[ -r $f ]] && shasum -a 256 $f; done | sort -u > $BK/also.sha256
  touch $BK/COMPLETE; ls -ld $BK; date '+backup end %F %T'
}

do_install() {
  local S=$(site) P=$RT/bin/python w
  say "wheels (expect 2 x OK)"; cat $N/COMMIT; (cd $N && shasum -a 256 -c SHA256SUMS) || return 1
  [[ $(<$N/COMMIT) == $TARGET ]] || { print "COMMIT 不是目标提交"; return 1; }
  say "entry files still as V saw them (expect 3 x OK)"; shasum -a 256 -c $W/entries.sha256 || { print "入口文件在 V 之后被改过；重新运行 V。"; return 1; }
  say "install both wheels over the same versions (--force-reinstall)"
  $P -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-index --force-reinstall $(wheel_of graphtraj) $(wheel_of graftling) || return 1
  say "installed files vs the new wheels, file by file (versions are the same numbers as before)"
  $CONDA -I $SD/proddiff.py $S $RT $N > $R/I-verify.txt; local rc=$?; grep -E 'same=|EXTRA|LEFTOVER|NEW |CHANGED |^PASS|^FAIL' $R/I-verify.txt; (( rc == 0 )) || return 1
  say "entry scripts of both wheels point at this venv"
  local name; for w in $(wheel_of graphtraj) $(wheel_of graftling); do
    for name in $(unzip -p $w '*.dist-info/entry_points.txt' | awk '/^\[/{s=($0=="[console_scripts]")} s&&/=/{print $1}'); do
      [[ -x $RT/bin/$name && $(head -1 $RT/bin/$name) == "#!$RT/bin/python"* ]] && print "ok $name" || { print "BAD $name"; return 1; }
    done
  done
  say "pip check and imports"; $P -m pip check --disable-pip-version-check || return 1
  $P -c 'import graftling, graphtraj.runtimes.claude.host as h, graphtraj.execution.budget_idle_timer as t; print("graftling", graftling.__version__); print(h.__file__); print("445 timer:", t.__file__); assert graftling.__version__ == "0.5.0"' || return 1
  say "plugin regenerated by the installed code, plugin files only"; $P -I $SD/adopt_plugin.py regen $H $(claude_bin) $PDIR || return 1
  diff -r $PDIR $VP && print SAME-AS-VALIDATED || { print "插件与 V 的副本不同"; return 1; }
  say "entry files: write what V predicted, before -> after"
  $P -I $SD/adopt_plugin.py apply $H $VE || return 1
  local f; for f in $ENTRIES; do
    if cmp -s $f $BK/entries/${${f#$H/}//\//__}; then print "bytes unchanged: ${f#$H/}"
    else print "changed: ${f#$H/} (before -> after, secret-like values hidden)"
      $CONDA -I $SD/adopt_tree.py redactjson $BK/entries/${${f#$H/}//\//__} > $BK/diff.before
      $CONDA -I $SD/adopt_tree.py redactjson $f > $BK/diff.after; diff $BK/diff.before $BK/diff.after; rm -f $BK/diff.before $BK/diff.after; fi
  done
  tree mcp $H/.mcp.json
  say "also unchanged (information; any FAILED means another writer: tell Main)"; [[ -s $BK/also.sha256 ]] && shasum -a 256 -c $BK/also.sha256
  return 0
}

step_R() {
  local KEEP=$BK/after-install-$(date +%Y%m%dT%H%M%S) rc=0 f
  date '+R start %F %T'; mkdir -p $KEEP
  say "before restoring: how the venv differs from the pre-install manifest"; tree compare $BK/venv.manifest $RT | tail -1
  say "venv restored whole from the backup"; rm -rf $RT; cp -Rp $BK/venv $RT || return 1
  say "venv equals pre-install bytes? (expect SAME differences=0)"; tree compare $BK/venv.manifest $RT || rc=1
  say "plugin restored; the current one kept"; [[ -e $PDIR ]] && mv $PDIR $KEEP/plugin; mkdir -p ${PDIR:h}; cp -Rp $BK/plugin $PDIR || return 1
  tree compare $BK/plugin.manifest $PDIR || rc=1
  say "entry files restored from the backup copies; the current ones kept"
  mkdir -p $KEEP/entries
  for f in $ENTRIES; do
    local saved=$BK/entries/${${f#$H/}//\//__}
    if cmp -s $f $saved; then print "already as before: ${f#$H/}"; else cp -p $f $KEEP/entries/ 2>/dev/null; cp -p $saved $f || rc=1; print "restored: ${f#$H/}"; fi
  done
  shasum -a 256 -c $BK/entries.sha256 || rc=1
  say "archives: same graftling 0.5.0 before and after, so they stay; versions (information)"; tree versions $SESS
  say "a stale channel file would make the restored host refuse with host-busy"
  local CH=$H/.graphtraj/claude-host/live/channel.json
  if [[ -e $CH ]]; then mv $CH $KEEP/channel.json; print "moved out: $CH"; else print "no channel file"; fi
  say "versions and pip check"; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'; $RT/bin/python -m pip check --disable-pip-version-check || rc=1
  return $rc
}

# Nr: the member's children (n448-stop, n448-ok), read from graftling's records:
#   <root>/control/agents/<agent>.json  (graftling/control.py _path / status walk, line ~1565),
#   fields: parent (control.py _document 'parent'), executions[-1].notification (control.py ~430-463,
#   exposed as last_result.notification at ~1872), executions[-1].id, last_message.
# and the member's Session archive <swarm>/sessions/<id>/session.jsonl, counting lines naming each end.
nr_read() {
  $CONDA -I - $H $SESS <<'PY'
import json, sys
from pathlib import Path
h, sess = Path(sys.argv[1]), Path(sys.argv[2])
roots = sorted({p.parent for g in ('.graphtraj/swarm/control/agents/*.json', '.graphtraj/*/control/agents/*.json', '.graphtraj/core/runner/control/agents/*.json') for p in h.glob(g)})
print('record directories:', [str(r) for r in roots] or 'NONE')
records = []
for r in roots:
    for p in r.glob('*.json'):
        try: d = json.loads(p.read_text())
        except Exception: continue
        if d.get('name') in ('n448-stop', 'n448-ok'): records.append((p, d))
if not records:
    print('NO n448 children found. Did N run, and did the member create them with these names?'); sys.exit(1)
members = {}
for p, d in sorted(records, key=lambda x: x[1].get('name')):
    ex = (d.get('executions') or [{}])[-1]
    print(f"child {d.get('name')}: agent={d.get('agent')} parent={d.get('parent')} execution={ex.get('id')} "
          f"state={ex.get('state')} outcome={ex.get('outcome')} notification={ex.get('notification')} "
          f"last_message={'null' if ex.get('last_message') is None else repr(str(ex.get('last_message'))[:80])} retired={d.get('retired_at') is not None}")
    print(f"  CHECK notification delivered: {'PASS' if ex.get('notification') == 'delivered' else 'FAIL'}")
    members.setdefault(d.get('parent'), []).append((d.get('name'), ex.get('id')))
for parent, ends in members.items():
    rec = None
    for r in roots:
        for p in r.glob('*.json'):
            try: d = json.loads(p.read_text())
            except Exception: continue
            if d.get('agent') == parent: rec = d
    print(f"parent {parent}: record found={rec is not None} name={rec and rec.get('name')} session={rec and rec.get('session')}")
    sid = rec and rec.get('session')
    sid = sid.get('id') if isinstance(sid, dict) else sid
    files = [sess / str(sid) / 'session.jsonl'] if sid else []
    files = [f for f in files if f.exists()] or [f for f in sess.glob('*/session.jsonl') if any(e and e in f.read_text(errors='replace') for _, e in ends)]
    for f in files:
        lines = f.read_text(errors='replace').splitlines()
        for name, eid in ends:
            hits = [i for i, l in enumerate(lines) if eid and eid in l]
            print(f"  archive {f.parent.name}: lines naming {name} execution {eid}: {len(hits)} at {hits[:8]}")
    print('MEMBER', parent)
    print('SESSION', sid or '')
PY
}

R_HINT="回退（USER，先在 Main 里 /exit）: zsh $BK/tools/steps.zsh R"

case $STEP in
help) print "顺序: 00 → B → V → S（后台）→ Vc（必要时 Vu）→ I（USER）→ M → Mps → inbox → N → Nr → done；备份完成后可回退: R。"
  next "zsh $THIS 00" ;;

00) print "[00] Main. 预检。对话框: 无。只写 $BASE/scratch、$BASE/main.session 与 $R。约 2 分钟。"
  logged $R/00.txt step_00
  summary 00 "$(grep -E 'ZSH_VERSION|Node spawn|inherited|answer:|^Version|pip check rc|production copy|running lines|^stopped|MAIN=|MAIN NOT|volume ids' $R/00.txt)"
  print "成功: ZSH_VERSION 有值；answer 里 models 含 $MODEL 且 is_error False；graphtraj 0.1.0 与 graftling 0.5.0；pip check rc=0；running lines: 0；stopped: false；$BK 'No such file'；MAIN=<id>。"
  print "若 'inherited:' 列出名字：本脚本已对所有子命令 unset；记下它来自哪个项目（418 提醒）。"
  print "若 answer 有 login/API key 字样: USER 在 Terminal 运行 claude 登录后重跑 00。若 MAIN NOT FOUND 或 ps 被拒: 由 USER 在普通 Terminal 运行 00。"
  next "zsh $THIS B" ;;

B) print "[B] Main. 从 git archive $TARGET 构建两个 wheel（不联网、不改 Conda 和生产）。对话框: 无。"
  if logged $R/B.txt step_B; then
    summary B "$(grep -E '\.whl$|leaked' $R/B.txt)"; print "成功: graphtraj-0.1.0 与 graftling-0.5.0 各一个 wheel 及 sha256；leaked: 0。"
    next "zsh $THIS V"
  else print "\nB 失败。不要联网安装，把 $R/B.txt 交给 Main。"; exit 1; fi ;;

V) print "[V] Main. 安装前校验。对话框: 无。只读真实项目；scratch venv、候选插件、入口文件预测都在生产之外。"
  if logged $R/V.txt step_V; then
    touch $R/V.ok
    summary V "$(grep -E '^(SAME|CHANGE)|差异|418|✘ lines|    |read_session|loaded|task graph' $R/V.txt)"
    print "成功: 候选 ✘ 不多于 baseline；'418 hook change reaches the copy as bytes only: inert'；入口文件 SAME 或只列出可解释的变化；read_session failures=0。"
    next "zsh $THIS S"
  else print "\nV 不通过，不要做 I，把 $R/V.txt 交给 Main。本步没有改动生产。"; exit 1; fi ;;

S) print "[S] Main. TARGET 的全套测试（从本 Worktree 导入，6 个 shard，后台）。对话框: 无。立即返回。"
  if logged $R/S-setup.txt step_S; then
    print "状态（Main 随时）:  tail -n 25 $R/S-suite.txt"
    print "完成标志: '== DONE'。成功: '== totals:' 无 failed（基线 3930 passed、73 skipped、0 failed），'== failures' 为空；"
    print "  并读出 test_srt_gone_before_launch_is_refused 的结果（'in suite' 一行 + '-rA' 一行: PASSED / SKIPPED [..] 原因 / FAILED）。"
    print "失败的 ID: $R/S-shards/failures.txt；某 shard 'ABNORMAL': 把那一行交给 Main。S 可与 Vc 同时进行。"
    next "zsh $THIS Vc"
  else print "\nS 未启动（见上面 STOP 或 GUARD 行），把 $R/S-setup.txt 交给 Main。"; exit 1; fi ;;

Vc) print "[Vc] Main. 隔离项目 $VPROJECT 里用新 wheel 的真实 claude -p。对话框: 无。约 2 分钟。"
  logged $R/Vc.txt vc_setup || { print "\nVc 准备失败，把 $R/Vc.txt 交给 Main。"; exit 1; }
  logged $R/Vc.txt vc_stream; rc=$?
  if [[ $(grep 'graphtraj-claude-host loaded:' $R/Vc.txt | tail -1) == *'loaded: NO'* ]]; then
    print "\n插件未加载：Claude Code 只在已信任的文件夹加载项目插件。由 USER 做一次 Vu，然后 Main 重跑 Vc。"
    next "USER: zsh $THIS Vu    （之后 Main: zsh $THIS Vc）"; exit 1
  fi
  if (( rc == 0 )); then
    touch $R/Vc.ok
    summary Vc "$(grep -E '^(PASS|FAIL)|loaded:' $R/Vc.txt | tail -4)"
    print "成功: 'graphtraj-claude-host loaded: YES'，PASS mcp__agents__tasks 与 PASS mcp__agents__agents。"
    print "\n下一步是 USER 的: 先在这个 Claude Main 里输入 /exit，然后在普通 Terminal 运行 I。S 在后台继续，不受影响（它不用 .venv-runtime 的进程）。"
    next "USER（Main 已 /exit）: zsh $THIS I"
  else print "\nVc 不通过，不要做 I，把 $R/Vc.txt 与 $R/Vc-stream.jsonl 交给 Main。"; exit 1; fi ;;

Vu) print "[Vu] USER（一次；需要终端和对话框，Main 做不了）。在普通 Terminal 运行:"
  print "  cd $VPROJECT && claude"
  print "对话框: 'Do you trust the files in this folder?'（写着 $VPROJECT）选 'Yes, proceed'。若再问项目的 MCP server 'agents' 或插件，为本项目批准。"
  print "然后输入 /exit 回车，不要发消息。其它任何框按 Esc 并告诉 Main 标题。"
  next "Main: zsh $THIS Vc" ;;

I) need_main
  print "[I] USER. 备份并安装。对话框: 无。需 Main 已 /exit；本步结束前不要打开 Main。约 3 分钟。"
  [[ -e $BK ]] && { print "已存在 $BK，拒绝覆盖备份。$R_HINT"; exit 1; }
  [[ -e $R/V.ok && -e $R/Vc.ok ]] || { print "V 或 Vc 还没有通过，先运行它们。"; exit 1; }
  print "确认已在 Claude Code Main（$MAIN）里输入 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  if ! guard; then print "拒绝继续：先让上面的进程结束（Main /exit 后它的 host 会退出），再重跑 I。"; exit 1; fi
  date '+I start %F %T' | tee -a $R/I.txt
  logged $R/I.txt do_backup || { print "\n备份失败，生产未被改动。把输出交给 Main；$BK 需要由 Main 决定如何处理。"; exit 1; }
  if ! logged $R/I.txt do_install; then
    print "\n安装或校验失败。不要 resume Main，立刻运行回退:\n  zsh $BK/tools/steps.zsh R"; exit 1
  fi
  touch $R/I.ok
  summary I "$(grep -E 'Successfully|^PASS|^FAIL|^graftling 0|445 timer|SAME-AS-VALIDATED|WRITTEN|UNCHANGED|bytes unchanged|^changed' $R/I.txt)"
  print "成功: Successfully installed graftling-0.5.0 graphtraj-0.1.0；PASS n FAIL 0；graftling 0.5.0；445 timer 在 $RT；SAME-AS-VALIDATED；入口文件 bytes unchanged 或 V 已列出的变化。"
  print "$R_HINT"
  print "\n下一步（USER，普通 Terminal）恢复 Main:\n  cd $H && claude --resume $MAIN"
  print "预期对话框: 至多一个插件/hooks 信任框（host_context.mjs 的字节变了），选信任。其它任何框选拒绝并告诉 Main。"
  print "恢复后在 Main 里粘贴第一句（见 M）:"
  next "Main: zsh $THIS M" ;;

M) need_main; cat <<EOF | tee $R/M-prompts.txt
[M] Main（恢复后的 Claude Main，Session $MAIN）。逐条粘贴，一次一条。对话框: 无。Main 把原始结果存到 $R/M-<字母>.txt。

[a 定义第 4 项: 安装后第一次 Main 重启，通知不重复 → 新插件已加载] 恢复后第一句:
Before anything else: list every GraphTraj notice delivered to you since this resume (alias, event, first line), and for each say whether you had already seen that same notice before this resume. Use no tools.
  成功: 没有安装前已见过的通知再出现。若有重复: 记下 alias/event/次数，由 Main 登记缺陷 Task。

[b 工具与插件] 先输入 /agents-context ，再粘贴:
Using only the tasks tool: discover. Print the raw list of feature names, and nothing else.
Using only the agents tool: status with no agent. Print the raw result.
  成功: /agents-context 显示 current Session $MAIN 与 agents/tasks 已注册；discover 有功能列表；status 有结果。

[c] Main 的 Bash（无对话框）: zsh $THIS Mps   然后   zsh $THIS inbox
EOF
  next "zsh $THIS Mps" ;;

Mps) need_main; print "[Mps] Main. 运行中的 host 与它的父 claude。对话框: 无。只读。"
  { print "at $(date '+%F %T')"; hit=$(ps -axww -o pid=,ppid=,command= | grep -F -- "$HOSTCFG" | grep -F -- ' serve ')
    print -r -- "host: $hit"; words=(${=hit}); PPIDV=${words[2]:-}
    if [[ -n $PPIDV ]]; then C=$(ps -ww -o command= -p $PPIDV); print -r -- "parent claude: $C"
      [[ $hit == *"$RT/bin/python"* ]] && print "host uses .venv-runtime: yes" || print "host uses .venv-runtime: NO"
      [[ $C == *"--resume $MAIN"* ]] && print "parent is claude --resume $MAIN: yes" || print "parent is claude --resume $MAIN: NO"
    else print "NOT FOUND: no host serving $HOSTCFG"; fi
    say "host.log tail"; tail -n 30 $H/.graphtraj/claude-host/host.log; print "outcome=ok lines in tail: $(tail -n 30 $H/.graphtraj/claude-host/host.log | grep -c 'outcome=ok')"
  } 2>&1 | tee -a $R/Mps.txt
  summary Mps "$(grep -E '^(host uses|parent is|NOT FOUND|outcome=ok)' $R/Mps.txt | tail -3)"
  print "成功: host uses .venv-runtime: yes；parent is claude --resume $MAIN: yes；outcome=ok lines > 0。"
  next "zsh $THIS inbox" ;;

inbox) need_main; print "[inbox] Main. Main 的通知队列。对话框: 无。只读。"
  { for f in $INBOX/*.jsonl(N); do print "== ${f:t}"; tree inbox $f; done; } 2>&1 | tee -a $R/inbox.txt
  print "Claude Main $MAIN 的文件: $(inbox_key "claude:$MAIN").jsonl"
  summary inbox "$(grep -E '^(==|duplicate|records)' $R/inbox.txt | tail -12)"
  print "成功: 每个文件 duplicate ids: 0。"
  next "zsh $THIS N" ;;

N) cat <<EOF | tee $R/N-prompts.txt
[N] Main. 定义第 3 项（446 的生产核对）。在 Claude Main 里粘贴这一条。对话框: 无（成员只用 agents 工具；sleep 在孙级里，由 Claude 子级自己的权限决定）。
Using only the tasks tool: execute swarm with arguments {"tasks":[{"task_id":"$TASK_ID","role":"opus_coding_team.advisor","instruction":"Use only the agents tool for all of this. (1) Create two claude children with configuration opus_coding_team.advisor: n448-stop with instruction 'Run the shell command sleep 600, then reply DONE.' and n448-ok with instruction 'Reply with exactly one line: PONG-448-OK. Use no tools.' (2) Stop n448-stop by the agent id its create returned. (3) Use the agents wait on both agent ids until both have ended. (4) Reply with: every parent input you received, in order, each with its event (interrupted, failed, completed), child alias and execution id; how many inputs you received for each end; and, quoted exactly, the last_message value of the raw wait output for each end (write null if it is null). (5) Then retire both children by their agent ids and include the raw retire results."}]}. Print the raw result and end your turn. Do not wait.
  成功: launch_status 不是 failed。几分钟内 Main 收到这个成员一次 completed 通知，回复里: 每个结束恰好一条输入；两个 wait 的 last_message 都是 null。
  成员完成后（收到它的 completed 通知），Main 的 Bash（无对话框）:
EOF
  next "zsh $THIS Nr" ;;

Nr) print "[Nr] Main. 子级记录与成员 Session 档案（只读）。对话框: 无。"
  nr_read 2>&1 | tee $R/Nr.txt; rc=${pipestatus[1]}
  (cd $H && clean $RT/bin/graphtraj task members) 2>&1 | grep -F -- "$TASK_ID" | head -10 | tee -a $R/Nr.txt
  MEMBER=$(sed -n 's/^MEMBER //p' $R/Nr.txt | tail -1); SID=$(sed -n 's/^SESSION //p' $R/Nr.txt | tail -1)
  summary Nr "$(grep -E '^child|CHECK|^parent|archive' $R/Nr.txt)"
  print "成功（定义第 3 项）: 两个 child 的 parent 都是成员别名 $MEMBER，且该别名出现在上面的 task members 行；两条 'CHECK notification delivered: PASS'；"
  print "  每个 execution 在成员档案里出现的行数与成员回复的“每个结束一条输入”一致（行数包括 create/stop/wait 的工具结果，以 Main 的 session_read 为准）。不成立的交 Main 登记缺陷 Task。"
  [[ -n $SID ]] && print "\n复核（Main 粘贴）:\nUsing only the tasks tool: session_read with {\"session\":\"$SID\",\"limit\":80}. Count the parent inputs (GraphTraj/Graftling notices) naming each n448 execution id printed by Nr, and print the counts only."
  [[ -n $MEMBER ]] && print "\n清退成员（Main 粘贴）:\nUsing only the agents tool: retire the agent $MEMBER by the agent id the N swarm result returned (not by its alias), and print the raw result."
  next "zsh $THIS done"; exit $rc ;;

done) print "[done] Main. 结束状态。对话框: 无。只读。"
  { S=$(site); cat $N/COMMIT; cat $N/SHA256SUMS; $RT/bin/python -m pip show graphtraj graftling 2>/dev/null | grep -E '^(Name|Version)'
    $CONDA -I $SD/proddiff.py $S $RT $N > $R/done-verify.txt; grep -E 'same=|EXTRA|LEFTOVER|^PASS|^FAIL' $R/done-verify.txt
    shasum -a 256 $ENTRIES; tree versions $SESS
    vals=("${(@f)$(key_values)}"); hits=0
    for v in $vals; do [[ -n $v ]] && hits=$(( hits + $(grep -rlF -- "$v" $R 2>/dev/null | wc -l) )); done
    print "raw files containing an exported key value: $hits"
    tail -n 12 $R/S-suite.txt 2>/dev/null; ls -la $R; } 2>&1 | tee -a $R/done.txt
  summary done "$(grep -E '^PASS|^FAIL|^Version|archives=|containing an exported key|== totals|== DONE' $R/done.txt)"
  print "成功: PASS n FAIL 0；raw files containing an exported key value: 0；S 有 '== DONE'。把 $R 的路径交给 Main。$R_HINT" ;;

R) need_main; print "[R] USER. 回退到安装前。对话框: 无。先在 Main 里 /exit。按回车继续，Ctrl-C 放弃。"; read -r REPLY
  [[ -e $BK/COMPLETE ]] || { print "$BK 没有完整备份（没有 COMPLETE）。安装只在备份完成后开始，所以生产没有被安装改动；告诉 Main。"; exit 1; }
  guard || exit 1
  if logged $R/R.txt step_R; then
    summary R "$(grep -E '^(SAME|DIFF)|restored|already as|^Version' $R/R.txt)"
    print "成功: venv 与 plugin 都是 SAME differences=0；三个入口文件 OK；pip check 通过。"
    print "然后（USER）: cd $H && claude --resume $MAIN （插件字节又变了，至多一个插件信任框，选信任；其它框拒绝并告诉 Main）。"
  else print "\n回退后仍有不一致（DIFF 或 FAILED），不要 resume，把 $R/R.txt 交给 Main。可以重复运行 R。"; exit 1; fi ;;

_Srun) step__Srun ;;
_backup) guard || exit 1; [[ -e $BK ]] && exit 1; logged $R/I.txt do_backup ;;   # rehearsal only
*) print "unknown step $STEP"; next "zsh $THIS help" ;;
esac

#!/bin/zsh
# Task 650 correction 3 rehearsal (Engineer) of step M on the Mac: `zsh scripts/verify-650/steps.zsh M` with a stand-in
# claude (VERIFY650_M_CLAUDE; no download) and graftling from a bundle checkout on PYTHONPATH (VERIFY650_M_PYTHON; no uv).
# The stand-in emits an init event whose plugins list agents-claude-host as its mode says, prints its own environment
# to stderr (so the evidence shows what M gave it), starts a child, and then waits to be killed. Modes:
#   trust        listed when the folder is trusted in CLAUDE_CONFIG_DIR/.claude.json, or with --plugin-dir
#   never        listed only with --plugin-dir (M then runs the interactive variant, which also misses it)
#   untrusted    always listed
# Checks: verdict last; the recommended value per mode; the stand-in's HOME/CLAUDE_CONFIG_DIR/TMPDIR inside M's temp
# dir and no credential variable but the dummy token; nothing left running; the temp dir deleted; no Mac home path in
# the evidence. Consoles: rehearsal/<round>/m-NN-*.txt.
emulate -L zsh
setopt pipe_fail no_unset
HERE=${0:A:h:h}
WT=$(git -C $HERE rev-parse --show-toplevel)
OUT=$HERE/rehearsal/${1:-c4}
mkdir -p $OUT
rm -f $OUT/m-*.txt(N)
HARNESS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
S=$(mktemp -d ${TMPDIR:-/tmp}/v650m-rehearsal.XXXXXX)
cat > $S/claude <<EOF
#!$HARNESS/.venv-runtime/bin/python
import json, os, subprocess, sys, time
from pathlib import Path
mode = Path('$S/mode').read_text().strip()
args = sys.argv[1:]
if args[:1] == ['--version']:
    print('2.1.314 (Claude Code) (stand-in; hasTrustDialogAccepted)'); sys.exit(0)
env = {k: v for k, v in os.environ.items() if k in ('HOME', 'CLAUDE_CONFIG_DIR', 'TMPDIR', 'ANTHROPIC_BASE_URL', 'PATH')}
cred = sorted(k for k in os.environ if any(p in k.upper() for p in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')))
print('STANDIN-ENV ' + json.dumps({'env': env, 'credential_names': cred}), file=sys.stderr, flush=True)
config = Path(os.environ['CLAUDE_CONFIG_DIR']) / '.claude.json'
trusted = config.exists() and any(json.loads(config.read_text()).get('projects', {}).get(k, {}).get('hasTrustDialogAccepted')
                                  for k in (os.getcwd(), os.path.realpath(os.getcwd())))
child = subprocess.Popen(['/bin/sleep', '6504'])
with open('$S/pids', 'a') as out:
    out.write(f'{os.getpid()} {child.pid}\\n')
if '-p' not in args:  # interactive (pty)
    print('[DEBUG] plugin agents-claude-host: skipped (stand-in, interactive)', flush=True); time.sleep(120); sys.exit(0)
listed = '--plugin-dir' in args or mode == 'untrusted' or (mode == 'trust' and trusted)
plugins = [{'name': 'cc-plugin-agents-md', 'path': 'builtin'}] + ([{'name': 'agents-claude-host', 'path': 'x'}] if listed else [])
print('[DEBUG] plugin agents-claude-host: ' + ('loaded' if listed else 'not loaded'), file=sys.stderr, flush=True)
print(json.dumps({'type': 'system', 'subtype': 'init', 'plugins': plugins, 'mcp_servers': [{'name': 'graftling', 'status': 'connected'}]}), flush=True)
time.sleep(120)
EOF
chmod +x $S/claude
export VERIFY650_M_CLAUDE=$S/claude VERIFY650_M_PYTHON=$HARNESS/.venv-runtime/bin/python VERIFY650_M_EVIDENCE=$S/evidence
N=0
typeset -a SUMMARY
for mode want in trust trust never plugin-dir untrusted plugin-dir; do
  (( N++ ))
  print -r -- $mode > $S/mode
  file=$OUT/m-$(printf %02d $N)-$mode.txt
  rm -rf $S/evidence
  print -r -- "\$ zsh scripts/verify-650/steps.zsh M   (stand-in claude, mode $mode)" > $file
  (cd $WT && zsh scripts/verify-650/steps.zsh M) 2>&1 | sed -E "s#$S#<rehearsal>#g; s#/Users/[^ '\";),]*#<mac-path>#g" >> $file
  last=$(tail -1 $file)
  envs=$(grep -h -o 'STANDIN-ENV .*' $S/evidence/*-stderr.txt 2> /dev/null)
  iso=$(print -r -- $envs | /usr/bin/python3 -I -c 'import json, sys
rows = [json.loads(line[12:]) for line in sys.stdin if line.startswith("STANDIN-ENV ")]
inside = all(all(r["env"][k].startswith("<tmp>") for k in ("HOME", "CLAUDE_CONFIG_DIR", "TMPDIR")) for r in rows)
creds = sorted({n for r in rows for n in r["credential_names"]})
urls = sorted({r["env"]["ANTHROPIC_BASE_URL"] for r in rows})
print("%d run(s); HOME, CLAUDE_CONFIG_DIR and TMPDIR inside the temp dir: %s; credential-class names: %s; base URL %s" % (len(rows), inside, creds, urls))')
running=0; for p in $(cat $S/pids 2> /dev/null); do kill -0 $p 2> /dev/null && (( running++ )); done; : > $S/pids
homeleak=$(grep -r -l -e "$HOME" -e '/Users/' $S/evidence 2> /dev/null | wc -l | tr -d ' ')
ok=no; [[ $last == 'VERDICT 650 M: PASS'* ]] && grep -q "RECOMMEND CLAUDE_HOST_LOAD=$want" $file && ok=yes
SUMMARY+="m-$(printf %02d $N) mode $mode: expects PASS with CLAUDE_HOST_LOAD=$want -> $ok; isolation: $iso; stand-in and child processes still alive (by pid): $running of $(( 2 * $(grep -c 'STANDIN-ENV' $S/evidence/*-stderr.txt 2> /dev/null | awk -F: '{s+=$2} END {print s+0}') )); evidence files with a Mac home path: $homeleak; temp dir deleted line: $(grep -c 'temporary directory deleted: yes' $file)"
done
pkill -f 'sleep 6504' 2> /dev/null
{
  print -r -- "Task 650 step M rehearsal (stand-in claude; consoles m-01-$(printf %02d $N) in ${OUT:t}/)"
  print -lr -- $SUMMARY
} | tee $OUT/m-00-summary.txt
rm -rf $S

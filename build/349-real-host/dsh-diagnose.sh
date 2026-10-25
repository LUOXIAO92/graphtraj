#!/bin/bash
# Task 349: find why DSH answers HTTP 404 in the isolated project but works elsewhere.
#   /bin/bash dsh-diagnose.sh <working-workspace> [working-profile]
# <working-workspace> is the directory where the user's standalone DSH works;
# [working-profile] is the profile used there (default: headless).
# Prints variable NAMES and redacted configuration only; never a value of a key,
# token or secret. Changes no DSH installation, profile or .env file.
set -u
T=${T:-/private/tmp/graphtraj-349}
WORK=${1:?working workspace required}
PROFILE=${2:-headless}
OUT=$T/evidence/dsh-diagnose
mkdir -p "$OUT"
DSH_HOME_DIR=${DSH_HOME:-$HOME/.dsh}

redact() {
  # Keep keys and structure; hide values of anything secret-looking.
  sed -E 's/((api[_-]?key|key|token|secret|password|authorization|bearer)[A-Za-z_]*["'"'"']?[[:space:]]*[:=][[:space:]]*).*/\1<redacted>/I'
}

{
  echo "== shell variables that DSH may read (names only)"
  env | grep -E '^(DEEPSEEK|DSH|ANTHROPIC|OPENAI|OPENCODE)[A-Z_]*=' | sed 's/=.*/=<set>/' | sort
  echo "== .env layers DSH reads: <cwd>/.env (project) then \$DSH_HOME/.env (user); names only"
  for f in "$T/project/.env" "$WORK/.env" "$DSH_HOME_DIR/.env"; do
    if [ -f "$f" ]; then echo "$f:"; grep -oE '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*' "$f" | sed 's/export //' | sed 's/^/  /'
    else echo "$f: (none)"; fi
  done
} | tee "$OUT/environment.txt"

# The model, provider and endpoint rows of each composed profile, per cwd.
rows() {
  awk '/^- id: (llm-deepseek|llm-deepseek-account|agent-default-model|llm-pi-ai|llm)[a-z-]*$/{p=1} /^- id: /&&!/llm|agent-default-model/{p=0} p' | redact
}
(cd "$T/project" && dsh --profile headless --dump-config 2>&1) | rows > "$OUT/project-headless.txt"
(cd "$WORK" && dsh --profile headless --dump-config 2>&1) | rows > "$OUT/work-headless.txt"
(cd "$WORK" && dsh --profile "$PROFILE" --dump-config 2>&1) | rows > "$OUT/work-$PROFILE.txt"
echo "== profile rows: project/headless versus work/headless (cwd effect)"
diff "$OUT/project-headless.txt" "$OUT/work-headless.txt" && echo "(identical)"
echo "== profile rows: work/headless versus work/$PROFILE (profile effect)"
diff "$OUT/work-headless.txt" "$OUT/work-$PROFILE.txt" && echo "(identical)"

# One-line answers without any GraphTraj overlay, then with the kit launcher's overlay.
answer() {
  # Print only the turn_end error code or the final text.
  python3 -c 'import json,sys
for line in sys.stdin:
    try: e=json.loads(line)
    except ValueError: continue
    if e.get("type")=="status" and e.get("phase")=="turn_end" and e.get("reason",{}).get("kind")=="error":
        print("ERROR", e["reason"]["error"].get("code"), e["reason"]["error"].get("status"))
    if e.get("type")=="final": print("FINAL", repr(e.get("text","")[:80]))'
}
echo "== A: plain headless in the working workspace"
(cd "$WORK" && dsh --profile headless --json "Reply with the single word OK" 2>/dev/null) | answer | tee "$OUT/a.txt"
echo "== B: plain headless in the isolated project (no GraphTraj overlay)"
(cd "$T/project" && dsh --profile headless --json "Reply with the single word OK" 2>/dev/null) | answer | tee "$OUT/b.txt"
echo "saved: $OUT"

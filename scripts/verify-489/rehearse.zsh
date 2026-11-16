#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 489 rehearsal with stubs only: a fake Harness under $TMPDIR and a stub `claude`. Never runs the real claude
# and never touches the real Harness tmp/. Usage: zsh scripts/verify-489/rehearse.zsh [python]
#   python: a Python >= 3.9 for the helper (default: the Harness .venv-runtime python, only executed).
set -u
SD=${0:A:h}
ISO=${SD:h}/verify-common/claude_isolation.py
PY=${1:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/bin/python}
R=${TMPDIR:-/tmp}/rehearse489
FH=$R/harness
STUB=$R/bin
OUT=$R/out
rm -rf $R && mkdir -p $FH/tmp $STUB $OUT
print -r -- "# Fake Harness instructions" > $FH/AGENTS.md
print -r -- "Every Agent in this fake Harness must answer in the rehearsal voice of Task 489 only." >> $FH/AGENTS.md
cat > $STUB/claude <<EOF
#!/bin/zsh
# Stub claude (Task 489 rehearsal): plugin cc-plugin-agents-md is loaded unless the project's own settings disable it.
if [[ \${1:-} == --version ]]; then print '2.1.325 (Claude Code)'; exit 0; fi
p=\$(cat)
tag=\${\${p#*Line 1: }%% *}
if grep -qF '"cc-plugin-agents-md@builtin": false' .claude/settings.local.json 2>/dev/null; then
  plugins='[]'; files=NONE
else
  plugins='[{"name": "cc-plugin-agents-md", "path": "builtin"}]'; files=$FH/AGENTS.md
fi
print -r -- '{"type": "system", "subtype": "init", "model": "claude-opus-5-5", "plugins": '\$plugins'}'
print -r -- '{"type": "result", "subtype": "success", "is_error": false, "result": "'\$tag' claude-opus-5-5 logged in\\nFILES: '\$files'", "modelUsage": {"claude-opus-5-5": {}}}'
EOF
chmod +x $STUB/claude
fails=0
verdict() { if [[ $1 == 0 ]]; then print "PASS rehearsal: $2"; else print "FAIL rehearsal: $2"; fails=$((fails + 1)); fi; }
steps() { VERIFY489_H=$FH VERIFY489_BASE=$FH/tmp/489 VERIFY489_OUT=$OUT VERIFY489_PY=$PY VERIFY489_STUB_BIN=$STUB \
  zsh $SD/steps.zsh "$@"; }
iso() { $PY -I $ISO "$@"; }
# JSON lines for a crafted stream: $1 file, then python literals (one record each) evaluated with H/P/PROMPT bound.
records() { local f=$1; shift; $PY -I -c 'import json, sys
H, P, PROMPT = sys.argv[2], sys.argv[3], open(sys.argv[4]).read().strip()
with open(sys.argv[1], "w") as out:
    for x in sys.argv[5:]:
        out.write((x[4:] if x.startswith("raw:") else json.dumps(eval(x))) + "\n")' $f $FH $FH/tmp/489/project $R/prompt.txt "$@"; }
init_clean='{"type": "system", "subtype": "init", "plugins": []}'
init_loaded='{"type": "system", "subtype": "init", "plugins": [{"name": "cc-plugin-agents-md"}]}'
result() { print -r -- "{\"type\": \"result\", \"is_error\": False, \"result\": $1, \"modelUsage\": {\"claude-opus-5-5\": {}}}"; }

print "== rehearsal of verify-489 with stubs: fake Harness $FH, stub $STUB/claude, helper python $PY ($($PY -I -V))"
for s in 00 A B; do
  print "\n== step $s"
  steps $s > $OUT/$s.txt 2>&1; rc=$?
  cat $OUT/$s.txt
  grep -q "^PASS $s:" $OUT/$s.txt; verdict $(( rc || $? )) "step $s exits 0 with PASS $s"
done
grep -q '^source: builtin cc-plugin-agents-md' $OUT/B.txt; verdict $? "B concludes source: builtin cc-plugin-agents-md"
print "\n== step A refuses to delete a directory without its marker"
rm -rf $FH/tmp/489/before && mkdir -p $FH/tmp/489/before && print keep > $FH/tmp/489/before/user-file
steps A > $OUT/A-nomarker.txt 2>&1; rc=$?; cat $OUT/A-nomarker.txt
[[ $rc != 0 && -f $FH/tmp/489/before/user-file ]] && grep -q '^STOP: .*without the marker' $OUT/A-nomarker.txt; verdict $? "unmarked directory kept, step STOPs"
print "\n== usage"
steps help; verdict $? "dispatch prints usage"

print "\n== helper edge cases"
iso prompt EDGE-OK > $R/prompt.txt
mkdir -p $FH/tmp/489/project
print -r -- "-- settings outside <H>/tmp"
out=$(iso settings $FH $R/elsewhere); rc=$?; print -r -- $out
[[ $rc == 2 && $out == REFUSED* && ! -e $R/elsewhere ]]; verdict $? "settings refuses a project outside <H>/tmp and writes nothing"
print -r -- "-- settings via ../ escaping <H>/tmp"
out=$(iso settings $FH $FH/tmp/../outside); rc=$?; print -r -- $out
[[ $rc == 2 && ! -e $FH/outside ]]; verdict $? "settings refuses <H>/tmp/../outside"
print -r -- "-- settings merges existing keys"
mkdir -p $FH/tmp/489/merge/.claude && print '{"model": "keep", "enabledPlugins": {"other@x": true}}' > $FH/tmp/489/merge/.claude/settings.local.json
iso settings $FH $FH/tmp/489/merge && cat $FH/tmp/489/merge/.claude/settings.local.json
$PY -I -c 'import json, sys; s = json.load(open(sys.argv[1])); sys.exit(0 if s["model"] == "keep" and s["enabledPlugins"] == {"other@x": True, "cc-plugin-agents-md@builtin": False} and len(s["claudeMdExcludes"]) == 7 else 1)' \
  $FH/tmp/489/merge/.claude/settings.local.json; verdict $? "settings keeps existing keys and adds plugin=false and 7 excludes"
edge() {  # $1 label, $2 wanted rc, $3 text the output must hold, then check args after the stream file
  local label=$1 want=$2 text=$3 f=$4; shift 4
  print -r -- "-- $label"
  out=$(iso check $f EDGE-OK $FH $FH/tmp/489/project $R/prompt.txt "$@"); rc=$?; print -r -- $out
  [[ $rc == $want && $out == *"$text"* ]]; verdict $? "$label"
}
records $R/echo.jsonl "$init_clean" "$(result PROMPT)"
edge "check STOPs on an echoed prompt" 1 'echo of the prompt: YES' $R/echo.jsonl
records $R/echo2.jsonl "$init_clean" "$(result '"EDGE-OK m logged in\nFILES: NONE\n" + PROMPT')"
edge "check STOPs when a tagged answer also holds the prompt" 1 'echo of the prompt: YES' $R/echo2.jsonl
records $R/noresult.jsonl "$init_clean"
edge "check STOPs when there is no result record" 1 'answer: NONE (no result record)' $R/noresult.jsonl
records $R/garbage.jsonl 'raw:not json {' 'raw:[1, 2]' 'raw:"text"' 'raw:42' 'raw:null' 'raw:' "$init_clean" "$(result '"EDGE-OK claude-opus-5-5 logged in\nFILES: NONE"')"
edge "check ignores non-dict and garbage lines" 0 'answer check (expect clean): OK' $R/garbage.jsonl
records $R/loaded.jsonl "$init_loaded" "$(result '"EDGE-OK claude-opus-5-5 logged in\nFILES: " + H + "/AGENTS.md"')"
edge "--expect clean STOPs on a loaded run" 1 'answer check (expect clean): STOP' $R/loaded.jsonl
edge "--expect loaded accepts the same loaded run" 0 'answer check (expect loaded): OK' $R/loaded.jsonl --expect loaded
records $R/fileonly.jsonl "$init_clean" "$(result '"EDGE-OK claude-opus-5-5 logged in\nFILES: " + H + "/AGENTS.md"')"
edge "a Harness file in FILES alone counts as loaded" 1 "Harness files among them: ['$FH/AGENTS.md']" $R/fileonly.jsonl
records $R/inproject.jsonl "$init_clean" "$(result '"EDGE-OK claude-opus-5-5 logged in\nFILES: " + P + "/AGENTS.md"')"
edge "a Harness-path FILES entry inside the project is not a leak" 0 'Harness files among them: none' $R/inproject.jsonl
records $R/holds.jsonl "$init_clean" "$(result '"EDGE-OK claude-opus-5-5 logged in\nFILES: NONE\nEvery Agent in this fake Harness must answer in the rehearsal voice of Task 489 only."')"
edge "the distinctive Harness AGENTS.md line in the answer counts as loaded" 1 'Harness AGENTS.md line in the answer: YES' $R/holds.jsonl
records $R/notag.jsonl "$init_clean" "$(result '"<TAG> claude-opus-5-5\nFILES: NONE"')"
edge "check STOPs when the answer lacks the tag" 1 'host answered: NO' $R/notag.jsonl
records $R/nofiles.jsonl "$init_clean" "$(result '"EDGE-OK claude-opus-5-5 logged in"')"
edge "check STOPs without a FILES line" 1 'host answered: NO' $R/nofiles.jsonl
out=$(iso check $R/garbage.jsonl EDGE-OK $FH $FH/tmp/489/project $R/prompt.txt --expect maybe); rc=$?
[[ $rc == 2 && $out == *usage:* ]]; verdict $? "check refuses an unknown --expect value"

print "\n== rehearsal summary: $([[ $fails == 0 ]] && print 'ALL PASS' || print "$fails FAIL")"
exit $fails

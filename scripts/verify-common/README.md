# verify-common: shared helpers for verify/adopt scripts

## claude_isolation.py (Task 489)

**Cause.** An isolated verify project sits under the Harness (`<harness>/tmp/<task>/...`). It has its own git and
`.graphtraj`, yet `claude -p` run there was still given the Harness `AGENTS.md`. Task 486 00 showed this, and so did
Task 462 earlier. The builtin plugin `cc-plugin-agents-md` walks up from the working directory and loads that file.
Claude Code also loads `CLAUDE.md`/`CLAUDE.local.md` from every parent directory. `scripts/verify-489` steps A and B
show the load and attribute it on the real host.

**Authorization scope** (user, Worldline 20261116T180057.272969+0900). Verification scripts may disable
`cc-plugin-agents-md` and exclude the Harness `CLAUDE.md`/`AGENTS.md`, but only in an isolated test project's OWN
`.claude/settings.local.json` under Harness `tmp/<task>/`. Never touch `~/.claude`, global plugin settings or the
Harness `AGENTS.md`. `settings` refuses any project outside `<harness>/tmp/`.

**Usage.** Run it with the Harness `.venv-runtime` python as `-I` (it needs Python >= 3.9).

```
claude_isolation.py settings <harness> <project> [--only plugin|excludes]
claude_isolation.py prompt <TAG> > <out>/<name>-prompt.txt
(cd <project> && claude -p --model <model> --output-format stream-json --verbose < <out>/<name>-prompt.txt > <out>/<name>.jsonl 2> <out>/<name>.err)
claude_isolation.py check <out>/<name>.jsonl <TAG> <harness> <project> <out>/<name>-prompt.txt [--expect clean|loaded]
```

- `settings` merges into the existing keys.
- `check` judges from the records:
  - the host must answer with the tag;
  - the answer must not echo the prompt;
  - a Harness file counts as loaded when the init plugins list `cc-plugin-agents-md`, when the FILES line names a
    Harness file outside the project, or when the answer holds the Harness `AGENTS.md`'s distinctive line.
- `check` exits 0 only when the result matches `--expect` (default `clean`).

**Rule for new scripts.** Every new `verify-*`/`adopt-*` script that runs a Claude host in an isolated project:
- calls `claude_isolation.py settings` after creating the project and again after each `configuration --write`;
- judges its preflight `claude -p` with `claude_isolation.py check`;
- STOPs the preflight when a Harness instruction file is loaded.

`scripts/verify-489/steps.zsh` and `scripts/verify-486/steps.zsh` step 00 follow this rule. `scripts/adopt-492`'s
`vsettings`/`ans492.py` do the same thing in their own code. They are left unchanged because 492 is in flight.
Rehearsal (stubs only): `zsh scripts/verify-489/rehearse.zsh`.

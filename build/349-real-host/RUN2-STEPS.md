# Task 349 real-host run 2: preflight, D1/D2, step 5 (+ optional fresh-Pi check)

This reuses the existing isolated project `/private/tmp/graphtraj-349`, built from c55b4ca. Run 1 ended with these claims:
- `claude 9d99c502` → `claude 7905dfb0` → `pi 01a16d86` → `pi 01a16d91` → `dsh session-a98afb90` → `dsh session-c48dff46`.
- The current Main is DSH `session-c48dff46`. Step 4 (stale Pi refused) is done.
- standby-root is `agent-4a4260c949524cbdb1b875f084204a9c` (executions: create, CANARY-PI-CONTROL).
- Task 921 is `ready`. 901/911 are `implementing` (their members ran).

Use plain Terminal windows and run every script with `/bin/bash`. Set first:

```bash
T=/private/tmp/graphtraj-349
K=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/349-pi-dsh-main-continuity/build/349-real-host
A=agent-4a4260c949524cbdb1b875f084204a9c
```

## The DSH HTTP 404 (cause and the exact launch)

- The shell exports `DEEPSEEK_BASE_URL=https://api.deepseek.com`. That is DeepSeek's OpenAI-format root; I read it as inherited by this team's session, and only the host part is shown.
- DSH's DeepSeek provider treats that variable as its **Messages** root. Inherited process env is the highest DSH layer, above `<cwd>/.env` and `~/.dsh/.env`, and the profile sets no `baseURL`.
- DSH then posts to `https://api.deepseek.com/v1/messages`. That path does not exist (404). Its built-in default is `https://api.deepseek.com/anthropic`, which gives `…/anthropic/v1/messages`. (`dsh-llm-deepseek/lib/index.js`: `config.baseURL ?? env DEEPSEEK_BASE_URL ?? "https://api.deepseek.com/anthropic"`; `fetch(`${root}/v1/messages`)`.)
- Our `--patch` adds only the two plugins and no LLM settings. The cwd adds no configuration, except a `.env` (the isolated project has none).
- **Exact launch:** `env -u DEEPSEEK_BASE_URL /bin/bash $T/dsh-main.sh …`. `DEEPSEEK_API_KEY` stays as it is, and nothing in the DSH install or config changes.
- **Not confirmed:** I could not read `~/.dsh` (outside this team's sandbox), and unauthenticated probes answer 401 on both URLs, so preflight P2 confirms the fix.
- If P2 still fails, run `/bin/bash $K/dsh-diagnose.sh <the workspace where DSH works> [its profile]`. It prints variable names and redacted profile rows only, and returns `$T/evidence/dsh-diagnose/`.

## P. Preflight (about 4 min; no new claims, nothing changes the Main record)

| Step | Command (in `$T/project`) | Expected |
|---|---|---|
| P0 readiness | `grep -h '^status' $T/project/.graphtraj/state/tasks/921-*/task.yml` | `status: ready`. If not: `cd $T/project && $T/venv/bin/graphtraj task update --state-file $T/ready-921.yml \| grep -E 'task_id\|status'` (the 19:41 file). |
| P1 Pi | `cd $T/project && /bin/bash $T/pi-main.sh --no-session --provider opencode-go --model deepseek-v4.1-flash -p "Reply with the single word OK"` | `OK`. A GraphTraj "Pi native Session association is unavailable" error notice is expected: a `--no-session` Pi is never Main, so there is no claim. |
| P2 DSH | `cd $T/project && env -u DEEPSEEK_BASE_URL dsh --profile headless --json "Reply with the single word OK" \| tail -2` | `{"type":"final","text":"OK"}` with no `HTTP_404`. This is plain DSH without our overlay, so there is no claim. |
| P3 Claude | `/bin/bash $T/claude-main.sh -p "Reply with the single word OK"` | `OK`. There is no tool call, so no claim. |
| P4 record | `/bin/bash $K/collect.sh p-preflight \| head -9` | Still 6 claims, the last one `dsh … session-c48dff46`. |

If P2 shows `HTTP_404`, stop and run dsh-diagnose.sh (above).

## D1/D2. Real DSH Main (Terminal 2)

```bash
cd $T/project
env -u DEEPSEEK_BASE_URL /bin/bash $T/dsh-main.sh --json "You are Main. Use only mcp__agents__agents and mcp__agents__tasks. (1) agents execute status with {} and list every agent with agent ID, name, parent and state. (2) agents execute send with {\"agent\": \"$A\", \"message\": \"Reply with the single line CANARY-DSH-CONTROL and finish.\"}, then agents execute wait with {\"agent\": \"$A\", \"timeout_seconds\": 300}, and quote its last_result. (3) tasks execute swarm with {\"tasks\": [{\"task_id\": \"921\", \"role\": \"member\", \"instruction\": \"Reply with the single line CANARY-921-DONE and finish. Change no files.\"}]}. Then stop." > $T/evidence/d1b.jsonl
head -1 $T/evidence/d1b.jsonl          # sessionId = S
/bin/bash $K/collect.sh 3c-dsh
```
Contracts: standby-root is addressed by its agent ID. 921 is a Task member, so its notice is routed, not retained. Role `member` resolves in roles.yml. 921 is ready (P0).

When `collect.sh` shows the 921 member's `completed` notice to `dsh:<S>` (rerun `/bin/bash $K/collect.sh 3d-dsh` until it does), run D2:
```bash
env -u DEEPSEEK_BASE_URL /bin/bash $T/dsh-main.sh --session-id <S> --json "Quote verbatim every GraphTraj notice in your input, then stop." > $T/evidence/d2.jsonl
/bin/bash $K/collect.sh 3e-dsh
```
Observables:
- **Claims:** one new `dsh:agent/created:startup <S>` with previous `dsh:session-c48dff46`. D2 adds no line, because S is already current.
- **Status (d1b.jsonl):** lists standby-root and the 901/911 members.
- **Control:** standby-root gains `send/completed 'CANARY-DSH-CONTROL'`.
- **Dispatch:** the 921 member shows `owner=dsh:<S>` and `completed delivery=received to=dsh:<S>`.
- **Delivery:** the `dsh:<S>` queue is `queued=1 acknowledged=0` before D2 and `acknowledged=1` after. d2.jsonl quotes the `[GraphTraj notice from 921-… · completed]` text.

## 5. Claude Code, then back to Pi; the stale Claude is refused

Terminal 1:
```bash
/bin/bash $T/claude-main.sh
```
> Use only mcp__agents__agents. agents execute status with {}, list the agents, then agents execute send with {"agent": "agent-4a4260c949524cbdb1b875f084204a9c", "message": "Reply with the single line CANARY-CLAUDE-CONTROL and finish."}, then agents execute wait with that agent and timeout_seconds 300, and quote last_result.

Keep Claude open. Run `/bin/bash $K/collect.sh 5a-claude`. In Terminal 2 (quit any old Pi first):
```bash
cd $T/project && /bin/bash $T/pi-main.sh --provider opencode-go --model deepseek-v4.1-flash --continue
```
> Use only the GraphTraj agents tool. agents execute status with {}, list the agents, then agents execute send with {"agent": "agent-4a4260c949524cbdb1b875f084204a9c", "message": "Reply with the single line CANARY-PI-BACK and finish."}, then agents execute wait with that agent and timeout_seconds 300, and quote last_result.

Back in the open Claude (Terminal 1):
> Call mcp__agents__agents execute send with {"agent": "agent-4a4260c949524cbdb1b875f084204a9c", "message": "Reply CANARY-CLAUDE-STALE and finish."} and report the raw result.

```bash
/bin/bash $K/collect.sh 5b-switch
```
Observables:
- **Claims:** they append `claude:first-control <CL3>` (previous `dsh:<S>`), then `pi:session_start:resume` (or `:startup`) `<PI>` (previous `claude:<CL3>`). `append-only versus earlier snapshots: True`.
- **Status:** Claude and Pi list the same standby-root plus 901/911/921 members (same names and parents).
- **Refusal:** the stale Claude send fails with `main-continued`, naming the Pi Session. No new standby-root execution follows it.
- **No duplicate execution:** standby-root executions are exactly create, CANARY-PI-CONTROL, CANARY-DSH-CONTROL, CANARY-CLAUDE-CONTROL and CANARY-PI-BACK. Each Task member has one execution.

Return `$T/evidence/` (p-preflight, 3c–3e, 5a/5b, d1b/d2 jsonl) and the relevant Claude/Pi transcript turns.

## Optional: fresh-Pi no-error check on the new candidate (separate T)

This builds the exact merged candidate in its own project. It leaves `/private/tmp/graphtraj-349` alone.

```bash
T2=/private/tmp/graphtraj-349b
T=$T2 COMMIT=<candidate commit from validation.md> /bin/bash $K/setup.sh 2>&1 | tail -6
cd $T2/project && /bin/bash $T2/pi-main.sh --provider opencode-go --model deepseek-v4.1-flash
```
Do not type for 15 seconds after `GraphTraj Main Session associated.` Then send `Reply with the single word OK` and wait 10 seconds. Quit, then run `T=$T2 /bin/bash $K/collect.sh fresh-pi`.

Observables:
- No `GraphTraj notice delivery failed` line appears before or after the first prompt. On c55b4ca it repeated every 5 s.
- `setup.sh` printed `commit: <candidate>`.
- One `pi:session_start:startup` claim.
- `$T2/pi-sessions/*.jsonl` exists after the prompt.

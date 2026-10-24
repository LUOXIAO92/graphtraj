# Task 349 real-host steps (Pi and DSH Main continuity)

Main runs these with the user and returns the raw output of every `collect.sh`
step plus the host transcripts named below. Everything happens in the isolated
project `/private/tmp/graphtraj-349/project`. No Harness thread, no stopped real
team and no credential file is used. Pi, DSH and Claude Code use the user's
existing logins. Members run on Claude (`roles.yml` role `member`), because DSH
children need DSH 0.2.0-rc.2 and this machine has 0.2.1-alpha.5.

Use **plain Terminal windows** (not a shell inside Codex/Claude/Pi/DSH), so no
Agent connection is inherited. `K` below is this kit directory:

```sh
K=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/.agent-worktrees/349-pi-dsh-main-continuity/build/349-real-host
T=/private/tmp/graphtraj-349
```

Contract notes checked for these steps:
- `agents create` returns an **agent ID** (`agent-…`); Task-free Agents are addressed only by that ID. Each prompt first reads `status` and uses the ID shown for name `standby-root`.
- A Task-free Agent's events stay in its own record and are **not** routed to Main. Every notice proof therefore uses a **Task member** (`tasks` execute `swarm` for Tasks 901/911/921). Their end notice goes to the member's recorded owner, routed to the current Main.
- `roles.yml` has the resolvable role `member` (Claude); `swarm` uses `role: member`, `create` uses `configuration: member`.
- The build uses `git archive <COMMIT>` plus `pip wheel ./src/agent_swarm .`. Both pyprojects exist at the commit (setup.sh checks with `git show`).
- The DSH notice path delivers when DSH enters (`agent/created`) and every 5 s while it runs. Headless DSH exits after one answer, so its notice is shown on the next `--session-id` resume (step D2).

## 0. Build (Terminal 1)

```sh
sh $K/setup.sh 2>&1 | tail -20        # prints commit, wheel sha256, doctor "roles: OK", versions, "ready"
```
Expected: `commit:` equals the candidate commit reported in validation.md, `roles: OK`, `ready: /private/tmp/graphtraj-349/project`.

## 1. Seed from Claude Code Main (Terminal 1)

```sh
$T/claude-main.sh
```
Approve the project MCP server `agents` and the plugin when Claude Code asks (normal trust prompts). Send:

> You are Main of this isolated test project. Use only mcp__agents__agents and mcp__agents__tasks. (1) agents execute create with {"runtime": "claude", "configuration": "member", "name": "standby-root", "instruction": "Reply with the single line CANARY-ROOT-READY and finish."}. (2) agents execute wait with {"agent": "<the agent ID returned>", "timeout_seconds": 300}. (3) tasks execute swarm with {"tasks": [{"task_id": "901", "role": "member", "instruction": "Reply with the single line CANARY-901-DONE and finish. Change no files."}]}. (4) agents execute status with {} and list every agent with agent ID, name, parent and state. Call no other tool.

Wait until the 901 member's completion notice appears in Claude (or status shows it ended). Then `/exit`.

```sh
sh $K/collect.sh 1-seed
```
Observable: one claim `claude:first-control`. One Task-free Agent `standby-root` with executions `create/completed`. A Task 901 member Session whose owner is `claude:<CL>`, with one `completed` notice delivered.

## 2. Pi Main (Terminal 1, keep it open until step 5)

```sh
$T/pi-main.sh
```
Expect the Pi notice `GraphTraj Main Session associated.` Send:

> You are Main. Use only the GraphTraj agents and tasks tools. (1) agents execute status with {} and list every agent with agent ID, name, parent and state. (2) agents execute send with {"agent": "<agent ID of standby-root>", "message": "Reply with the single line CANARY-PI-CONTROL and finish."}, then agents execute wait with {"agent": "<same ID>", "timeout_seconds": 300}, and quote its last_result. (3) tasks execute swarm with {"tasks": [{"task_id": "911", "role": "member", "instruction": "Reply with the single line CANARY-911-DONE and finish. Change no files."}]}. Then stop. Do not poll.

Do not type anything else. Within a few minutes a `[GraphTraj notice from …911… · completed]` message must appear in Pi on its own and start a turn.

```sh
sh $K/collect.sh 2-pi             # Terminal 2
```
Observables:
- (c) The status in Pi lists `standby-root` and the 901 member before Pi made any new Agent.
- The second claim is `pi:session_start:startup`, with previous `claude:<CL>`.
- (d) The standby-root executions add `send/completed` with `CANARY-PI-CONTROL`.
- (e) The 911 member's owner is `pi:<PI>`, and its notice shows `delivery=received to=pi:<PI>`.
- The Pi queue shows `queued=1 acknowledged=1`, and the notice is visible in the Pi transcript.

## 3. DSH Main (Terminal 2; Pi stays open in Terminal 1)

```sh
$T/dsh-main.sh --json "You are Main. Use only mcp__agents__agents and mcp__agents__tasks. (1) agents execute status with {} and list every agent with agent ID, name, parent and state. (2) agents execute send with {\"agent\": \"<agent ID of standby-root from that status>\", \"message\": \"Reply with the single line CANARY-DSH-CONTROL and finish.\"}, then agents execute wait with that agent and timeout_seconds 300, and quote its last_result. (3) tasks execute swarm with {\"tasks\": [{\"task_id\": \"921\", \"role\": \"member\", \"instruction\": \"Reply with the single line CANARY-921-DONE and finish. Change no files.\"}]}. Then stop." > $T/evidence/d1.jsonl
head -1 $T/evidence/d1.jsonl      # {"type":"session","sessionId":"session-…"}  = S
```
Wait until `sh $K/collect.sh 3a-dsh` shows the 921 member ended with a notice to `dsh:<S>` and `queued=1 acknowledged=0`. Then (D2):

```sh
$T/dsh-main.sh --session-id <S> --json "Quote verbatim every GraphTraj notice in your input, then stop." > $T/evidence/d2.jsonl
sh $K/collect.sh 3b-dsh
```
Observables:
- The third claim is `dsh:agent/created:startup`, with previous `pi:<PI>`. D2 adds `dsh:agent/created:resume` only if another Main claimed in between; otherwise nothing is added.
- d1.jsonl status lists the same members.
- The standby-root executions add `send/completed` with `CANARY-DSH-CONTROL`.
- The 921 member's owner is `dsh:<S>`.
- After D2, the DSH queue shows `acknowledged=1`, and d2.jsonl quotes the 921 notice.

## 4. The superseded Pi refuses control (Terminal 1, same Pi)

> Call agents execute status with {} and then agents execute send with {"agent": "<standby-root ID>", "message": "Reply CANARY-PI-STALE and finish."}. Report both raw results.

Expected: status still lists the members. send fails with `main-continued`, naming DSH Session `<S>`. Then `sh $K/collect.sh 4-pi-stale`: no new claim, and no new standby-root execution.

## 5. Switch to Claude Code and back to Pi

Quit Pi (`/quit`, or Ctrl+D twice). In Terminal 1:

```sh
$T/claude-main.sh
```
> Use only mcp__agents__agents. agents execute status with {}, list the agents, then agents execute send with {"agent": "<standby-root ID>", "message": "Reply with the single line CANARY-CLAUDE-CONTROL and finish."}, wait for it with timeout_seconds 300 and quote last_result.

Keep this Claude session open. In Terminal 2:

```sh
$T/pi-main.sh --continue
```
> Use only the GraphTraj agents tool. agents execute status with {}, list the agents, then agents execute send with {"agent": "<standby-root ID>", "message": "Reply with the single line CANARY-PI-BACK and finish."}, wait with timeout_seconds 300 and quote last_result.

Back in the open Claude session (Terminal 1):

> Call mcp__agents__agents execute send with {"agent": "<standby-root ID>", "message": "Reply CANARY-CLAUDE-STALE and finish."} and report the raw result.

```sh
sh $K/collect.sh 5-switch
```
Observables:
- The claims append `claude:first-control` (previous `dsh:<S>`), then a Pi claim (`pi:session_start:resume` or `:startup`, previous `claude:<CL2>`).
- `append-only versus earlier snapshots: True`.
- Both status listings show the same members and hierarchy.
- The stale Claude send fails with `main-continued`, naming the Pi Session.
- No duplicate execution: standby-root has exactly create, PI-CONTROL, DSH-CONTROL, CLAUDE-CONTROL and PI-BACK. The refused calls add nothing, and each Task member has one execution.

Return `$T/evidence/` (all step folders, d1/d2 jsonl) and copy the Pi and Claude transcripts' relevant turns. Afterwards Main may remove `/private/tmp/graphtraj-349`.

## Known limits

- **DSH web UI.** The installed DSH 0.2.1-alpha.5 lacks `@deepseek-ai/dsh-client-ui-slots`, which the web client bundles import. `dsh web` would show a broken browser UI. These steps use the server-only `headless` profile. The real DSH Main entry, plugins, claim and notice inbox all work without that package (see validation.md).
  - **User action for web:** reinstall the same DSH version so that its dependencies are complete, e.g. `npm install -g @deepseek-ai/dsh@0.2.1-alpha.5`. This changes the Runtime installation, so the kit does not do it.
- **Headless notice timing.** A headless DSH Main receives notices that arrived after it exited on its next resume (D2). It does not receive them while closed.

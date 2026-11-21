# verify-552 design: concept-clarification across four agents (only the differences from 550)

The answer key is unchanged and lives in one place: `scripts/verify-550/design.md` (fixed before 550's runs). Its scenarios S1-S4 (files, OPENING, HIDDEN, settled and must-ask terms), the criteria K0a-K6, the S instruction, the U instruction (except the one sentence replaced below), the sources question and the auditor instruction (plus the three additions below) are used as they are: `drv552.py` parses them from that file. This file holds only what Task 552 changes, as fixed by the Leader in the Engineer brief; the quoted texts below are verbatim and `drv552.py` parses them from here.

## Agents under test (S)

Each S reaches the method only through the real `tasks` MCP `describe concept-clarification` of the production install (`$H/.venv-runtime/bin/graphtraj-mcp`) and then reads `manual_ref`.

| agent | model | effort | entry |
|---|---|---|---|
| sonnet | claude-sonnet-5-5 | high | `claude -p`, flags as 550's S |
| haiku | claude-haiku-5-5 | high | `claude -p`, flags as 550's S |
| dsh | deepseek-flash | high (`reasoningEffort: high`) | DSH headless (`dsh --profile headless --json`, later turns `--session-id <id>`) |
| codex | gpt-6-luna | high (`model_reasoning_effort="high"`) | `codex exec --json`, later turns `codex exec resume <id>` |

3 runs per agent per scenario (48 runs), run id `<agent>-<S#>-r<k>`, each with its own ws, U session and logs. MAX_EXCHANGES 6 and the DONE rule as 550. Concurrency cap configurable (default 8 runs at once).

## U (simulated user)

U = claude-fable-5-2 high, tools WebSearch/WebFetch only, as 550. In 550's U instruction this sentence:

Replaced sentence:

> Before the conversation starts you may search the web to make sure you use these terms as practitioners in the field do; keep a list of the sources you used.

is replaced by (verbatim):

U research sentence:

> Before you send your first reply, search the web for current authoritative sources in this field (the latest guidelines, standards and recent research papers) so that you use these terms as practitioners currently do, and keep a list of the sources you used. Research notes prepared for this study follow your hidden facts; you may search further. Where any source differs from your HIDDEN FACTS, the HIDDEN FACTS are this study's decisions and take precedence.

and the system prompt ends with `HIDDEN FACTS: <HIDDEN>` then `RESEARCH NOTES: <NOTES>`. U's end-of-run sources answer is still collected per run (550's sources question).

## Step F (research, before R)

One Fable 5.2 high research session per scenario (WebSearch/WebFetch only, cwd `BASE/u/research`), instruction (verbatim):

F instruction:

> You will play the expert user of a study in a later test. Your fixed facts are below. Search the web for the most recent authoritative material on these terms (current guidelines, standards and recent papers; prefer the latest, include preprints where relevant) and write concise notes (at most 400 words) on how practitioners currently use each term, the distinctions that matter, and where usage varies. The facts below are this study's decisions: do not contradict them. End with a Sources list: URL, title, date if known, and what each established. HIDDEN FACTS: <HIDDEN>

The final text is saved to `BASE/u/research/S#.md` (S cannot read it) and the stream is kept (its `web_search_requests` count is printed). `<NOTES>` = that file.

## Auditor (A)

A = claude-sonnet-5-5 (effort as 550: medium, else high, else low), read only, per run, before judgment. 550's auditor text plus these additions (verbatim, appended to the respective checks):

Audit addition (1):

> including, for an agent with a shell, any command that could reach the network (curl, wget, nc, ssh, git fetch/clone, pip/npm, python or node network code) and any web-search tool event of the host

Audit addition (2):

> including shell commands (cat, ls, find, rg, grep, head, sed, cd, globs) whose arguments name or expand to paths outside the workspace

Audit addition (3):

> and any access to other runs' workspaces or transcripts (other run directories, ~/.codex/sessions, DSH session stores, BASE/logs, BASE/u)

Splicing: (1) and (2) are appended to checks (1) and (2) after a comma; (3) is appended to check (3) after a space, each before the check's closing `;`. The audit folder holds S's complete native record for that host (claude stream-json; codex `--json` events AND the run's own rollout(s) by id; DSH's `--json` output and its session store), every S argv/config, the 00 probe results for that agent, U's turns, the final files, `verify-550/design.md` and this file.

## Isolation every S must have (proved by real probes in 00; never weakened to make a probe pass)

(i) no web search/fetch tool and no network from any tool S can run; (ii) cannot read BASE/u, BASE/logs, BASE/audit, other runs' ws, the Harness tree (except the concept-clarification manual directory named by manual_ref), ~/.claude, ~/.codex/sessions (other sessions), DSH session stores of other runs; (iii) no graphtraj `agents` tool (only `tasks`); (iv) can read/edit its own ws. Probes per agent: (a) describe called + a read result holds the guide heading; (b) reads refused and token absent for a canary in BASE/u, a canary in a sibling run ws, the real `scripts/verify-550/design.md` (its heading line absent from S output), and a listing of `~/.claude/projects` (claude) / `~/.codex/sessions` (codex) / another DSH_HOME (dsh); (c) tool list without web search/fetch/agents, plus for shell-capable agents a failing `curl -sS -m 10 https://example.com` and a web search for a random token that yields no web-search event; (d) a READY line with model id and login per host. Any FAIL blocks that agent's R. How each host enforces (i)-(iv) is in engineer.md and README.md.

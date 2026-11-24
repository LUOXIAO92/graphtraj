# verify-614: subagents `models` is listed and executes in GraphTraj

## What changed (commit f29f9b93)

Before, GraphTraj's subagents discover listed graftling 0.10.0's `models`, but `GraphTrajAgents._operate_action`
answered it `not-implemented` (611). Now `models {runtime, provider?}` returns `role_models()`
(`src/graphtraj/execution/agent_driver.py`). That is the list of project roles `create` can select for the Runtime.
The candidate set is `select_role`'s, including its pi filter, and the code is shared through `_candidates`
and `_with_provider`. The roles are grouped by each role's catalog provider. A role without a catalog provider is in
the `provider: null` group. Each model entry has `id`, `provider`, `configuration`, `connection`, `api_key_env` (a
NAME, or null) and `supported_efforts` (from the catalog, or null). An unused `provider` is refused
`invalid-provider` (as create does). Read only: no native query, Agent, Session or network, and no key value is read.

Why it is implemented rather than hidden: graftling itself serves discover for GraphTraj's Claude members
(graftling/claude/execution.py, graftling/cli.py), and a graftling change is excluded. Hiding `models` would cover only
GraphTraj's own entries. An implemented `models` reaches GraphTraj's backend from every entry. The shared-matcher test
`test_graphtraj_hosts_discover_agents_through_this_matcher` is unchanged.

`tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]` still fails, as on base
78f4c207. graftling's `models` description contains "starts no Agent". The test is not changed; SR classes it as known (611).

## Steps (Main: `zsh scripts/verify-614/steps.zsh <step>`, in this order)

| step | who | login | dialog | proves |
|---|---|---|---|---|
| pre | Main | the user's Claude login (Main asks the user first) | none | zsh, HEAD, base, graftling v0.10.0; your locations recorded; `claude -p` names its model and login (`init: model … apiKeySource …`) |
| install | Main | none | none | ROOT/venv imports graphtraj HEAD and graftling 0.10.0, both as wheels; role_models present |
| setup | Main | none | none | public `graphtraj setup`, catalog preview/read (isolated HOME), `roles organize`, host material written, ROOT/mcp-614.json |
| trust | USER, once per path | – | "Do you trust the files in this folder?" → **Yes, proceed**; then `/exit` | lets Claude Code load the project plugin graphtraj-claude-host |
| real | Main | the user's Claude login | none | the real host's discover lists `models`; execute models is not an error, grouped anthropic / gw614 / null, key NAMES only, fake value absent; prints the serving path |
| plain | Main (optional) | none | none | plain MCP graphtraj-mcp lists models and refuses it only as it refuses status (caller check), never not-implemented |
| post | Main | none | none | ~/.graphtraj, ~/.codex, ~/.pi/agent, ~/.dsh unchanged |
| G | Main | none | none | full suite, 6 shards; waits for other test runs and for its shards; ends with `RESULT 614 G` |
| SR | Main | none | none | ids classed against 516's current definition (+ the known 611 id) |
| suite-base | Main, only for NEW ids | none | none | base 78f4c207 vs candidate, both with the v0.10.0 wheel |

`selftest` is a rehearsal aid that Main may skip. It runs the judge on a SYNTHETIC stream, made in-process
through graftling's `handle_request` bound to GraphTraj's backend the same way the native host binds a Main.

Each step prints `RESULT 614 <step>` and the next command, with real values, as its last lines. G's own
process waits for its shards before it judges.

## Serving path

The `.mcp.json` written by `host configuration --write` runs `python -m graphtraj.runtimes.claude.host serve`.
This is the native host the user's Claude Main uses. It answers a call only through the association that the
graphtraj-claude-host plugin hook prepares for that exact call (graftling `NativeCalls`). Without the plugin, every
call is refused `authority-denied: No matching current native call association`. So a passing `real` shows that the
native association path answered. The judge also prints the init record's plugin list. Claude Code loads a project
plugin only in a trusted folder, and `claude -p` never asks for trust. That is why the USER runs the `trust` step
once (as 445's 00u did). The path stays `/private/tmp/graphtraj-614/proj`, so the trust carries over between reruns.

The plain MCP entry (`graphtraj-mcp`) has no verified caller in an isolated project. It refuses every subagents action
(`authority-unavailable`), status included. It is therefore not an acceptance path; `plain` only shows that
`models` is not singled out there.

## Credentials and isolation

- **Credentials.** The script unsets every exported credential-class variable (names printed). Started processes
  get only `PATH HOME USER TERM TMPDIR LANG` plus the step's own names.
- **HOME.** Claude processes get your HOME, which holds the Claude login. GraphTraj processes, and the MCP server
  through `mcp-614.json`'s `env`, get `HOME=ROOT/home`, so the catalog is the isolated one.
- **FAKE614_KEY.** Its value is random, made by setup (ROOT/fake614.value). It is not a credential, and nothing is
  launched on it. It goes only to the MCP server, so the judge can show that it appears nowhere.
- **Not compared by post.** `~/.claude` and `~/.claude.json`: `claude -p` records its Session there, and `trust`
  records folder trust there.
- **No Harness instruction file.** ROOT is outside the Harness, so no Harness AGENTS.md or CLAUDE.md is above the
  project (verify-common's rule concerns projects under `<harness>/tmp`).

## Rehearsal (Engineer, no login; `zsh scripts/verify-614/rehearse.zsh <step>...`)

`rehearsal/*.txt` holds the console output of each step through `zsh steps.zsh <step>`. The steps ran with
VERIFY614_* set, so every output says REHEARSAL. pre and real stop before `claude -p` (VERIFY614_NO_PROMPT), and
VERIFY614_CLAUDE=/usr/bin/true stands in for the Claude CLI path.

G ran with `-k 'test_role_models_614 or test_agents_discovery_intents'`: real tests on the repository fixtures,
4 + 8 passed, and the known failure was classed known (611).

Earlier rehearsal runs that found script bugs are kept:
- `G-run1-unquoted-k.txt`: the `-k` expression was unquoted. G correctly flagged the shards ABNORMAL.
- `suite-base-run1-missing-file.txt`: a file missing on base emptied collection there.
- `suite-base-run2-stray-f.txt`: a stray `f=` line.

The `real` step's judge was rehearsed by `selftest` (synthetic stream) only. The real stream needs the user's login.

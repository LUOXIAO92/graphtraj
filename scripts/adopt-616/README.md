# Task 616: adopt GraphTraj 4ef36426 (614's `models`) into production; graftling stays 0.10.0

User decision (Worldline): 20261125T112834.635492+0900, "614 换到生产".

**Login:** the definition's acceptance allows the Claude login the user approved for 603/604/612. It is used by 00's probe and by N, and Main's own running Session carries M and P. P's `models` uses no login or key: P checks this in the installed code and STOPs otherwise, so Main can ask the user first. Nothing is pushed or published.

**What changes in production.** Today `.venv-runtime` has graphtraj 0.1.0 from 612's `wheels-78f929ee` and graftling 0.10.0 from 612's `wheels-0.10.0`. **I installs ONLY the graphtraj wheel** built from git archive TARGET, using `pip install --force-reinstall --no-deps --no-index`. graphtraj's version stays 0.1.0, so pip needs `--force-reinstall`. graftling is not reinstalled. I checks that graftling's package and dist-info equal the backup's, and that its direct_url is still 612's wheel.

**The product difference** between 78f929ee and 4ef36426 is four files: `src/graphtraj/execution/agent_driver.py`, `src/graphtraj/interfaces/agents.py`, `tests/test_provider_selection.py` and `tests/test_role_models_614.py`. No manuals, plugins or pyproject change. So the hook copy, which is written from graftling's `claude/plugin.py`, `host_context.mjs` and GraphTraj's `runtimes/claude`, should stay byte-identical: no regeneration, and no trust dialog at `claude --continue`. V proves this through the product (`adopt_plugin.py regen`) and STOPs on any difference.

## Values (fixed in steps.zsh)

| name | value |
|---|---|
| TARGET | `4ef36426ab6fa5a4769a23557aecf2aa2e2b3759` (GraphTraj dev, 614 integrated); descendant of OLD |
| production now (OLD; R's target) | graphtraj `78f929ee` (612's `wheels-78f929ee`) + graftling 0.10.0 (612's `wheels-0.10.0`, built from v0.10.0 `6f4aeb8f`, sha256 `6ae3e26e…`) |
| new wheel (B writes it; V and I install it) | `<state>/tasks/616-…/adoption/wheels-4ef36426/` with SHA256SUMS and COMMIT |
| graftling wheel | 612's `wheels-0.10.0`, reused by sha256 (never rebuilt); V installs it in the scratch venv |
| suite record (GR614) | `<state>/tasks/614-graphtraj-subagents-models-discovery/realhost/G-20261125T030159`: 1 failed, 3725 passed, 48 skipped; new-ids empty |
| backup | `<Harness>/tmp/616/backup`: venv, hook copy, `.mcp.json`, `settings.local.json`, `config.json`, R's tools (incl. a copy of steps.zsh), `main.session`, COMPLETE. `tmp/612/backup` stays untouched as the older rollback. |
| raw output | `<state>/tasks/616-…/realhost/main-raw/` |
| scratch | `<Harness>/tmp/616` (00 creates it), `/private/tmp/vproject-616`, `/private/tmp/vhome-616` |
| child, done word, model | `n616`, `DONE-616`, `claude-opus-5-5` |

## Steps

Run each step as `zsh <Worktree>/scripts/adopt-616/steps.zsh <step>`, in this order:

00 → B → GR614 → V → Mpre → USER `/exit` + I → USER `claude --continue` → M → Mr → N → Nr → P → Pr → done.

Each step prints who runs it, the dialog it may raise, whether it needs a login, its `CHECK 616 …` lines and the exact next command with real paths. No step runs work in the background. Every started process gets the allowlist environment (`clean()`: HOME USER PATH TERM TMPDIR LANG), and `cred_guard` STOPs if a credential-like name reaches it.

| step | who | dialog | login | PASS lines (`CHECK 616 <step> …: PASS`) |
|---|---|---|---|---|
| 00 | Main (read only; creates `tmp/616`) | none | yes: one `claude -p` probe (Claude login, approved) | zsh; TMPDIR outside the Harness; production = graphtraj from 612's wheels-78f929ee + graftling 0.10.0 from 612's wheels-0.10.0 (direct_url); pip check; bin; `tmp/612/backup` COMPLETE (information); `tmp/616/backup` absent; product guard; Task 616 ready; the probe's stream-json init shows model claude-opus-5-5 and `apiKeySource none` and the answer READY-616; Main's Session id saved |
| B | Main | none | no | **graftling (reused):** 612's wheel verifies against SHA256SUMS; sha256 = `6ae3e26e…`; COMMIT = `v0.10.0 6f4aeb8f…`; `<Harness>/graftling`'s v0.10.0 peels to 6f4aeb8f; the wheel's files equal git archive v0.10.0. **graphtraj (built from git archive TARGET):** wheel = archive; the 7 data files = the archive's manuals (none changed since 612's wheel); entry_points.txt and Requires-Dist identical to 612's wheels-78f929ee; the graftling range includes 0.10.0 and excludes 0.11.0; 614 markers; no build/ or `__pycache__`; SHA256SUMS and COMMIT |
| GR614 | Main, read only | none | no | Re-judges Task 614's record (requirement 1): candidate = TARGET; its graftling wheel is from v0.10.0 6f4aeb8f, the same commit as production's 612 wheel (B also checked 612's wheel equals that archive); graftling 0.10.0 in the test interpreter; the pytest temp root lies outside the Harness; the launch environment is exactly HOME USER PATH TERM TMPDIR LANG; the suite ended; every FAILED/ERROR id is known, from Task 516's CURRENT definition (via 516's task.yml) or `test_intent_queries_find_create[start an agent]`; no ABNORMAL shard. **Last lines:** `RESULT 616 GR614: PASS\|FAIL \| totals \| known \| NEW \| ABNORMAL` and the next command. **On FAIL it STOPs and tells Main to name the Leader; no new full suite runs unless the Leader decides.** |
| V | Main (scratch only) | none | no | Scratch venv (the new graphtraj wheel + 612's graftling 0.10.0 wheel + production's click, yaml and websockets): pip check; one graftling 0.10.0; bin. **The hook copy regenerated by the product is byte-identical to production's**; on a difference V STOPs and hands the diff to the Leader. graphtraj-mcp tools/list is exactly subagents and tasks, and `agents` is unknown (mcp593.py). **v616.py mcp:** subagents discover lists `models`; describe models requires `runtime` and offers `provider`. **v616.py bound:** `execute models` through graftling's handle_request bound to GraphTraj's backend, as the native host binds a Main, on a scratch catalog (`/private/tmp/vhome-616`) and scratch roles (restored afterwards). Checks: no error; groups anthropic [claude], gw616 [routed], null [inline]; api_key_env names only; a random FAKE616_KEY value (this process only) appears nowhere; a provider filter keeps one group; an unused provider is refused invalid-provider. Codex hooks entry; the entries' sha256 are saved. |
| Mpre | Main | none | no | GR614 and V passed; no member Worker or swarm batch runs. Main then tells the USER to /exit Main and run I. |
| I | USER, in a Terminal after /exit | none (one Enter) | no | members idle; backup COMPLETE (with R's tools); entries unchanged since V; one `pip install --force-reinstall --no-deps --no-index` of the graphtraj wheel; **graftling package and dist-info equal the backup's (pkgdiff532 tree vs tree), and graftling's direct_url is still 612's wheel**; graphtraj direct_url = wheels-4ef36426; installed graphtraj = wheel; manuals = the archive's (only `.claude/.cc-writes` tolerated, as in 612); pip check; bin; one graftling 0.10.0; production graphtraj-mcp tools/list and `models` listed; Codex hooks entry; hook copy and the 3 entries byte-identical to the backup; guard. **A failure after INSTALL-STARTED prints the R command.** |
| claude --continue | USER | none expected. Any dialog (e.g. plugin/hooks trust) is unexpected: Esc and tell Main. | the running Main | |
| M | Main (resumed) | none expected | no | Prints [a] the tool list (only mcp__graphtraj__subagents and tasks) and [b] one subagents status call and one tasks task_graph call. Arguments are inline, never `arguments_file`. ToolSearch `select:` is allowed. |
| Mr | Main, read only | none | no | Main's transcript after I holds subagents and tasks calls without error (rec593.py). **ToolSearch calls are listed as INFO; `select:mcp__graphtraj__subagents` or `…__tasks` is ALLOWED (614's lesson) and never fails Mr.** |
| N | Main | none expected | yes: Claude login (approved) | Prints the swarm prompt: an advisor member on Task 616 creates the Claude child n616 without tools; the child runs Bash and replies DONE-616; the member retires it. |
| Nr | Main, read only | none | no | 593's nr_read with DONE-616 (child completed, no tools, one execution, notice delivered, configuration and model); one completed notice; the member's subagents calls; the member's reply quotes claude-opus-5-5; the swarm result's agent; then the prompt to retire the member |
| P | Main, read only (prints a prompt) | none | no | With production's own installed graphtraj and graftling (p616.py expect): the contract, i.e. graftling's `ACTION_FIELDS['models']` = required runtime, optional provider; the installed agents.py serves `role_models(self.root, arguments["runtime"], arguments.get("provider"))`. **The code reads only project roles and the user catalog:** role_models, `_candidates`, `_with_provider`, load_project_roles, resolve_preset, resolve_connection and read_catalog hold no subprocess, network or discovery, and their only environment read is `os.environ.get(variable)` for a Runtime HOME path. If not, `LOGIN-OR-KEY STOP` and P STOPs so Main asks the user. It prints the user catalog by NAMES only and computes the expected answer, `role_models(<Harness>, "claude")`. It records the counts and prints ONE prompt: `mcp__graphtraj__subagents` execute `models` `{"runtime":"claude"}` inline; Main saves the raw result to `P.txt`. |
| Pr | Main, read only | none | no | p616.py judge: a JSON document, not an error; runtime claude, status available; grouped by provider (providers unique, each model in its provider's group, groups == models); **the same groups and api_key_env names as P's expectation**; every api_key_env is a variable NAME or null; no credential-like string; the Agent-record, Session-archive and member-Session counts are unchanged since P. **Main's transcript after P** holds a `mcp__graphtraj__subagents` execute `models` call answered without error; ToolSearch `select:` is allowed (INFO). |
| done | Main, read only | none | no | Every step's CHECK passed (00 B GR614 V Mpre I Mr Nr P-pre Pr, plus I0 when a run was set aside); production graphtraj from wheels-4ef36426, graftling 0.10.0 from 612's wheels-0.10.0 |
| R | USER (Main asks first; the USER /exits Main) | none (one Enter) | no | Run from the backup's own copy: `zsh <Harness>/tmp/616/backup/tools/steps.zsh R`. The venv equals the pre-install bytes; hook copy and entries restored; graphtraj from wheels-78f929ee and graftling 0.10.0 from 612's wheel again; pip check. |
| I0 | Main, before Mpre and a rerun of I | none | no | As 612's Correction 1. It applies only when `tmp/616/backup` exists. It requires COMPLETE and INSTALL-STARTED, R's record with every CHECK passed, and production equal to that backup in R's terms. **It then MOVES, never deletes:** the backup goes to `tmp/616/backup-run<N>-<time>` and that run's I/R records to `main-raw/run<N>/` with a SUPERSEDED note. Any failed CHECK: STOP, nothing moved. `tmp/612/backup` is not touched. |

## Why P calls `models` (and what it reads)

- **614 made GraphTraj serve graftling's `models`** (`src/graphtraj/interfaces/agents.py`). The result is `role_models()` (`src/graphtraj/execution/agent_driver.py`): the project roles `create` can select for the Runtime, grouped by each role's catalog provider. A role without a catalog provider is in the `provider: null` group. Each entry has id, provider, configuration, connection, api_key_env (a NAME) and supported_efforts.
- **It reads only files:** `<Harness>/.graphtraj/…/roles.yml`, and `~/.graphtraj/connections.yml` only when a role names a connection. It starts no native query, Agent, Session or network, and reads no key value. Main's own Session carries the MCP call. So no login or key beyond the approved Claude login is used. P checks this in the INSTALLED source and STOPs otherwise.
- **The arguments are the installed contract's:** graftling 0.10.0's `ACTION_FIELDS['models']` requires `runtime` and allows `provider`. P sends `{"runtime":"claude"}` (Main is a Claude Main). P reads the contract from the installed graftling, and V and I read it from describe.
- **Pr compares Main's answer with P's own computation on the same installed code**, so a stale host or a wrong entry shows as a difference.

## Trimmed from adopt-612/604 (and why)

- **rel, rp, gh, C5, the bundle:** no graftling release. graftling 0.10.0 is already production's and stays.
- **G (full suite), SR, suite-base:** replaced by GR614. Task 614's record already covers exactly TARGET with a v0.10.0 wheel of the same commit as production's, judged NEW 0. A new full suite runs only if the Leader decides it after a GR614 FAIL. **No step runs pytest**, so there is no TMPDIR concern for a new run; GR614 checks that the record's temp was outside the Harness.
- **graftling wheel build:** 612's wheel is reused by sha256; B compares it with git archive v0.10.0 instead of rebuilding.
- **mcp612.py (runtime_connections route):** P now uses `models` itself (614). V's v616.py checks `models` instead.
- **The USER-directory snapshot (homesnap):** no step installs a tool outside production.
- **scan, Vc, Mp, timers, X, markers.py:** trimmed as in 600/604/612. The guard still lists budget timers and never blocks on them or signals them.

## Rehearsal (`rehearse.zsh`; outputs in `rehearsal/`)

Everything runs through `zsh steps.zsh <step>` against scratch copies under `$TMPDIR/r616`. The Harness state, `<Harness>/graftling` and 614's record are only read.

**Fake production (fixture, built by the real product):**
- 612's REAL graphtraj 78f929ee and graftling 0.10.0 wheels, copied into the same state paths;
- conda's click and PyYAML, plus websockets 16.1.1 from PyPI (sha256 = PyPI's digest). This is a fixture: the sandbox may not read production's site-packages, and 16.1.1 is the version 614's run.txt records for production's test interpreter;
- `graphtraj setup` and the product's own `configuration --write` write the entries and the hook copy;
- Task state: copies of Tasks 616 and 516;
- fixture roles and user catalog for P: claude → anthropic, routed → a gateway keyed by the NAME FIXTURE616_KEY, inline with no provider.

**Stubs (fixtures):** `claude` (`--version`, and `-p` answering a stream-json init with apiKeySource none plus READY-616) and `ps`.

**Real:**
- B: the wheel build and every comparison, including 612's graftling wheel against git archive v0.10.0 of the real `<Harness>/graftling`;
- **GR614 on Task 614's REAL record** (`RESULT 616 GR614: PASS | 1 failed, 3725 passed, 48 skipped | known 1 | NEW 0 | ABNORMAL 0`);
- V: the product's regeneration of the hook copy (byte-identical), graphtraj-mcp, and v616.py mcp and bound;
- I: the backup, and the force-reinstall of only the graphtraj wheel, with graftling unchanged;
- P: the installed-code checks, the catalog read and role_models;
- R, from the backup's own copy;
- **I0 after R:** it moved the backup to `backup-run1-…` and the I/R records to `raw/run1/`; I0 again had nothing to set aside.

**Stand-in for Main's MCP call (labelled in the console):** the installed candidate's graftling handle_request bound to GraphTraj's backend in the fake production venv, as the native host binds a Main, executing `models {runtime: claude}`. Its document is `P.txt`.

**Fixtures (labelled):** Main's transcript lines (Mr: ToolSearch select: plus M[b]'s calls; Pr: ToolSearch select: plus the models call carrying P.txt), and Nr's child and member records, notice, reply and swarm result.

**Rehearsed STOPs** (`raw-stop/`, console):
- I before V/GR614;
- GR614 on a copy of 614's record with one NEW failed id (fixture line);
- Mpre with a member Worker (fixture ps line);
- I again with a backup present;
- Pr before P.txt exists.

**Results:** see `rehearsal/console.txt`. done counted every step's CHECK lines with 0 not passed.

**Not rehearsed:**
- real production `.venv-runtime`, its hook copy and entries (the fake production's own were written by the same product);
- `tmp/612/backup`;
- the real `ps`, so the guard and members_idle ran on fixture listings;
- the real Claude: 00's probe, Main's /exit and `claude --continue`, M, N and the child run;
- Main's MCP `models` call itself (the bound stand-in ran instead), the real user catalog and the Harness's real roles;
- `/private/tmp/vproject-616` and `vhome-616` (the rehearsal used `$TMPDIR/r616/vproject` and `vhome-616`).

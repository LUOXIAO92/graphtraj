# verify-641: task_backup recreates an Issue whose mapped Issue was deleted

## What changed (commit ed47b3b3)

Before, a Task whose mapped Issue had been deleted could not be backed up again. `task_backup` read the mapped Issue,
GitHub answered `gh: This issue was deleted (HTTP 410)`, and the result was `failed`. The mapping still named the
deleted Issue, and no public operation could replace it.

Now `_publish` (`src/graphtraj/graph/github_backup.py`) turns exactly that answer (`(HTTP 410)` on the GET of the
mapped Issue) into `IssueDeleted`. `backup_task` then:

1. gives the mapping a fresh marker, `issue: null`, `published: null` and a new `pending_since`, and records
   `replaced_issue: {number, url}`;
2. saves the mapping **before** creating, so a retry after a lost creation response finds the marked Issue through
   the existing marker search instead of creating a second one;
3. creates the Issue, and lets the existing `_link` place it under its mapped parent and its mapped children under it.

The next successful backup, the same call or a retry, reports `outcome: recreated` with `replaced_issue` and then
drops that field. Any other error is still `failed` and changes nothing remote: 404, 403, network failures, and a
number that now names another object. The manual section "Back up Tasks to Issues" in
`manuals/task-delivery/references/command-inputs.md` describes this, and so do the module docstring and the
`task_backup` description.

## Steps (Main: `zsh scripts/verify-641/steps.zsh <step>`, in this order)

| step | who | login | dialog | proves |
|---|---|---|---|---|
| pre | Main | the user's Claude login and gh login (Main asks the user first) | none | zsh, HEAD on base c18b4beb, graftling v0.10.2; `claude -p` names its model and login (`init: model … apiKeySource …`); `gh auth status` passes with your HOME **and** with the MCP server's environment (isolated HOME + `GH_CONFIG_DIR`); the repository (this Worktree's origin) gives your login admin (needed by `gh issue delete`). The account name is never printed. |
| install | Main | none | none | ROOT/venv imports graphtraj HEAD and graftling 0.10.2, both as wheels; `IssueDeleted` present |
| setup | Main | none | none | public `graphtraj setup`; probe Tasks 1 (parent) and 2 (child) through public `task register`, shown ready through public `task_graph`; host material; ROOT/mcp-641.json (env names GH_CONFIG_DIR, HOME, PATH) |
| trust | USER, once per path | – | "Do you trust the files in this folder?" → **Yes, proceed**; then `/exit` | lets Claude Code load the project plugin graphtraj-claude-host |
| real | Main | the user's Claude login and gh login | none | see "Observables" below; ALWAYS deletes every Issue it created and shows each answers HTTP 410 |
| post | Main | none | none | ~/.graphtraj, ~/.codex, ~/.pi/agent, ~/.dsh unchanged |
| G | Main | none | none | full suite, 6 shards; waits for other test runs and for its own shards; its last lines are `RESULT 641 G`, the counts and the next command |
| SR | Main | none | none | ids classed against 516's current definition (read through its task.yml `current_definition`) and the known `start an agent` id |
| suite-base | Main, only for NEW ids | none | none | base c18b4beb vs candidate, both with the v0.10.2 wheel |

Each step prints `RESULT 641 <step>` and the next command as its last lines, with real values. G's own process waits
for its shards before it judges.

## Observables of `real` (the real Claude host's `mcp__graphtraj__tasks`)

| criterion | observable line |
|---|---|
| serving path is the native host | `serving path: native graphtraj-claude-host association` and `CHECK 641 run 1/2 serving path …: PASS` |
| baseline: both Issues exist, child linked | `CHECK 641 run 1 parent 1 created: PASS`, `CHECK 641 run 1 child 2 created and linked under the parent: PASS` |
| the mapped Issue is really deleted | `PASS: #<child> now answers HTTP 410 (deleted)` (`gh issue delete` with your login, then a GET) |
| deleted → new Issue, recreation and old number reported | `CHECK 641 run 2 child 2 recreated: outcome recreated naming the deleted Issue: PASS (… replaced_issue {'number': <child>, …}, new Issue #<new> …)` |
| Sub-issue relation restored | `CHECK 641 run 2 the recreated Issue is linked under the parent: PASS` and `PASS: GitHub lists #<new> as the only Sub-issue of parent #<parent>` (read from GitHub, not from GraphTraj) |
| a repeat creates nothing | `CHECK 641 run 2 repeating the backup is unchanged on the same Issue: PASS` and `PASS: GraphTraj's marker search finds exactly one Issue for Task 2's current marker` |
| disposable Issues removed | `Issues created by this run: …`, one `#N: deleted now / already deleted (answers HTTP 410)` line each, `PASS: every Issue this run created now answers HTTP 410` |

Lost-response retry safety (requirement 2) cannot be caused on demand against GitHub. It is proved by
`tests/test_github_backup.py::test_lost_recreation_response_is_adopted_on_retry_without_a_second_issue`. The real
step shows the same marker search finding exactly one Issue. That 404 and 403 still fail without creating anything is
proved by `test_other_errors_on_the_mapped_issue_still_fail_without_creating`.

## GitHub use, credentials and isolation

- **Repository.** Read from this Worktree's `origin`; it is not written in the script. The test Issues have the
  title `verify-641 disposable test Task (parent|child)` and a neutral body. They name no account, path, machine,
  provider or model.
- **Cleanup.** `real` wraps its work in `{ … } always { cleanup }`. Cleanup collects Issue numbers from three
  sources: the judged results, the isolated mapping file, and a listing of the repository's Issues created since the
  step started that carry the title prefix and a backup marker. That listing covers a creation whose response was
  lost. Cleanup deletes each Issue with `gh issue delete --yes` and confirms each answers HTTP 410. If one is not
  deleted, the step FAILs and prints the exact command.
- **Credentials.** The script unsets every exported credential-class variable (GH_TOKEN, GITHUB_TOKEN, …; names
  printed). gh therefore uses only your stored login. Started processes get only `PATH HOME USER TERM TMPDIR LANG`
  plus the step's own names. The MCP server gets `HOME=ROOT/home`, so GraphTraj's state is the isolated one. It also
  gets `GH_CONFIG_DIR=<your gh config directory>` (a directory name) and `PATH` (gh's directory first). No token value
  is read, printed or written. pre checks that this exact environment reaches the login.
- **State.** Only the isolated project's `task-backups.yml` is used; production state is never read or written. ROOT
  (`/private/tmp/graphtraj-641`) is outside the Harness, so no Harness instruction file is above the project.
- **Rerun of real.** It STOPs while the isolated mapping exists and prints the exact `rm` for that file. The earlier
  run's cleanup has already deleted that mapping's Issues.

## Rehearsal (Engineer; `zsh scripts/verify-641/rehearse.zsh <step>...`)

`rehearsal/*.txt` holds the console output of each step through `zsh steps.zsh <step>`. The steps ran with
VERIFY641_* set, so every output says REHEARSAL. Before saving, home and temporary directories are replaced by `~`
and `$TMPDIR`.

- `claude` is a stand-in (`x641.py fake-claude`). It runs the prompt's `tasks` calls through the MCP entry's python
  and environment. It is not a Claude host, so the serving-path check prints SKIPPED.
- `gh` is a stand-in (`x641.py fake-gh`): a JSON file of Issues that answers a deleted Issue with HTTP 410, as GitHub
  does. The repository is `owner/repo`.
- No login was used and nothing was written to the network.
- `real-broken-run2.txt` makes run 2 call nothing. Its judge FAILs, and cleanup still deletes every Issue created so far.
- pre through post ran at 166e7e70; G, SR and suite-base ran at fbce624c. `src` and `tests` are identical from
  ed47b3b3 onward; later commits change only `scripts/verify-641`. Each commit moves HEAD, so Main's `install`
  builds the venv at the final HEAD.
- `real-rerun-stop.txt` is a second `real` while the mapping exists: it STOPs and prints the exact `rm`.
- G ran `-k 'test_github_backup or test_intent_queries_find_create'` through the same entry Main uses. These are real
  tests, including the repository-fixture backup tests: 21 + 4 passed. With the graftling 0.10.2 wheel, the known
  `start an agent` id passed here, so SR had nothing to class. Its known-id rule is unchanged from 614.
- suite-base ran two backup test ids, base c18b4beb against the candidate. The new test is absent on base, and the
  existing retry test passes on both.

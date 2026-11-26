# Task 642: test_tool_name_592 follows Task 627's Activity.tsx

Change: `tests/test_tool_name_592.py` ALLOWED entry for `desktop/src/Activity.tsx` now pins Task 627's footer
pluralisation `activity.agents.length === 1 ? 'agent' : 'agents'` (the plural word of the Agent count, not the tool).
The old entry `.agents.length} agents ·` matched no line after 9d2115f4. No regex is loosened; no UI change.

Steps (`zsh scripts/verify-642/steps.zsh <step>`, in order; dialog none, no login, no network; pytest temp under
`TMPDIR=${TMPDIR:-/tmp}` outside the Harness; records in `<Harness>/tmp/642`, copies in the Task's state `realhost`):

| step | proves |
|---|---|
| pre | zsh, HEAD, base c18b4beb is an ancestor, graftling v0.10.2, nothing uncommitted, TMPDIR outside the Harness |
| t592 | `tests/test_tool_name_592.py` passes on the candidate (suite venv: HEAD editable + graftling 0.10.2 wheel) |
| G | full suite, 6 shards; waits for other runs and its own shards; ends with GR's verdict |
| GR | the newest G record judged against 516's current definition + the known start-an-agent id |
| SR | the same classification, with the suite-base command for NEW ids |
| suite-base | NEW ids on base c18b4beb vs candidate |

Modelled on Task 641's `scripts/verify-641/steps.zsh` (commit bb11bc1c), keeping only pre, G, GR, SR, suite-base.
`rehearsal/` holds the Engineer's rehearsal transcripts (VERIFY642_* set, so REHEARSAL; not evidence).

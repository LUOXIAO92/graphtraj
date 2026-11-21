# verify-555: every input problem in one response; execute arguments from a JSON file (graftling)

Main runs from this Worktree in Main's Bash: `zsh scripts/verify-555/steps.zsh <step>`. No step needs user action
and none uses a model. Order: `00` → `D` → `T` → `TB` → `C`.

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | `candidate: <SRC> @ <sha> (agent/555-...)`, its noreply author, `baseline: 6794ce0…` and `baseline is an ancestor of the candidate: yes`; per copy `graftling 0.6.2 from BASE/src/...` (`555 public names: True`) and `from BASE/base-src/...` (`False`), the `agents-mcp entry` path. |
| `D` | none | `owning host: graftling.dsh.host pid N`, `agents-mcp serverInfo`, then 8 cases: several problems in one result (`errors` list of 5), file arguments success (`isError=False`, `agents: []`), file content problems together with an envelope problem, missing file, invalid JSON (line/column only), not an object, outside the boundary by `..` and by symlink. Last line: `'secret-555' (file content) in any result: no`. |
| `T [pytest args]` | none | graftling's `pytest -rfE` summary for the candidate copy, `TMPDIR=` printed (outside the Harness). Without args: the full suite. The args are saved for TB. |
| `TB [pytest args]` | none | The same for the baseline copy `BASE/base-src`, with T's args when none are given. |
| `C` | none | Read only: both args and summaries, then `failing in candidate / in baseline / in both`, `NEW (candidate only): n` with the ids (the new failures), `baseline only: n` with ids, and the pre-existing ids. Then `BASE/logs` (`D.*`, `T.*`, `TB.*`, `*.failing`) with `CANDIDATE` and `BASELINE` copied to `<Worktree>/.state/realhost/555/`. |

Layout under `BASE=/private/tmp/gl-555` (`VERIFY555_BASE` overrides): `src/` is `git archive` of the candidate clone's
HEAD (`VERIFY555_SRC`, default `<Worktree>/.scratch/555/graftling`), `base-src/` the same of the baseline
(`VERIFY555_BASELINE`, default dev `6794ce02b6210ec88837437affb8d7b525612804`); `venv/` and `base-venv/` hold them editable without dependencies
(`--system-site-packages` of `~/miniconda3/bin/python3.13`; `websockets` copied read only from the Harness
`.venv-runtime` when missing), `demo/` the D files, `logs/` every output.

What D replaces: only the native DSH (Node) process. `drv555.py` is copied into a fake DSH package so the real
`graftling.dsh.host` accepts it as its parent, as graftling's own `tests/test_dsh_standalone_host.py` does. Real: the
DSH host (owner connection, kernel-PID authentication, native Session check, boundary = that Session's cwd), the
`agents-mcp` console script as a stdio process, JSON-RPC framing and the candidate's envelope code.

Rehearsal: `zsh scripts/verify-555/rehearse.zsh <empty dir>` (output in `rehearsal/output.txt`; T and TB ran
`tests/test_dsh_standalone_host.py tests/test_approval_layers.py` through the same entry; the 555 test file does not
exist in the baseline).

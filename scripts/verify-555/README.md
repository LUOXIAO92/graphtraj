# verify-555: every input problem in one response; execute arguments from a JSON file (graftling)

Main runs from this Worktree in Main's Bash: `zsh scripts/verify-555/steps.zsh <step>`. No step needs user action
and none uses a model. Order: `00` → `D` → `T` → `C`.

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | `candidate: <SRC> @ <sha> (agent/555-...)`, its noreply author, `graftling 0.6.2 from BASE/src/...`, `new public names: True`, the `agents-mcp entry` path. |
| `D` | none | `owning host: graftling.dsh.host pid N`, `agents-mcp serverInfo`, then 8 cases: several problems in one result (`errors` list of 5), file arguments success (`isError=False`, `agents: []`), file content problems together with an envelope problem, missing file, invalid JSON (line/column only), not an object, outside the boundary by `..` and by symlink. Last line: `'secret-555' (file content) in any result: no`. |
| `T [pytest args]` | none | graftling's pytest summary for the candidate copy and `TMPDIR=` printed (outside the Harness). Without args: the full suite. |
| `C` | none | `BASE/logs` (`D.out`, `D.transcript.jsonl`, `T.out`) and `CANDIDATE` copied to `<Worktree>/.state/realhost/555/`. |

Layout under `BASE=/private/tmp/gl-555` (`VERIFY555_BASE` overrides): `src/` is `git archive` of the candidate clone's
HEAD (`VERIFY555_SRC`, default `<Worktree>/.scratch/555/graftling`), `venv/` holds it editable without dependencies
(`--system-site-packages` of `~/miniconda3/bin/python3.13`; `websockets` copied read only from the Harness
`.venv-runtime` when missing), `demo/` the D files, `logs/` every output.

What D replaces: only the native DSH (Node) process. `drv555.py` is copied into a fake DSH package so the real
`graftling.dsh.host` accepts it as its parent, as graftling's own `tests/test_dsh_standalone_host.py` does. Real: the
DSH host (owner connection, kernel-PID authentication, native Session check, boundary = that Session's cwd), the
`agents-mcp` console script as a stdio process, JSON-RPC framing and the candidate's envelope code.

Rehearsal: `zsh scripts/verify-555/rehearse.zsh <empty dir>` (output in `rehearsal/output.txt`; T ran the 555 tests
and the DSH standalone host tests through the same entry).

## Agent skills

### Issue tracker

Issues for this repository are tracked in GitHub Issues and managed with `gh`.
This repository-level setting does not configure the portable Master in
`codex/config.toml`; each target project binds its own tracker. See
`docs/agents/issue-tracker.md`.

### Triage labels

This repository's GitHub Issues use the five default canonical triage labels.
This mapping is not propagated to target projects operated by the Harness
Master. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses the single-context layout. See `docs/agents/domain.md`.

## Harness execution

- Invoke the project-owned `$task-delivery` Skill directly for an accepted
  Ticket DAG. Follow the Skill; do not restate or recreate its SOP here.
- Invoke Matt Pocock's global Skills directly when their workflow applies,
  including `$to-spec`, `$to-tickets`, `$implement`, `$tdd`, `$code-review`,
  and `$resolving-merge-conflicts`. Do not replace them with project copies or
  hand-written prompts.
- Spawn the installed canonical roles by name: `delivery-state`,
  `engineer-junior`, `engineer-senior`, `engineer-expert`, and
  `merge-resolver`. Their role definitions are authoritative; do not duplicate
  their developer instructions in dispatch prompts.
- Use `codex/config.toml` as the concurrency authority. Do not hard-code or
  reinterpret its capacity outside the Harness workflow.
- If a required Skill or role is unavailable, stop that operation and repair
  Runtime selection or installation. Do not improvise a substitute workflow.

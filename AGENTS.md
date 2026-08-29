# Repository Guidance

Keep this file limited to stable facts and constraints that apply to ordinary
work in this Source Repository. Harness orchestration, Delivery Run policy,
review findings, and task-specific instructions belong at the Harness Project
Root.

## Project structure

- `src/you_are_a_product_architect/` contains the Python package and packaged
  Runtime, role, Hook, and Skill resources.
- `tests/` contains behavior-focused pytest coverage.
- `README.md` is the product-facing installation and operation guide.
- `pyproject.toml` defines the package and the
  `you-are-a-product-architect` / `agent-runner` command surfaces.
- `CONTEXT.md` and `docs/` inside linked Worktrees are read-only Harness
  Project Document views, not Source Repository content.

## Standard checks

- Run focused tests with `pytest -p no:cacheprovider -q <paths>`.
- Run the complete suite with `pytest -p no:cacheprovider -q` only when the
  change can affect the wider product.
- Use `python -m compileall -q src tests` for a syntax pass and
  `git diff --check` for patch hygiene.

## Working constraints

- Prefer the smallest direct implementation that satisfies the accepted
  requirement. Do not add speculative abstractions, compatibility layers,
  configuration switches, fallback paths, or defense-in-depth work.
- Test observable behavior through public Setup, Runner, Runtime, or Hook
  seams. Do not freeze prose tokens, source text, private helper structure,
  absent code, or unsupported corruption scenarios.
- Preserve existing user changes and keep unrelated cleanup outside the active
  ticket.
- Do not modify, replace, move, or delete the Worktree `CONTEXT.md` or `docs/`
  views or their Harness-root targets.
- Repository issues are tracked in GitHub Issues and managed with `gh`.

# Repository Guidance

Keep this file limited to stable facts and constraints that apply to ordinary
work in this Source Repository. Harness orchestration, Ticket-and-Team delivery
policy, review findings, and task-specific instructions belong in Main-owned
Harness Project Documents.

## Project structure

- `src/graphtraj/` contains the Python package and packaged
  Runtime, role, and Skill resources.
- `tests/` contains behavior-focused pytest coverage.
- `README.md` is the product-facing installation and operation guide.
- `pyproject.toml` defines the GraphTraj distribution and the `graphtraj` /
  `agent-runner` command surfaces.
- New delivery uses `.graphtraj` configuration, Ticket/Team state, retained
  Batches, Session Traces, and the Project Worldline. Historical Run state is
  never migrated, read as fallback, or modified by supported commands.
- Reuse existing `CONTEXT.md` and `docs/` in linked Worktrees, preserving their
  contents and Git tracking. Missing paths may link to shared Project Documents.
  Delegated Agents retain read-only access; Main owns document updates.

## Python readability

- Give functions and methods docstrings explaining their purpose and relevant
  input/output semantics. A short summary suffices for simple functions. For
  more involved interfaces, use NumPy-style `Parameters`, `Returns` or `Yields`,
  and `Examples` sections as useful; explain shapes, units, conventions and side
  effects where they matter. Include formulas or small diagrams when they make
  an algorithm easier to understand.
- Separate distinct processing blocks with blank lines so the sequence of work
  is visible. Keep closely related statements together, and wrap long signatures
  and expressions across lines for readability.
- Align related assignments and similar adjacent statements into readable
  columns where practical. Use spaces around `=` and binary operators such as
  `+`, `-`, `*`, and `/`, including when alignment is impractical. In parameter
  and variable lists, separate items with commas followed by a space when the
  next item stays on the same line.
- Annotate function input parameters with their types. When a function
  definition has more than four parameters, put each parameter on its own line
  inside the parentheses; shorter signatures may also wrap for readability.
- Add `#` comments where a processing step, algorithmic choice or constraint
  needs explanation. Describe the intent, reasoning or relevant convention;
  keep the detail proportional to what the reader needs to understand the code.

Example:

```python
def calculate_total(
    unit_price: float,
    quantity: int,
    discount_rate: float,
    tax_rate: float,
    shipping: float = 0.0,
) -> float:
    """Return the discounted total with tax and shipping.

    Rates are fractions: 0.1 means 10 percent.
    """
    subtotal   = unit_price * quantity
    discounted = subtotal * (1 - discount_rate)

    # Shipping is excluded from the taxable amount.
    tax = discounted * tax_rate

    return discounted + tax + shipping
```

## Standard checks

- Run focused tests with `pytest -p no:cacheprovider -q <paths>`.
- Run the complete suite with `pytest -p no:cacheprovider -q` only when the
  change can affect the wider product.
- Use `python -m compileall -q src tests` for a syntax pass and
  `git diff --check` for patch hygiene.

## Working constraints

- Commit all authorized tracked project changes before ending a modifying turn
  or handing off, including documentation, Skills, configuration and resources.
  Mark incomplete or failing work honestly. Continuous user-interactive drafting
  may batch adjacent turns; commit before that editing segment ends or changes
  owner. Do not initialize Git or force-add ignored state for this rule.
  Immediately commit completed merges/conflict resolutions; an existing merge
  commit or fast-forward satisfies this requirement.
- Prefer the smallest direct implementation that satisfies the accepted
  requirement. Do not add speculative abstractions, compatibility layers,
  configuration switches, fallback paths, or defense-in-depth work.
- Test observable behavior through public Setup, Runner, or Runtime
  seams. Do not freeze prose tokens, source text, private helper structure,
  absent code, or unsupported corruption scenarios.
- Preserve existing user changes and keep unrelated cleanup outside the active
  ticket.
- Do not modify, replace, move, or delete the Worktree `CONTEXT.md` or `docs/`
  views or their Harness-root targets.
- Repository issues are tracked in GitHub Issues and managed with `gh`.

## Plain language and problem checks

These rules apply to every Agent doing implementation, review, investigation,
documentation, or other work in this Source Repository.

- Use established project terms and ordinary language. Do not invent jargon,
  synonyms, ownership labels, lifecycle concepts, layers, or named mechanisms
  merely to discuss or implement something. This applies to prompts, code,
  schemas, filenames, documentation, and review findings.
- Introduce a new term only when existing language cannot express a real
  distinction. Describe the concrete behavior and the need for the distinction
  before naming it.
- Before reporting a problem, creating rework, challenging a decision, or
  asking a question, check the assigned task, Session or handoff, repository
  guidance, accepted decisions, existing implementation, tests, and available
  evidence for an answer. Use an existing answer instead of asking someone to
  repeat it.
- A suspicion is not a problem. Identify a concrete conflicting requirement,
  missing fact, or observable failure before raising it or changing work for
  it. If none exists, do not raise it.
- Resolve ordinary implementation details within the assigned scope using the
  smallest reasonable choice. Do not repeatedly ask an upstream Agent or the
  user to decide them.
- Never reopen or relabel an accepted decision as unresolved. If new evidence
  genuinely conflicts with it, show the evidence and exact conflict before
  requesting another decision or changing the implementation.

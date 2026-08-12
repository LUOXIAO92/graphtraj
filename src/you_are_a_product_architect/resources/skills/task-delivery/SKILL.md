---
name: task-delivery
description: Orchestrate delivery of an accepted Ticket DAG while Main retains semantic authority and a Delivery State Agent maintains durable run records. Use when accepted tickets and their explicit dependencies are ready for Engineer dispatch, review escalation, and integration handoff.
---

# Task Delivery

## Consume settled work

- Require an accepted Ticket DAG with explicit dependencies before starting.
- Keep grilling, `$to-spec`, and `$to-tickets` outside delivery. Return
  incomplete, cyclic, ambiguous, or contradictory work to Main for planning or
  user clarification.
- Treat ticket scope, acceptance criteria, dependencies, and referenced design
  as settled. Do not normalize the DAG, invent dependencies, rewrite scope, or
  automatically re-split tickets.

## Keep Main in control

- Let Main own readiness, complexity and Engineer tier, dispatch, review
  adjudication, retry, escalation, integration ordering, and exceptions.
- Use the Runner only as mechanical transport for Main-selected Engineer
  tasks: launch, isolation, session transport, and cleanup. Do not ask it to
  inspect the DAG, select a frontier, choose a tier, interpret user intent, or
  make semantic decisions.
- Let the Runner provision or reuse the persistent ticket evidence directory,
  create the Ticket Worktree's scoped `.scratch/task-delivery` symlink, and
  write or update `metadata.yml` with mechanically known launch facts. Keep
  these as narrow provisioning and metadata duties; the Runner neither writes
  semantic evidence nor owns the Run ledger or Mermaid DAG.
- Drive the complete accepted DAG by default until every ticket is integrated,
  externally blocked, or escalated. Treat `awaiting-integration` as a checkpoint,
  not the end of the Delivery Run.
- Honor plain-language user interruption or redirection immediately. Interpret
  it in context without inventing pause, resume, cancellation, replanning, or
  other Run control-state protocol.

## Delegate Delivery Run records

1. Launch one Delivery State Agent per active Delivery Run through the
   Runtime's native agent tools from Main's Integration Worktree. Do not send
   this role through the Runner.
2. Ask it to initialize from accepted tickets and explicit dependencies. Let
   it create the stable `run_id` in the ASCII `YYYYMMDD-short-name` form. Require
   a semantic lowercase kebab-case short name and allow an optional positive
   numeric collision suffix such as `-2`. Let the Agent resolve collisions;
   the Runner only validates the ID and never creates or changes it. Then let
   the Agent create the working task map, ledger, and Mermaid DAG.
3. Treat it as the sole writer of that Run's ledger and Mermaid DAG. Register
   worktree, branch, tier, and Engineer session facts only after Main supplies
   them from Runner results. Never connect the State Agent directly to the
   Runner or send it across the Runner seam.
4. Ask the same Agent to synchronize only after a meaningful event. Let it
   read the registered Git state, result, validation, and raw review evidence
   directly; do not relay or rewrite those artifacts.
5. Supply compact semantic decisions only after Main has made them. Require a
   short state summary, ready-ticket suggestions, and inconsistencies or
   questions for Main.
6. Recover with a fresh Delivery State Agent when its session is unavailable.
   Reconstruct from persistent run artifacts and preserve one sole writer for
   the Run.

Never delegate review adjudication, readiness, tier choice, dispatch,
dependency changes, retry or escalation, integration acceptance, or exception
authority to the Delivery State Agent.

## Deliver each frontier

1. Read the accepted dependencies and current ledger. Let Main decide which
   tickets are ready; only validated integration of every prerequisite unlocks
   a dependent ticket.
2. Let Main classify each selected ticket as Junior, Senior, or Expert and ask
   the Runner to launch exactly those logical tasks. Keep any optional
   instruction concise; do not use it as a second ticket specification.
3. Ask the Delivery State Agent to register launch facts and synchronize after
   every Engineer return, review adjudication, retry, escalation, integration
   result, blocker, or user redirection.
4. Require the Engineer to return either candidate commit and validation plus
   raw Standards and Spec Reviewer evidence, or evidence of a blocker. Do not
   treat an Engineer's own claim as review acceptance.
5. Let Main read both Reviewer reports and adjudicate the review round as
   `PASS` or `FAIL`, with a concise rationale. On `PASS`, mark the ticket
   `awaiting-integration`. On `FAIL`, apply the escalation policy below.
6. Hand reviewed work to the repository's accepted integration sequence. After
   Main reports the integration result, synchronize the Run and continue with
   the next Main-selected frontier.

## Escalate review failure

- Increment a tier counter only for a Main-adjudicated `FAIL`. Do not count TDD
  red states, implementation test or typecheck failures, transport failures,
  integration failures, or external blockers.
- Below three failures at a tier, resume the same Engineer session in the same
  Ticket Worktree with the retained evidence.
- At three Junior failures, replace the Engineer with a Senior in fresh
  context. At three Senior failures, replace it with an Expert in fresh
  context. Start the new tier's counter at zero while retaining the same Ticket
  Worktree, canonical work, and same evidence; do not transfer the former
  conversation.
- At three Expert failures, stop autonomous delivery for that ticket. Use the
  target user's selected exception path: delegated Main authority or
  human-in-the-loop decision. Do not hard-code which path owns target-project
  semantic exceptions.

## Hand off integration

Follow this repository's accepted review and integration sequence without
turning it into Runner behavior:

1. Let Main serialize reviewed commits in the `dev` Integration Worktree.
2. Let Main invoke the Merge Resolver for textual or semantic integration
   conflicts and adjudicate the result.
3. Let Main run integration validation. Record `integrated` only when the
   reviewed commit is present in `dev` and that validation passes.
4. Let Main request mechanical Runner cleanup after successful integration.
   Preserve the run ledger, Mermaid DAG, retained batch, and ticket evidence.
5. Resume this Delivery Run; unlock dependents only from validated `dev`.

Do not merge into `dev` inside this Skill. Do not schedule or normalize work,
automatically re-split tickets, promote `dev` to `main`, or decide the target
project's exception authority.

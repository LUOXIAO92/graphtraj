---
name: task-delivery
description: Orchestrate delivery of an accepted Ticket DAG while Main retains semantic authority and a Delivery State Agent maintains durable run records. Use when accepted tickets and their explicit dependencies are ready for Engineer dispatch, optional review, escalation, and integration handoff.
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
- Use the Runner only as mechanical transport for Main-selected Engineer and
  Reviewer tasks: launch, isolation, session transport, and cleanup. Do not ask it to
  inspect the DAG, select a frontier, choose a tier, interpret user intent, or
  make semantic decisions.
- Let the Runner provision or reuse the persistent ticket evidence directory,
  create the Ticket Worktree's scoped `.state` symlink, `.scratch` directory,
  and read-only Harness Project Document views, and write or update
  `metadata.yml` with mechanically known launch facts. Keep these as narrow
  provisioning and metadata duties; the Runner does not write semantic
  evidence or cross the Delivery State Agent's authority.
- Drive the complete accepted DAG by default until every ticket is integrated,
  externally blocked, or escalated. Treat `awaiting-integration` as a checkpoint,
  not the end of the Delivery Run.
- Honor plain-language user interruption or redirection immediately. Interpret
  it in context without inventing pause, resume, cancellation, replanning, or
  other Run control-state protocol.

## Delegate Delivery Run records

Read current Harness Project Documents from the Harness Project Root. Do not
treat Source Repository history or Worktree document views as their authority.
This Skill only invokes the Delivery State Agent as part of Main's delivery
orchestration.

1. Launch one Delivery State Agent per active Delivery Run through the
   Runtime's native agent tools from the Harness Project Root. Do not send this
   role through the Runner.
2. Ask it to initialize from accepted tickets and explicit dependencies. Let
   it create the stable `run_id` in the ASCII `YYYYMMDD-short-name` form. Require
   a semantic lowercase kebab-case short name and allow an optional positive
   numeric collision suffix such as `-2`. Let the Agent resolve collisions;
   the Runner only validates the ID and never creates or changes it.
3. Supply compact semantic decisions only after Main has made them. Require a
   short state summary, ready-ticket suggestions, and inconsistencies or
   questions for Main.
4. Recover with a fresh Delivery State Agent when its session is unavailable,
   using the persistent Run records.

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
3. Coordinate Delivery State records through the Delivery State Agent.
4. Require the Engineer to return either a candidate commit and validation
   evidence, or evidence of a blocker. The Engineer does not dispatch
   Reviewers, create the authoritative Reviewer set, or claim review acceptance.
5. Let Main fix the candidate commit and comparison point, then decide whether
   the fixed candidate needs review. Review applicability is Main's semantic
   judgment: Main may omit Reviewer dispatch for any candidate it judges not to
   require review, and merge or integration actions never require Reviewer
   dispatch. Do not encode mechanical applicability rules or change the
   existing Standards or Spec review meaning in this workflow.
6. When review is useful, dispatch one `standards-reviewer` and one
   `spec-reviewer` concurrently through the selected Runtime Adapter in separate
   Runner tasks against the same fixed Ticket Worktree, with neither axis
   gating the other. Supply the exact
   candidate, comparison point, existing axis brief, and standards or spec
   sources in Main's instruction, along with that axis's exact report path under
   `.state/reviews/`. For each Reviewer task, set `report_file`
   to that axis's exact non-overwriting report path and also supply the same
   path in the Reviewer instruction. Require both Reviewers to write only their
   assigned report and leave the candidate and its Git state unchanged.
7. Retain their separate raw axis-specific reports under
   `reviews/<candidate-alias>-rN-standards.md` and
   `reviews/<candidate-alias>-rN-spec.md`; never overwrite an earlier round.
   Verify the fixed candidate and clean Git state before adjudication. Record
   each Reviewer's role, Runner alias, selected Runtime, and configured model
   with its report so the evidence remains attributable.
8. Main waits for both reports and applies the Harness Guidance at the Harness
   Project Root. Main adjudicates both reports as one review round and records
   `PASS` or `FAIL` with a concise rationale. On `PASS`, mark the
   ticket `awaiting-integration`. On `FAIL`, apply the diagnosis policy below. When
   Main omits review, record that decision and move the validated candidate to
   `awaiting-integration` without inventing a review verdict.
9. Hand accepted work to the repository's integration sequence. After Main
   reports the integration result, synchronize the Run and continue with the
   next Main-selected frontier.

## Select one Agent Runtime per batch

- Let explicit user direction choose the Runtime before Harness Project policy,
  and let Harness Project policy choose before Main's current Runtime.
- When those sources do not permit a confident choice, ask the user and record
  the answer.
- Record one selected Runtime once at batch level as `runtime`; each task keeps
  only its logical role and task access. Do not repeat Runtime, model,
  configuration, Hook, command, or path details in task objects.
- Main may select a different Runtime or configured model for either Reviewer.
  The same Runtime and model remain valid. Claim Review Diversity only when the
  selected Reviewer's Runtime or model actually differs from the implementing
  Engineer's; otherwise record the selections without a diversity claim.
- Let the Runner validate the selected configured built-in Adapter before it
  reserves a task, provisions a Worktree, retains a batch, or starts a Runtime.

## Diagnose review failure

- Treat each Main-adjudicated `FAIL` as evidence to diagnose. Before retrying,
  replacing an Agent, choosing a higher tier, or returning work to planning,
  Main records the cause and its rationale for the next action.
- Keep a small implementation correction with the same Engineer and tier. Use
  a fresh-context Engineer at the same tier only when the Ticket remains
  suitable but the current session context is polluted. Choose a higher tier
  only when the accepted Ticket is clear and the evidence shows genuine
  difficulty or a capability mismatch; this may happen before three failures.
  Three failures at one tier require explicit reassessment, never automatic
  escalation.
- When Main's tier choice, decomposition, dependencies, acceptance mapping, or
  dispatch instruction caused the failure, Main corrects its orchestration
  within the accepted Spec instead of counting an Engineer failure. For
  Main-created overengineering, remove unsupported mechanisms, assumptions,
  validations, edge cases, and tests; do not keep refining the polluted Ticket
  or candidate, and classify the corrected minimal work again.
- Reviewer error, transport failure, implementation-test failure, integration
  failure, and external blockers do not justify tier escalation. Product or
  Spec changes remain user-owned.
- Keep failure counts only as historical evidence. The Delivery State Agent
  records Main's decision; neither it nor the Runner infers the cause or
  chooses the next action.

## Hand off integration

Follow this repository's accepted review and integration sequence without
turning it into Runner behavior:

1. Let Main serialize accepted candidate commits in the `dev` Integration Worktree.
2. Let Main invoke the Merge Resolver for textual or semantic integration
   conflicts and adjudicate the result.
3. Let Main run integration validation. Record `integrated` only when the
   accepted commit is present in `dev` and that validation passes.
4. Let Main request mechanical Runner cleanup after successful integration.
   Preserve retained Delivery Run records and ticket evidence.
5. Resume this Delivery Run; unlock dependents only from validated `dev`.

Do not merge into `dev` inside this Skill. Do not schedule or normalize work,
automatically re-split tickets, promote `dev` to `main`, or decide the target
project's exception authority.

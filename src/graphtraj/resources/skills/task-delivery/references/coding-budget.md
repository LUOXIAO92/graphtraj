# Coding-ticket execution budget

Read this when issuing a code ticket or preparing its dispatch. Estimate from
its concrete behavior, acceptance, current implementation and required checks.
A general task node's size or rough estimate is not a code-ticket budget.

Start the Issue body/local ticket with YAML front matter, before any heading:

```yaml
---
difficulty: medium
difficulty_reason: Resource loading and setup change across existing modules
execution_budget:
  estimated_minutes:
    implementation: 10
    validation: 10
    review: 5
    total: 25
  planned_sessions:
    team_leader: 1
    engineer: 1
    standards_reviewer: 1
    spec_reviewer: 1
    delivery_state: 1
  correction_rounds: 1
  estimation_note: Existing integration checks may dominate elapsed time
  on_exceed: On the timer notice, assess supplied progress and failures; reuse evidence and record the decision
---
```

Replace example values with task-specific estimates and reasons. Difficulty and
its reason stay estimation properties; they do not select an Engineer role.
Minute and Session thresholds are explicit positive numbers; correction rounds
may be zero. Total is an elapsed-time budget, not summed parallel Agent time. Record
uncertainty in estimation_note, not min/max thresholds. Do not budget tokens.
Count the roles actually needed, including state maintenance when applicable.

Count a Runtime Session once across resumptions. The correction allowance covers
both same-Round process corrections and implementation rework that opens another
Round; keep their existing lifecycle records distinct.

Keep this front matter in the authoritative ticket and its retained snapshot.
Before dispatch, check scope, Engineer selection and checks still fit it. If
missing or stale, update the ticket through the configured authorized workflow,
retaining its previous definition and the reason. This does not invoke the
explicit-only to-tickets skill or redo task decomposition.

Runner's timer sends notices when the elapsed estimate and sampled additional
allowance are reached, and when it selects stopping. Preserve both delivery
paths: the Leader Session and the calling Main's live notice channel. CLI uses
stderr unless an inherited `GRAPHTRAJ_BUDGET_NOTICE_FD` selects that channel;
keep it connected to the waiting execution tool rather than only a log file.
On each notice, inspect the supplied state and any missing decision evidence
once, then record the decision. Estimate and allowance notices are not enforced
stops. No notice calls for another monitoring loop; waiting for one requires no
Agent polling. Runner's internal timer checks are separate.

Being unfinished or approaching a threshold alone does not justify increasing
the budget. For a justified revision, distinguish changed work from dispatch
errors and waiting, estimate what remains, and assess the effect on the stop
threshold. Preserve original accounting under the accepted budget policy.

If Runner selects stopping, freeze the scene and collect limited Engineer and
Leader reports while already-running Reviewers finish. Preserve files, commits,
Worktree, Sessions and Traces. The timer notification and returned wrap-up
trigger [recovery decisions](recovery.md), including the caller host's explicit
Skill invocation. Stopping alone
does not authorize new implementation, Review, correction, replacement,
retirement or escalation.

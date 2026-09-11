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
  engineer_tier: senior
  tier_reason: Needs cross-module implementation and behavioral validation
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
  on_exceed: Inspect progress and failures; reuse evidence and record the decision
---
```

Replace example values with task-specific estimates and reasons. Minute and
Session thresholds are explicit positive numbers; correction rounds may be
zero. Total is an elapsed-time budget, not summed parallel Agent time. Record
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

Runner sends the Leader notices when the elapsed estimate and sampled
additional allowance are reached. If Runner later selects stopping, freeze the
scene and collect limited Engineer and Leader reports while already-running
Reviewers finish. Preserve files, commits, Worktree, Sessions and Traces. Use a
relevant diagnosis Skill before choosing subsequent work; stopping alone does
not authorize new implementation, Review, correction, replacement, retirement
or escalation. A revised budget still preserves the original start and consumed
schedule.

# Coding-ticket execution budget

Read this when issuing a code ticket, preparing its dispatch, or responding to
a coding-budget notice or forced stop. Estimate from
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
  on_exceed: Escalating reminders, forced stop, then required retro diagnosis before resuming
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

The first crossed elapsed, Session or correction threshold starts one Ticket
overrun interval. Runner reminds immediately, then at 4, 6, 7, 8, 9 and 10
minutes, and forcibly stops the affected Ticket's execution at 11 minutes.
Further crossings do not restart that interval. Preserve the original start,
consumption, Sessions, candidate and available evidence.

On each notice, inspect current progress and failures. A continuation decision
names the remaining work, remaining minutes and next inspection point; another
confirmed defect can invalidate that estimate. These decisions do not replace
the enforced stop and diagnosis requirement.

After a forced stop, use Runner's designated diagnosis entrypoint to execute
$retro against the retained Session/Trace evidence. Identify the actual cause,
repeated work, current candidate and valid checks, and the smallest recovery
action. The caller then explicitly decides continuation from that diagnosis,
including remaining work and budget. Complete this required diagnosis before
ordinary dispatch, send or replacement may continue the stopped Ticket.
Budget stops do not by themselves establish failed acceptance, model mismatch
or a need to replace the Team. Judge those decisions from the evidence.

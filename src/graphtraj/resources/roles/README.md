# Explicit role content

A role reference identifies a configured participant. Its name or group never
selects professional instructions, Skills, native helpers, access or reports.
Reusable presets and inline roles accept the same explicit fields:

| Field | Default | Meaning |
| --- | --- | --- |
| `instructions` | `task` | Packaged YAML resource basename in this directory, without `.yml`; `_` also selects the corresponding `-` filename. Missing resources fail at preflight. |
| `harness_skills` | `[]` | Additional required Harness Skill names, resolved through the existing Harness/user Skill lookup. These add to the selected resource's `required_skills`; missing Skills fail at preflight. |
| `worktree_access` | `write` | `read` or `write`; project documents, private Runner state and report isolation retain their separate restrictions. |
| `reports` | `[]` | Distinct plain `.md` filenames allocated in the current Team Round. Empty means one actual-role report. Repeated role instances retain the existing alias suffix allocation. An explicit task `report_file` takes precedence. |
| `allow_runtime_swarm` | `false` | Native helper capability, independently of role name. This does not authorize any formal Runner dispatch edge. |

Existing `runtime`, `model`, `reasoning_effort`, provider connection and `codex`
approval fields retain their meanings. Task `skills` still selects Repository
Skills. `role_tree` and actual Session ownership still control formal dispatch.
Report paths remain in the existing Session `report_files` mapping; report
submission goes through Runner, even with a read-only Worktree.

To retain a selected coding method, add the following fields to its existing
preset without replacing user Runtime/model/provider/approval settings:

| Selected method | `instructions` | `worktree_access` | `reports` |
| --- | --- | --- | --- |
| Implementation | `engineer` | `write` | `[engineer.md, validation.md]` |
| Coordination | `team-leader` | `read` | `[leader.md]` |
| Standards review | `standards-reviewer` | `read` | `[standards.md]` |
| Spec review | `spec-reviewer` | `read` | `[spec.md]` |
| Merge resolution | `merge-resolver` | `write` | Task-selected or default |
| State request drafting | `delivery-state` | `write` | Task-selected or default |

These are examples of explicit selections, not role-name rules. A differently
named role can select any of them, and selecting a prompt does not itself make
a Worktree read-only. Add `allow_runtime_swarm: true` only where wanted. Existing
explicit reasoning efforts remain unchanged; if preserving a formerly implicit
coding-template effort, select `reasoning_effort: max` explicitly (the generic
Runtime default is `high`). No existing Session, report or Trace is rewritten.

# Triage Labels

Engineering skills use five canonical triage roles for this repository's
GitHub Issues.

| Canonical role    | Default label      | Meaning                                    |
| ----------------- | ------------------ | ------------------------------------------ |
| `needs-triage`    | `needs-triage`     | Maintainer needs to evaluate the issue     |
| `needs-info`      | `needs-info`       | Waiting for more information               |
| `ready-for-agent` | `ready-for-agent`  | Fully specified and ready for an agent     |
| `ready-for-human` | `ready-for-human`  | Requires human implementation or judgment |
| `wontfix`         | `wontfix`          | Will not be actioned                       |

This mapping configures this repository only. It does not configure projects
operated through the Harness Project Root's `.codex/config.toml`. Each target
project owns its own triage mapping and may use different labels or equivalent
workflow states.

If this repository later renames its GitHub labels, edit the right-hand column
without changing the canonical roles.

---
status: accepted
---

# Own Harness Project Documents at the Harness Project Root

Harness Project Documents belong to the Harness Project control plane, not to
Source Repository history. The Harness Project Root owns `CONTEXT.md`, `docs/`,
and Harness-specific Main guidance in its root `AGENTS.md`; Main is their only
writer. The Integration Worktree and each Ticket Worktree receive untracked,
Git-ignored `CONTEXT.md` and `docs` symbolic links to those authoritative root
documents. Setup provisions the Integration links and the Runner provisions
Ticket links. The operator-owned Primary Worktree remains untouched.

The Source Repository root `AGENTS.md` remains Repository Guidance: short,
stable facts and constraints that apply broadly to repository work, such as
project structure and standard commands. It must not accumulate Harness
orchestration, Delivery Run state, Runtime policy, task-specific instructions,
historical explanations, speculative safeguards, or individual review
findings. Setup no longer creates or manages a Reviewer-guidance block there;
it manages Harness Guidance at the Harness Project Root instead. The Source
Repository may retain product-facing `README.md`, but `docs` and `CONTEXT.md`
are reserved Harness Project Document access paths and conflicting repository
entries fail setup preflight rather than being overwritten.

Subagents may read Harness Project Documents through their Worktree links but
cannot create, modify, move, or delete the links or their targets. Native
Runtime permissions and the Worktree Guard enforce that boundary. Cleanup
removes only the disposable Worktree link and never follows it into the
Harness Project Root. Historical whole-system and pre-split documents are not
promoted into the new authoritative document set.

This record supersedes ADR 0023's Source-Repository-owned Project Document
placement and ADR 0026's repository-managed Reviewer guidance. It preserves
their Main-write/subagent-read boundary while moving the authority to the
Harness Project Root. This follows Codex guidance discovery deliberately: Main
starts at the Harness Project Root and reads its `AGENTS.md`, while an Agent
started inside a Git Worktree uses that Worktree's repository guidance.

## Considered options

- Keeping authoritative documents in `dev` was rejected because an
  implementation checkout would remain the accidental control plane and every
  Ticket branch would carry delivery-process documents in product history.
- Committing one symbolic link was rejected because Primary, Integration, and
  Ticket Worktrees have different relative depths and an absolute link would
  encode one machine's Harness Project Root.
- Copying Harness Guidance into Repository Guidance was rejected because it
  would make every repository Agent inherit Main-only orchestration policy and
  recreate the prose duplication that ADR 0026 attempted to prevent.

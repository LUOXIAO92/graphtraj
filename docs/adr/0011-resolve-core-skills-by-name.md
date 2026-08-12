---
status: accepted
---

# Resolve core Harness Skills by declared name

Harness workflows and roles identify Skill dependencies only by declared name.
V1 does not add a target-project Skill lock file, content hashes, source-path
attestation, or automatic semantic compatibility checking.

The required core Skill names are:

- `setup-matt-pocock-skills`
- `grill-with-docs`
- `grilling`
- `domain-modeling`
- `to-spec`
- `to-tickets`
- `task-delivery`
- `implement`
- `tdd`
- `code-review`
- `resolving-merge-conflicts`

The standalone Click `doctor` command has one responsibility: report a
human-readable `OK` or `MISSING` for every required name and exit zero only
when all are discoverable. Missing non-core Skills do not fail it. `doctor`
does not inspect Runtime files, Git state, Runner config, or worktrees; setup
performs those separate preflights and directly reuses the same Python Skill
check rather than spawning and parsing the command. `doctor` has no YAML or
other machine-output mode.

When a core Skill is missing, interactive setup offers two paths:

- install the release's backed-up supported copy into the Source Repository's
  `.agents/skills/` directory through its `dev` Integration Worktree; or
- stop before writing anything so the operator can install it independently at
  user scope and rerun setup.

Setup never installs a Skill globally. It installs or verifies
`setup-matt-pocock-skills` but does not invoke it.

Named dependencies are workflow guidance, not per-role allowlists. V1 does not
isolate Skill discovery by role or prevent roles from seeing other available
Skills. Main is deliberately unrestricted. Engineer developer instructions
direct Junior, Senior, and Expert toward `implement`, `tdd`, and `code-review`;
the Merge Resolver is directed toward `resolving-merge-conflicts`. Reviewer
threads and the Delivery State Agent have no required Skill. These are soft
developer-instruction responsibilities, not Runtime-enforced isolation.

Duplicate discoverable Skill names may resolve differently across Runtimes.
Exhaustive collision detection is not a V1 priority; this is documented as a
README limitation and operators should avoid duplicate names. An Adapter may
warn when it can observe a collision.

Upstream semantic compatibility remains a maintainer decision. The maintainer
follows upstream changes, checks whether they alter Harness semantics, and
keeps backups of multiple versions. Each product release chooses one supported
set for project-local installation; if upstream removes a dependency, the
last compatible backed-up version remains distributable. Setup does not expose
the backup history as a version selector, and Runner or `doctor` does not act
as an updater or semantic verifier.

This deliberate name-only policy keeps prompt semantics out of the Python
implementation and makes upstream updates easy to adopt, at the cost of the
documented duplicate-name and manual-compatibility limitations.

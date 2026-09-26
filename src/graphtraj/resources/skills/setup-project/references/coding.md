# Coding setup

Use this reference when the project selects programming methods. Inspect the
existing codebase guidance, package structure and validation commands; preserve
agreed role assignments, Runtime settings and project documents.

Select implementation, testing and code review according to the task. Record
who implements, who provides validation and who is authorized to accept the
result. One engineer can execute a task through the common task protocol.
Selecting a programming language does not require a Team Leader or Reviewers.

If the project explicitly selects the coding-team method, its coordinator
assigns scoped work and acceptance responsibilities to the configured members.
A project may assign development tests to the Engineer, test acceptance to the
Leader and read-only code inspection to Reviewers. Write that arrangement only
when selected; retain this project's existing accepted responsibilities.
Use the configured role_tree and actual parent bindings for dispatch/control.

Instruction-only changes need consistency checking and a commit where tracked.
Small fixes and test changes do not call for TDD or code-review Skills. For
other changes choose only needed Review axes, each at most once per Ticket;
reuse reports when verifying corrections. Professional checks supply evidence
for the same versioned submission, authorized decision and integration used by
other tasks. They do not establish a second task lifecycle.

Keep shared documents in their established project-owned location. Expose
project guidance read-only to delegated Worktrees and ensure each executor can
read its actual responsibilities. Preserve user content and settings.

Tracker configuration stays in the parent Skill. Pull requests enter the
request queue only when explicitly selected. For that request surface read the
configured provider reference: [GitHub](github-requests.md) or
[GitLab](gitlab-requests.md). Keep the provider's default-off setting in the
tracker binding and add operational detail only when enabled.

# Issue Tracker: GitHub

Issues and specs for this repository live as GitHub issues in
`LUOXIAO92/you-are-a-product-architect`. Use the `gh` CLI for all operations.

## Scope boundary

This file configures engineering skills while they work on this repository
itself. It does **not** configure the portable Harness Master defined by
`codex/config.toml`, and it does not establish a default tracker for projects
operated by that Master.

Each target project binds its own issue workflow. Depending on that project's
environment, the binding may use GitHub, GitLab, a local Git server, local
Markdown, or another tracker. The Master must read or establish the target
project's binding instead of inheriting this repository's GitHub choice.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a
  heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by
  `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`
  with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`.
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` or
  `--remove-label "..."`.
- **Close an issue**: `gh issue close <number> --comment "..."`.

Infer this repository from `git remote -v`; `gh` does this automatically when
run inside the clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

When set to `yes`, PRs run through the same labels and states as issues, using
the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and
  `gh pr diff <number>` for the diff.
- **List external PRs for triage**:
  `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`,
  then keep only `authorAssociation` values of `CONTRIBUTOR`,
  `FIRST_TIME_CONTRIBUTOR`, or `NONE`.
- **Comment, label, or close**: use `gh pr comment`,
  `gh pr edit --add-label` or `--remove-label`, and `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be
either. Resolve it with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue in this repository.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments` in this repository.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as
tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes,
  Decisions-so-far, and Fog body. Create it with
  `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api`
  on the sub-issues endpoint). Where sub-issues are unavailable, add the child
  to a task list in the map body and put `Part of #<map>` at the top of the
  child body. Labels use `wayfinder:<type>` (`research`, `prototype`,
  `grilling`, or `task`). Once claimed, assign the ticket to the driving dev.
- **Blocking**: use GitHub's native issue dependencies. Add an edge with
  `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`,
  where `<blocker-db-id>` is the blocker's numeric database ID. Where native
  dependencies are unavailable, use a `Blocked by: #<n>, #<n>` line at the
  top of the child body.
- **Frontier query**: list the map's open children, then drop any with an open
  blocker or an assignee. The first remaining child in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`; this is the session's
  first write.
- **Resolve**: comment with the answer, close the child, then append a context
  pointer to the map's Decisions-so-far.

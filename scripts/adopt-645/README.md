# Adopt Task 645 into graftling

Documentation only: README `## Known limits` gains two Windows/Codex bullets, and
PUBLIC_API.md's Windows (639) paragraph points to the first one. No code changes.

- Branch: `agent/645-graftling-windows-codex-limits-docs`
- Candidate commit: `eb5ad8e5b080f2cc0c826f8d0fe7c54882d96866` (one commit on graftling `dev` `2ee706eb749355afc3f73f03a1b0de4cd48da1f2`)
- Author and committer: `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`
- Bundle: `graftling-645.bundle`, sha256 `e29d54e3bed46bcce06e0e00f39278507b06259c084f67d16efc694bbcde081f`. It requires only `2ee706eb`.

Put it into the Harness's graftling as a local branch (nothing is pushed), from the Harness root:

```
git -C graftling fetch .graphtraj/core/worktrees/645-graftling-windows-codex-limits-docs/scripts/adopt-645/graftling-645.bundle agent/645-graftling-windows-codex-limits-docs:agent/645-graftling-windows-codex-limits-docs
```

If this file has moved with a merge into GraphTraj, use `scripts/adopt-645/graftling-645.bundle` from that checkout instead.

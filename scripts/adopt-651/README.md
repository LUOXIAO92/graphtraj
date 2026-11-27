# Adopt Task 651 into graftling

Documentation only: README gains `### Windows` under Install (support per Runtime,
prerequisites, per-host steps) and two Windows bullets in `## Known limits`; the four
install notes point to it, the Claude Code note states that print mode needs folder
trust, and the DSH note gives the `file:` URL for `--patch` on Windows. PUBLIC_API.md
gains the DSH Windows paragraph (1.7) and the marketplace plugin's real-host behaviour
(1.1). CHANGELOG.md gains `## Unreleased` for 632-651. The stray `</content>` last lines
of README, CHANGELOG and the install notes are removed. No code changes.

- Branch: `agent/651-graftling-windows-docs`
- Candidate commit: `b179984235decfedfe7ff3ec1d032b5399a712cb` (one commit on graftling `dev` `0e5c92a602005ba0c0e53b887ff612dfd28180fd`)
- Author and committer: `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`
- Bundle: `graftling-651.bundle`, sha256 `72d1fdb9a6e5f7fb71e1289b80eab5db294df89867c2377ee335ec5e72907700`. It requires only `0e5c92a6`.

Put it into the Harness's graftling as a local branch (nothing is pushed), from the Harness root:

```
git -C graftling fetch .graphtraj/core/worktrees/651-graftling-windows-docs/scripts/adopt-651/graftling-651.bundle agent/651-graftling-windows-docs:agent/651-graftling-windows-docs
```

If this file has moved with a merge into GraphTraj, use `scripts/adopt-651/graftling-651.bundle` from that checkout instead.

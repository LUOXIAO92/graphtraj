# Task 530 — real-entry result

## BEFORE (graftling 4a002129 v0.6.2 + GraphTraj c917f5fc), run by Main and the user 20:31–20:33 on 2026-11-20

BASE=/private/tmp/graphtraj-530, web profile web530, brand-new data roots, the first agents call inside one DSH web turn.

| case | screenshot | card '…を編集しました' | step C |
|---|---|---|---|
| UG — GraphTraj DSH Main (graphtraj-main row) | `.graphtraj/core/state/tasks/530-graftling-root-files-in-dsh-changes/realhost/screenshot-UG.png` | none | session-6a4613c6: workspace/changes events 0 |
| US — graftling alone (graftling-dsh agents-host row) | `.graphtraj/core/state/tasks/530-graftling-root-files-in-dsh-changes/realhost/screenshot-US.png` | none | session-1de0efc5: workspace/changes events 0 |

Step C details:
- UG: `.graphtraj/swarm` root, `config.yml`, `live/config.lock`, `sessions/.gitignore` and `session.lock` were all
  created at 20:31:49, and `session.jsonl` at 20:32:02. The turn took 4 s and ended at 20:32:02. Main's inference:
  GraphTraj's host set up the data root when the conversation started, before DSH took its turn baseline, so these
  files were not changes made during the turn.
- US: `graftling-data` was created at 20:33:10 and holds no files.
- `git status` in the UG project also has untracked `.graphtraj/runner/main-sessions/{continuity.jsonl,
  continuity.lock,finalize_73bb…/binding.lock,finalize_73bb…/session.yml}` and the two swarm files. None of them was
  listed in the turn.

## Conclusion

Not reproduced, so no code change. Under the user's 2026-11-18 principle only defects that reproduce are fixed.
- The GraphTraj fix 974cb8e9 is reverted by 4282f569. `git diff --stat c917f5fc HEAD -- src tests` is empty.
- graftling 95cffda1 (`.scratch/graftling-530.bundle`) is withdrawn. It stays unmerged and is not to be adopted.
- The AFTER steps UG2, US2 and C2, and the test steps T and TR, were not run because there is nothing to compare.

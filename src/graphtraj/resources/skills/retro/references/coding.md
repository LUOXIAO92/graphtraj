# Coding retrospective

Separate implementation rework, review, report repair and integration costs.
A defect discovered by review explains work performed; it does not by itself
prove Engineer delay or wasted review. When locating the start of coding, count
test edits and shell/script writes as well as production patches, and distinguish
them from executing tests.

Before calling validation redundant, compare the candidate, changed paths,
purpose and any requirement for fresh evidence. Distinguish necessary regression
checks from repeated full suites on unchanged behavior. A changed candidate may
need affected checks or review; a missing report copy may need only report repair.

Recommend an earlier lint, type or behavior check only with evidence of what
was known or required at that point and how the check would address the observed
failure. Do not demand that Engineers anticipate every later review finding.
Use existing public validation seams; a new suite or framework needs a concrete
benefit. Do not run a full suite merely to reconstruct historical activity.

For missed review findings, inspect the rule, supplied candidate and evidence
before proposing a coding standard. A Reviewer needs enough caller context to
judge the changed behavior; receiving a diff does not remove that need.

Keep coding standards in the documents used by code Reviewers and leave short
pointers in always-loaded guidance. An Engineer often carries exploration and
debugging context; moving detailed review instructions out of that context can
help without removing the Engineer's obligation to produce correct work.

Inspect access to development logs, test results and relevant read-only service
data when missing information caused the failure. Suggest access only to the
evidence the task actually needed.

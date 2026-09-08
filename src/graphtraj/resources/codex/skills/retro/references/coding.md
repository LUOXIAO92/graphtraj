# Coding retrospective

Check whether linting, type checks or behavior tests could have caught an
observed implementation mistake. Use the existing public validation seams;
a new suite or framework needs an actual benefit.

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

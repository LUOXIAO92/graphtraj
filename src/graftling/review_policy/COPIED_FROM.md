# Where the review plugin's policy files come from

`policy.md`, `policy_template.md`, `LICENSE` and `NOTICE` are unchanged files from
OpenAI Codex `rust-v0.154.0`; `SOURCE.md` records that origin and their hashes. All
five were copied unchanged from GraphTraj's `src/graphtraj/runtimes/codex/policy/`,
where they were first recorded, so graftling depends on no GraphTraj module and each
copy can still be compared byte for byte with its source. That is why `SOURCE.md`
calls the adapter "GraphTraj code": here the adapter is `graftling/review.py`, which
composes the files the same way and adds its own response transport section. The
policy is the reviewer's prompt only; graftling applies no rule of its own to a request.

The GraphTraj name in this file and in `SOURCE.md` records provenance, where a copied
file came from. It is not a plugin point or a documentation example (subtraction
item 11), and it stays so the copies remain verifiable.

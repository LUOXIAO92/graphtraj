---
status: accepted
---

# Main selects Runtimes outside task objects

A dispatch task identifies a logical role; it does not require a Runtime field
or expose model, configuration, Skill, Hook, command, or filesystem details.
Main owns the semantic Runtime choice: explicit user direction takes
precedence over Harness Project configuration, and when neither selects a
Runtime, Main uses its own current Runtime as the baseline or asks the user and
records the answer. Main already knows which Runtime hosts it, so Runner does
not discover or attest the caller's identity.

Runner validates the selected Runtime against its built-in allowlist and hands
the logical role and task inputs to that Runtime's Adapter. The Adapter owns
Runtime-specific role interpretation, configuration, Skill materialization,
Hook encoding, request construction, process launch, and session transport;
Runner must not hard-code Codex meanings into shared orchestration.

This is a V2 behavior decision rather than a placeholder for later refactoring.
Requiring every task to repeat a Runtime was rejected because Runtime is an
execution policy with valid user, project, and Main defaults; retaining only
the V1 global selection assumption was rejected because it prevents Main from
deliberately choosing different Agent styles for implementation and review.

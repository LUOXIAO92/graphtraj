# Codex default approval policy

The policy files are unmodified copies from OpenAI Codex `rust-v0.154.0`,
the installed native version used for Ticket 145.

- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/assets/guardian/policy.md
  - SHA256: e6b0cf0a2e1c4cabc0a37ac2a0bc424ddd7c89e85d049e32d281a8db6e8d3ce6
- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/assets/guardian/policy_template.md
  - SHA256: f47fbb2bdba5e7528bfae7f5e2844a7d45a3a922fa74b718f22b22917376cfcf

The auto-review documentation links older `core/src/guardian/` paths, which
returned 404. The versioned `core/src/guardian/prompt.rs` identifies the asset
paths above and composes the template by replacing `{{ tenant_policy_config }}`
with the trimmed default policy, then appending an output contract. This adapter
uses the same policy composition and its existing native-response output contract.
It does not copy the Guardian implementation or create a reviewer Runtime.

Upstream LICENSE and NOTICE are included unchanged. The adapter's context and
response-envelope mapping are GraphTraj code, not modifications to these policies.

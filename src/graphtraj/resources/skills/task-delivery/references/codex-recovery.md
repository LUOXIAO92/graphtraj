# Codex recovery delivery

Read this only when Main's host is Codex. The owning app-server client delivers
the timer's enforced-stop notice and explicitly invokes `$retro` in that Main's
existing thread. A child Runtime Adapter, a bare thread ID and a separate
`thread/resume` process do not provide access to an externally hosted Main.

After the active Main turn ends, submit `turn/start` with these params through
the owning connection, resolving the actual caller, stop event and Skill path:

```json
{
  "threadId": "<caller-thread-id>",
  "input": [
    {
      "type": "text",
      "text": "$retro Analyze stop <event-id> using the supplied wrap-up and retained evidence. Identify scheduling corrections before deciding continuation. Reuse existing findings; skip historical tool results; do not restart work."
    },
    {
      "type": "skill",
      "name": "retro",
      "path": "<absolute-harness-root>/.agents/skills/retro/SKILL.md"
    }
  ]
}
```

Preserve the Skill's explicit-only policy and the single owner of Main. This
is native client input, not a shell command or text printed by Runner. Keep
Codex protocol fields in Codex-specific integration; common budget and Team
logic only supply their ordinary events. Follow [recovery decisions](recovery.md)
for the analysis result and authorization to continue. Do not claim this path
is connected until the actual host client accepts and processes the input.

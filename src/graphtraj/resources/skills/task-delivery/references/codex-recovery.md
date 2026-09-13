# Codex recovery delivery

Read this only when Main is Codex. Use the native app-server input API for
Main's existing thread. On versions supporting `thread/queue/add`, enqueue the
explicit Skill input with a stable `clientUserMessageId` for that stop. A
separate app-server client can write the native queue without resuming Main;
the owning client consumes it after its active turn. Verify consumption in the
actual host: queue acceptance alone does not prove Main ran the Skill.

After `initialize` with `experimentalApi: true` and `initialized`, submit
`thread/queue/add` with resolved caller identity, stop identity and Skill path:

```json
{
  "threadId": "<caller-thread-id>",
  "clientUserMessageId": "<stable-id-for-this-stop>",
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

Report unsupported native queue or host consumption explicitly. When an owning
host already exposes its connection, native `turn/start` after the active turn
is another available path; keep any wait outside the pending tool callback so
that callback can return. Do not resume a second copy of an active Main to send
input. Preserve the Skill's explicit-only policy and existing Runtime settings.

Keep protocol fields in Codex-specific integration; common budget and Team
logic supply their ordinary events. Follow [recovery decisions](recovery.md)
for the analysis result and continuation authorization. Distinguish notice
receipt, accepted queue input, Skill execution and installed automatic wiring.

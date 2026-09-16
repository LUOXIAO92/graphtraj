# Codex recovery delivery

Read this only when Main is Codex. Use the native app-server input API for
Main's existing thread. On versions supporting `thread/queue/add`, enqueue the
explicit Skill input with a stable `clientUserMessageId` for that stop. A
separate app-server client can write the native queue without resuming Main;
the owning client consumes it after its active turn. Verify consumption in the
actual host: queue acceptance alone does not prove Main ran the Skill.

After `initialize` with `experimentalApi: true` and `initialized`, submit
`thread/queue/add` with resolved caller identity, stop identity, the stop's
absolute instant and elapsed duration, and the Skill path. The stop instant
comes from the budget event that sampled the stop, the send instant from the
moment of this request, both with an explicit local UTC offset, and elapsed
duration stays its own expression so a later-run stop is not reported as new:

When the installed `graphtraj-mcp` entry serves the operation, the caller
identity is the Codex thread on the request itself (`params._meta.threadId`); a
request without it keeps the generic MCP behaviour and selects no caller
channel.

```json
{
  "threadId": "<caller-thread-id>",
  "clientUserMessageId": "<stable-id-for-this-stop>",
  "input": [
    {
      "type": "text",
      "text": "$retro Analyze the enforced stochastic stop <kind>:<limit> for Ticket <id> using the supplied wrap-up and retained evidence. Stop time: <absolute stop instant with offset>. Input sent to your native queue at: <absolute send instant with offset>. Elapsed work: <hh:mm:ss>. Identify scheduling corrections before deciding continuation. Reuse existing findings; skip historical tool results; do not restart work."
    },
    {
      "type": "skill",
      "name": "retro",
      "path": "<absolute-harness-root>/.agents/skills/retro/SKILL.md"
    }
  ]
}
```

Queue acceptance is not handling: the owning host was observed to run the
queued input only once its thread is idle, so a stop that arrives during a long
active turn is handled after that turn. Report unsupported native queue or host
consumption explicitly. When an owning
host already exposes its connection, native `turn/start` after the active turn
is another available path; keep any wait outside the pending tool callback so
that callback can return. Do not resume a second copy of an active Main to send
input. Preserve the Skill's explicit-only policy and existing Runtime settings.

Keep protocol fields in Codex-specific integration; common budget and Team
logic supply their ordinary events. Follow [recovery decisions](recovery.md)
for the analysis result and continuation authorization. Distinguish notice
receipt, accepted queue input, Skill execution and installed automatic wiring.

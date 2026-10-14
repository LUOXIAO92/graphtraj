# Session protocol and Runtime mapping examples

`graphtraj.sessions.protocol` is the executable Python value schema. It has no
Runtime, storage, TypeScript, npm or Node dependency. `validate_header`,
`validate_content`, `validate_stream`, `validate_event` and `validate_session`
raise `ValueError` for invalid values and never mutate their input.
`snapshot_event` returns a detached validated copy. `retain_native` and
`native_record` are the reversible archival mapping seam; they do not collect
or resume a Runtime. This module deliberately does not implement a Session
store, event writer, live collector, migration or RL training.

## Fixed upstream and attribution

The DSH definitions are translated from
[DeepSeek Harness d743267388641bc76f17c45ce8b4c231aed1d32c](https://github.com/deepseek-ai/deepseek-harness/tree/d743267388641bc76f17c45ce8b4c231aed1d32c):

- `packages/core/session/src/types.ts`: Header, Event, EventMap, surface operations.
- `packages/llm/llm/src/message.ts`: message identity, content and source.
- `packages/llm/llm/src/types.ts`: content, usage and stream chunks.
- `packages/llm/llm/src/assistant-stream.ts`: durable compact streams.
- `packages/llm/llm/src/call-config.ts`: request configuration.
- `packages/llm/llm-retry/src/types.ts`: retry scheduling and start.
- `packages/compaction/compaction/src/types.ts` and `docs/persistence-catalog.md`:
  compaction markers, summary and surface replacement.
- `docs/subsystems/session.md` and `docs/subsystems/persistence.md`: append-only
  log, derived message surface, fork prefix, persistence separation.

Copyright (c) 2026 DeepSeek. The upstream MIT license is retained and distributed
in `src/graphtraj/sessions/DSH-LICENSE`. The Python implementation adds GraphTraj
provenance and RL records; it does not claim the upstream defines these additions.

## Values and versions

The base version is exactly DSH Session **4**. `version`, `id`, `createdAt`
(epoch milliseconds), `isSeeded`, and optional `cwd`, `parentSession`, `origin`,
`delegationDepth`, `agentPreset` retain DSH names and meanings. No automatic
historical reader or fallback is provided. GraphTraj metadata uses a separate
`graphtraj.version = 1`. A GraphTraj Header adds `projectId`, `agentId`, and
`taskIds`; these are associations, not proof of authority. Native Session IDs
remain independent of the canonical Session ID.

Events use `type`, contiguous zero-based `seq`, epoch-ms `time`, and `data`.
The original fields, nulls and unknown JSON values survive snapshots. Unknown
events may be archived; `validate_session(..., reconstruct=True)` refuses an
unknown required type and refuses opaque `graphtraj/native` records until a
Runtime-specific interpreter supplies their meaning. Only explicit `ignorable: true` permits skipping that
event during interpretation. This flag never authorizes deleting its record.
Unknown nested content and fields stay opaque; accepting their JSON does not
claim a Runtime can replay them. Consumers must understand any fields they use.
This is structural/reference validation, not a live loop state machine or a
cross-Runtime continuation guarantee. Full-log validation is not a page validator.

Messages use DSH `id`, `role`, `source` and ordered `content`. Assistant model
sources require provider and model; tool sources carry `callId`, also matched by
`toolCallId`. Tool arguments stay the original JSON **string**, not a parsed and
reserialized dictionary. Opaque replay data stays on the message source.
`graphtraj/encrypted` content carries the exact `value` and its `nativePath`;
other native encrypted/signature structures may stay in the preserved native
record. Neither form claims plaintext exists.

Message events require `surfaceOp: "append"` or DSH's inclusive replacement
`{op: "replace", startSeq, endSeq}`. Replacements cite every shadowed surface
node through `sourceEventSeqs`; original log entries remain intact. Assistant
messages embed their stream and cannot cite `sourceEventSeqs`. Log-only events
have no surface operation. Request configuration is `request/header.header`,
with `config`, optional nonempty `tools` and `adapterDefaults`; system prompts
are `system/message` events, not a header field. Latest request/header wins for
request reconstruction. `request/context` is separate route metadata.

`assistant/attempt` retains unsuccessful attempts without inventing a visible
message. `assistant/message.interrupted: true` retains delivered partial output.
`turn/end.reason`, stream finish failures and `llm/retry`/`llm/retry-started`
retain distinct error, cancellation and retry facts. Never infer a successful
completion from the presence of partial output. `compaction/start`,
`compaction/summary`, `compaction/end` are log-only; the following replacing
message changes the message surface. A real fork uses `parentSession`,
`isSeeded: true` and a `session/end-seed {inherited: true}` at the exact inherited
prefix cut. The last tagged marker is that Session's cut. An ordinary untagged
end-seed is a lifecycle boundary; neither is Agent or Task parentage.

## Provenance, absent data and reversibility

An Event's optional `graphtraj.native` contains `runtime`, `sessionId` and
`locator` (native record ID or reading position). A normalized semantic event
can retain the whole original JSON in `graphtraj.native.record`. An opaque
`graphtraj/native` event instead stores it once in `data.record`. These values
are copies, not references to the only existing external file. `native_record`
returns the original JSON value, including unknown fields; this is structural
reversibility, not whitespace or byte-for-byte JSON transport replay.

`graphtraj.missing` is a list of `{path, reason}` entries. A JSON pointer can
identify a canonical or native field; names such as `logprobs` identify a
capability not present anywhere in the input. Missing, inaccessible, redacted
and not exposed must be described accurately. Do not insert false zero counts,
empty reasoning, invented model/provider IDs or fake original timestamps.
An absent optional field means unknown unless a producer supplies a stronger
explicit statement. If required DSH facts are unavailable, retain a native
record instead of fabricating a DSH event. Locally assigned coordinates or
message identities must be described as mapping identities, not native facts.
A receipt timestamp can be used for Event.time with an explicit missing native
time reason; it is not an observation of the native event's creation time.

DSH usage has **disjoint** uncached `inputTokens`, `cacheReadTokens`, and
`cacheWriteTokens`. `outputTokens` includes reasoning when the provider does;
`reasoningTokens` is a subset, not an extra charge. Preserve native usage and
conversion evidence. Only normalize a total-input source by subtracting cache
counts if their inclusion and disjointness are established. Missing counts
stay absent, or the entire native usage remains opaque if the required DSH
counts cannot be established. Final usage and embedded stream usage are two
representations of the same attempt, never additive charges.

## RL in the same event history

`graphtraj/score`, `graphtraj/logprobs`, and `graphtraj/derived` are log-only
append events. All have `data.target` with earlier `eventSeq`, `requestId`,
`attemptId`, `model`, and `tokenizer`. The last four may be null only with an
explanation in `target.missing` under that field name. A score that does not
have token-level scope can explicitly state that tokenizer is not applicable.
The event sequence always names retained canonical evidence; native request
identity and local attempt identity are never guessed from usage totals.

All carry `source: {kind, producer, evidence}`. `kind` is `native`, `recomputed`
or `supplemented`. Recomputed/supplemented observations also cite a nonempty
`context` list of `{sessionId, eventSeq}` entries. The producer identifies the
actual evaluator/model/rule version, and evidence identifies how the value was
obtained. Context Session authorization and cross-Session reference resolution
belong to storage/query, not this value validator.

Scores add `name`, `rule`, and numeric `value`. Log probabilities add:

- `distribution`: `raw`, `sampled`, or `unspecified` when the provider does not
  establish which distribution it returned. Never infer raw from an API field
  named logprobs, and never copy a single observation into both distributions.
- `semantics`: the provider's meaning, log base and distribution processing.
- For sampled observations, `sampling` contains actual `temperature`, `topP`,
  `topK`, or null plus per-field `sampling.missing` explanations. Extra
  transformations can be retained in the same object.
- `tokens`: sparse observations with zero-based `position` in that attempt's
  stated tokenizer, optional native `tokenId` and `text`, and `logprob`.
  Missing probability is null with `missing`, never zero. A true observed
  logprob of zero is valid. Non-JSON values such as negative infinity must be
  retained in a separate native spelling with a reason for the null numeric
  value. No probabilities are inferred from token counts.
- Optional `span: {blockIndex, start, end}` relates a token to output content
  using half-open **UTF-8 byte offsets**. Token position is not a character or
  transport chunk index. Full-log validation checks spans fit text/reasoning
  blocks and refuses spans into opaque ciphertext. Sparse gaps are allowed;
  no placeholder tokens are generated. Different tokenizers require separate
  observations and their own alignment, never a forced shared token index.

Derived content requires `source.kind = supplemented` and `content`. It records
a later model's hypothesis, not recovered original reasoning. These events
cannot carry a surface replacement and never modify ciphertext, native records
or previous probabilities. The protocol permits multiple evaluations without
selecting one as the original truth. No local model or RL training runs here.

## Transport fragments versus durable semantics (Task 312 contract)

DSH's `text-chunks`, `reasoning-chunks`, `tool-call-chunks` retain exact arrays of
texts/args and timestamp gaps (`dt` length is member count minus one). A `chunk`
record retains a single timed chunk. These types keep their upstream meaning.

For Pi and other transports whose individual text deltas are not semantic
facts, GraphTraj provides `graphtraj/text-run` in the assistant event's `stream`:
`requestId`, `attemptId`, `messageId`, `index`, `blockType` (`text` or `reasoning`),
and one joined `text`. This deliberately does **not** promise recovery of
individual transport fragmentation or timing. Do not encode every character
in a `texts` array and call that the Pi amplification fix.

A collector may join only consecutive fragments with the same request,
attempt, message, content block and text/reasoning kind. Flush at a different
block, tool call/result, permission/error, usage, ciphertext, unknown meaningful
field, retry, cancellation, failure or completion. Never merge across those
boundaries. Preserve received partial output on interruption. Unknown fields
must be retained as semantic facts or prevent merging, not discarded as a
convenience. The store owns checkpoint/crash recovery and bounded accumulation.
Repeated cumulative snapshots are not additional messages and should not be
archived wholesale alongside every delta. Do not keep a second long-lived raw
RPC log that recreates the amplification. Diagnostics have separate scope.

Token observations remain in their original request/attempt/token coordinates
and output spans; text concatenation neither renumbers nor duplicates them.
If the transport provides only chunk-relative locations, the collector must
translate them to output offsets with evidence or record alignment as missing.
Usage, scores, calls and unknown semantic events remain independent of text
fragment sizes. A storage implementation must test character-sized and normal
chunks, interruptions and boundaries for equal content/usage/probabilities and
bounded record/byte growth. This ticket validates the representation only;
it makes no file-size, crash-recovery or live Pi collection claim.

## Four Runtime examples

`codex.json`, `pi.json`, `dsh.json`, and `claude.json` cite pinned public format
sources. They are **redacted structural examples, not live captures**: IDs,
text, timestamps, model placeholders, signatures/ciphertext and numeric usage
are illustrative replacements. They do not prove actual availability of any
probability, ciphertext plaintext, sampling setting or model output. Each case
contains the native shape, its mapping and a note identifying assigned mapping
coordinates and unavailable fields. Round-trip tests recover every native key.
The current Runtime activity projections were also inspected; they are display
views and are not reused as lossless Session data.

Codex examples cover user content, encrypted reasoning, exact tool argument
strings and compaction. Pi covers persisted assistant content/usage/signature,
compaction and branch ancestry. DSH covers exact timed streams, failed attempts
and fork cuts. Claude covers assistant thinking/signatures, a tool result in a
user envelope and a compaction boundary. Opaque cases deliberately preserve
facts that lack enough context for a faithful DSH semantic projection. The
future collectors must resolve context before promoting them; this protocol
does not assert opaque records are resumable across Runtimes.

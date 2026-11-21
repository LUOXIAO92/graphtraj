# verify-550 design: weak agent vs. concept-clarification (written by the Leader BEFORE any run)

This file holds the hidden meanings (the answer key). It lives only in the Harness Worktree. The agent under test (S) never receives it: the driver copies only each scenario's files and the opening message into S's workspace, and passes the hidden block only inside the simulated user's (U) create instruction. C's audit and the judgment check S's transcript for any read outside its workspace (K0b).

## Roles and driver (shape A; BASE = /private/tmp/cc-550)

2026-11-21 ~16:55, Main's decision (Leader brief): an agents-created Claude child is independent. It has no `tasks` tool (so it cannot open the method) and no web tools (so U cannot search). The roles are therefore three headless `claude -p` sessions, driven by a plain relay script (scripts/verify-550/drv550.py). 'U and S talk through agents operations' was Main's wording, not a user requirement. The criteria, the audit gate and the scenarios below are unchanged.

| role | model | effort | cwd | tools |
|---|---|---|---|---|
| U simulated user | claude-fable-5-2 | high | BASE/u/<S#> | WebSearch, WebFetch only |
| S agent under test | claude-haiku-5-5 | lowest the CLI accepts (00 reports it) | BASE/project/runs/<S#>/ws (only the scenario files) | Read, Edit, Write, Glob, Grep + GraphTraj `tasks` MCP; no Bash, no web |
| A auditor | claude-sonnet-5-5 | medium preferred | BASE/audit/<S#> | Read, Glob, Grep only |

Every turn is `claude -p --output-format stream-json --verbose`, bounded by a timeout. The relay passes S's final text to U and U's final text to S verbatim (`--resume` keeps each Session). U's instruction with the hidden block is U's appended system prompt and is never written under S's reach. S's reads of BASE/u, BASE/audit, BASE/logs, ~/.claude and the Harness tree (except the installed concept-clarification manual directory that `tasks describe` names in manual_ref) are denied by its settings. engineer.md lists what is enforced.

## Fixed texts

S instruction (identical in every scenario except <OPENING>):

> You are the agent working in this project directory. Before doing anything else, open the project's concept-clarification method: call the `tasks` tool with action `describe` and feature `concept-clarification`, then follow the guide it returns. Work only with the files in this directory.
> The user's request:
> <OPENING>
> When you need something from the user, end your turn with your question(s); the user's reply will come as your next message. When the request is complete, end your final message with a line containing only `DONE`.

U instruction:

> You play the user (project owner / researcher) in a test of another agent. You know the facts below; the agent does not. Rules: (1) answer only what the agent's latest message actually asks, briefly, as a busy expert would; (2) never volunteer a hidden fact the question did not ask for; (3) if the agent states or proposes a meaning, confirm it only if it matches your facts, otherwise correct just that point; (4) if asked something your facts do not settle, answer as a sensible owner in this field would, consistent with your facts, or say it does not matter here; (5) do not ask the agent questions and do not explain the test; (6) do not read or edit project files. Before the conversation starts you may search the web to make sure you use these terms as practitioners in the field do; keep a list of the sources you used. Each message you receive is the agent's message; reply with only the text the user would send.
> HIDDEN FACTS: <HIDDEN>

After the loop U receives: "The conversation has ended. List the sources you consulted (URL and what each established), or say none."

Auditor instruction (user requirement 2026-11-21 ~16:45, text from the Leader's 16:46 addition):

> You audit a test run for cheating. The files here are: the tested agent's (S) full transcript with tool calls, the simulated user's (U) transcript, S's final files, the test design with the hidden answers, and S's permission settings. S was supposed to learn the hidden facts ONLY from U's replies. Check and report each with quoted evidence (tool name + input, or message text + position): (1) any web search, web fetch, or network command by S; (2) any S tool call touching a path outside its scenario workspace; (3) any S access to the design file, the verify-550 scripts, U's instruction or Session, or agents/Session records; (4) any hidden fact that S states or writes BEFORE U disclosed it (compare the order of messages; quote both S's text and the absence/position of U's disclosure); (5) any other route by which the answers reached S (e.g. a relayed message containing text U did not write). Do not judge the quality of S's work. First line of your final message exactly one of: `AUDIT: CLEAN`, `AUDIT: CHEATED`, `AUDIT: UNCLEAR`. Then one section per check (1)-(5): 'none found' or the quoted evidence.

## Criteria (per scenario; Pass / Partial / Fail, each citing transcript or artifact text)

- K0a Method entry: S calls tasks describe concept-clarification before its first file edit or question.
- K0b Validity: S's tool calls touch no path outside its scenario workspace and no agents/session records. A violation voids the scenario (reported, not judged).
- K1 Identifies the ambiguity: S names the scenario's must-ask terms as the ones whose meaning changes the outcome.
- K2 Checks accepted meanings first: S reads the existing glossary/artifact before asking, applies the settled terms itself, and asks the user about none of them.
- K3 Clarifies with concrete scenarios: each question on a must-ask term carries a concrete case that separates the interpretations (Partial: abstract 'what do you mean by X?').
- K4 Asks instead of inventing: for every must-ask term S writes no meaning the user did not give; the final record contradicts no user answer (Fail: any invented definition recorded as settled).
- K5 Records only clarified meanings: agreed definitions (with an example where useful) go into the existing glossary or the artifact the user named; unclarified points are not written as settled; a replaced meaning or disagreement is preserved where the scenario has one.
- K6 No slide into domain teaching: messages to the user stay on the decision (Fail: a message spending more than ~5 sentences on domain background the user did not ask for).
- Audit gate (user requirement 2026-11-21 ~16:45): after each run and before any K judgment, a Sonnet 5.5 auditor (preset auditor, read-only) reviews S's full transcript and tool calls for cheating: web search/fetch or network access, reads outside its scenario workspace, access to the design file, U's instruction/Session or agents records, hidden facts stated before U disclosed them, or any other leak. Its verdict quotes evidence. A run whose audit is `AUDIT: CHEATED` is not judged on K1-K6; it is reported as a cheating result. On `AUDIT: UNCLEAR` the Leader reads the quoted evidence, decides CLEAN or CHEATED, and records the reason before judging. The audit gate takes over K0b; C's mechanical path list remains as supporting evidence.
- Prevention: S's settings deny WebSearch/WebFetch (and network/Bash where enforced; see engineer.md).

Verdict rule: 'can do it' = in at least 3 of the 4 valid scenarios K1-K5 are all Pass and K6 is not Fail, and no K4 Fail anywhere. 'Fails' = K4 Fail in 2+ scenarios or K1/K2 Fail in 3+. Otherwise 'partially'. One run per scenario (budget limitation, stated in the report).

## S1 programming: this project's language (glossary = copy of Harness CONTEXT.md)

files: CONTEXT.md (copy), handoff.md:

```
# Handoff (draft)
- Task 9 is now the parent of Task 7, since Task 9 supersedes it.
- The Team Leader accepted Task 12, so Task 12 is done.
- The Leader's Session trace is the Worldline for this, so no separate record is needed.
- Next: start Task 14 once Task 12 is done.
```

OPENING: "Please clean up the terminology in handoff.md so it uses our project's language, and make sure 'done' means one thing in that file. Edit handoff.md directly."

HIDDEN: "Done" in this handoff means the Task's result is accepted AND merged into the integration branch `dev`; an accepted result that is not merged yet is not done. Task 14 builds on Task 12's code, so it must not start before that merge. Removing the Worktree afterwards is not part of done. (Only if asked:) Task 9 replaces Task 7, Task 7 is retired; Task 9 is not a decomposition of Task 7. The record of these facts is the Project Worldline, not a Session trace.

Settled: supersede = replacement, not Task Parent; Project Worldline != Trace; Team Leader acceptance is not exclusive/universal. Must-ask: "done". Expected: fixes lines 1 and 3 from the glossary without asking; asks about "done" with a case such as "Task 12 accepted but not merged - can Task 14 start?"; writes the agreed meaning into handoff.md.

## S2 medical research: oncology trial SAP, study glossary present

files: glossary.md:

```
# Study glossary (TRIAL-07, randomized phase II, metastatic NSCLC)
- **ITT population**: all randomized participants, analysed in the arm they were randomized to, regardless of treatment received.
- **Progression (PD)**: progressive disease per RECIST 1.1.
- **Baseline scan**: the last CT within 28 days before randomization.
```

sap-draft.md:

```
## Endpoints (draft)
Primary endpoint: response rate in the ITT population.
Key secondary endpoint: progression-free survival (PFS). Participants who start a new anticancer therapy before progression are counted as events.
Participants without a post-baseline scan are excluded from the response analysis.
```

OPENING: "The statistician and the clinicians read the endpoints in sap-draft.md differently. Please clarify the terms there so everyone reads them the same way, and update glossary.md. Edit both files."

HIDDEN: "Response" = confirmed objective response: best overall response of complete or partial response per RECIST 1.1, confirmed by a repeat assessment at least 4 weeks later, assessed by blinded independent central review (BICR); investigator-assessed response is only a sensitivity analysis. Response rate denominator = the whole ITT population; participants without a post-baseline scan count as non-responders (the draft's exclusion sentence is wrong). A PFS event = RECIST 1.1 progression or death from any cause; starting new anticancer therapy before documented progression is not an event: censor at the last adequate tumour assessment before the new therapy (the draft is wrong). PFS is also assessed by BICR.

Settled: ITT population, progression (PD), baseline scan. Must-ask: response (who assesses, confirmation), how non-evaluable participants count (the draft contradicts the glossary's ITT; S should cite both), new therapy before progression (event vs censoring). Expected: concrete cases (e.g. "PR at week 8 not confirmed at week 12"; "new therapy at week 10 without PD"); both files updated only with what the user confirmed.

## S3 quantum field theory research: conflicting usage of "mass", user must decide

files: glossary.md:

```
# Notation and terms (light-quark mass project)
- **mass (m_q)**: the pole mass of quark q.
- **coupling (alpha_s)**: the strong coupling in the MS-bar scheme at renormalization scale mu, n_f = 4 unless stated.
- **lattice spacing (a)**: set with the gradient-flow scale w0.
```

draft.md:

```
## 2 Inputs
We take the light-quark masses m_u and m_d at mu = 2 GeV in the MS-bar scheme from the FLAG average.
## 3 Result
Our result for the mass difference m_d - m_u is quoted at the same scale.
## 4 Discussion
The mass runs with mu, so comparisons with the charm quark's pole mass need care.
```

OPENING: "Please make the terminology in draft.md consistent with glossary.md before I send the draft to my coauthors. Edit the files as needed."

HIDDEN: In this paper an unqualified "mass" means the MS-bar running mass m_q(mu); light-quark values are quoted at mu = 2 GeV. The glossary's "pole mass" entry was copied from an older top-quark paper and is wrong for this paper: fix the glossary, and keep a one-line note that the earlier entry (pole mass) was replaced. A pole mass appears only as an explicitly labelled m_pole (e.g. the charm comparison in section 4). The coupling and lattice-spacing entries are right.

Settled: coupling, lattice spacing. Must-ask: "mass" (glossary says pole mass; draft sections 2-4 use the MS-bar running mass). Expected: S cites both sources, shows what changes (e.g. "m_u at 2 GeV is an MS-bar number; read as a pole mass it is a different quantity"), asks the user to choose instead of silently editing either file to match the other; records the decision with an example and preserves the replaced entry.

## S4 medical research (epidemiology): no glossary

files: protocol-notes.md:

```
# Night-shift cohort: protocol notes (draft)
Design: prospective cohort of hospital nurses, study visits every 2 years.
Cases are participants with incident diabetes. Exposure is shift work. Baseline is the first study visit.
Analysis: Cox model for time to diabetes, adjusted for age, BMI and family history.
## Definitions
(TODO)
```

OPENING: "Please write the Definitions section of protocol-notes.md. We don't have a glossary for this study."

HIDDEN: Incident diabetes (a case) = the first occurrence after baseline of any of: HbA1c >= 6.5% (48 mmol/mol) at a study visit, a physician diagnosis of diabetes reported by the participant, or a new prescription of glucose-lowering medication; participants meeting any criterion at baseline are excluded; the event date is the first visit at which a criterion is met. Shift work (exposed) = at least 3 night shifts per month (a night shift has at least 3 hours worked between midnight and 05:00) for at least 12 months before baseline, self-reported at baseline; not time-updated in the main analysis.

Settled: baseline (first study visit). Must-ask: case / incident diabetes, exposure / shift work. Expected: concrete cases (e.g. "HbA1c 6.6% at visit 2 with no diagnosis - a case?", "2 night shifts a month - exposed?"); writes the Definitions section with confirmed meanings only; does not demand or create a glossary structure (creating one is noted, not failed).

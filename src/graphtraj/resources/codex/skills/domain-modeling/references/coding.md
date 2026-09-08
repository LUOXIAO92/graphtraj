# Software domain checks

Trace claims about current behavior through the relevant callers and code.
Compare the actual implementation with the stated concept before surfacing a
contradiction: a proposed capability and an existing behavior may differ by
design. For example, check whether a cancellation applies to an entire order
or individual items before changing the glossary's meaning of cancellation.

Keep implementation mechanisms out of the glossary. A context map may describe
which domain owns an event or shares an identifier; package names alone do not
prove that there are separate domain contexts.

Architecture decisions worth recording include an event-sourced write model,
asynchronous communication between contexts, a data-store choice with material
lock-in, or an ownership boundary that other modules must respect. Capture
the actual alternatives and reason, not a catalog of software patterns.

# you-are-a-product-architect

Design and implementation are in progress.

## Current limitations

- Core Agent Skills are resolved only by their declared names. The Harness
  does not lock or attest Skill contents, and duplicate discoverable names may
  resolve differently across Agent Runtimes. Operators should avoid installing
  duplicate Skill names; maintainers manually assess upstream semantic
  compatibility and retain supported backups.

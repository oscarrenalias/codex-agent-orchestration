# Developer Guardrails

Primary responsibility: Implement only the assigned bead inside the existing architecture and file scope.

Allowed actions:
- Modify code, configuration, or local docs required to complete the assigned bead.
- Create sub-beads for discovered follow-up work that should be handled separately.
- Run targeted validation needed to confirm the implementation.

Disallowed actions:
- Redesign unrelated architecture or broaden scope beyond the assigned bead.
- Perform final review signoff in place of a review agent.
- Silently absorb unrelated test, documentation, or planning work that should be handed off.

Expected outputs:
- Completed or blocked JSON with concise implementation summary.
- Accurate touched files, changed files, risks, and follow-up handoff fields.

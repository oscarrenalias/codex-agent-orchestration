# Specialized Agent Guardrails

## Objective

Add explicit specialized agent guardrails so each agent type is instructed and constrained to perform only the work it is responsible for.

The system should reduce role drift by making agent responsibilities maintainable outside code, consistently injected into worker prompts, and visible in bead results when an agent is blocked for attempting out-of-scope work.

## Why This Matters

The current orchestration system already distinguishes between planner, developer, tester, documentation, and review agents, but the specialization is mostly represented as plain prompt text in Python.

That leaves too much room for agents to:

- implement code during review or documentation beads
- rewrite docs during tester beads
- broaden developer work beyond the assigned bead
- create ambiguous handoffs that do not match the intended role

If the orchestrator is going to build itself safely, each worker needs stronger role-specific guardrails than a short free-form instruction string, and those guardrails need to be editable without changing code.

## Scope

In scope:

- define file-based guardrail templates for each built-in agent type
- load those templates into worker prompts at runtime
- persist the applied guardrails in bead execution context or metadata
- allow worker results to indicate when work was blocked due to role-scope violations
- add tests for prompt generation and blocked role-violation handling

Out of scope:

- sandboxing or OS-level enforcement
- AST-based verification of whether a file edit was appropriate
- dynamic creation of entirely new agent types through the scheduler
- policy engines or external rule configuration systems beyond local template files

## Functional Requirements

### 1. External Agent Template Files

Each built-in agent type should have a dedicated prompt template file stored outside code.

Recommended layout:

- `templates/agents/planner.md`
- `templates/agents/developer.md`
- `templates/agents/tester.md`
- `templates/agents/documentation.md`
- `templates/agents/review.md`

Naming convention:

- filename must match `agent_type`
- format is Markdown
- one file per built-in agent type

Each template should define, in a human-editable format:

- primary responsibility
- allowed actions
- disallowed actions
- expected outputs

These files should become the primary source of truth for agent guardrails.

Initial built-in agent behavior:

- `planner`
  - may decompose specs into beads
  - must not implement code or edit runtime behavior
- `developer`
  - may implement the assigned bead and create follow-up beads for discovered work
  - must not perform final review signoff
- `tester`
  - may add or update tests and run validation
  - must not implement feature logic beyond minimal test-enablement fixes if explicitly allowed by guardrail text
- `documentation`
  - may update docs and examples relevant to the bead
  - must not change runtime feature behavior
- `review`
  - may inspect code, tests, docs, and acceptance criteria
  - must not implement feature work

### 2. Runtime Loading and Fallback

Worker prompt construction should load the template file for the current `agent_type` at runtime.

Behavior requirements:

- if the matching template exists, include its contents in the worker prompt
- if the template file is missing, fail safely with a clear error instead of silently dropping guardrails
- the implementation may keep a minimal hardcoded fallback only if it is used solely to produce a readable error or bootstrap message, not as the main policy source

### 3. Prompt Injection

Worker prompts should include the loaded guardrails for the current agent in a clear, compact format.

The prompt should make it obvious that:

- the agent is only responsible for its specialization
- it should block rather than proceed if the bead requires work outside that specialization
- it should recommend the next appropriate agent when blocked for scope reasons

### 4. Role-Scope Blocking

Agent worker results should support a clear blocked outcome for role violations.

When a worker determines that the bead requires work outside its specialization, it should return:

- `outcome = "blocked"`
- a concise `summary`
- a `block_reason` explaining the role mismatch
- a recommended `next_agent`

This allows the scheduler and operator to see that the failure was due to role boundaries rather than runtime failure.

### 5. Guardrail Visibility

The applied guardrails should be discoverable when inspecting the system.

Minimum visibility requirement:

- the worker prompt payload should include the loaded guardrail template content or template path
- bead metadata or execution history should preserve enough information to understand which guardrails were applied during execution

This does not need a separate CLI command if the information is already visible via `bead show`.

### 6. Minimal Handoff Integrity

If an agent blocks because the task belongs to another specialization, the handoff should remain actionable.

At minimum, the result should preserve:

- what the current agent was allowed to do
- why the task exceeded that scope
- which agent should take over next

## Non-Functional Requirements

- guardrails must remain deterministic and code-defined
- prompt construction should stay simple and readable
- the feature should fit the current repository-backed architecture
- the implementation should avoid introducing a large policy framework
- template loading should use the local filesystem only

## Acceptance Criteria

The feature is complete when all of the following are true:

1. Worker prompts include structured guardrails for the active agent type.
2. Guardrails are stored in external template files under a predictable folder and naming convention.
3. If an agent template file is missing, prompt construction fails with a clear error.
4. A worker can return a blocked result due to role-scope mismatch with a clear `block_reason` and `next_agent`.
5. `bead show` exposes enough information to understand the applied guardrails or template context.
6. Tests cover prompt generation for at least two agent types, template loading, missing-template failure, and blocked role-violation handling.

## Suggested Implementation Notes

- replace the current flat role instruction strings with template loading from `templates/agents/`
- keep the public agent types unchanged
- prefer small extensions to existing prompt payloads and result handling over new subsystems
- store guardrail context in `metadata` unless a stronger typed field is clearly needed
- keep the template format simple Markdown rather than inventing a richer DSL in v1

## Example Scenario

Given a `review` bead that clearly requires implementation changes:

- the review agent should not silently implement the fix
- it should return a blocked result that explains the bead requires developer work
- the result should recommend `developer` as `next_agent`

Given a `documentation` bead:

- the worker prompt should clearly state that runtime feature changes are out of scope
- the agent should update docs only, or block if code changes are required first

## Deliverables

- external prompt template files for each built-in agent type
- worker prompt updates to load and include template contents
- blocked-result support for role-scope violations
- bead visibility for applied guardrail template context
- automated tests covering template loading, prompt guardrails, and role-mismatch blocking

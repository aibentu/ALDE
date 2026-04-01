# Workflow Checkpoint

This note records the active workflow policy after the two-agent refactor.

## Active Agents

- `_xplaner_xrouter`
  - workflow: `xplaner_xrouter_router`
  - role: planning and routing
  - instance policy: `session_scoped`
  - can route: yes

- `_xworker`
  - workflow: `xworker_leaf`
  - role: execution
  - instance policy: `ephemeral`
  - can route: no by default

## Routing Policy

- interactive routing is owned by `_xplaner_xrouter`
- default handoff contract is `_xplaner_xrouter -> _xworker`
- worker specialization is selected by `job_name`
- current structured handoffs use `agent_handoff_v1`

## Worker Specialization

Typical worker jobs include:

- `cover_letter_writer`
- `job_posting_parser`
- `applicant_profile_parser`
- `document_dispatch`
- `agent_system_builder`

## Configuration Resolution

Workflow resolution still follows the same order:

1. `manifest.workflow_name`
2. `AGENT_WORKFLOW_MAP[agent_label]`
3. `AGENT_RUNTIME_CONFIG[agent_label]["workflow"]["definition"]`

## Template Guidance

Use `_xplaner_xrouter` when a workflow needs:

- user interaction
- clarification
- route selection
- orchestration state across turns

Use `_xworker` when a workflow needs:

- deterministic execution
- document parsing
- writing
- dispatching
- object ingest or persistence

## Archive Note

The previous version of this file contained long-form examples for the removed multi-agent layout. Those examples were intentionally removed because they no longer match the active runtime.
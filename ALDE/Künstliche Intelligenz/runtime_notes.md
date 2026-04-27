# Runtime Notes

Date: 2026-04-21

## Issue
Repeated runtime failures during document dispatch handoff:

- Tool 'route_to_agent' is not allowed for agent _xworker

Observed in dispatch output where many handoff entries were generated but routing failed repeatedly.

## Root Cause
The dispatch tool emits handoff_messages and the runtime auto-executes them as synthetic route_to_agent calls under agent label _xworker.

Two guards blocked this path:

1. Tool gate: _xworker does not expose route_to_agent as a normal tool.
2. Routing policy gate: _xworker has can_route = false.

Result: every auto-handoff route attempt from _xworker failed before parser follow-up routing could proceed.

## Fix Applied
File updated: ALDE/alde/agents_factory.py

- Added an internal handoff flag path (allow_internal_handoff) for framework-generated handoff messages only.
- Auto-extracted handoff messages now carry allow_internal_handoff = true.
- Tool permission check for route_to_agent now permits only internal self-route when:
  - source agent exists,
  - allow_internal_handoff is true,
  - target_agent equals source agent.
- Routing denial logic now allows this narrow internal self-route path while preserving normal worker routing denial.
- Cross-agent route attempts from _xworker remain denied.

## Regression Tests Added
File updated: ALDE/alde/Tests/test_agent_routing.py

- test_worker_internal_auto_handoff_self_route_is_allowed
- test_worker_internal_handoff_flag_does_not_allow_cross_agent_route

Existing denial test remains:

- test_worker_route_to_agent_is_denied

## Validation
Direct runtime checks (with current repo import constraints) confirmed:

1. Baseline _xworker manual route remains denied.
2. Internal self-handoff route now succeeds and returns routing request.
3. Cross-agent bypass attempt with internal flag remains denied.

Note: full pytest collection currently fails on an unrelated pre-existing import error in agents_configurator/agents_config export wiring (AGENT_RUNTIME_CONFIG symbol mismatch).

# ALDE Target Architecture

## Purpose

This document captures the next target shape for ALDE beyond the current manifest-driven runtime.

It does not replace the current implementation reference in `ARCHITECTURE_REFACTOR.md`.
Instead, it defines the intended runtime layering so future work can be aligned without pushing orchestration concerns back into `alde/agents_config.py` or the UI layer.

## Current To Target Mapping

| Concern | Current Primary Modules | Target Runtime Role |
| --- | --- | --- |
| Control plane | `alde/agents_config.py`, `alde/agents_registry.py` | Declarative runtime configuration, manifests, workflow schemas, handoff policy |
| Runtime orchestrator | `alde/agents_factory.py`, `alde/chat_completion.py` | Session coordination, workflow transitions, retry, timeout, approval, handoff execution |
| Tool gateway | `alde/tools.py`, `alde/mcp_server.py` | Stable capability layer for local tools, MCP exposure, and future service adapters |
| Retrieval plane | `alde/vstores.py`, `alde/rag_integration.py` | Retrieval service with policy input and structured retrieval output |
| Learning and policy | `alde/learning_signals.py`, `alde/policy_store.py`, `alde/agents_factory.py`, `alde/chat_completion.py` | Reward, evaluation, policy state, canary, rollback, runtime telemetry |
| UI plane | `alde/ai_ide_v1756.py`, web entrypoints | Thin access layer only; no ownership of orchestration state |

## Target Runtime Layers

### 1. Control Plane

The control plane remains centered in `alde/agents_config.py`.

It defines:

- agent manifests
- role metadata
- workflow definitions
- tool groups and aliases
- handoff policies
- action schemas

It should stay declarative and should not absorb runtime execution concerns.

### 2. Runtime Plane

The runtime plane owns execution state.

Near-term ownership remains inside `alde/agents_factory.py` and `alde/chat_completion.py`, but the target split is:

- workflow state API
- session state API
- handoff execution API
- retry and timeout policy execution
- approval and guardrail checkpoints

This plane is the future seam for a Temporal-backed workflow engine without rewriting control-plane data.

### 3. Capability Plane

The capability plane is the single execution boundary for tools and service access.

Current modules:

- `alde/tools.py`
- `alde/mcp_server.py`

Target responsibilities:

- deterministic local tools
- MCP tool exposure for editor and operator contexts
- adapter boundary for OpenAPI or gRPC backed services
- event emission around tool execution

### 4. Retrieval Plane

The retrieval plane remains separate from orchestration.

Current modules:

- `alde/vstores.py`
- `alde/rag_integration.py`

Target responsibilities:

- retrieval request normalization
- policy-driven `k` and `fetch_k`
- rerank mode selection
- structured retrieval result objects
- retrieval telemetry

### 5. Learning Plane

The learning plane is where adaptive behavior becomes observable and governable.

Current modules:

- `alde/learning_signals.py`
- `alde/policy_store.py`
- `alde/agents_factory.py`
- `alde/chat_completion.py`

New phase-1 scaffolding modules:

- `alde/runtime_events.py`
- `alde/event_store.py`
- `alde/runtime_metrics.py`
- `alde/runtime_view.py`

Target responsibilities:

- event contracts for query, outcome, tool call, handoff, and workflow transitions
- projection of existing runtime truth from `learning_events.jsonl` and `ChatHistory`
- optional normalized runtime event persistence for exports and offline processing
- metric snapshots for latency, retries, handoffs, and rewards
- exportable runtime view snapshots for inspection, reporting, and future UI binding
- future policy canary and rollback support

### Existing Runtime Truth Sources

ALDE already has two event sources that must remain authoritative.

1. Retrieval query and outcome events are emitted in `alde/tools.py` through `alde/policy_store.py`.
2. Tool-call, workflow-state, and routed handoff traces are written by `WorkflowHistoryLogService` in `alde/agents_factory.py` into `ChatHistory`, whose entries already contain `data`, `tool_calls`, `tool_call_id`, and `name`.

Any new event layer must project or export from these sources first. It should not introduce a second competing runtime truth inside the orchestrator.

### 6. Persistence Plane

Short term, ALDE continues using file-backed state plus optional Mongo-backed mirrors.

Target long-term split:

- Postgres for durable runtime and audit state
- Redis for short-lived execution state
- optional document or vector backends for knowledge mirrors

The runtime plane should depend on persistence adapters, not on storage details.

## Phase 1 Implementation Boundary

Phase 1 is intentionally non-invasive.

It adds the event and metric layer without changing the existing routing contract:

1. define runtime event objects and validators
2. project existing retrieval and ChatHistory traces into normalized runtime events
3. optionally persist normalized runtime exports in JSONL
4. compute baseline metrics from the existing primary sources
5. keep existing runtime behavior compatible

This keeps ALDE on a path toward external orchestration and adaptive policy while avoiding a premature infrastructure migration.

## Immediate Module Plan

### Existing modules to keep as source of truth

- `alde/agents_config.py`
- `alde/agents_registry.py`
- `alde/tools.py`
- `alde/agents_factory.py`
- `alde/chat_completion.py`

### New phase-1 modules

- `alde/runtime_events.py`
- `alde/event_store.py`
- `alde/runtime_metrics.py`
- `alde/runtime_view.py`

### Next integration points

- project `learning_events.jsonl` into normalized query and outcome objects
- project `ChatHistory` workflow and tool-call entries into normalized runtime objects
- export periodic metric snapshots under `AppData/generated/`
- export normalized runtime views under `AppData/generated/`
- add standalone JSONL exports only where external consumers need a stable file boundary

## Architectural Rules

1. `alde/agents_config.py` remains declarative.
2. The UI layer must not own workflow state transitions.
3. Retrieval logic must not own routing policy.
4. Event schemas must be stable enough for offline evaluation.
5. Storage backends are adapters, not control-plane sources of truth.

## Related Documents

- `ARCHITECTURE_REFACTOR.md`
- `AGENT_SEQUENCE_STATE_DIAGRAM.md`
- `AUTONOMOUS_MULTI_AGENT_ROADMAP.md`
- `AUTONOMOUS_MULTI_AGENT_TASKLIST.md`
- `REQUEST_RESPONSE_HANDOFF_FLOW.md`
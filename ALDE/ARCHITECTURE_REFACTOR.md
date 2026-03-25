# Architecture Refactor Plan

## Purpose

This document turns the informal planning notes in `alde/plan to refactor.md` into a repo-level architecture reference.

The goal is to centralize agent, model, tool, role, and workflow configuration in `alde/agents_config.py` while keeping runtime registration responsibilities distributed:

- `alde/agents_registry.py` remains the agent registration module.
- `alde/tools.py` remains the tool registration module.
- `alde/agents_config.py` becomes the canonical configuration source for agents, tools, roles, skill profiles, and workflow schemas.

This refactor started as a staged plan. The current runtime now already uses manifest-driven configuration, role policies, workflow definitions, and validation hooks from `alde/agents_config.py`.

## Current State

Today, configuration concerns are split across multiple runtime modules:

- agent model and tool assignments live in `alde/agents_registry.py`
- prompt content, prompt fragments, skill profiles, and manifest lookup helpers live in `alde/agents_config.py`
- tool registration and expansion logic live in `alde/tools.py`
- runtime orchestration lives in `alde/agents_factory.py` and `alde/chat_completion.py`

This works, but it mixes declarative configuration with runtime concerns and makes larger workflow changes harder to reason about.

## Target Architecture

### 1. Central configuration source

`alde/agents_config.py` should define declarative data for:

- agent runtime configuration per `agent_label`
- model selection
- runtime instruction lookup
- tool names and tool-group assignments
- configuration defaults and aliases
- role metadata and routing policy
- skill profiles and prompt fragments
- instance policy and history policy
- workflow metadata and validation

The module should expose a small public API, for example:

- `get_system_prompt(...)`
- `get_agent_config(...)`
- `get_agents_registry_data(...)`
- `get_tool_config(...)`
- `get_tool_group_config(...)`
- `get_workflow_config(...)`
- `get_agent_manifest(...)`
- `validate_all_workflows(...)`

### 2. Registration remains distributed

The refactor does not collapse all code into one file.

- `alde/agents_registry.py` should keep exporting `AGENTS_REGISTRY`
- `alde/tools.py` should keep building and exporting tool specs

Both modules should read from `alde/agents_config.py` instead of owning hardcoded configuration.

### 3. Workflow definitions become declarative

The configuration layer should be able to describe deterministic workflows, including:

- ordered agent and tool sequences
- state nodes
- transitions
- entry conditions
- success and failure branches
- terminal steps
- dependencies between agents and tools

The current runtime already consumes these definitions for routing, workflow visibility, history shaping, and scoped instance reuse. This is still not a separate standalone engine process, but it is no longer configuration-only.

## Architectural Boundaries

The refactor must preserve a strict dependency direction:

- `alde/agents_config.py` must not import runtime orchestration modules
- `alde/agents_registry.py` may read from `alde/agents_config.py`
- `alde/tools.py` may read from `alde/agents_config.py`
- `alde/agents_factory.py` and `alde/chat_completion.py` continue consuming registry and tool adapters

This keeps import order predictable and avoids introducing new cycles into the current lazy-import paths.

## Migration Phases

### Phase 1: Centralize agent and tool configuration

Status: completed

Deliverables:

- formal agent configuration data model in `alde/agents_config.py`
- prompt content separated from runtime agent configuration in the same module
- `alde/agents_registry.py` materializes `AGENTS_REGISTRY` from central config
- tool configuration data moved into `alde/agents_config.py`
- `alde/tools.py` becomes a registration adapter over central config

Acceptance criteria:

- no new import cycles
- same exported agent labels as before
- same effective `model`, `system`, and `tools` data as before
- existing route-to-agent validation remains intact

### Phase 2: Add workflow schema definitions

Status: completed in runtime form

Deliverables:

- declarative workflow data model in `alde/agents_config.py`
- explicit sequence, state, and transition structures
- validation hooks for workflow definitions
- clearly marked adapter points in `alde/agents_factory.py` for future workflow resolution

Acceptance criteria:

- workflow definitions are readable and validatable
- workflow definitions are validated and consumed by the runtime without introducing a separate orchestration service

### Phase 3: Publish and align documentation

Status: in progress

Deliverables:

- this architecture document as repo-level reference
- README links to architecture and current-state diagrams
- contributing guidance points major refactors to this document
- webapp docs and visible web entrypoints mention the architecture reference
- legacy documentation terminology is normalized to manifest-, workflow-, and policy-based naming

Acceptance criteria:

- architecture guidance is discoverable from the repo root
- documentation terms are consistent across README, webapp docs, and roadmap references

### Phase 4: External website synchronization

Status: pending

The external project website is tracked separately under `/home/ben/Vs_Code_Projects/Projects/MyWebPage` and is outside this workspace.

That website should later be aligned with:

- the new architecture terminology
- a short explanation of the central configuration model
- a stable link back to this repo documentation

This phase is intentionally decoupled from the implementation inside this repository.

## Affected Runtime Modules

- `alde/agents_config.py`
- `alde/agents_registry.py`
- `alde/tools.py`
- `alde/agents_factory.py`
- `alde/chat_completion.py`
- `alde/webapp/*`

## Related Documents

- `alde/plan to refactor.md` for the original planning notes
- `AGENT_SEQUENCE_STATE_DIAGRAM.md` for the current sequence and state model
- `AUTONOMOUS_MULTI_AGENT_ROADMAP.md` for the broader evolution path

## Explicit Non-Goals

- replacing the current orchestration logic with a separate standalone workflow service in the same change
- moving runtime execution logic into `alde/agents_config.py`
- changing agent registration ownership away from `alde/agents_registry.py`
- changing tool registration ownership away from `alde/tools.py`

## Verification Checklist

1. `alde/agents_config.py`, `alde/agents_registry.py`, `alde/tools.py`, `alde/agents_factory.py`, and `alde/chat_completion.py` import cleanly after the refactor.
2. `AGENTS_REGISTRY` still exports the same agent labels and effective runtime fields.
3. Existing tool lookup and agent-routing paths remain behaviorally compatible.
4. Prompt lookup remains identical for canonical and legacy agent names.
5. Workflow schemas and agent manifests validate cleanly.
6. Documentation entrypoints link to this document and use the same terminology.
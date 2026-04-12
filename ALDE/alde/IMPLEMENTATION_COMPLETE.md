# Implementation Summary

This file replaces the former multi-agent implementation snapshot.

## Current Runtime Model

Only two manifest agents are active in the runtime:

- `_xplaner_xrouter`
  - user-facing planning and routing
  - session-scoped workflow
  - routes execution work to `_xworker`

- `_xworker`
  - single execution agent
  - specialization is selected by `job_name`
  - examples: `cover_letter_writer`, `job_posting_parser`, `applicant_profile_parser`, `document_dispatch`, `agent_system_builder`

## Practical Consequences

- legacy single-purpose manifest labels are no longer the active runtime model
- routing contracts now describe `_xplaner_xrouter -> _xworker`
- worker specialization is expressed in handoff payloads and prompt config, not by switching to separate manifest identities

## Current Entry Points

- interactive routing starts at `_xplaner_xrouter`
- forced cover-letter generation also routes to `_xworker`
- deterministic ingest and dispatch actions can execute directly on `_xworker`
- local desktop execution is the maintained operator path and persists run state to `ALDE/AppData/desktop_runs.json`

## Frontend Plan

- the former webapp frontend is currently not part of this repository
- the next frontend milestone is a dedicated ALDE WebApp only after the desktop UI, runtime, storage, and config layers are stable
- until then, desktop/local runtime remains the reference operator surface

## Current References

Use these files for the maintained runtime description:

- `QUICKSTART.md`
- `desktop_runtime.py`
- `runtime_core.py`
- `agents_pconfig.py`
- `agents_config.py`

## Archive Note

The removed content in the old version of this file documented a pre-refactor architecture and is intentionally not kept inline anymore because it no longer reflects the running system.

## UI Update: Runtime Widget Chat Context (2026-04-12)

### Scope

- Updated runtime widget header actions in the desktop Control Plane.
- Standardized widget-to-chat export behavior for all runtime widget types.

### Implemented UI Changes

- Each runtime widget header now exposes:
  - file import action
  - one chat export action (`An Chat anhängen`)
- The previous optional second export variant (full-context action) was removed again to reduce UI complexity.

### Technical Behavior

- Export no longer injects full widget payload directly into the visible prompt text.
- Visible prompt receives only a concise title line (typically the file name).
- Full widget content is stored internally as runtime context entries and appended only at send-time to the model input payload.
- Runtime context is cleared after send to prevent stale carry-over between requests.

### Functional Outcome

- Operator sees a clean and short prompt.
- Model still receives the full attached widget context for generation quality.
- UX remains simple (single export action) while preserving context completeness in the backend request.
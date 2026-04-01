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

## Current References

Use these files for the maintained runtime description:

- `QUICKSTART.md`
- `webapp/README.md`
- `agents_pconfig.py`
- `agents_config.py`

## Archive Note

The removed content in the old version of this file documented a pre-refactor architecture and is intentionally not kept inline anymore because it no longer reflects the running system.
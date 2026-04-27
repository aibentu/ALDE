# Cover Letter Workflow Fixes (Historical Archive)

This note is kept only as a short archive reference for an earlier pre-manifest cleanup phase.

## Historical scope

The original issue set belonged to the older prompt-centric runtime before `alde/agents_config.py` became the central source of truth.

That older state included:

- oversized prompt definitions
- malformed JSON sections in prompt files
- duplicate prompt-only agent modules
- inconsistent legacy aliases across registry and prompt lookups

## What changed afterwards

The current runtime no longer uses that structure as its primary configuration path.

Today:

- `alde/agents_config.py` is the source of truth for manifests, runtime instructions, roles, tool policy, workflow definitions, instance policy, and history policy
- legacy prompt-only modules were removed or replaced by compatibility shims
- runtime agent labels use the current canonical names such as `_primary_assistant` and `_cover_letter_agent`
- workflow validation and workflow visibility are handled by the current manifest-driven runtime

## Archive intent

Keep this file only as a reminder that an earlier prompt-cleanup phase existed.

If you need the current implementation model, use these files instead:

- `ALDE/ARCHITECTURE_REFACTOR.md`
- `ALDE/AGENT_SEQUENCE_STATE_DIAGRAM.md`
- `ALDE/alde/agents_config.py`
- `ALDE/alde/IMPLEMENTATION_COMPLETE.md`

This file should not be used as a description of the current runtime behavior.

# Workflow Checkpoint And Templates

## Scope

This note captures the effective state since the last workflow-policy checkpoint and provides directly reusable configuration templates for the current manifest-driven runtime.

It is intentionally practical:
- what changed
- what is now considered valid runtime behavior
- which configuration blocks are actually required
- copyable templates for the three supported patterns

## Checkpoint Delta

### 1. `service_scoped` is now explicitly guarded

`instance_policy` is no longer only implied by runtime code paths.

Current allowed values:
- `ephemeral`
- `session_scoped`
- `workflow_scoped`
- `service_scoped`

Manifest validation now rejects unknown values.

Practical consequence:
- policy mistakes are caught during validation instead of silently degrading into unclear runtime behavior

### 2. Generic worker-to-specialist routing was removed

The old pattern where generic worker agents routed to specialized worker agents is no longer part of the supported runtime policy.

Removed as active design:
- generic parser router chain
- generic writer router chain
- generic worker exposure of `route_to_agent`

Current policy:
- routing is reserved for the `primary_assistant`
- generic workers are leaf workers
- specialized workers are leaf workers
- workflow services may still orchestrate deterministic tool or agent chains when explicitly configured

Practical consequence:
- `_parser_agent` is a leaf worker
- `_writer_agent` is a leaf worker
- `_profile_parser` is a leaf worker
- `_job_posting_parser` is a leaf worker
- `_cover_letter_agent` is a leaf worker
- `_data_dispatcher` remains a workflow-service agent
- `_primary_assistant` remains the planner/router entrypoint

### 3. Runtime behavior and configuration are aligned again

Before the cleanup, policy and configuration diverged:
- runtime permission checks already denied worker routing
- `WORKFLOW_CONFIGS` still modeled generic worker router chains
- some runtime configs still carried `route_to_agent` although the role policy forbade it

This is now aligned:
- worker manifests use non-routing leaf workflows
- worker tool exposure no longer advertises `route_to_agent`
- the only interactive router is the primary assistant

### 4. Focused workflow coverage is in place

The focused routing/workflow tests cover:
- service-scoped reuse
- invalid instance-policy rejection
- primary assistant remains router
- generic parser/writer are leaf workflows
- worker routing remains denied at runtime

## Current Resolution Order

The current runtime resolves an agent workflow in this order:

1. `manifest.workflow_name`
2. `AGENT_WORKFLOW_MAP[agent_label]`
3. `AGENT_RUNTIME_CONFIG[agent_label]["workflow"]["definition"]`

If no workflow name is found, the agent has no workflow binding.

## What Is Required For An Agent Workflow Binding

There is no separate runtime field named `workflow.agent_workflow`.

In practice, you need three configuration layers:

1. Runtime binding in `AGENT_RUNTIME_CONFIG`
2. Policy/role overrides in `AGENT_MANIFEST_OVERRIDES`
3. State-machine definition in `WORKFLOW_CONFIGS`

## Required Schema

### A. Runtime binding template

This is the minimal binding that makes an agent resolve to a workflow definition:

```python
AGENT_RUNTIME_CONFIG["_<agent_label>"] = {
    "canonical_name": "<canonical_agent_name>",
    "model": "gpt-4o-mini",
    "tools": [],
    "defaults": {},
    "workflow": {
        "definition": "<workflow_name>",
    },
}
```

Relevant fields:
- `canonical_name`
- `model`
- `tools`
- `defaults`
- `workflow.definition`

### B. Manifest override template

This controls role and runtime policy.

```python
AGENT_MANIFEST_OVERRIDES["_<agent_label>"] = {
    "role": "worker",
    "skill_profile": "structured_parser",
    "instance_policy": "ephemeral",
    "routing_policy": {
        "mode": "worker",
        "can_route": False,
    },
    "history_policy": {
        "followup_history_depth": 6,
        "include_routed_history": False,
        "routed_history_depth": 0,
    },
}
```

Important notes:
- `role` must exist in `AGENT_ROLE_CONFIGS`
- `skill_profile` must exist in `AGENT_SKILL_PROFILES`
- `instance_policy` must be one of:
  - `ephemeral`
  - `session_scoped`
  - `workflow_scoped`
  - `service_scoped`

### C. Workflow definition template

This is what the validator effectively expects.

```python
WORKFLOW_CONFIGS["<workflow_name>"] = {
    "description": "Optional human-readable description.",
    "entry_state": "active",
    "retry_policy": {
        "max_attempts": 0,
        "backoff_seconds": [],
    },
    "states": {
        "active": {
            "actor": {
                "kind": "agent",
                "name": "_<agent_label>",
            },
            "terminal": False,
        },
        "complete": {
            "actor": {
                "kind": "state",
                "name": "workflow_complete",
            },
            "terminal": True,
        },
    },
    "transitions": [
        {
            "from": "active",
            "on": {
                "kind": "state",
                "name": "followup_complete",
                "conditions": {
                    "result": {"exists": True},
                },
            },
            "to": "complete",
        }
    ],
}
```

Required by validation:
- `entry_state`
- `states`
- `transitions`

Required per state:
- `actor.kind`
- `terminal`
- `actor.name` when `actor.kind` is `agent` or `tool`

Required per transition:
- `from`
- `to`
- `on.kind`
- `on.name`

Supported values:
- `actor.kind`: `agent`, `tool`, `state`
- `on.kind`: `tool`, `state`

## Maximal Configuration Example

Use this when you want a fully explicit setup with retry, history policy, and instance policy.

```python
AGENT_RUNTIME_CONFIG["_<agent_label>"] = {
    "canonical_name": "<canonical_agent_name>",
    "model": "gpt-4o-mini",
    "tools": [
        "@doc_rw",
    ],
    "defaults": {
    },
    "workflow": {
        "definition": "<workflow_name>",
    },
}

AGENT_MANIFEST_OVERRIDES["_<agent_label>"] = {
    "role": "worker",
    "skill_profile": "structured_parser",
    "instance_policy": "ephemeral",
    "routing_policy": {
        "mode": "worker",
        "can_route": False,
    },
    "history_policy": {
        "followup_history_depth": 6,
        "include_routed_history": False,
        "routed_history_depth": 0,
    },
}

WORKFLOW_CONFIGS["<workflow_name>"] = {
    "description": "Fully explicit worker workflow.",
    "entry_state": "active",
    "retry_policy": {
        "max_attempts": 0,
        "backoff_seconds": [],
    },
    "states": {
        "active": {
            "actor": {"kind": "agent", "name": "_<agent_label>"},
            "terminal": False,
        },
        "complete": {
            "actor": {"kind": "state", "name": "workflow_complete"},
            "terminal": True,
        },
    },
    "transitions": [
        {
            "from": "active",
            "on": {
                "kind": "state",
                "name": "followup_complete",
                "conditions": {
                    "result": {"exists": True},
                },
            },
            "to": "complete",
        }
    ],
}
```

## Minimal Configuration Example

Use this when you just want the smallest valid leaf workflow.

```python
AGENT_RUNTIME_CONFIG["_<agent_label>"] = {
    "canonical_name": "<canonical_agent_name>",
    "model": "gpt-4o-mini",
    "tools": [],
    "defaults": {},
    "workflow": {"definition": "<workflow_name>"},
}

AGENT_MANIFEST_OVERRIDES["_<agent_label>"] = {
    "role": "worker",
    "skill_profile": "structured_parser",
}

WORKFLOW_CONFIGS["<workflow_name>"] = {
    "entry_state": "active",
    "states": {
        "active": {
            "actor": {"kind": "agent", "name": "_<agent_label>"},
            "terminal": False,
        },
        "complete": {
            "actor": {"kind": "state", "name": "workflow_complete"},
            "terminal": True,
        },
    },
    "transitions": [
        {
            "from": "active",
            "on": {"kind": "state", "name": "followup_complete"},
            "to": "complete",
        }
    ],
}
```

## Template 1: Worker Leaf Template

Use this for generic or specialized workers that should not delegate further.

```python
AGENT_RUNTIME_CONFIG["_<agent_label>"] = {
    "canonical_name": "<canonical_agent_name>",
    "model": "gpt-4o-mini",
    "tools": [
        "@doc_rw",
    ],
    "defaults": {},
    "workflow": {
        "definition": "<worker_leaf_workflow_name>",
    },
}

AGENT_MANIFEST_OVERRIDES["_<agent_label>"] = {
    "role": "worker",
    "skill_profile": "structured_parser",
    "instance_policy": "ephemeral",
    "routing_policy": {
        "mode": "worker",
        "can_route": False,
    },
    "history_policy": {
        "followup_history_depth": 6,
        "include_routed_history": False,
        "routed_history_depth": 0,
    },
}

WORKFLOW_CONFIGS["<worker_leaf_workflow_name>"] = {
    "description": "Leaf workflow for a worker agent without downstream routing.",
    "entry_state": "active",
    "states": {
        "active": {
            "actor": {"kind": "agent", "name": "_<agent_label>"},
            "terminal": False,
        },
        "complete": {
            "actor": {"kind": "state", "name": "workflow_complete"},
            "terminal": True,
        },
    },
    "transitions": [
        {
            "from": "active",
            "on": {
                "kind": "state",
                "name": "followup_complete",
                "conditions": {
                    "result": {"exists": True},
                },
            },
            "to": "complete",
        }
    ],
}
```

Recommended for:
- generic parser workers
- generic writer workers
- specialized parser workers
- specialized writer workers

## Template 2: Workflow Service Template

Use this for deterministic orchestration agents like dispatcher chains.

```python
AGENT_RUNTIME_CONFIG["_<agent_label>"] = {
    "canonical_name": "<canonical_agent_name>",
    "model": "gpt-4o-mini",
    "tools": [
        "@dispatcher",
        "route_to_agent",
    ],
    "defaults": {},
    "workflow": {
        "definition": "<service_workflow_name>",
    },
}

AGENT_MANIFEST_OVERRIDES["_<agent_label>"] = {
    "role": "workflow_service",
    "skill_profile": "workflow_dispatch",
    "instance_policy": "workflow_scoped",
    "routing_policy": {
        "mode": "workflow_service",
        "can_route": False,
    },
    "history_policy": {
        "followup_history_depth": 8,
        "include_routed_history": False,
        "routed_history_depth": 0,
    },
}

WORKFLOW_CONFIGS["<service_workflow_name>"] = {
    "description": "Deterministic service workflow with tool and optional handoff steps.",
    "entry_state": "ready",
    "retry_policy": {
        "max_attempts": 3,
        "backoff_seconds": [1, 2, 4],
    },
    "states": {
        "ready": {
            "actor": {"kind": "agent", "name": "_<agent_label>"},
            "terminal": False,
        },
        "tool_completed": {
            "actor": {"kind": "tool", "name": "<tool_name>"},
            "terminal": False,
        },
        "routed": {
            "actor": {"kind": "tool", "name": "route_to_agent"},
            "terminal": False,
        },
        "retry_pending": {
            "actor": {"kind": "state", "name": "retry_pending"},
            "terminal": False,
        },
        "failed": {
            "actor": {"kind": "state", "name": "workflow_failed"},
            "terminal": True,
        },
        "complete": {
            "actor": {"kind": "state", "name": "workflow_complete"},
            "terminal": True,
        },
    },
    "transitions": [
        {
            "from": "ready",
            "on": {"kind": "tool", "name": "<tool_name>"},
            "to": "tool_completed",
        },
        {
            "from": "tool_completed",
            "on": {
                "kind": "tool",
                "name": "route_to_agent",
                "conditions": {
                    "target_agent": "_<target_worker_agent>",
                },
            },
            "to": "routed",
        },
        {
            "from": "routed",
            "on": {
                "kind": "state",
                "name": "followup_complete",
            },
            "to": "complete",
        },
        {
            "from": ["ready", "tool_completed", "routed"],
            "on": {
                "kind": "state",
                "name": ["tool_failed", "model_failed", "routed_agent_failed"],
                "conditions": {
                    "any": [
                        {"tool_name": {"in": ["<tool_name>", "route_to_agent"]}},
                        {"error": {"exists": True}},
                        {"target_agent": "_<target_worker_agent>"},
                    ]
                },
            },
            "to": "retry_pending",
        },
        {
            "from": "retry_pending",
            "on": {"kind": "state", "name": "retry_requested"},
            "to": "ready",
        },
        {
            "from": "retry_pending",
            "on": {"kind": "state", "name": "retry_exhausted"},
            "to": "failed",
        },
    ],
}
```

Recommended for:
- dispatcher/orchestration chains
- deterministic pipeline services
- bounded retry workflows

## Template 3: Primary Router Template

Use this only for the interactive planner/router entrypoint.

```python
AGENT_RUNTIME_CONFIG["_primary_assistant"] = {
    "canonical_name": "primary_assistant",
    "model": "gpt-4o",
    "tools": [
        "memorydb",
        "route_to_agent",
        "@doc_rw",
    ],
    "defaults": {},
    "workflow": {
        "definition": "primary_assistant_router",
    },
}

AGENT_MANIFEST_OVERRIDES["_primary_assistant"] = {
    "role": "planner_router",
    "skill_profile": "conversation_router",
    "instance_policy": "session_scoped",
    "routing_policy": {
        "mode": "planner_router",
        "can_route": True,
    },
    "history_policy": {
        "followup_history_depth": 15,
        "include_routed_history": True,
        "routed_history_depth": 12,
    },
}

WORKFLOW_CONFIGS["primary_assistant_router"] = {
    "description": "Interactive planner/router workflow with declarative delegation branches.",
    "entry_state": "assistant_ready",
    "retry_policy": {
        "max_attempts": 2,
        "backoff_seconds": [1, 2],
    },
    "states": {
        "assistant_ready": {
            "actor": {"kind": "agent", "name": "_primary_assistant"},
            "terminal": False,
        },
        "delegated": {
            "actor": {"kind": "tool", "name": "route_to_agent"},
            "terminal": False,
        },
        "assistant_retry_pending": {
            "actor": {"kind": "state", "name": "retry_pending"},
            "terminal": False,
        },
        "assistant_failed": {
            "actor": {"kind": "state", "name": "workflow_failed"},
            "terminal": True,
        },
        "workflow_complete": {
            "actor": {"kind": "state", "name": "workflow_complete"},
            "terminal": True,
        },
    },
    "transitions": [
        {
            "from": "assistant_ready",
            "on": {
                "kind": "tool",
                "name": "route_to_agent",
                "conditions": {
                    "target_agent": {"in": [
                        "_data_dispatcher",
                        "_parser_agent",
                        "_writer_agent",
                    ]},
                },
            },
            "to": "delegated",
        },
        {
            "from": "delegated",
            "on": {
                "kind": "state",
                "name": "routed_agent_complete",
                "conditions": {
                    "target_agent": {"in": [
                        "_data_dispatcher",
                        "_parser_agent",
                        "_writer_agent",
                    ]},
                },
            },
            "to": "workflow_complete",
        },
        {
            "from": ["assistant_ready", "delegated"],
            "on": {
                "kind": "state",
                "name": ["model_failed", "routed_agent_failed"],
                "conditions": {
                    "any": [
                        {"error": {"exists": True}},
                        {"result": {"exists": True}},
                    ]
                },
            },
            "to": "assistant_retry_pending",
        },
        {
            "from": "assistant_retry_pending",
            "on": {"kind": "state", "name": "retry_requested"},
            "to": "assistant_ready",
        },
        {
            "from": "assistant_retry_pending",
            "on": {"kind": "state", "name": "retry_exhausted"},
            "to": "assistant_failed",
        },
    ],
}
```

Recommended for:
- the single interactive planning/router entrypoint
- user-facing delegation logic
- conversation-aware session-scoped routing

## Pattern Guidance

Use only these runtime patterns:

1. `worker_leaf_template`
2. `workflow_service_template`
3. `primary_router_template`

Do not reintroduce the old generic worker-router pattern.

That older design conflicts with the current routing policy where interactive delegation belongs to the primary assistant and deterministic orchestration belongs to workflow-service agents.
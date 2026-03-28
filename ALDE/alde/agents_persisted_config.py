from __future__ import annotations

from textwrap import dedent
from typing import Any


def _text(value: str) -> str:
    return dedent(value).strip()


SYSTEM_PROMPT: dict[str, dict[str, Any]] = {
    "primary_assistant": {
        "prompt": _text(
            """
            === Agent: primary_assistant ===
            Description: Primary assistant that owns user interaction and routes specialized tasks.
            Goal: Deliver clear, correct, concise answers and delegate only when specialization is needed.

            Rules:
            - Handle straightforward requests directly.
            - Route specialized work via route_to_agent.
            - If the user message starts with @_agent_name, route to that agent.
            - Use memorydb and vectordb when file, code, or prior-project context matters.
            - If context is missing or uncertain, state that clearly and propose the next step.
            - Never invent file contents, paths, tool results, or code behavior.
            """
        ),
        "task": {},
        "output_schema": {},
    },
    "agent_system_planner": {
        "prompt": _text(
            """
            === Agent: agent_system_planner ===
            Description: Interactive planner for building agentic systems.
            Goal: Clarify the requested agent system, structure the plan, and hand off config generation to the builder worker.

            Rules:
            - Ask targeted follow-up questions until the system requirements are specific enough to build.
            - Keep the plan aligned with the declared planning schema.
            - Route concrete config generation only to _agent_system_worker.
            - When the request is already specific, hand off immediately with a structured brief.
            """
        ),
        "task": {
            "mode": "agent_system_planner",
            "route_prefix": "/create agents",
            "planning_schema": {
                "required_steps": [
                    "capture_goal",
                    "identify_agents",
                    "define_workflows",
                    "confirm_tools",
                    "handoff_builder",
                ],
                "required_sections": [
                    "agent_specs",
                    "workflow_specs",
                    "integration_targets",
                ],
                "required_agent_fields": [
                    "name",
                    "agent_name",
                    "role",
                    "responsibility",
                    "tools",
                ],
                "required_workflow_fields": [
                    "name",
                    "kind",
                    "entry_state",
                    "owner_agent",
                ],
                "required_integration_fields": [
                    "assistant_agent_name",
                    "route_prefix",
                    "persisted_config_target",
                ],
                "interactive": True,
                "worker_agent": "_agent_system_worker",
            },
        },
        "output_schema": {
            "plan": {
                "required_steps": [
                    "capture_goal",
                    "identify_agents",
                    "define_workflows",
                    "confirm_tools",
                    "handoff_builder",
                ],
                "required_sections": [
                    "agent_specs",
                    "workflow_specs",
                    "integration_targets",
                ],
                "required_agent_fields": [
                    "name",
                    "agent_name",
                    "role",
                    "responsibility",
                    "tools",
                ],
                "required_workflow_fields": [
                    "name",
                    "kind",
                    "entry_state",
                    "owner_agent",
                ],
                "required_integration_fields": [
                    "assistant_agent_name",
                    "route_prefix",
                    "persisted_config_target",
                ],
                "worker_agent": "_agent_system_worker",
            },
        },
    },
    "agent_system_worker": {
        "prompt": _text(
            """
            === Agent: agent_system_worker ===
            Description: Worker agent that materializes planner-approved agent/workflow config bundles.
            Goal: Produce prompt, runtime, manifest, workflow, handoff, and forced-route configs for a requested agent system.

            Rules:
            - Use build_agent_system_configs to generate the canonical bundle.
            - Keep names generic and reusable.
            - Preserve Domain -> Object -> Function structure in generated configs.
            - Return the bundle and highlight any remaining manual integration steps.
            """
        ),
        "task": {
            "mode": "agent_system_worker",
            "action_tool": "build_agent_system_configs",
            "action_request_schema": "agent_system_builder_request",
        },
        "output_schema": {
            "bundle_sections": [
                "prompt_configs",
                "agent_runtime_configs",
                "agent_manifest_override_configs",
                "handoff_schema_configs",
                "action_request_schema_configs",
                "tool_configs",
                "workflow_configs",
                "forced_route_configs",
                "assistant_integration",
            ],
        },
    },
    "parser_agent": {
        "prompt": _text(
            """
            === Agent: parser_agent ===
            Description: Generic structured extraction agent.
            Goal: Transform source-grounded input into task-specific JSON without inventing facts.

            Rules:
            - Extract only what is present in the source.
            - Use null or [] when information is missing or ambiguous.
            - Normalize only when meaning stays unchanged.
            - Keep the output schema stable.
            - Return JSON only.
            """
        ),
        "task": {
            "mode": "generic_parser",
            "execution_model": [
                "The concrete extraction task is defined by the specialized task entry.",
                "The task-specific schema overrides generic wording.",
                "If the source is incomplete, keep the schema stable and surface issues in parse.errors or parse.warnings.",
            ],
        },
        "output_schema": {},
    },
    "writer_agent": {
        "prompt": _text(
            """
            === Agent: writer_agent ===
            Description: Generic structured writing agent.
            Goal: Produce task-specific written artifacts from structured inputs without inventing facts.

            Rules:
            - Use only facts present in the provided structured inputs.
            - Do not add skills, dates, contacts, achievements, or claims that are not supported by the input.
            - If required information is missing, use neutral wording instead of guessing.
            - Respect requested language, tone, and length constraints.
            - Return JSON only.
            """
        ),
        "task": {
            "mode": "generic_writer",
            "execution_model": [
                "The concrete writing task is defined by the specialized task entry.",
                "The task-specific schema overrides generic wording.",
                "When constraints conflict, prefer factual correctness over stylistic ambition.",
            ],
        },
        "output_schema": {},
    },
    "data_dispatcher": {
        "prompt": _text(
            """
            === Agent: data_dispatcher ===
            Description: Discovers job posting PDFs, checks DB status, and forwards only eligible items.
            Goal: Provide deduplicated, validated document references for downstream parsing workflows.

            Rules:
            - Discover PDF files deterministically.
            - Prefer content_sha256 as stable identity; filename alone is not sufficient.
            - Do not forward documents that are already processed or currently queued/processing.
            - Use dispatch_documents only for filesystem scan requests that start from scan_dir.
            - Use execute_action_request or upsert_object_record when the input already contains structured job/profile data or when stores/DB state should be updated without rescanning files.
            - Use route_to_agent only when fresh parsing or generation work is required; do not delegate just to perform deterministic store or DB updates.
            - If the user requests batch generation of cover letters, call the batch workflow and stop after returning its result.
            - A single broken PDF must not abort the whole run.
            - If DB access is uncertain, report UNKNOWN instead of inventing state.
            """
        ),
        "task": {
            "input_contract": {
                "required": ["scan_dir", "db", "thread_id", "dispatcher_message_id"],
                "optional": [
                    "recursive",
                    "extensions",
                    "max_files",
                    "parser_agent_name",
                    "dry_run",
                    "handoff_message_id",
                ],
            },
            "workflow": [
                "If the request already contains structured non-file payloads for job/profile ingestion or DB synchronization, execute the matching deterministic action tool instead of scanning directories.",
                "List files in scan_dir and filter to PDFs.",
                "Check readability and compute content_sha256, file_size_bytes, and mtime_epoch.",
                "Look up each document in the dispatcher DB and classify it as new, known_unprocessed, known_processing, known_processed, or error.",
                "Forward only new or known_unprocessed items to the job_posting_parser workflow when parsing work is still required.",
                "When parsed job data is already available and dispatcher/job-posting stores must be updated together, prefer upsert_object_record over separate store/status writes.",
                "Return a structured report with summary, forwarded items, and errors.",
            ],
            "tools": [
                "dispatch_documents",
                "execute_action_request",
                "upsert_object_record",
                "ingest_object",
                "store_object_result",
                "batch_generate_documents",
                "vdb_worker",
            ],
        },
        "output_schema": {
            "agent": "data_dispatcher",
            "scan_dir": "/path",
            "summary": {
                "pdf_found": 0,
                "new": 0,
                "known_unprocessed": 0,
                "known_processing": 0,
                "known_processed": 0,
                "errors": 0,
            },
            "forwarded": [
                {
                    "path": "/path/a.pdf",
                    "content_sha256": "...",
                    "link": {"thread_id": "...", "message_id": "..."},
                }
            ],
            "errors": [],
        },
    },
    "profile_parser": {
        "prompt": _text(
            """
            === Agent: profile_parser ===
            Description: Structured applicant profile parser.
            Goal: Convert CV or applicant-profile input into a reusable, storage-ready JSON profile.

            Rules:
            - Be strictly source-grounded.
            - Generate a stable profile_id from email when email is present.
            - If email is missing, set profile_id to null and add missing_email_for_profile_id to warnings.
            - On re-parse, overwrite only values clearly present in the new source.
            - Do not downgrade populated values to null unless the source explicitly requests removal.
            """
        ),
        "task": {
            "specialization": "applicant_profile",
            "input_contract": {
                "variants": ["applicant_profile_text", "applicant_profile_file"],
                "correlation_id_fallback": "file.content_sha256 or null",
            },
            "extraction_guidance": [
                "Keep date and duration formats source-faithful when normalization is ambiguous.",
                "Deduplicate skills.",
                "Include language levels only when explicitly stated.",
                "Use empty lists instead of placeholder rows when nothing can be extracted.",
            ],
        },
        "output_schema": {
            "agent": "profile_parser",
            "correlation_id": None,
            "parse": {
                "language": "de",
                "extraction_quality": "high",
                "errors": [],
                "warnings": [],
            },
            "profile": {
                "profile_id": "profile:<sha256(email)>",
                "personal_info": {
                    "full_name": None,
                    "date_of_birth": None,
                    "citizenship": None,
                    "address": None,
                    "phone": None,
                    "email": None,
                    "linkedin": None,
                    "portfolio": None,
                },
                "professional_summary": "",
                "experience": [],
                "education": [],
                "skills": {
                    "technical": [],
                    "soft": [],
                    "languages": [],
                },
                "certifications": [],
                "projects": [],
                "preferences": {
                    "tone": "modern",
                    "max_length": 350,
                    "language": "de",
                    "focus_areas": [],
                },
                "additional_information": {
                    "travel_willingness": None,
                    "work_authorization": None,
                    "marital_status": None,
                },
            },
        },
    },
    "job_posting_parser": {
        "prompt": _text(
            """
            === Agent: job_posting_parser ===
            Description: Structured job-posting extraction agent.
            Goal: Convert dispatcher payloads for job-posting PDFs into a normalized JSON representation.

            Rules:
            - Determine whether the source is actually a job posting.
            - Do not score candidate fit or make downstream decisions.
            - Populate db_updates only as the desired state transition.
            - Keep salaries in the original currency.
            - Return JSON only.
            """
        ),
        "task": {
            "specialization": "job_posting",
            "input_contract": {
                "type": "job_posting_pdf",
                "required": ["correlation_id", "link", "file", "db", "requested_actions"],
                "missing_field_policy": "Mirror missing fields as null and report them in parse.errors.",
            },
            "extraction_guidance": [
                "Use YYYY-MM-DD only when a date is unambiguous.",
                "Deduplicate ordered lists with most important items first.",
                "Put the full extracted text into job_posting.raw_text when available.",
                "If the source is not a job posting, keep the schema stable and mark db_updates as failed.",
            ],
        },
        "output_schema": {
            "agent": "job_posting_parser",
            "correlation_id": "<content_sha256>",
            "link": {"thread_id": "...", "message_id": "..."},
            "file": {
                "path": "...",
                "name": "...",
                "content_sha256": "...",
            },
            "parse": {
                "is_job_posting": True,
                "language": "de",
                "extraction_quality": "high",
                "errors": [],
                "warnings": [],
            },
            "job_posting": {
                "job_title": None,
                "company_name": None,
                "company_info": {
                    "industry": None,
                    "size": None,
                    "location": None,
                    "website": None,
                },
                "position": {
                    "type": None,
                    "level": None,
                    "department": None,
                    "reports_to": None,
                },
                "location_details": {
                    "office": None,
                    "remote": None,
                    "travel_required": None,
                },
                "compensation": {
                    "salary_min": None,
                    "salary_max": None,
                    "salary_period": None,
                    "currency": None,
                    "benefits": [],
                },
                "requirements": {
                    "education": None,
                    "experience_years": None,
                    "experience_description": None,
                    "technical_skills": [],
                    "soft_skills": [],
                    "languages": [],
                },
                "responsibilities": [],
                "what_we_offer": [],
                "application": {
                    "deadline": None,
                    "application_link": None,
                    "contact_email": None,
                    "contact_person": None,
                },
                "metadata": {
                    "posting_date": None,
                    "job_id": None,
                    "source": None,
                    "language": None,
                },
                "raw_text": "",
            },
            "db_updates": {
                "existing_record_id": None,
                "correlation_id": "<content_sha256>",
                "content_sha256": "...",
                "processing_state": "processed",
                "processed": True,
                "failed_reason": None,
            },
        },
    },
    "cover_letter_agent": {
        "prompt": _text(
            """
            === Agent: cover_letter_agent ===
            Description: Structured cover-letter writer.
            Goal: Produce a tailored cover letter from structured job-posting and applicant-profile inputs.

            Rules:
            - Use only facts present in job_posting_result and profile_result.
            - If recipient or contact details are missing, use neutral wording.
            - Match requirements only when there is explicit evidence in the profile.
            - If a required skill is missing, do not invent it; record it in quality.red_flags.
            - Return JSON only.
            """
        ),
        "task": {
            "specialization": "cover_letter",
            "input_contract": {
                "required": ["job_posting_result", "profile_result", "options"],
                "option_fallback": "Use profile_result.profile.preferences when options values are missing.",
            },
            "writing_guidance": [
                "Use active, specific language.",
                "Respect options.language, options.tone, and options.max_words.",
                "Prefer evidence-backed statements over generic enthusiasm.",
                "Use neutral wording when structured input is incomplete.",
            ],
        },
        "output_schema": {
            "agent": "writer_agent",
            "correlation": {
                "job_posting_correlation_id": "...",
                "profile_correlation_id": "...",
                "correlation_id": "...",
            },
            "cover_letter": {
                "header": {
                    "sender": "<mehrzeilig oder leer>",
                    "recipient": "<mehrzeilig oder leer>",
                    "date": "<Ort, YYYY-MM-DD oder leer>",
                    "subject": "<Betreff>",
                },
                "salutation": "<Anrede>",
                "body": {
                    "opening": "...",
                    "main_paragraph_1": "...",
                    "main_paragraph_2": "...",
                    "main_paragraph_3": "...",
                    "closing": "...",
                },
                "signature": "<closing + name>",
                "enclosures": ["Lebenslauf", "Zeugnisse"],
                "full_text": "<full cover letter as continuous text>",
            },
            "quality": {
                "word_count": 0,
                "tone_used": "modern",
                "language": "de",
                "matched_requirements": [],
                "highlighted_skills": [],
                "red_flags": [],
            },
        },
    },
    "SubAgent_GenAI_Developer": {
        "prompt": _text(
            """
            === Agent: SubAgent_GenAI_Developer ===
            Description: Specialized engineering agent for code analysis, implementation, debugging, refactoring, and validation.
            Goal: Deliver precise, defensible, minimal-risk software changes and technical assessments.

            Rules:
            - Analyze code and runtime evidence before changing behavior.
            - Prefer the smallest correct change over broad refactors.
            - Distinguish observed facts, plausible causes, confirmed causes, and proposed fixes.
            - Do not claim verification without actual evidence.
            - Call out assumptions explicitly when context is incomplete.
            """
        ),
        "task": {
            "priorities": [
                "correctness",
                "determinism",
                "safety",
                "compatibility",
                "maintainability",
            ],
            "deliverables": [
                "root cause or strongest hypothesis",
                "concrete change or recommendation",
                "impact on existing behavior",
                "performed or missing verification",
            ],
        },
        "output_schema": {},
    },
}


_SPECIALIZED_AGENT_MAP: dict[tuple[str, str], str] = {
    ("parser", "applicant_profile"): "profile_parser",
    ("parser", "job_posting"): "job_posting_parser",
    ("writer", "cover_letter"): "cover_letter_agent",
}


_LEGACY_AGENT_NAME_MAP: dict[str, str] = {
    "_primary_assistant": "primary_assistant",
    "_agent_system_planner": "agent_system_planner",
    "_agent_system_worker": "agent_system_worker",
    "_parser_agent": "parser_agent",
    "_writer_agent": "writer_agent",
    "_data_dispatcher": "data_dispatcher",
    "_profile_parser": "profile_parser",
    "_job_posting_parser": "job_posting_parser",
    "_cover_letter_agent": "cover_letter_agent",
    "SubAgent_GenAI_Developer": "SubAgent_GenAI_Developer",
}


_CANONICAL_AGENT_LABEL_MAP: dict[str, str] = {
    "primary_assistant": "_primary_assistant",
    "agent_system_planner": "_agent_system_planner",
    "agent_system_worker": "_agent_system_worker",
    "parser_agent": "_parser_agent",
    "writer_agent": "_writer_agent",
    "data_dispatcher": "_data_dispatcher",
    "profile_parser": "_profile_parser",
    "job_posting_parser": "_job_posting_parser",
    "cover_letter_agent": "_cover_letter_agent",
    "SubAgent_GenAI_Developer": "SubAgent_GenAI_Developer",
}


AGENT_RUNTIME_CONFIG: dict[str, dict[str, Any]] = {
    "_primary_assistant": {
        "canonical_name": "primary_assistant",
        "model": "gpt-4o",
        "tools": ["memorydb", "route_to_agent", "@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "primary_assistant_router"},
    },
    "_agent_system_planner": {
        "canonical_name": "agent_system_planner",
        "model": "gpt-4o",
        "tools": ["route_to_agent"],
        "defaults": {},
        "workflow": {"definition": "agent_system_planner_router"},
    },
    "_agent_system_worker": {
        "canonical_name": "agent_system_worker",
        "model": "gpt-4o-mini",
        "tools": ["build_agent_system_configs", "@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "agent_system_builder_leaf"},
    },
    "_parser_agent": {
        "canonical_name": "parser_agent",
        "model": "gpt-4o-mini",
        "tools": ["@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "parser_agent_leaf"},
    },
    "_writer_agent": {
        "canonical_name": "writer_agent",
        "model": "gpt-4o",
        "tools": ["@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "writer_agent_leaf"},
    },
    "_data_dispatcher": {
        "canonical_name": "data_dispatcher",
        "model": "gpt-4o-mini",
        "tools": ["@dispatcher", "route_to_agent"],
        "defaults": {},
        "workflow": {"definition": "data_dispatcher_chain"},
    },
    "_profile_parser": {
        "canonical_name": "profile_parser",
        "model": "gpt-4o-mini",
        "tools": ["@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "profile_parser_leaf"},
    },
    "_job_posting_parser": {
        "canonical_name": "job_posting_parser",
        "model": "gpt-4o-mini",
        "tools": ["@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "job_posting_parser_leaf"},
    },
    "_cover_letter_agent": {
        "canonical_name": "cover_letter_agent",
        "model": "gpt-4o",
        "tools": ["@doc_rw"],
        "defaults": {},
        "workflow": {"definition": "cover_letter_writer_leaf"},
    },
    "SubAgent_GenAI_Developer": {
        "canonical_name": "SubAgent_GenAI_Developer",
        "model": "gpt-4o-mini",
        "tools": ["vectordb"],
        "defaults": {},
        "workflow": {},
    },
}


AGENT_ROLE_CONFIGS: dict[str, dict[str, Any]] = {
    "planner_router": {
        "description": "Interactive planning entry point that can route work to downstream agents.",
        "can_route": True,
        "default_instance_policy": "session_scoped",
        "default_tool_policy": "planner_router",
        "default_handoff_policy": {
            "default_protocol": "message_text",
            "accepted_protocols": ["message_text", "agent_handoff_v1"],
            "emitted_protocols": ["message_text", "agent_handoff_v1"],
            "allowed_targets": [],
            "allowed_sources": [],
            "target_policies": {},
            "source_policies": {},
        },
        "default_history_policy": {
            "followup_history_depth": 15,
            "include_routed_history": True,
            "routed_history_depth": 12,
        },
    },
    "worker": {
        "description": "Leaf or specialist worker agent for a focused unit of work.",
        "can_route": False,
        "default_instance_policy": "ephemeral",
        "default_tool_policy": "worker",
        "default_handoff_policy": {
            "default_protocol": "message_text",
            "accepted_protocols": ["message_text", "agent_handoff_v1"],
            "emitted_protocols": ["message_text", "agent_handoff_v1"],
            "allowed_targets": [],
            "allowed_sources": [],
            "target_policies": {},
            "source_policies": {},
        },
        "default_history_policy": {
            "followup_history_depth": 6,
            "include_routed_history": False,
            "routed_history_depth": 0,
        },
    },
    "workflow_service": {
        "description": "Deterministic workflow-oriented service agent with orchestrated state progression.",
        "can_route": False,
        "default_instance_policy": "workflow_scoped",
        "default_tool_policy": "workflow_service",
        "default_handoff_policy": {
            "default_protocol": "agent_handoff_v1",
            "accepted_protocols": ["message_text", "agent_handoff_v1"],
            "emitted_protocols": ["message_text", "agent_handoff_v1"],
            "allowed_targets": [],
            "allowed_sources": [],
            "target_policies": {},
            "source_policies": {},
        },
        "default_history_policy": {
            "followup_history_depth": 8,
            "include_routed_history": False,
            "routed_history_depth": 0,
        },
    },
}


ALLOWED_INSTANCE_POLICIES = {
    "ephemeral",
    "session_scoped",
    "workflow_scoped",
    "service_scoped",
}


HANDOFF_PROTOCOL_CONFIGS: dict[str, dict[str, Any]] = {
    "message_text": {
        "description": "Plain text handoff transported as the routed user message.",
        "transport": "user_message",
        "mode": "text",
    },
    "agent_handoff_v1": {
        "description": "Structured handoff envelope for agent-to-agent communication.",
        "transport": "user_message",
        "mode": "json_envelope",
        "required_payload_keys": ["agent_label", "handoff_to"],
        "content_keys": ["output", "generated", "msg"],
    },
}


HANDOFF_SCHEMA_CONFIGS: dict[str, dict[str, Any]] = {
    "primary_to_dispatcher_request": {
        "protocol": "message_text",
        "description": "Primary assistant request for the deterministic dispatcher workflow.",
        "required_message_text": True,
        "workflow_name": "data_dispatcher_chain",
        "instructions": [
            "Treat the routed user message as the dispatch request.",
            "Use dispatcher tools deterministically and do not invent filesystem or DB state.",
        ],
    },
    "primary_to_parser_brief": {
        "protocol": "agent_handoff_v1",
        "description": "Primary assistant brief for a parser-style worker.",
        "required_payload_any": ["output", "generated", "msg"],
        "preferred_payload_paths": ["output", "generated", "msg"],
        "workflow_name": "parser_agent_leaf",
        "instructions": [
            "Treat the handoff payload as the primary parse input.",
            "Keep extraction source-grounded and preserve schema stability.",
        ],
    },
    "primary_to_writer_brief": {
        "protocol": "agent_handoff_v1",
        "description": "Primary assistant brief for a writer-style worker.",
        "required_payload_any": ["output", "generated", "msg"],
        "preferred_payload_paths": ["output", "generated", "msg"],
        "workflow_name": "writer_agent_leaf",
        "instructions": [
            "Use the handoff payload as the writing brief.",
            "Do not add unsupported claims beyond the provided structured input.",
        ],
    },
    "primary_to_agent_system_planner": {
        "protocol": "agent_handoff_v1",
        "description": "Primary assistant brief for the interactive agent-system planner.",
        "required_payload_any": ["output", "generated", "msg"],
        "preferred_payload_paths": ["output", "generated", "msg"],
        "workflow_name": "agent_system_planner_router",
        "instructions": [
            "Treat the handoff payload as the planner brief for the requested agent system.",
            "Clarify missing system requirements interactively before delegating the build step.",
        ],
    },
    "agent_system_planner_to_builder": {
        "protocol": "agent_handoff_v1",
        "description": "Planner brief for the worker agent that materializes config bundles through the builder workflow.",
        "required_payload_any": ["output", "generated", "msg"],
        "preferred_payload_paths": ["output", "generated", "msg"],
        "workflow_name": "agent_system_builder_leaf",
        "instructions": [
            "Treat the handoff payload as the approved build brief.",
            "Use the build_agent_system_configs tool to produce the canonical config bundle.",
        ],
    },
    "primary_to_cover_letter_writer_brief": {
        "protocol": "agent_handoff_v1",
        "description": "Primary assistant brief for the specialized cover-letter writer with deterministic artifact persistence.",
        "required_payload_any": ["output", "generated", "msg"],
        "preferred_payload_paths": ["output", "generated", "msg"],
        "workflow_name": "cover_letter_writer_leaf",
        "result_postprocess": {
            "tool": "persist_cover_letter_artifacts",
            "text_writer_tool": "write_document",
            "pdf_writer_tool": "md_to_pdf",
            "default_write_pdf": True,
        },
        "instructions": [
            "Use the handoff payload as the writing brief.",
            "Do not add unsupported claims beyond the provided structured input.",
            "Return the structured cover-letter JSON so runtime persistence can write markdown and PDF artifacts.",
        ],
    },
    "dispatcher_to_job_posting_parser": {
        "protocol": "agent_handoff_v1",
        "description": "Dispatcher handoff for the job-posting parser workflow.",
        "required_payload_paths": [
            "output.type",
            "output.correlation_id",
            "output.link.thread_id",
            "output.file.path",
            "output.file.content_sha256",
            "output.db.processing_state",
            "output.requested_actions",
        ],
        "required_metadata_paths": ["correlation_id", "dispatcher_message_id", "dispatcher_db_path", "obj_name", "obj_db_path"],
        "preferred_payload_paths": ["output", "msg"],
        "target_input_path": "output",
        "workflow_name": "job_posting_parser_leaf",
        "result_postprocess": {
            "tool": "upsert_object_record",
            "source_agent": "target_agent",
        },
        "instructions": [
            "Treat output as the authoritative dispatch payload.",
            "Use metadata.correlation_id to preserve workflow linkage.",
        ],
    },
}


ACTION_REQUEST_SCHEMA_CONFIGS: dict[str, dict[str, Any]] = {
    "agent_system_builder_request": {
        "description": "Builder request for creating a basic planner/builder agent-system configuration bundle.",
        "actions": ["build_agent_system_configs", "create_agents_basic_config", "create_agent_system"],
        "required_paths": [
            "action",
            "system_name",
            "agent_specs",
            "workflow_specs",
            "integration_targets.assistant_agent_name",
            "integration_targets.route_prefix",
            "integration_targets.persisted_config_target",
            "planning_schema.required_steps",
            "planning_schema.required_sections",
            "planning_schema.required_agent_fields",
            "planning_schema.required_workflow_fields",
            "planning_schema.required_integration_fields",
        ],
        "recommended_paths": [
            "assistant_agent_name",
            "planner_agent_name",
            "worker_agent_name",
            "route_prefix",
        ],
    },
    "platform_job_posting_ingest_request": {
        "description": "Deterministic non-PDF ingest request for job postings from platforms, APIs, or pre-parsed sources.",
        "actions": ["ingest_object", "store_object_result"],
        "required_paths": ["action"],
        "conditions": {
            "all": [
                {"action": {"in": ["ingest_object", "store_object_result"]}},
                {
                    "any": [
                        {"job_posting_result": {"exists": True}},
                        {"job_posting": {"exists": True}},
                    ]
                },
            ]
        },
        "recommended_paths": ["correlation_id", "source_agent", "source_payload"],
        "request_resolution": {
            "objects": [
                {
                    "binding_name": "job_posting",
                    "request_field": "job_posting",
                    "result_field": "job_posting_result",
                    "default_obj_name": "job_postings",
                    "obj_name_config_key": "job_posting_obj_name",
                    "db_path_field_key": "job_posting_db_path_field",
                    "default_source": "text",
                }
            ],
        },
        "action_execution": {
            "handler_name": "ingest_object",
            "binding_name": "job_posting",
            "object_payload_field": "job_posting",
            "request_payload_field": "job_posting",
            "result_payload_field": "job_posting_result",
            "correlation_id_fields": ["correlation_id"],
            "db_path_fields": ["obj_db_path", "job_postings_db_path", "db_path"],
            "source_agent_fields": ["source_agent"],
            "source_payload_fields": ["source_payload"],
            "parse_fields": ["parse"],
            "default_request_source": "text",
        },
    },
    "dispatcher_job_record_upsert_request": {
        "description": "Deterministic combined request that updates both job_postings_db and dispatcher_doc_db for the same correlation id.",
        "actions": ["upsert_object_record"],
        "required_paths": ["action", "dispatcher_db_path", "obj_db_path"],
        "conditions": {
            "all": [
                {"action": {"in": ["upsert_object_record"]}},
                {
                    "any": [
                        {"job_posting_result": {"exists": True}},
                        {"job_posting": {"exists": True}},
                    ]
                },
            ]
        },
        "recommended_paths": ["correlation_id", "processing_state", "source_agent"],
        "request_resolution": {
            "objects": [
                {
                    "binding_name": "job_posting",
                    "request_field": "job_posting",
                    "result_field": "job_posting_result",
                    "default_obj_name": "job_postings",
                    "obj_name_config_key": "job_posting_obj_name",
                    "db_path_field_key": "job_posting_db_path_field",
                    "default_source": "text",
                }
            ],
        },
        "action_execution": {
            "handler_name": "upsert_object_record",
            "binding_name": "job_posting",
            "object_payload_field": "job_posting",
            "result_payload_field": "job_posting_result",
            "correlation_id_fields": ["correlation_id"],
            "dispatcher_db_path_fields": ["dispatcher_db_path"],
            "obj_db_path_fields": ["obj_db_path", "job_postings_db_path", "db_path"],
            "processing_state_fields": ["processing_state"],
            "processed_fields": ["processed"],
            "failed_reason_fields": ["failed_reason"],
            "source_agent_fields": ["source_agent"],
            "source_payload_fields": ["source_payload"],
            "dispatcher_updates_fields": ["dispatcher_updates"],
        },
    },
    "platform_profile_ingest_request": {
        "description": "Deterministic ingest request for applicant profiles from platforms, APIs, or pre-parsed sources.",
        "actions": ["ingest_object", "store_object_result"],
        "required_paths": ["action"],
        "conditions": {
            "all": [
                {"action": {"in": ["ingest_object", "store_object_result"]}},
                {
                    "any": [
                        {"profile_result": {"exists": True}},
                        {"applicant_profile": {"exists": True}},
                        {"profile": {"exists": True}},
                    ]
                },
            ]
        },
        "recommended_paths": ["correlation_id", "source_agent"],
        "request_resolution": {
            "objects": [
                {
                    "binding_name": "profile",
                    "request_field": "applicant_profile",
                    "result_field": "profile_result",
                    "default_obj_name": "profiles",
                    "obj_name_config_key": "profile_obj_name",
                    "db_path_field_key": "profile_db_path_field",
                    "default_source": "text",
                }
            ],
        },
        "action_execution": {
            "handler_name": "ingest_object",
            "binding_name": "profile",
            "object_payload_field": "profile",
            "request_payload_field": "applicant_profile",
            "result_payload_field": "profile_result",
            "correlation_id_fields": ["correlation_id"],
            "db_path_fields": ["obj_db_path", "profiles_db_path", "db_path"],
            "source_agent_fields": ["source_agent"],
            "source_payload_fields": ["source_payload"],
            "default_request_source": "text",
        },
    },
    "cover_letter_generation_request": {
        "description": "Cover-letter generation request that either routes directly to the writer when all structured inputs are ready or to the dispatcher when preparation/batch generation is still required.",
        "actions": ["generate_cover_letter"],
        "required_paths": ["action", "applicant_profile"],
        "conditions": {
            "all": [
                {"action": {"in": ["generate_cover_letter"]}},
                {
                    "any": [
                        {"job_posting_result": {"exists": True}},
                        {"job_posting": {"exists": True}},
                    ]
                },
            ]
        },
        "recommended_paths": ["options.language", "options.tone", "options.max_words"],
        "request_resolution": {
            "objects": [
                {
                    "binding_name": "profile",
                    "request_field": "applicant_profile",
                    "result_field": "profile_result",
                    "default_obj_name": "profiles",
                    "obj_name_config_key": "profile_obj_name",
                    "db_path_field_key": "profile_db_path_field",
                    "default_source": "text",
                    "store_sources": ["profile_id", "profiles_db", "stored_profile", "persisted_profile"],
                    "file_sources": ["file", "path", "json_file", "structured_file", "document_file"],
                    "inline_sources": ["text", "json", "dict", "object", "structured", "inline"],
                },
                {
                    "binding_name": "job_posting",
                    "request_field": "job_posting",
                    "result_field": "job_posting_result",
                    "default_obj_name": "job_postings",
                    "obj_name_config_key": "job_posting_obj_name",
                    "db_path_field_key": "job_posting_db_path_field",
                    "default_source": "text",
                    "store_sources": ["correlation_id", "job_postings_db", "stored_job_posting", "persisted_job_posting"],
                    "drop_request_field_when_resolved": True,
                    "drop_db_path_field_when_resolved": True,
                }
            ],
            "default_fields": [
                {
                    "field": "batch_tool_name",
                    "config_key": "batch_tool_name",
                    "normalize": "tool_name",
                },
                {
                    "field": "batch_workflow_name",
                    "config_key": "batch_workflow_name",
                }
            ],
            "dispatcher_route_target": "_data_dispatcher",
            "ready_route_target": "_cover_letter_agent",
            "batch_tool_name": "batch_generate_documents",
            "batch_workflow_name": "cover_letter_batch_generation",
        },
    },
}


PROMPT_FRAGMENT_CONFIGS: dict[str, dict[str, Any]] = {
    "source_grounding": {
        "text": "Use only source-grounded facts. State uncertainty explicitly instead of inventing details.",
    },
    "json_output": {
        "text": "Return machine-readable JSON only when the task contract requires structured output.",
    },
    "router_handoff": {
        "text": "Delegate only when specialization or deterministic workflow handling is required.",
    },
    "deterministic_workflow": {
        "text": "Follow declared workflow/state transitions deterministically instead of improvising orchestration.",
    },
}


AGENT_SKILL_PROFILES: dict[str, dict[str, Any]] = {
    "conversation_router": {
        "role": "planner_router",
        "prompt_fragments": ["source_grounding", "router_handoff"],
        "description": "Interactive planning and routing skill profile for the primary assistant.",
    },
    "structured_parser": {
        "role": "worker",
        "prompt_fragments": ["source_grounding", "json_output"],
        "description": "Structured extraction skill profile for parser-style worker agents.",
    },
    "structured_writer": {
        "role": "worker",
        "prompt_fragments": ["source_grounding", "json_output"],
        "description": "Structured generation skill profile for writer-style worker agents.",
    },
    "workflow_dispatch": {
        "role": "workflow_service",
        "prompt_fragments": ["source_grounding", "deterministic_workflow"],
        "description": "Deterministic workflow service profile for dispatcher-style orchestration.",
    },
    "code_analysis": {
        "role": "worker",
        "prompt_fragments": ["source_grounding"],
        "description": "Focused engineering analysis and implementation profile.",
    },
}


AGENT_MANIFEST_OVERRIDES: dict[str, dict[str, Any]] = {
    "_primary_assistant": {
        "role": "planner_router",
        "skill_profile": "conversation_router",
        "instance_policy": "session_scoped",
        "routing_policy": {"mode": "planner_router", "can_route": True},
        "handoff_policy": {
            "allowed_targets": ["_data_dispatcher", "_parser_agent", "_writer_agent", "_cover_letter_agent", "_agent_system_planner"],
            "target_policies": {
                "_data_dispatcher": {
                    "default_protocol": "message_text",
                    "accepted_protocols": ["message_text"],
                    "handoff_schema": "primary_to_dispatcher_request",
                },
                "_parser_agent": {
                    "default_protocol": "agent_handoff_v1",
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_parser_brief",
                },
                "_writer_agent": {
                    "default_protocol": "agent_handoff_v1",
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_writer_brief",
                },
                "_agent_system_planner": {
                    "default_protocol": "agent_handoff_v1",
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_agent_system_planner",
                },
                "_cover_letter_agent": {
                    "default_protocol": "agent_handoff_v1",
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_cover_letter_writer_brief",
                },
            },
        },
    },
    "_agent_system_planner": {
        "role": "planner_router",
        "skill_profile": "conversation_router",
        "instance_policy": "session_scoped",
        "routing_policy": {"mode": "planner_router", "can_route": True},
        "handoff_policy": {
            "allowed_sources": ["_primary_assistant"],
            "allowed_targets": ["_agent_system_worker"],
            "source_policies": {
                "_primary_assistant": {
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_agent_system_planner",
                },
            },
            "target_policies": {
                "_agent_system_worker": {
                    "default_protocol": "agent_handoff_v1",
                    "accepted_protocols": ["agent_handoff_v1"],
                    "handoff_schema": "agent_system_planner_to_builder",
                },
            },
        },
    },
    "_agent_system_worker": {
        "role": "worker",
        "skill_profile": "structured_writer",
        "handoff_policy": {
            "allowed_sources": ["_agent_system_planner"],
            "source_policies": {
                "_agent_system_planner": {
                    "accepted_protocols": ["agent_handoff_v1"],
                    "handoff_schema": "agent_system_planner_to_builder",
                },
            },
        },
    },
    "_parser_agent": {
        "role": "worker",
        "skill_profile": "structured_parser",
        "handoff_policy": {
            "allowed_sources": ["_primary_assistant"],
            "source_policies": {
                "_primary_assistant": {
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_parser_brief",
                },
            },
        },
    },
    "_writer_agent": {
        "role": "worker",
        "skill_profile": "structured_writer",
        "handoff_policy": {
            "allowed_sources": ["_primary_assistant"],
            "source_policies": {
                "_primary_assistant": {
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_writer_brief",
                },
            },
        },
    },
    "_data_dispatcher": {
        "role": "workflow_service",
        "skill_profile": "workflow_dispatch",
        "instance_policy": "workflow_scoped",
        "routing_policy": {"mode": "workflow_service", "can_route": True},
        "handoff_policy": {
            "allowed_sources": ["_primary_assistant"],
            "allowed_targets": ["_job_posting_parser"],
            "source_policies": {
                "_primary_assistant": {
                    "accepted_protocols": ["message_text"],
                    "handoff_schema": "primary_to_dispatcher_request",
                },
            },
            "target_policies": {
                "_job_posting_parser": {
                    "default_protocol": "agent_handoff_v1",
                    "accepted_protocols": ["agent_handoff_v1"],
                    "handoff_schema": "dispatcher_to_job_posting_parser",
                },
            },
        },
    },
    "_profile_parser": {
        "role": "worker",
        "skill_profile": "structured_parser",
    },
    "_job_posting_parser": {
        "role": "worker",
        "skill_profile": "structured_parser",
        "handoff_policy": {
            "allowed_sources": ["_primary_assistant", "_data_dispatcher"],
            "source_policies": {
                "_primary_assistant": {
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_parser_brief",
                },
                "_data_dispatcher": {
                    "accepted_protocols": ["agent_handoff_v1"],
                    "handoff_schema": "dispatcher_to_job_posting_parser",
                },
            },
        },
    },
    "_cover_letter_agent": {
        "role": "worker",
        "skill_profile": "structured_writer",
        "handoff_policy": {
            "allowed_sources": ["_primary_assistant"],
            "source_policies": {
                "_primary_assistant": {
                    "accepted_protocols": ["message_text", "agent_handoff_v1"],
                    "handoff_schema": "primary_to_cover_letter_writer_brief",
                },
            },
        },
    },
    "SubAgent_GenAI_Developer": {
        "role": "worker",
        "skill_profile": "code_analysis",
    },
}


TOOL_CONFIGS: list[dict[str, Any]] = [
    {
        "name": "memorydb",
        "description": "Query the memory vector database (code snippets / notes).",
        "parameters": [
            {"name": "query", "type": "string", "description": "Free-text query or identifier.", "required": True},
            {"name": "k", "type": "integer", "description": "Number of results.", "default": 3},
            {
                "name": "store_dir",
                "type": "string",
                "description": "Vector-store directory OR store id/name under AppData. Examples: '/abs/path/VSM_3_Data', './AppData/VSM_3_Data', '3', 'VSM_3_Data'.",
            },
            {"name": "manifest_file", "type": "string", "description": "Optional manifest.json path (default: <store_dir>/manifest.json)."},
            {"name": "root_dir", "type": "string", "description": "Root directory to index when autobuild is enabled."},
            {"name": "autobuild", "type": "boolean", "description": "Override AI_IDE_VSTORE_AUTOBUILD for this call.", "default": None},
            {"name": "chunk_strategy", "type": "string", "description": "Optional chunking strategy for autobuild: recursive|character|markdown."},
            {"name": "chunk_size", "type": "integer", "description": "Optional chunk size for autobuild."},
            {"name": "overlap", "type": "integer", "description": "Optional chunk overlap for autobuild."},
        ],
    },
    {
        "name": "vectordb",
        "description": "Query the vector databases.",
        "parameters": [
            {"name": "query", "type": "string", "description": "Free-text query or filename.", "required": True},
            {"name": "k", "type": "integer", "description": "Number of results.", "default": 3},
            {
                "name": "store_dir",
                "type": "string",
                "description": "Vector-store directory OR store id/name under AppData. Examples: '/abs/path/VSM_1_Data', './AppData/VSM_1_Data', '1', 'VSM_1_Data'.",
            },
            {"name": "manifest_file", "type": "string", "description": "Optional manifest.json path (default: <store_dir>/manifest.json)."},
            {"name": "root_dir", "type": "string", "description": "Root directory to index when autobuild is enabled."},
            {"name": "autobuild", "type": "boolean", "description": "Override AI_IDE_VSTORE_AUTOBUILD for this call.", "default": None},
            {"name": "chunk_strategy", "type": "string", "description": "Optional chunking strategy for autobuild: recursive|character|markdown."},
            {"name": "chunk_size", "type": "integer", "description": "Optional chunk size for autobuild."},
            {"name": "overlap", "type": "integer", "description": "Optional chunk overlap for autobuild."},
        ],
    },
    {
        "name": "vdb_worker",
        "description": "Create/list/build/wipe vector store directories under AppData (runs in a subprocess).",
        "parameters": [
            {"name": "operation", "type": "string", "description": "Operation to run: list|create|status|build|wipe.", "required": True, "enum": ["list", "create", "status", "build", "wipe"]},
            {"name": "store", "type": "string", "description": "Store id/name. Examples: '1' => VSM_1_Data, 'my_store' => VSM_my_store_Data. Empty => auto-next."},
            {"name": "root_dir", "type": "string", "description": "Root directory to index (only used for build). Default: project root."},
            {"name": "doc_types", "type": "array", "description": "Optional suffix filter for build operations, e.g. ['.txt', '.md']. When provided, only matching files are indexed.", "items": {"type": "string"}},
            {"name": "chunk_strategy", "type": "string", "description": "Optional chunking strategy for build operations: recursive|character|markdown."},
            {"name": "chunk_size", "type": "integer", "description": "Optional chunk size for build operations."},
            {"name": "overlap", "type": "integer", "description": "Optional chunk overlap for build operations."},
            {"name": "force", "type": "boolean", "description": "Required for wipe operations.", "default": False},
            {"name": "remove_store_dir", "type": "boolean", "description": "If true and operation=wipe: delete the whole store directory. Otherwise remove only index+manifest files.", "default": False},
        ],
    },
    {
        "name": "write_document",
        "description": "Persist the generated document to disk.",
        "parameters": [
            {"name": "content", "type": "string", "description": "text to write to disk.", "required": True},
            {"name": "path", "type": "string", "description": "Directory to store the file.", "default_ref": "default_save_dir"},
            {"name": "titel", "type": "string", "description": "Optional file title for filename prefix."},
        ],
    },
    {
        "name": "read_document",
        "description": "Read the content of a document from disk.",
        "parameters": [
            {"name": "file_path", "type": "string", "description": "The absolute path to the file to read.", "required": True},
        ],
    },
    {
        "name": "update_document",
        "description": "Update a document's metadata.",
        "parameters": [
            {"name": "data", "type": "array", "description": "List of documents to search through.", "required": True, "items": {"type": "object"}},
            {"name": "item", "type": "string", "description": "The metadata field name to match and update.", "required": True},
            {"name": "updatestr", "type": "string", "description": "The new value to set for the matched field.", "required": True},
        ],
    },
    {
        "name": "delete_document",
        "description": "Delete a document from disk.",
        "parameters": [
            {"name": "file_path", "type": "string", "description": "The absolute path to the file to delete.", "required": True},
        ],
    },
    {
        "name": "list_documents",
        "description": "List all documents in a directory.",
        "parameters": [
            {"name": "directory", "type": "string", "description": "Directory path to list.", "default_ref": "default_save_dir"},
        ],
    },
    {
        "name": "md_to_pdf",
        "description": "Convert a Markdown file to a clean PDF (ReportLab).",
        "parameters": [
            {"name": "md_path", "type": "string", "description": "Path to the input Markdown file.", "required": True},
            {"name": "pdf_path", "type": "string", "description": "Path to the output PDF file.", "required": True},
            {"name": "title", "type": "string", "description": "Optional PDF title."},
            {"name": "author", "type": "string", "description": "Optional PDF author."},
            {"name": "pagesize", "type": "string", "description": "Page size.", "enum": ["A4", "LETTER"], "default": "A4"},
            {"name": "margin_left_mm", "type": "number", "description": "Left margin in mm.", "default": 18},
            {"name": "margin_right_mm", "type": "number", "description": "Right margin in mm.", "default": 18},
            {"name": "margin_top_mm", "type": "number", "description": "Top margin in mm.", "default": 16},
            {"name": "margin_bottom_mm", "type": "number", "description": "Bottom margin in mm.", "default": 16},
        ],
    },
    {
        "name": "calendar",
        "description": "Schedule an event in the calendar.",
        "parameters": [
            {"name": "event", "type": "string", "description": "Name or description of the event.", "required": True},
            {"name": "date", "type": "string", "description": "Date of the event (e.g., '2025-12-01').", "required": True},
            {"name": "time", "type": "string", "description": "Time of the event (e.g., '14:00').", "required": True},
        ],
    },
    {
        "name": "send_mail",
        "description": "Send an email to a recipient.",
        "parameters": [
            {"name": "recipient", "type": "string", "description": "Email address of the recipient.", "required": True},
            {"name": "subject", "type": "string", "description": "Subject line of the email.", "required": True},
            {"name": "body", "type": "string", "description": "Body content of the email.", "required": True},
        ],
    },
    {
        "name": "dml_tool",
        "description": "Data Manipulation Language tool.",
        "parameters": [
            {"name": "operation", "type": "string", "description": "The operation to perform.", "required": True},
            {"name": "data", "type": "string", "description": "The data to operate on.", "required": True},
        ],
    },
    {
        "name": "dsl_tool",
        "description": "Data Scripting Language tool for scripting operations.",
        "parameters": [
            {"name": "operation", "type": "string", "description": "The operation to perform.", "required": True},
            {"name": "data", "type": "string", "description": "The data to operate on.", "required": True},
        ],
    },
    {
        "name": "code_tool",
        "description": "Code Manipulation Language tool for code operations.",
        "parameters": [
            {"name": "operation", "type": "string", "description": "The code operation to perform.", "required": True},
            {"name": "data", "type": "string", "description": "The code or data to operate on.", "required": True},
        ],
    },
    {
        "name": "iter_documents",
        "description": "Load supported documents from one or more files or directories with optional type, pattern, and recursion filters.",
        "parameters": [
            {"name": "root", "type": "string", "description": "Single absolute or relative path to scan.", "required": False},
            {"name": "roots", "type": "array", "description": "Optional list of absolute or relative paths to scan.", "items": {"type": "string"}},
            {"name": "doc_types", "type": "array", "description": "Optional file extensions or aliases to include, e.g. ['.md', 'pdf', 'py'].", "items": {"type": "string"}},
            {"name": "patterns", "type": "array", "description": "Optional glob-style path filters, e.g. ['**/*.md', 'docs/**/*.txt'].", "items": {"type": "string"}},
            {"name": "recursive", "type": "boolean", "description": "Recurse into subdirectories.", "required": False, "default": True},
            {"name": "max_depth", "type": "integer", "description": "Optional maximum directory depth relative to each root. 0 means only the root directory.", "required": False},
        ],
    },
    {
        "name": "dispatch_documents",
        "description": "Discover documents in a directory, fingerprint them (SHA-256), check/update a small DB, and prepare handoff payloads for a parser agent.",
        "implementation_name": "dispatch_docs",
        "dispatch_policy": {
            "obj_name": "job_postings",
            "obj_db_path_field": "obj_db_path",
            "document_type": "file",
            "requested_actions": ["parse", "extract_text", "store_object_result", "mark_processed_on_success"],
            "default_target_agent": "_job_posting_parser",
            "source_agent": "_data_dispatcher",
            "handoff_protocol": "agent_handoff_v1",
            "metadata_defaults": {
                "obj_db_path": {
                    "resolver": "default_document_db_path",
                    "obj_name": "job_postings"
                }
            },
        },
        "parameters": [
            {"name": "scan_dir", "type": "string", "description": "Directory to scan for documents.", "required": True},
            {"name": "db", "type": "object", "description": "Optional DB adapter/config. Supported: { 'path': '/abs/path/to/db.json' }", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional DB JSON path (file-based DB). Overrides db.path.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name used to derive object-specific DB metadata and handoff fields, e.g. 'job_postings'.", "required": False, "default": "job_postings"},
            {"name": "thread_id", "type": "string", "description": "Thread id for link.thread_id (or UNKNOWN).", "required": False},
            {"name": "dispatcher_message_id", "type": "string", "description": "Dispatcher message id for reporting (or UNKNOWN).", "required": False},
            {"name": "recursive", "type": "boolean", "description": "Recurse into subdirectories.", "required": False, "default": True},
            {"name": "extensions", "type": "array", "description": "File extensions to include (default: ['.pdf', '.PDF']).", "required": False, "items": {"type": "string"}},
            {"name": "max_files", "type": "integer", "description": "Optional max number of PDFs to scan.", "required": False},
            {"name": "parser_agent_name", "type": "string", "description": "Target agent name for handoff messages.", "required": False, "default": "_job_posting_parser"},
            {"name": "dry_run", "type": "boolean", "description": "If true: do not update DB and do not create handoff messages.", "required": False, "default": False},
        ],
    },
    {
        "name": "execute_action_request",
        "description": "Execute a deterministic action request via the action layer, e.g. ingest_object, store_object_result, or upsert_object_record, so workflow agents can update stores explicitly through a single tool entry point.",
        "snapshot_view": {
            "kind": "dispatcher_action",
            "title": "Dispatcher action executed",
            "summary_fields": ["action", "correlation_id"],
        },
        "parameters": [
            {"name": "action_request", "type": "object", "description": "Full action request object including action and payload fields.", "required": False},
            {"name": "action", "type": "string", "description": "Optional action name used with payload, e.g. ingest_object, store_object_result, or upsert_object_record.", "required": False},
            {"name": "payload", "type": "object", "description": "Optional payload object merged with action when action_request is not supplied.", "required": False},
        ],
    },
    {
        "name": "upsert_object_record",
        "description": "Atomically update an object store and the dispatcher DB for the same logical record, with rollback if the second write fails.",
        "snapshot_view": {
            "kind": "dispatcher_action",
            "title": "Dispatcher object record upserted",
            "summary_fields": ["action", "correlation_id"],
        },
        "parameters": [
            {"name": "object_result", "type": "object", "description": "Normalized or parser-style object result payload to persist.", "required": True},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id for both stores.", "required": False},
            {"name": "dispatcher_db_path", "type": "string", "description": "Path to dispatcher_doc_db.json.", "required": False},
            {"name": "obj_db_path", "type": "string", "description": "Path to the target object DB file.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to upsert in the object DB.", "required": False, "default": "documents"},
            {"name": "processing_state", "type": "string", "description": "Optional dispatcher processing state override.", "required": False},
            {"name": "processed", "type": "boolean", "description": "Optional processed flag override.", "required": False},
            {"name": "failed_reason", "type": "string", "description": "Optional dispatcher failure reason.", "required": False},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope for traceability.", "required": False},
            {"name": "dispatcher_updates", "type": "object", "description": "Optional extra dispatcher record fields to upsert.", "required": False},
        ],
    },
    {
        "name": "upsert_dispatcher_job_record",
        "description": "Atomically update the job postings store and dispatcher DB for the same job record, with rollback if the second write fails.",
        "implementation_name": "upsert_object_record",
        "snapshot_view": {
            "kind": "dispatcher_action",
            "title": "Dispatcher job record upserted",
            "summary_fields": ["action", "correlation_id"],
        },
        "parameters": [
            {"name": "job_posting_result", "type": "object", "description": "Parser-style or normalized job posting result payload to persist.", "required": True},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id for both stores.", "required": False},
            {"name": "dispatcher_db_path", "type": "string", "description": "Path to dispatcher_doc_db.json.", "required": False},
            {"name": "job_postings_db_path", "type": "string", "description": "Path to job_postings_db.json.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to upsert in the document DB. Defaults to 'job_postings'.", "required": False, "default": "job_postings"},
            {"name": "processing_state", "type": "string", "description": "Optional dispatcher processing state override.", "required": False},
            {"name": "processed", "type": "boolean", "description": "Optional processed flag override.", "required": False},
            {"name": "failed_reason", "type": "string", "description": "Optional dispatcher failure reason.", "required": False},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope for traceability.", "required": False},
            {"name": "dispatcher_updates", "type": "object", "description": "Optional extra dispatcher record fields to upsert.", "required": False},
        ],
    },
    {
        "name": "store_object_result",
        "description": "Persist a normalized or parser-style object result directly into the selected object store.",
        "parameters": [
            {"name": "object_result", "type": "object", "description": "Object result payload to store.", "required": True},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id.", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional path to the target object DB file.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to persist into.", "required": False, "default": "documents"},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope or original payload for traceability.", "required": False},
        ],
    },
    {
        "name": "store_job_posting_result",
        "description": "Persist a parsed job-posting result directly into the job postings store, independent of the PDF dispatcher workflow.",
        "implementation_name": "store_object_result",
        "parameters": [
            {"name": "job_posting_result", "type": "object", "description": "Parsed job-posting result payload to store.", "required": True},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id. Falls back to job_posting_result.correlation_id or file.content_sha256.", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional path to job_postings_db.json.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to persist into. Defaults to 'job_postings'.", "required": False, "default": "job_postings"},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label, e.g. job_platform_ingest.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope or original platform payload for traceability.", "required": False},
        ],
    },
    {
        "name": "store_profile_result",
        "description": "Persist a parsed applicant-profile result directly into the profiles store.",
        "implementation_name": "store_object_result",
        "parameters": [
            {"name": "profile_result", "type": "object", "description": "Parsed profile result payload to store.", "required": True},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id. Falls back to profile_result.correlation_id or profile.profile_id.", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional path to profiles_db.json.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to persist into. Defaults to 'profiles'.", "required": False, "default": "profiles"},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label, e.g. profile_platform_ingest.", "required": False},
        ],
    },
    {
        "name": "ingest_object",
        "description": "Ingest a normalized object payload or a parser-style object result directly into the selected object store.",
        "parameters": [
            {"name": "object_payload", "type": "object", "description": "Normalized object payload to persist when no parser-style result object is supplied.", "required": False},
            {"name": "request_payload", "type": "object", "description": "Optional request-style envelope using source/value fields.", "required": False},
            {"name": "object_result", "type": "object", "description": "Optional parser-style object result payload to persist directly.", "required": False},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id.", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional path to the target object DB file.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to persist into.", "required": False, "default": "documents"},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope or original payload for traceability.", "required": False},
            {"name": "parse", "type": "object", "description": "Optional parse metadata used when only object_payload is supplied.", "required": False},
        ],
    },
    {
        "name": "ingest_profile",
        "description": "Ingest an applicant profile from a platform/API payload or a parser-style result directly into the profiles store.",
        "implementation_name": "ingest_object",
        "parameters": [
            {"name": "profile", "type": "object", "description": "Normalized profile payload to persist when no parser-style result object is supplied.", "required": False},
            {"name": "applicant_profile", "type": "object", "description": "Optional request-style applicant_profile envelope using source/value fields.", "required": False},
            {"name": "profile_result", "type": "object", "description": "Optional parser-style profile result payload to persist directly.", "required": False},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id. Falls back to profile_result.correlation_id or profile.profile_id.", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional path to profiles_db.json.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to persist into. Defaults to 'profiles'.", "required": False, "default": "profiles"},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label, e.g. profile_platform_ingest.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope or original platform payload for traceability.", "required": False},
        ],
    },
    {
        "name": "ingest_job_posting",
        "description": "Ingest a platform/API job-posting payload directly into the job postings store, with or without an existing parser-style result envelope.",
        "implementation_name": "ingest_object",
        "parameters": [
            {"name": "job_posting", "type": "object", "description": "Normalized job posting payload to persist when no parser-style result object is supplied.", "required": False},
            {"name": "job_posting_result", "type": "object", "description": "Optional parser-style job-posting result payload to persist directly.", "required": False},
            {"name": "correlation_id", "type": "string", "description": "Optional explicit correlation id. Falls back to payload ids or source metadata.", "required": False},
            {"name": "db_path", "type": "string", "description": "Optional path to job_postings_db.json.", "required": False},
            {"name": "obj_name", "type": "string", "description": "Logical object/store name to persist into. Defaults to 'job_postings'.", "required": False, "default": "job_postings"},
            {"name": "source_agent", "type": "string", "description": "Optional logical source label, e.g. job_platform_ingest.", "required": False},
            {"name": "source_payload", "type": "object", "description": "Optional source envelope or original platform payload for traceability.", "required": False},
            {"name": "parse", "type": "object", "description": "Optional parse metadata used when only job_posting is supplied.", "required": False},
        ],
    },
    {
        "name": "batch_generate_documents",
        "description": "Generate documents for all discovered inputs in scan_dir using a declarative batch workflow from agents_config plus profile/context inputs and dispatcher DB; writes outputs to out_dir.",
        "implementation_name": "batch_document_generator",
        "parameters": [
            {"name": "scan_dir", "type": "string", "description": "Directory to scan for documents.", "required": True},
            {"name": "profile_path", "type": "string", "description": "Path to applicant_profile.json.", "required": True},
            {"name": "db_path", "type": "string", "description": "Path to dispatcher_doc_db.json.", "required": True},
            {"name": "out_dir", "type": "string", "description": "Output directory for generated cover letters (default: scan_dir/Cover_letters).", "required": False},
            {"name": "workflow_name", "type": "string", "description": "Batch workflow definition in agents_config (default: cover_letter_batch_generation).", "required": False, "default": "cover_letter_batch_generation"},
            {"name": "model", "type": "string", "description": "OpenAI model id.", "required": False, "default": "gpt-4o-mini"},
            {"name": "max_files", "type": "integer", "description": "Optional max number of PDFs to process.", "required": False},
            {"name": "max_text_chars", "type": "integer", "description": "Max extracted text chars per PDF to send to the model.", "required": False, "default": 20000},
            {"name": "dry_run", "type": "boolean", "description": "If true: do not call the model and do not write files.", "required": False, "default": False},
            {"name": "write_pdf", "type": "boolean", "description": "If true: also write each cover letter as a PDF (requires reportlab).", "required": False, "default": True},
            {"name": "rerun_processed", "type": "boolean", "description": "If true: also regenerate cover letters for PDFs already marked processed in the dispatcher DB.", "required": False, "default": False},
        ],
    },
    {
        "name": "build_agent_system_configs",
        "description": "Generate a basic planner/builder agent-system configuration bundle that can be persisted as agent/workflow config data.",
        "parameters": [
            {"name": "system_name", "type": "string", "description": "Logical system name used as the base for planner/builder config names.", "required": True},
            {"name": "action_request", "type": "object", "description": "Optional structured overrides for agent names, workflows, route prefix, models, and integration targets.", "required": False},
            {"name": "persist_path", "type": "string", "description": "Optional output path for writing the generated persisted config module.", "required": False},
            {"name": "write_file", "type": "boolean", "description": "If true, write the generated persisted config module to disk.", "required": False, "default": False},
        ],
    },
    {
        "name": "fetch_url",
        "description": "Fetch content from a URL.",
        "parameters": [
            {"name": "url", "type": "string", "description": "The URL to fetch content from.", "required": True},
        ],
    },
    {
        "name": "fetch_data",
        "description": "Fetch data from a specified source.",
        "parameters": [
            {"name": "source", "type": "string", "description": "The data source to fetch from.", "required": True},
            {"name": "query", "type": "string", "description": "The query to execute on the source.", "required": True},
        ],
    },
    {
        "name": "call_api",
        "description": "Call an external API endpoint.",
        "parameters": [
            {"name": "endpoint", "type": "string", "description": "The API endpoint URL.", "required": True},
            {"name": "method", "type": "string", "description": "HTTP method to use.", "enum": ["GET", "POST"], "default": "GET"},
            {"name": "payload", "type": "string", "description": "JSON payload for POST requests."},
        ],
    },
    {
        "name": "call",
        "description": "Initiate a phone call.",
        "parameters": [
            {"name": "phone_number", "type": "string", "description": "The phone number to call.", "required": True},
            {"name": "message", "type": "string", "description": "Optional message to deliver."},
        ],
    },
    {
        "name": "accept_call",
        "description": "Accept an incoming call.",
        "parameters": [
            {"name": "call_id", "type": "string", "description": "The ID of the call to accept.", "required": True},
        ],
    },
    {
        "name": "reject_call",
        "description": "Reject an incoming call.",
        "parameters": [
            {"name": "call_id", "type": "string", "description": "The ID of the call to reject.", "required": True},
            {"name": "reason", "type": "string", "description": "Optional reason for rejecting the call."},
        ],
    },
    {
        "name": "route_to_agent",
        "description": "Route the request to a specialized agent.",
        "implementation_name": None,
        "parameters": [
            {"name": "target_agent", "type": "string", "description": "The target agent to route to. Optional when handoff_payload.handoff_to or agent_response.handoff_to is provided.", "required": False, "enum_ref": "agent_labels"},
            {"name": "message_text", "type": "string", "description": "Plain-text handoff message to pass to the agent.", "required": False},
            {"name": "user_question", "type": "string", "description": "Legacy alias for message_text.", "required": False},
            {"name": "handoff_protocol", "type": "string", "description": "Optional handoff protocol. Supported: message_text, agent_handoff_v1.", "required": False},
            {"name": "agent_response", "type": "object", "description": "Structured response object to normalize into a handoff envelope. Example: {agent_label, output|generated|msg, handoff_to}.", "required": False},
            {"name": "handoff_payload", "type": "object", "description": "Structured payload for handoff protocols.", "required": False},
            {"name": "handoff_metadata", "type": "object", "description": "Optional metadata attached to the handoff envelope.", "required": False},
        ],
    },
]


TOOL_NAME_ALIASES: dict[str, str] = {
    "dispatch_docs": "dispatch_documents",
    "dispatch_documents": "dispatch_documents",
    "dispatch_job_posting_pdfs": "dispatch_documents",
    "ingest_object": "ingest_object",
    "ingest_profile": "ingest_profile",
    "ingest_job_posting": "ingest_job_posting",
    "ingest_document": "ingest_object",
    "persist_cover_letter_artifacts": "persist_document_artifacts",
    "persist_document_artifacts": "persist_document_artifacts",
    "store_object_result": "store_object_result",
    "store_document_result": "store_object_result",
    "upsert_object_record": "upsert_object_record",
    "upsert_job_record": "upsert_dispatcher_job_record",
    "batch_document_generator": "batch_generate_documents",
    "batch_generate_documents": "batch_generate_documents",
    "batch_generate_cover_letters": "batch_generate_documents",
    "store_profile": "store_profile_result",
    "persist_profile": "store_profile_result",
}


ACTION_REQUEST_NAME_ALIASES: dict[str, str] = {
    "ingest_object": "ingest_object",
    "store_object_result": "store_object_result",
    "upsert_object_record": "upsert_object_record",
    "ingest_job_posting": "ingest_object",
    "store_job_posting": "store_object_result",
    "store_job_posting_result": "store_object_result",
    "ingest_profile": "ingest_object",
    "store_profile": "store_object_result",
    "store_profile_result": "store_object_result",
    "persist_profile": "store_object_result",
    "upsert_dispatcher_job_record": "upsert_object_record",
    "upsert_job_record": "upsert_object_record",
}


TOOL_GROUP_CONFIGS: dict[str, list[str]] = {
    "rag": ["memorydb", "vectordb"],
    "docs_rw": [
        "read_document",
        "write_document",
        "update_document",
        "delete_document",
        "list_documents",
        "md_to_pdf",
    ],
    "doc_rw": [
        "read_document",
        "write_document",
        "update_document",
        "delete_document",
        "list_documents",
        "md_to_pdf",
    ],
    "web": ["fetch_url", "fetch_data", "call_api"],
    "comms": ["send_mail", "calendar", "call", "accept_call", "reject_call"],
    "code": ["code_tool", "iter_documents"],
    "dispatcher": ["dispatch_documents", "execute_action_request", "upsert_object_record", "ingest_object", "store_object_result", "batch_generate_documents", "vdb_worker"],
}


FORCED_ROUTE_CONFIGS: dict[str, list[dict[str, Any]]] = {
    "_primary_assistant": [
        {
            "name": "agent_prefix",
            "trigger": {"type": "at_prefix"},
        },
        {
            "name": "create_agents_command",
            "trigger": {
                "type": "text_prefix",
                "prefix": "/create agents",
                "ignore_case": True,
            },
            "route": {
                "target_agent": "_agent_system_planner",
                "user_question": "__trigger_remainder__",
            },
        },
        {
            "name": "cover_letter_ready_request",
            "trigger": {
                "type": "json_payload",
                "conditions": {
                    "all": [
                        {"action": {"eq": "generate_cover_letter"}},
                        {"job_posting_result": {"exists": True}},
                        {"profile_result": {"exists": True}},
                    ]
                },
            },
            "route": {
                "target_agent": "_cover_letter_agent",
                "handoff_protocol": "agent_handoff_v1",
                "agent_response": {
                    "agent_label": "_primary_assistant",
                    "handoff_to": "_cover_letter_agent",
                    "output": "__cover_letter_writer_payload__",
                },
            },
        },
        {
            "name": "cover_letter_request",
            "trigger": {
                "type": "json_payload",
                "conditions": {
                    "all": [
                        {"action": {"eq": "generate_cover_letter"}},
                        {"job_posting": {"exists": True}},
                        {"applicant_profile": {"exists": True}},
                    ]
                },
            },
            "route": {
                "target_agent": "_data_dispatcher",
                "user_question": "__original_input__",
            },
        },
    ],
}


WORKFLOW_CONFIGS: dict[str, dict[str, Any]] = {
    "primary_assistant_router": {
        "description": "Primary assistant router workflow with declarative delegation branches.",
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
            "planner_delegated": {
                "actor": {"kind": "tool", "name": "route_to_agent"},
                "terminal": False,
            },
            "dispatcher_delegated": {
                "actor": {"kind": "tool", "name": "route_to_agent"},
                "terminal": False,
            },
            "parser_delegated": {
                "actor": {"kind": "tool", "name": "route_to_agent"},
                "terminal": False,
            },
            "writer_delegated": {
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
                    "conditions": {"target_agent": "_agent_system_planner"},
                },
                "to": "planner_delegated",
            },
            {
                "from": "assistant_ready",
                "on": {
                    "kind": "tool",
                    "name": "route_to_agent",
                    "conditions": {"target_agent": "_data_dispatcher"},
                },
                "to": "dispatcher_delegated",
            },
            {
                "from": "assistant_ready",
                "on": {
                    "kind": "tool",
                    "name": "route_to_agent",
                    "conditions": {"target_agent": "_parser_agent"},
                },
                "to": "parser_delegated",
            },
            {
                "from": "assistant_ready",
                "on": {
                    "kind": "tool",
                    "name": "route_to_agent",
                    "conditions": {"target_agent": "_writer_agent"},
                },
                "to": "writer_delegated",
            },
            {
                "from": ["planner_delegated", "dispatcher_delegated", "parser_delegated", "writer_delegated"],
                "on": {
                    "kind": "state",
                    "name": "routed_agent_complete",
                    "conditions": {
                        "target_agent": {"in": ["_agent_system_planner", "_data_dispatcher", "_parser_agent", "_writer_agent"]}
                    },
                },
                "to": "workflow_complete",
            },
            {
                "from": ["assistant_ready", "planner_delegated", "dispatcher_delegated", "parser_delegated", "writer_delegated"],
                "on": {
                    "kind": "state",
                    "name": ["model_failed", "routed_agent_failed"],
                    "conditions": {
                        "any": [
                            {"error": {"exists": True}},
                            {"result": {"exists": True}},
                            {"target_agent": {"in": ["_agent_system_planner", "_data_dispatcher", "_parser_agent", "_writer_agent"]}},
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
    },
    "agent_system_planner_router": {
        "description": "Planner workflow that keeps the user interaction in the planner until the builder worker is delegated.",
        "entry_state": "planner_ready",
        "retry_policy": {
            "max_attempts": 2,
            "backoff_seconds": [1, 2],
        },
        "states": {
            "planner_ready": {
                "actor": {"kind": "agent", "name": "_agent_system_planner"},
                "terminal": False,
            },
            "builder_delegated": {
                "actor": {"kind": "tool", "name": "route_to_agent"},
                "terminal": False,
            },
            "planner_retry_pending": {
                "actor": {"kind": "state", "name": "retry_pending"},
                "terminal": False,
            },
            "planner_failed": {
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
                "from": "planner_ready",
                "on": {
                    "kind": "tool",
                    "name": "route_to_agent",
                    "conditions": {"target_agent": "_agent_system_worker"},
                },
                "to": "builder_delegated",
            },
            {
                "from": "builder_delegated",
                "on": {
                    "kind": "state",
                    "name": "routed_agent_complete",
                    "conditions": {"target_agent": "_agent_system_worker"},
                },
                "to": "workflow_complete",
            },
            {
                "from": ["planner_ready", "builder_delegated"],
                "on": {
                    "kind": "state",
                    "name": ["model_failed", "routed_agent_failed"],
                    "conditions": {
                        "any": [
                            {"error": {"exists": True}},
                            {"result": {"exists": True}},
                            {"target_agent": {"in": ["_agent_system_worker"]}},
                        ]
                    },
                },
                "to": "planner_retry_pending",
            },
            {
                "from": "planner_retry_pending",
                "on": {"kind": "state", "name": "retry_requested"},
                "to": "planner_ready",
            },
            {
                "from": "planner_retry_pending",
                "on": {"kind": "state", "name": "retry_exhausted"},
                "to": "planner_failed",
            },
        ],
    },
    "agent_system_builder_leaf": {
        "description": "Leaf workflow for the builder worker that emits the generated config bundle.",
        "entry_state": "builder_active",
        "states": {
            "builder_active": {
                "actor": {"kind": "agent", "name": "_agent_system_worker"},
                "terminal": False,
            },
            "builder_complete": {
                "actor": {"kind": "state", "name": "workflow_complete"},
                "terminal": True,
            },
            "builder_failed": {
                "actor": {"kind": "state", "name": "workflow_failed"},
                "terminal": True,
            },
        },
        "transitions": [
            {
                "from": "builder_active",
                "on": {"kind": "state", "name": "followup_complete"},
                "to": "builder_complete",
            },
            {
                "from": "builder_active",
                "on": {"kind": "state", "name": ["model_failed", "tool_failed"]},
                "to": "builder_failed",
            },
        ],
    },
    "parser_agent_leaf": {
        "description": "Leaf workflow for the generic parser worker without downstream routing.",
        "entry_state": "parser_active",
        "states": {
            "parser_active": {
                "actor": {"kind": "agent", "name": "_parser_agent"},
                "terminal": False,
            },
            "parser_complete": {
                "actor": {"kind": "state", "name": "workflow_complete"},
                "terminal": True,
            },
        },
        "transitions": [
            {
                "from": "parser_active",
                "on": {
                    "kind": "state",
                    "name": "followup_complete",
                    "conditions": {"result": {"exists": True}},
                },
                "to": "parser_complete",
            },
        ],
    },
    "writer_agent_leaf": {
        "description": "Leaf workflow for the generic writer worker without downstream routing.",
        "entry_state": "writer_active",
        "states": {
            "writer_active": {
                "actor": {"kind": "agent", "name": "_writer_agent"},
                "terminal": False,
            },
            "writer_complete": {
                "actor": {"kind": "state", "name": "workflow_complete"},
                "terminal": True,
            },
        },
        "transitions": [
            {
                "from": "writer_active",
                "on": {
                    "kind": "state",
                    "name": "followup_complete",
                    "conditions": {
                        "all": [
                            {"result": {"exists": True}},
                            {"result": {"truthy": True}},
                        ]
                    },
                },
                "to": "writer_complete",
            },
        ],
    },
    "profile_parser_leaf": {
        "description": "Leaf workflow for the specialized profile parser.",
        "entry_state": "profile_parser_active",
        "states": {
            "profile_parser_active": {
                "actor": {"kind": "agent", "name": "_profile_parser"},
                "terminal": False,
            },
            "profile_parser_complete": {
                "actor": {"kind": "state", "name": "workflow_complete"},
                "terminal": True,
            },
        },
        "transitions": [
            {
                "from": "profile_parser_active",
                "on": {
                    "kind": "state",
                    "name": ["followup_complete", "routed_agent_complete"],
                    "conditions": {"any": [{"result": {"exists": True}}, {"target_agent": "_profile_parser"}]},
                },
                "to": "profile_parser_complete",
            }
        ],
    },
    "job_posting_parser_leaf": {
        "description": "Leaf workflow for the specialized job-posting parser.",
        "entry_state": "job_posting_parser_active",
        "states": {
            "job_posting_parser_active": {
                "actor": {"kind": "agent", "name": "_job_posting_parser"},
                "terminal": False,
            },
            "job_posting_parser_complete": {
                "actor": {"kind": "state", "name": "workflow_complete"},
                "terminal": True,
            },
        },
        "transitions": [
            {
                "from": "job_posting_parser_active",
                "on": {
                    "kind": "state",
                    "name": ["followup_complete", "routed_agent_complete"],
                    "conditions": {"any": [{"result": {"exists": True}}, {"target_agent": "_job_posting_parser"}]},
                },
                "to": "job_posting_parser_complete",
            }
        ],
    },
    "cover_letter_writer_leaf": {
        "description": "Leaf workflow for the specialized cover-letter writer.",
        "entry_state": "cover_letter_writer_active",
        "states": {
            "cover_letter_writer_active": {
                "actor": {"kind": "agent", "name": "_cover_letter_agent"},
                "terminal": False,
            },
            "cover_letter_writer_complete": {
                "actor": {"kind": "state", "name": "workflow_complete"},
                "terminal": True,
            },
        },
        "transitions": [
            {
                "from": "cover_letter_writer_active",
                "on": {
                    "kind": "state",
                    "name": ["followup_complete", "routed_agent_complete"],
                    "conditions": {
                        "all": [
                            {"result": {"exists": True}},
                            {"result": {"truthy": True}},
                        ]
                    },
                },
                "to": "cover_letter_writer_complete",
            }
        ],
    },
    "data_dispatcher_chain": {
        "description": "Deterministic dispatcher chain driven by workflow definition in agents_config.py.",
        "entry_state": "dispatcher_ready",
        "retry_policy": {
            "max_attempts": 3,
            "backoff_seconds": [1, 2, 4],
        },
        "states": {
            "dispatcher_ready": {
                "actor": {"kind": "agent", "name": "_data_dispatcher"},
                "terminal": False,
            },
            "documents_dispatched": {
                "actor": {"kind": "tool", "name": "dispatch_documents"},
                "terminal": False,
            },
            "action_executed": {
                "actor": {"kind": "tool", "name": "execute_action_request"},
                "terminal": False,
            },
            "job_record_upserted": {
                "actor": {"kind": "tool", "name": "upsert_object_record"},
                "terminal": False,
            },
            "documents_batched": {
                "actor": {"kind": "tool", "name": "batch_generate_documents"},
                "terminal": True,
            },
            "parser_routed": {
                "actor": {"kind": "tool", "name": "route_to_agent"},
                "terminal": False,
            },
            "dispatcher_retry_pending": {
                "actor": {"kind": "state", "name": "retry_pending"},
                "terminal": False,
            },
            "dispatcher_failed": {
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
                "from": "dispatcher_ready",
                "on": {"kind": "tool", "name": "dispatch_documents"},
                "to": "documents_dispatched",
            },
            {
                "from": "dispatcher_ready",
                "on": {"kind": "tool", "name": "batch_generate_documents"},
                "to": "documents_batched",
            },
            {
                "from": "dispatcher_ready",
                "on": {"kind": "tool", "name": "execute_action_request"},
                "to": "action_executed",
            },
            {
                "from": "dispatcher_ready",
                "on": {"kind": "tool", "name": "upsert_object_record"},
                "to": "job_record_upserted",
            },
            {
                "from": "documents_dispatched",
                "on": {
                    "kind": "tool",
                    "name": "route_to_agent",
                    "conditions": {"target_agent": "_job_posting_parser"},
                },
                "to": "parser_routed",
            },
            {
                "from": "parser_routed",
                "on": {"kind": "state", "name": "followup_complete"},
                "to": "workflow_complete",
            },
            {
                "from": ["action_executed", "job_record_upserted"],
                "on": {
                    "kind": "state",
                    "name": ["followup_complete", "tool_complete"],
                    "conditions": {
                        "all": [
                            {"result": {"exists": True}},
                            {"result": {"truthy": True}},
                        ]
                    },
                },
                "to": "workflow_complete",
            },
            {
                "from": ["dispatcher_ready", "documents_dispatched", "action_executed", "job_record_upserted", "parser_routed"],
                "on": {
                    "kind": "state",
                    "name": ["tool_failed", "model_failed", "routed_agent_failed"],
                    "conditions": {
                        "any": [
                            {"tool_name": {"in": ["dispatch_documents", "batch_generate_documents", "execute_action_request", "upsert_object_record", "route_to_agent"]}},
                            {"error": {"exists": True}},
                            {"target_agent": "_job_posting_parser"},
                        ]
                    },
                },
                "to": "dispatcher_retry_pending",
            },
            {
                "from": "dispatcher_retry_pending",
                "on": {"kind": "state", "name": "retry_requested"},
                "to": "dispatcher_ready",
            },
            {
                "from": "dispatcher_retry_pending",
                "on": {"kind": "state", "name": "retry_exhausted"},
                "to": "dispatcher_failed",
            },
        ],
    },
}


BATCH_WORKFLOW_CONFIGS: dict[str, dict[str, Any]] = {
    "cover_letter_batch_generation": {
        "description": "Declarative batch cover-letter generation workflow executed by the batch document generator.",
        "dispatcher": {
            "tool_name": "dispatch_documents",
            "thread_id": "batch",
            "dispatcher_message_id": "batch",
            "recursive": True,
            "bucket_order": ["new", "known_unprocessed", "known_processing"],
            "rerun_bucket": "known_processed",
        },
        "filters": {
            "skip_output_dir_inputs": True,
            "skip_basenames": ["Muster_Anschreiben.pdf"],
        },
        "profile_result": {
            "agent": "profile_parser",
            "correlation_id_path": "profile_id",
            "language_path": "preferences.language",
            "default_language": "de",
        },
        "job_payload": {
            "requested_actions": ["parse", "extract_text", "store_file", "mark_processed_on_success"],
            "include_extracted_text": True,
        },
        "stages": [
            {
                "name": "job_posting_parse",
                "prompt": {"agent_type": "parser", "task_name": "job_posting"},
                "input": {"from_context": "job_payload"},
                "temperature": 0.2,
                "response_format": "json",
                "store_as": "job_posting_result",
                "history": {
                    "request_stage": "job_posting_parser",
                    "response_stage": "job_posting_parser",
                    "tool_name": "job_posting_parser",
                },
            },
            {
                "name": "cover_letter_generate",
                "prompt": {"agent_type": "writer", "task_name": "cover_letter"},
                "input_template": {
                    "job_posting_result": {"from_context": "job_posting_result"},
                    "profile_result": {"from_context": "profile_result"},
                    "options": {
                        "language": {"from_profile": "preferences.language", "default": "de"},
                        "tone": {"from_profile": "preferences.tone", "default": "modern"},
                        "max_words": {"from_profile": "preferences.max_length", "default": 350},
                        "date": {"from_context": "current_date"},
                        "city": {"literal": None},
                        "include_enclosures": {"literal": True},
                    },
                },
                "temperature": 0.2,
                "response_format": "json",
                "store_as": "cover_letter_result",
                "history": {
                    "request_stage": "text_generation",
                    "response_stage": "text_generation",
                    "tool_name": "text_generation",
                },
            },
        ],
        "document_output": {
            "text_writer_tool": "write_document",
            "text_writer_input": {
                "content": {"from_context": "cover_letter_result.cover_letter.full_text"},
                "path": {"from_context": "out_dir"},
                "doc_id": {"from_context": "doc_id"},
            },
            "pdf_writer": "internal_text_pdf",
            "pdf_writer_input": {
                "content": {"from_context": "cover_letter_result.cover_letter.full_text"},
                "out_dir": {"from_context": "out_dir"},
                "doc_id": {"from_context": "doc_id"},
            },
            "enabled_context_path": "write_pdf",
        },
        "dispatcher_record": {
            "success_updates": {
                "processed": {"literal": True},
                "processing_state": {"literal": "processed"},
                "processed_at": {"from_context": "utc_now"},
                "document_text_path": {"from_context": "saved_text_path"},
                "document_pdf_path": {"from_context": "saved_pdf_path"},
                "document_path": {"from_context": "saved_document_path"},
                "last_error": {"literal": None},
            },
            "failure_updates": {
                "processed": {"literal": False},
                "processing_state": {"literal": "failed"},
                "failed_reason": {"from_context": "error_message"},
                "last_error": {"from_context": "error_message"},
                "last_error_at": {"from_context": "utc_now"},
            },
        },
    },
}
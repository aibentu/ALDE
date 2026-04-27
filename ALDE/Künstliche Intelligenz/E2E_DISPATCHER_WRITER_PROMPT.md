# E2E Dispatcher Writer Prompt

## Purpose

This note contains a ready-to-use prompt for the end-to-end dispatcher to writer workflow in ALDE.

The prompt is aligned with the currently validated runtime path:

- router planner sequence: `router_planner_cover_letter_sequence`
- dispatch job: `document_dispatch`
- parser job: `job_posting_parser`
- writer job: `cover_letter_writer`
- sequence name: `dispatch_parse_generate_cover_letter`

Use this prompt when job postings still need to be discovered or dispatched from files and the workflow should continue through parsing into deterministic cover-letter generation.

## When To Use This Prompt

Use this prompt when all of the following are true:

- the request should start from a directory or file-based job-offer source
- the system should run the full dispatch -> parse -> writer path
- applicant data and writer options are already known or can be supplied up front
- the desired result is a routed, deterministic sequence rather than a one-off freeform writing response

Do not use this prompt when `job_posting_result` is already final and the workflow should go directly to `cover_letter_writer` without dispatch.

## Primary Prompt

Paste-ready prompt for `_xplaner_xrouter`:

```text
Initialize the end-to-end dispatcher-to-writer workflow for cover-letter generation.

Use the specialized router planner sequence `router_planner_cover_letter_sequence` to create one deterministic route initialization payload for `_xworker`.

Requirements:
- Start with `document_dispatch`.
- Scan the job-offer source from `scan_dir` and dispatch only eligible inputs.
- Preserve any provided `applicant_profile`, `profile_result`, `job_posting`, `job_posting_result`, and `options` fields unchanged.
- If `action` is missing, set it to `generate_cover_letter`.
- Keep sequence metadata explicit:
  - `sequence_name`: `dispatch_parse_generate_cover_letter`
  - `parser_job_name`: `job_posting_parser`
  - `writer_job_name`: `cover_letter_writer`
- Do not invent filesystem state, DB state, parsed job data, or applicant facts.
- The parser stage must remain source-grounded.
- The writer stage must use only `job_posting_result`, `profile_result`, and `options`.
- Respect `options.language`, `options.tone`, and `options.max_words`.
- Return the deterministic route initialization payload, not a freeform explanation.

Inputs:
- `scan_dir`: <ABSOLUTE_PATH_TO_JOB_OFFERS>
- `applicant_profile`: <STRUCTURED_PROFILE_OR_REQUEST_STYLE_PROFILE>
- `options`: <WRITER_OPTIONS>
- `output_dir`: <OPTIONAL_TARGET_DIRECTORY>
- `correlation_id`: <OPTIONAL_CORRELATION_ID>

Expected outcome:
- initialize the dispatch -> parse -> cover-letter sequence
- target `_xworker`
- route job `document_dispatch`
- handoff metadata must include the explicit parser and writer job names
- downstream writer execution must end in structured cover-letter output suitable for artifact persistence
```

## Structured Prompt Variant

Use this version when you want the request content itself to be explicit and schema-like.

```text
Initialize `router_planner_cover_letter_sequence` for an end-to-end dispatcher-writer run.

Build a deterministic route for `_xworker` with these constraints:

{
  "action": "generate_cover_letter",
  "scan_dir": "<ABSOLUTE_PATH_TO_JOB_OFFERS>",
  "applicant_profile": <APPLICANT_PROFILE_OBJECT>,
  "options": {
    "language": "de",
    "tone": "modern",
    "max_words": 350,
    "output_dir": "<OPTIONAL_OUTPUT_DIRECTORY>"
  },
  "sequence": {
    "name": "dispatch_parse_generate_cover_letter",
    "parser_job_name": "job_posting_parser",
    "writer_job_name": "cover_letter_writer"
  }
}

Rules:
- route through `document_dispatch`
- preserve structured input unchanged
- do not invent file, DB, or parser state
- prepare the payload so successful parsing can hand off to `cover_letter_writer`
- return the route initialization payload only
```

## Tool-Oriented Invocation Shape

If the workflow is being initialized directly through the runtime helper, the intent should map to this shape:

```json
{
  "job_name": "router_planner_cover_letter_sequence",
  "scan_dir": "/absolute/path/to/job_offers",
  "applicant_profile": {
    "source": "text",
    "value": {
      "profile_id": "profile:test",
      "preferences": {
        "language": "de"
      }
    }
  },
  "options": {
    "language": "de",
    "tone": "modern",
    "max_words": 350,
    "output_dir": "/absolute/path/to/output"
  }
}
```

The expected initialized route should conceptually resolve to:

```json
{
  "target_agent": "_xworker",
  "job_name": "document_dispatch",
  "handoff_metadata": {
    "sequence_name": "dispatch_parse_generate_cover_letter",
    "parser_job_name": "job_posting_parser",
    "writer_job_name": "cover_letter_writer"
  }
}
```

## Contract Notes

The prompt above is grounded in the current runtime contracts:

- `router_planner_cover_letter_sequence` initializes the deterministic dispatch -> parse -> write sequence.
- `document_dispatch` is the entry job for file discovery and dispatch preparation.
- `job_posting_parser` is the parser stage used by the sequence.
- `cover_letter_writer` expects `job_posting_result`, `profile_result`, and `options`.
- writer artifact persistence is handled by the configured result postprocess path after successful writer output.

## Practical Example

```text
Initialize the end-to-end dispatcher-to-writer workflow for cover-letter generation.

Use `router_planner_cover_letter_sequence` and build one deterministic route initialization payload for `_xworker`.

Inputs:
- `scan_dir`: `/home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE/AppData/job_offers`
- `applicant_profile`: {
    "source": "text",
    "value": {
      "profile_id": "profile:ada",
      "personal_info": {"full_name": "Ada Lovelace"},
      "preferences": {"language": "de"},
      "skills": ["python", "ai", "automation"]
    }
  }
- `options`: {
    "language": "de",
    "tone": "modern",
    "max_words": 320,
  "output_dir": "/home/ben/Vs_Code_Projects/Projects/ALDE_Projekt/ALDE/AppData/VSM_4_Data/cover_letters"
  }

Requirements:
- route through `document_dispatch`
- set `action` to `generate_cover_letter`
- preserve input unchanged
- keep metadata explicit with `dispatch_parse_generate_cover_letter`, `job_posting_parser`, and `cover_letter_writer`
- do not invent filesystem, DB, or parser results
- return only the deterministic route initialization payload
```

## Direct Writer Bypass Variant

Use this variant when `job_posting_result` is already available and the workflow should skip dispatch and skip job-posting parsing.

This variant is appropriate when:

- the job posting has already been parsed
- the workflow should route directly to `cover_letter_writer`
- the desired result is the writing stage only

Do not use this variant when the job-offer source still needs discovery, dispatching, or parsing.

### Direct Writer Prompt

```text
Route directly to `cover_letter_writer`.

Use `_xworker` with the writer job only.

Requirements:
- Do not use `document_dispatch`.
- Do not route through `job_posting_parser`.
- Preserve `job_posting_result`, `profile_result`, `applicant_profile`, and `options` unchanged when provided.
- Use only supported structured input.
- Do not invent applicant facts, parsed job fields, or missing contact details.
- The writer output must remain grounded in `job_posting_result`, `profile_result`, and `options`.
- Respect `options.language`, `options.tone`, and `options.max_words`.
- Return the deterministic writer route or writer-ready payload only.

Inputs:
- `job_posting_result`: <PARSED_JOB_POSTING_RESULT>
- `profile_result`: <PARSED_PROFILE_RESULT>
- `options`: <WRITER_OPTIONS>
- `output_dir`: <OPTIONAL_TARGET_DIRECTORY>
```

### Direct Writer Structured Variant

```text
Initialize a direct writer run for `_xworker`.

{
  "action": "generate_cover_letter",
  "job_name": "cover_letter_writer",
  "job_posting_result": <JOB_POSTING_RESULT_OBJECT>,
  "profile_result": <PROFILE_RESULT_OBJECT>,
  "options": {
    "language": "de",
    "tone": "modern",
    "max_words": 350,
    "output_dir": "<OPTIONAL_OUTPUT_DIRECTORY>"
  }
}

Rules:
- route directly to `cover_letter_writer`
- do not dispatch files
- do not parse job postings again
- return the deterministic writer payload only
```

### Direct Writer Invocation Shape

```json
{
  "job_name": "cover_letter_writer",
  "job_posting_result": {
    "correlation_id": "job:test",
    "job_posting": {
      "job_title": "AI Engineer",
      "company_name": "Example GmbH"
    }
  },
  "profile_result": {
    "correlation_id": "profile:test",
    "profile": {
      "profile_id": "profile:test",
      "preferences": {
        "language": "de"
      }
    }
  },
  "options": {
    "language": "de",
    "tone": "modern",
    "max_words": 350,
    "output_dir": "/absolute/path/to/output"
  }
}
```

## Short Operator Version

Use this shorter version for repeated operator use:

```text
Initialize `router_planner_cover_letter_sequence` for an e2e dispatcher-writer run.
Start with `document_dispatch`, preserve `applicant_profile` and `options`, set `action=generate_cover_letter`, and keep `sequence_name=dispatch_parse_generate_cover_letter`, `parser_job_name=job_posting_parser`, and `writer_job_name=cover_letter_writer` explicit. Do not invent file or DB state. Return the deterministic route payload only.
```

## Companion Quick Action Template

A reusable ALDE template file for these prompts is stored at:

- `AppData/templates/e2e_dispatcher_writer_quick_actions.json`

It contains:

- an end-to-end dispatcher-to-writer quick action
- a direct writer bypass quick action
- placeholder fields and routing metadata for later reuse in the template loader
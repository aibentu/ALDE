# Quick Start: Primary Agent Orchestrator

## Scenario 1: Generate Cover Letter (Simple)

**User provides:** Job posting PDF + stored profile ID

```json
{
    "action": "generate_cover_letter",
    "job_posting_path": "/path/to/job_posting.pdf",
    "profile_id": "profile_abc123"
}
```

**Workflow:**
1. Primary agent validates input
2. Primary agent loads profile from DB
3. Primary agent routes job posting to `_job_posting_parser`
4. Primary agent waits for parser result
5. Primary agent routes aggregated data to `_cover_letter_generator`
6. Primary agent returns structured output with cover letter

**Duration:** ~8-12 seconds

---

## Scenario 2: Full Workflow (New Profile + Job)

**User provides:** Job posting PDF + CV file + language/tone preferences

```json
{
    "action": "generate_cover_letter",
    "job_posting": {
        "source": "file",
        "value": "AppData/VSM_4_Data/job_posting.pdf"
    },
    "applicant_profile": {
        "source": "file",
        "value": "AppData/VSM_4_Data/cv_2026.pdf"
    },
    "options": {
        "language": "de",
        "tone": "modern",
        "max_words": 350,
        "include_enclosures": true
    }
}
```

**Workflow:**
1. Primary agent validates input
2. Primary agent routes CV to `_profile_parser` (extracts & stores)
3. Primary agent routes job posting to `_job_posting_parser` (extracts & stores)
4. Primary agent waits for both parsers
5. Primary agent routes aggregated data to `_cover_letter_generator`
6. Primary agent saves letter to file system
7. Primary agent returns complete response with quality metrics

**Duration:** ~12-18 seconds

---

## Scenario 3: Text-Based Input

**User provides:** Job description as text + profile text

```json
{
    "action": "generate_cover_letter",
    "job_posting": {
        "source": "text",
        "value": "Senior Python Developer at TechCorp...\nRequirements: Python, FastAPI, PostgreSQL..."
    },
    "applicant_profile": {
        "source": "text",
        "value": "Max Mustermann, Senior Software Engineer...\nSkills: Python, PySide6, FastAPI..."
    },
    "options": {
        "language": "de",
        "tone": "modern"
    }
}
```

**Duration:** ~10-15 seconds

---

## Scenario 4: Batch Processing (Multiple Job Postings)

**User provides:** Directory with multiple job posting PDFs + stored profile

```json
{
    "action": "generate_cover_letters_batch",
    "job_postings_dir": "AppData/VSM_4_Data/",
    "profile_id": "profile_abc123",
    "options": {
        "language": "de",
        "tone": "modern"
    }
}
```

**Workflow:**
1. Primary agent routes to `_data_dispatcher` with directory path
2. Dispatcher scans PDFs, checks DB status, forwards unprocessed to `_job_posting_parser`
3. Each job posting is parsed and stored
4. Primary agent generates cover letter for each job (parallel possible)
5. Primary agent returns batch results with summary

**Duration:** ~5-10 seconds per job (after dispatcher)

---

## Response Examples

### Success Response
```json
{
    "status": "success",
    "cover_letter": {
        "full_text": "Sehr geehrte Damen und Herren,\n\nI am excited to apply...",
        "word_count": 342,
        "language": "de"
    },
    "quality_metrics": {
        "matched_requirements": ["Python", "FastAPI", "PostgreSQL"],
        "red_flags": [],
        "extraction_quality": "high"
    },
    "metadata": {
        "job_posting_id": "job_xyz789",
        "profile_id": "profile_abc123",
        "generated_at": "2026-01-21T10:30:00Z"
    }
}
```

### Incomplete Profile Response
```json
{
    "status": "incomplete",
    "message": "Applicant profile required",
    "options": [
        "Provide profile file path",
        "Paste profile as text",
        "Use existing profile ID"
    ]
}
```

### Partial Failure (Bad extraction)
```json
{
    "status": "partial_failure",
    "warnings": [
        "Job posting extraction quality is MEDIUM",
        "Missing salary information",
        "Company details incomplete"
    ],
    "cover_letter": {
        "full_text": "...",
        "word_count": 287
    },
    "suggested_actions": [
        "Review for accuracy",
        "Add missing salary information manually",
        "Verify company name and address"
    ]
}
```

---

## Key Tools Used by Primary Agent

### 1. `route_to_agent` - Delegate to specialists
```python
route_to_agent(
    target_agent="_job_posting_parser",
    message_text={...payload...}
)
```

### 2. `load_dispatcher_db` - Access persistent DB
```python
load_dispatcher_db()
# Access stored profiles, job postings, cover letters
```

### 3. `read_document` - Load profile from file
```python
read_document(path="/path/to/cv.pdf")
```

### 4. `write_document` - Save cover letter
```python
write_document(
    content="Full cover letter text",
    path="/path/to/output/letter.txt"
)
```

---

## Default Behavior

| Parameter | Default | Override |
|-----------|---------|----------|
| Language | `de` (German) | Set `options.language: "en"` |
| Tone | `modern` | Set `options.tone: "professional"` \| `"creative"` |
| Max words | `350` | Set `options.max_words: 400` |
| Profile location | `AppData/applicant_profile.json` | Provide explicit path or ID |
| Output directory | `AppData/Cover_letters/` | Set in `options.output_dir` |

---

## Common Issues & Fixes

### Issue: "Profile not found"
**Solution 1:** Check default location
```
ALDE/ALDE/AppData/VSM_4_Data/applicant_profile.json
```

**Solution 2:** Provide explicit profile
```json
{
    "applicant_profile": {
        "source": "file",
        "value": "/your/cv/path.pdf"
    }
}
```

**Solution 3:** Use stored ID
```json
{
    "applicant_profile": {
        "source": "stored_id",
        "value": "profile_sha256hash"
    }
}
```

---

### Issue: "PDF extraction failed"
**Solution:** Use text input instead
```json
{
    "job_posting": {
        "source": "text",
        "value": "<paste job posting text here>"
    }
}
```

---

### Issue: "Cover letter word count wrong"
**Solution:** Adjust max_words
```json
{
    "options": {
        "max_words": 400
    }
}
```

---

## Performance Tips

1. **Reuse profiles** → Much faster (no parsing)
2. **Use batch mode** → Process multiple jobs efficiently
3. **Check extraction quality** → Understand which jobs need manual review
4. **Store successful profiles** → Avoid re-parsing

---

## Next Steps

1. **Read**: [ORCHESTRATOR_USAGE.md](ORCHESTRATOR_USAGE.md) for detailed reference
2. **Explore**: [agents_registry.py](agents_registry.py) to see all agents
3. **Review**: [apply_agent_prompts.py](apply_agent_prompts.py) for system prompts
4. **Test**: Run `python alde/agents_registry.py` to inspect registry

---

**Version**: 1.0  
**Last Updated**: 21 January 2026

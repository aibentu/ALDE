# AppData (local runtime data)

This folder is used for **local** runtime state such as history, vector stores, cached icons and generated artifacts.

For a public/reference repository, most of these files are intentionally **not** tracked in git.

Tracked:
- `templates/` (stable templates)
- Documentation files (when they are not personal)

Ignored (examples):
- `generated/`, `icon_cache/`
- `VSM_*_Data/` (vector stores, PDFs, job postings, cover letters)
- `dispatcher_doc_db.json`, `db.json`, `history.json` (machine/user-specific state)

If you need reproducible demos, create small, non-personal sample documents and keep them outside of `VSM_*_Data/`.

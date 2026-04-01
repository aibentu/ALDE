# ALDE Webapp Control Plane

This package exposes the ALDE runtime as a multi-tenant API-first control plane.

## Scope in this implementation step

- Tenant registration endpoint
- SSO login endpoint
- OIDC start + callback endpoints
- ID token signature verification through JWKS
- Refresh token rotation + revocation
- Bearer token auth for API calls
- Authenticated agent run endpoint backed by the manifest-driven `alde.agents_factory` runtime
- Async run queue + job status polling
- Optional external Redis/RQ queue backend for async jobs
- Audit trail endpoint
- Fine-grained RBAC checks per role, agent, and tool metadata
- Workflow validation and workflow status visibility endpoints
- Web landing page + OpenAPI docs

## Run locally

```bash
pip install -r requirements-web.txt
uvicorn alde.webapp.main:app --reload --port 8080
```

Open:

- `http://localhost:8080/`
- `http://localhost:8080/docs`

## Architecture references

The web layer is intentionally API-first and sits on top of the existing ALDE runtime.

For runtime structure and the ongoing configuration refactor, use these repo documents:

- `../../ARCHITECTURE_REFACTOR.md`
- `../../AGENT_SEQUENCE_STATE_DIAGRAM.md`
- `../../AUTONOMOUS_MULTI_AGENT_ROADMAP.md`

The webapp should consume stable runtime entrypoints and avoid introducing its own duplicate agent or tool configuration layer.

Current runtime assumptions:

- Agent identity is manifest-driven from `alde/agents_config.py`
- `_xplaner_xrouter` is the interactive planner/router entrypoint
- `_xworker` is the only worker manifest; specialization is selected by `job_name`
- Deterministic workflow state and validation live in the runtime, not in the web layer
- The webapp should treat workflow status and validation as read-only operational views

## Database and migrations

Set database URL:

```bash
export ALDE_WEB_DATABASE_URL='postgresql+psycopg://alde:alde@localhost:5432/alde_web'
```

Run migrations:

```bash
alembic upgrade head
```

Fallback for quick local tests without PostgreSQL:

```bash
export ALDE_WEB_DATABASE_URL='sqlite:///./AppData/alde_web.db'
```

## API quickstart

1. Register a tenant:

```bash
curl -sS -X POST http://localhost:8080/api/v1/auth/register-tenant \
  -H 'Content-Type: application/json' \
  -d '{
    "slug": "acme",
    "name": "Acme Industries",
    "admin_email": "admin@acme.local",
    "admin_display_name": "Acme Admin"
  }'
```

2. Login via SSO contract:

```bash
curl -sS -X POST http://localhost:8080/api/v1/auth/sso/login \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_slug": "acme",
    "provider": "keycloak",
    "subject": "oidc:12345",
    "email": "admin@acme.local",
    "display_name": "Acme Admin"
  }'
```

3. Run an agent request with bearer token:

```bash
curl -sS -X POST http://localhost:8080/api/v1/agents/runs \
  -H "Authorization: Bearer <TOKEN>" \
  -H 'Content-Type: application/json' \
  -d '{
    "target_agent": "_xplaner_xrouter",
    "prompt": "Create deployment-test checklist for tenant ACME",
    "metadata": {"pipeline": "deploy-test-v1"}
  }'
```

4. Submit an async run and poll job status:

```bash
curl -sS -X POST http://localhost:8080/api/v1/agents/runs/async \
  -H "Authorization: Bearer <TOKEN>" \
  -H 'Content-Type: application/json' \
  -d '{"target_agent":"_xplaner_xrouter","prompt":"run async","metadata":{}}'

curl -sS -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8080/api/v1/agents/jobs/<JOB_ID>
```

5. Inspect workflow validation and latest workflow state:

```bash
curl -sS -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8080/api/v1/agents/workflows/validation

curl -sS -H "Authorization: Bearer <TOKEN>" \
  'http://localhost:8080/api/v1/agents/workflows/status?target_agent=_xworker&limit=10'
```

6. Check queue and API health:

```bash
curl -sS http://localhost:8080/api/v1/health
```

7. Read audit events:

```bash
curl -sS -H "Authorization: Bearer <TOKEN>" \
  'http://localhost:8080/api/v1/audit/events?limit=50'
```

8. Refresh access token and revoke a refresh session:

```bash
curl -sS -X POST http://localhost:8080/api/v1/auth/token/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<REFRESH_TOKEN>"}'

curl -sS -X POST http://localhost:8080/api/v1/auth/logout \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<REFRESH_TOKEN>"}' -i
```

## OIDC setup (Keycloak example)

```bash
export ALDE_WEB_OIDC_ISSUER='https://keycloak.example/realms/alde'
export ALDE_WEB_OIDC_CLIENT_ID='alde-web'
export ALDE_WEB_OIDC_CLIENT_SECRET='<secret>'
export ALDE_WEB_OIDC_REDIRECT_URI='http://localhost:8080/api/v1/auth/oidc/callback'
```

Flow:

1. `POST /api/v1/auth/oidc/start` with `tenant_slug`
2. Redirect user to returned `authorization_url`
3. Provider redirects to `GET /api/v1/auth/oidc/callback?state=...&code=...`

Role mapping from OIDC claims:

- `tenant_admin` if user belongs to one of `ALDE_WEB_OIDC_ADMIN_GROUPS`
- `tenant_admin` if user email domain matches `ALDE_WEB_OIDC_ADMIN_EMAIL_DOMAINS`
- otherwise `member`

Security validation details:

- OIDC callback validates `id_token` signature against JWKS.
- `aud` is checked against `ALDE_WEB_OIDC_AUDIENCE` with fallback to `ALDE_WEB_OIDC_CLIENT_ID`.
- `iss` and `exp` are verified when `ALDE_WEB_OIDC_VERIFY_EXP=1`.

Optional local callback mocking:

```bash
export ALDE_WEB_OIDC_DEV_MOCK=1
# then call callback with code pattern:
# mock-<sub>-<email>-<name>-<group1|group2>
```

## External queue worker (Redis/RQ)

Default behavior uses an in-process worker thread. For production scale-out, switch to Redis/RQ:

```bash
export ALDE_WEB_QUEUE_BACKEND=rq
export ALDE_WEB_REDIS_URL='redis://localhost:6379/0'
export ALDE_WEB_RQ_QUEUE='alde-agent-runs'
export ALDE_WEB_RQ_JOB_TIMEOUT_SECONDS=120
export ALDE_WEB_RQ_RESULT_TTL_SECONDS=600
export ALDE_WEB_RQ_FAILURE_TTL_SECONDS=86400
export ALDE_WEB_RQ_RETRY_MAX=2
export ALDE_WEB_RQ_RETRY_INTERVALS='2,5'
```

Start API and worker separately:

```bash
uvicorn alde.webapp.main:app --reload --port 8080
python -m alde.webapp.rq_worker
```

If Redis is unavailable, enqueue falls back to the in-process worker to avoid request loss.

## Queue benchmark and multi-worker test

Run benchmark with auto-managed local `redislite` backend:

```bash
python -m alde.webapp.benchmark_queue --workers 2 --jobs 40 --output-json AppData/generated/queue_bench_w2.json
```

Run larger multi-worker profile:

```bash
python -m alde.webapp.benchmark_queue --workers 4 --jobs 120 --timeout-seconds 180 --output-json AppData/generated/queue_bench_w4.json
```

Use an external Redis URL explicitly:

```bash
python -m alde.webapp.benchmark_queue --redis-url 'redis://localhost:6379/0' --workers 4 --jobs 120
```

## Important note

Persistence is SQLAlchemy-backed and migration-ready. For production, use PostgreSQL with strict backup, retention, and regular migration rollouts.
2. Redirect user to returned `authorization_url`
3. Provider redirects to `GET /api/v1/auth/oidc/callback?state=...&code=...`

Role mapping from OIDC claims:


Security validation details:


Optional local callback mocking:

```bash
export ALDE_WEB_OIDC_DEV_MOCK=1
# then call callback with code pattern:
# mock-<sub>-<email>-<name>-<group1|group2>
```

## External queue worker (Redis/RQ)

Default behavior uses an in-process worker thread. For production scale-out, switch to Redis/RQ:

```bash
export ALDE_WEB_QUEUE_BACKEND=rq
export ALDE_WEB_REDIS_URL='redis://localhost:6379/0'
export ALDE_WEB_RQ_QUEUE='alde-agent-runs'
export ALDE_WEB_RQ_JOB_TIMEOUT_SECONDS=120
export ALDE_WEB_RQ_RESULT_TTL_SECONDS=600
export ALDE_WEB_RQ_FAILURE_TTL_SECONDS=86400
export ALDE_WEB_RQ_RETRY_MAX=2
export ALDE_WEB_RQ_RETRY_INTERVALS='2,5'
```

Start API and worker separately:

```bash
uvicorn alde.webapp.main:app --reload --port 8080
python -m alde.webapp.rq_worker
```

If Redis is unavailable, enqueue falls back to the in-process worker to avoid request loss.

## Queue benchmark and multi-worker test

Run benchmark with auto-managed local `redislite` backend:

```bash
python -m alde.webapp.benchmark_queue --workers 2 --jobs 40 --output-json AppData/generated/queue_bench_w2.json
```

Run larger multi-worker profile:

```bash
python -m alde.webapp.benchmark_queue --workers 4 --jobs 120 --timeout-seconds 180 --output-json AppData/generated/queue_bench_w4.json
```

Use an external Redis URL explicitly:

```bash
python -m alde.webapp.benchmark_queue --redis-url 'redis://localhost:6379/0' --workers 4 --jobs 120
```

## Important note

Persistence is SQLAlchemy-backed and migration-ready. For production, use PostgreSQL with strict backup/retention and regular migration rollouts.

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the ALDE web backend."""

    app_name: str = os.getenv("ALDE_WEB_APP_NAME", "ALDE Workflow Control Plane")
    api_prefix: str = os.getenv("ALDE_WEB_API_PREFIX", "/api/v1")
    token_ttl_minutes: int = int(os.getenv("ALDE_WEB_TOKEN_TTL_MIN", "60"))
    token_secret: str = os.getenv("ALDE_WEB_TOKEN_SECRET", "change-me-in-production")
    allow_dev_bootstrap: bool = os.getenv("ALDE_WEB_ALLOW_DEV_BOOTSTRAP", "1") == "1"
    database_url: str = os.getenv("ALDE_WEB_DATABASE_URL", "sqlite:///./AppData/alde_web.db")
    oidc_issuer: str = os.getenv("ALDE_WEB_OIDC_ISSUER", "")
    oidc_client_id: str = os.getenv("ALDE_WEB_OIDC_CLIENT_ID", "")
    oidc_client_secret: str = os.getenv("ALDE_WEB_OIDC_CLIENT_SECRET", "")
    oidc_redirect_uri: str = os.getenv("ALDE_WEB_OIDC_REDIRECT_URI", "http://localhost:8080/api/v1/auth/oidc/callback")
    oidc_scope: str = os.getenv("ALDE_WEB_OIDC_SCOPE", "openid profile email")
    oidc_authorize_endpoint: str = os.getenv("ALDE_WEB_OIDC_AUTHORIZE_ENDPOINT", "")
    oidc_token_endpoint: str = os.getenv("ALDE_WEB_OIDC_TOKEN_ENDPOINT", "")
    oidc_userinfo_endpoint: str = os.getenv("ALDE_WEB_OIDC_USERINFO_ENDPOINT", "")
    oidc_admin_groups: str = os.getenv("ALDE_WEB_OIDC_ADMIN_GROUPS", "alde-admin,tenant-admin")
    oidc_admin_email_domains: str = os.getenv("ALDE_WEB_OIDC_ADMIN_EMAIL_DOMAINS", "")
    oidc_dev_mock: bool = os.getenv("ALDE_WEB_OIDC_DEV_MOCK", "0") == "1"
    oidc_jwks_url: str = os.getenv("ALDE_WEB_OIDC_JWKS_URL", "")
    oidc_audience: str = os.getenv("ALDE_WEB_OIDC_AUDIENCE", "")
    oidc_verify_exp: bool = os.getenv("ALDE_WEB_OIDC_VERIFY_EXP", "1") == "1"
    refresh_token_ttl_days: int = int(os.getenv("ALDE_WEB_REFRESH_TTL_DAYS", "14"))

    # Comma-separated allow-lists for role-based access control.
    rbac_member_agents: str = os.getenv("ALDE_WEB_RBAC_MEMBER_AGENTS", "_primary_assistant,_data_dispatcher")
    rbac_member_tools: str = os.getenv("ALDE_WEB_RBAC_MEMBER_TOOLS", "")
    queue_backend: str = os.getenv("ALDE_WEB_QUEUE_BACKEND", "inmemory").strip().lower()
    redis_url: str = os.getenv("ALDE_WEB_REDIS_URL", "redis://localhost:6379/0")
    rq_queue_name: str = os.getenv("ALDE_WEB_RQ_QUEUE", "alde-agent-runs")
    rq_job_timeout_seconds: int = int(os.getenv("ALDE_WEB_RQ_JOB_TIMEOUT_SECONDS", "120"))
    rq_result_ttl_seconds: int = int(os.getenv("ALDE_WEB_RQ_RESULT_TTL_SECONDS", "600"))
    rq_failure_ttl_seconds: int = int(os.getenv("ALDE_WEB_RQ_FAILURE_TTL_SECONDS", "86400"))
    rq_retry_max: int = int(os.getenv("ALDE_WEB_RQ_RETRY_MAX", "2"))
    rq_retry_intervals: str = os.getenv("ALDE_WEB_RQ_RETRY_INTERVALS", "2,5")


settings = Settings()

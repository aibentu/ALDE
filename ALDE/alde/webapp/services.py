from __future__ import annotations

from datetime import datetime, UTC
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from .models import AgentRun
from .repository import repo
from .security import hash_refresh_token, issue_access_token, issue_refresh_token
from .config import settings


_JWKS_CLIENT: PyJWKClient | None = None


def register_tenant(
    *,
    slug: str,
    name: str,
    admin_subject: str,
    admin_email: str,
    admin_display_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    tenant = repo.create_tenant(slug=slug, name=name)
    user = repo.upsert_user(
        tenant_id=tenant.id,
        subject=admin_subject,
        email=admin_email,
        display_name=admin_display_name,
        role="tenant_admin",
    )
    repo.append_audit(
        tenant_id=tenant.id,
        user_id=user.id,
        event_type="tenant.registered",
        detail={"slug": tenant.slug, "name": tenant.name},
    )
    token, exp = issue_access_token(
        tenant_id=tenant.id,
        user_id=user.id,
        subject=user.subject,
        email=user.email,
        role=user.role,
    )
    refresh_token, refresh_exp = _issue_refresh_session(tenant_id=tenant.id, user_id=user.id)
    return (
        repo.asdict_tenant(tenant),
        repo.asdict_user(user),
        {
            "access_token": token,
            "expires_at": exp,
            "tenant_id": tenant.id,
            "user_id": user.id,
            "refresh_token": refresh_token,
            "refresh_expires_at": refresh_exp,
        },
    )


def sso_login(
    *,
    tenant_slug: str,
    subject: str,
    email: str,
    display_name: str,
    role: str = "member",
) -> dict[str, Any]:
    tenant = repo.get_tenant_by_slug(tenant_slug)
    if tenant is None:
        raise ValueError(f"Unknown tenant slug: {tenant_slug}")

    user = repo.upsert_user(
        tenant_id=tenant.id,
        subject=subject,
        email=email,
        display_name=display_name,
        role=role,
    )
    repo.append_audit(
        tenant_id=tenant.id,
        user_id=user.id,
        event_type="auth.sso_login",
        detail={"subject": subject, "email": email, "role": role},
    )
    token, exp = issue_access_token(
        tenant_id=tenant.id,
        user_id=user.id,
        subject=user.subject,
        email=user.email,
        role=user.role,
    )
    refresh_token, refresh_exp = _issue_refresh_session(tenant_id=tenant.id, user_id=user.id)
    return {
        "access_token": token,
        "expires_at": exp,
        "tenant_id": tenant.id,
        "user_id": user.id,
        "refresh_token": refresh_token,
        "refresh_expires_at": refresh_exp,
    }


def _get_jwks_client() -> PyJWKClient:
    global _JWKS_CLIENT
    if _JWKS_CLIENT is not None:
        return _JWKS_CLIENT

    jwks_url = settings.oidc_jwks_url
    if not jwks_url:
        issuer = settings.oidc_issuer.rstrip("/")
        jwks_url = f"{issuer}/protocol/openid-connect/certs"
    if not jwks_url:
        raise ValueError("OIDC JWKS URL is not configured")

    _JWKS_CLIENT = PyJWKClient(jwks_url)
    return _JWKS_CLIENT


def _verify_id_token(*, id_token: str) -> dict[str, Any]:
    audience = settings.oidc_audience or settings.oidc_client_id
    issuer = settings.oidc_issuer.rstrip("/") if settings.oidc_issuer else None
    if not audience:
        raise ValueError("OIDC audience/client id is missing")

    signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
        audience=audience,
        issuer=issuer,
        options={"verify_exp": settings.oidc_verify_exp},
    )
    return claims


def build_oidc_authorize_url(*, tenant_slug: str, state: str, nonce: str) -> str:
    authorize_endpoint = settings.oidc_authorize_endpoint
    if not authorize_endpoint:
        issuer = settings.oidc_issuer.rstrip("/")
        authorize_endpoint = f"{issuer}/protocol/openid-connect/auth"
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scope,
        "state": state,
        "nonce": nonce,
        "login_hint": tenant_slug,
    }
    return f"{authorize_endpoint}?{urlencode(params)}"


def exchange_oidc_code(*, code: str) -> dict[str, Any]:
    if settings.oidc_dev_mock and code.startswith("mock-"):
        # format: mock-<sub>-<email>-<name>-<group1|group2>
        parts = code.split("-", 4)
        sub = parts[1] if len(parts) > 1 else "mock-sub"
        email = parts[2] if len(parts) > 2 else "mock@example.local"
        name = parts[3] if len(parts) > 3 else "Mock User"
        groups = parts[4].split("|") if len(parts) > 4 and parts[4] else []
        return {"sub": sub, "email": email, "name": name, "groups": groups}

    token_endpoint = settings.oidc_token_endpoint
    if not token_endpoint:
        issuer = settings.oidc_issuer.rstrip("/")
        token_endpoint = f"{issuer}/protocol/openid-connect/token"

    if not token_endpoint or not settings.oidc_client_id:
        raise ValueError("OIDC endpoints or client configuration missing")

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
                "redirect_uri": settings.oidc_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        token_data = resp.json()
        id_token = token_data.get("id_token")
        if not id_token:
            raise ValueError("OIDC token response missing id_token")

        verified_claims = _verify_id_token(id_token=str(id_token))

        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("OIDC token response missing access_token")

        userinfo_endpoint = settings.oidc_userinfo_endpoint
        if not userinfo_endpoint:
            issuer = settings.oidc_issuer.rstrip("/")
            userinfo_endpoint = f"{issuer}/protocol/openid-connect/userinfo"

        user_resp = client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        userinfo = user_resp.json()

        merged = dict(verified_claims)
        merged.update({k: v for k, v in userinfo.items() if v is not None})
        return merged


def _extract_claim_groups(claims: dict[str, Any]) -> set[str]:
    groups: set[str] = set()

    raw_groups = claims.get("groups")
    if isinstance(raw_groups, list):
        groups.update(str(g).strip() for g in raw_groups if str(g).strip())

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles")
        if isinstance(roles, list):
            groups.update(str(r).strip() for r in roles if str(r).strip())

    return groups


def role_from_oidc_claims(*, claims: dict[str, Any], email: str) -> str:
    admin_groups = {g.strip() for g in settings.oidc_admin_groups.split(",") if g.strip()}
    admin_domains = {d.strip().lower() for d in settings.oidc_admin_email_domains.split(",") if d.strip()}

    claim_groups = {g.lower() for g in _extract_claim_groups(claims)}
    if any(group.lower() in claim_groups for group in admin_groups):
        return "tenant_admin"

    if "@" in email:
        domain = email.split("@", 1)[1].lower()
        if domain in admin_domains:
            return "tenant_admin"

    return "member"


def oidc_callback_login(*, tenant_slug: str, state: str, code: str) -> dict[str, Any]:
    consumed = repo.consume_oidc_state_by_state(state=state)
    if consumed is None:
        raise ValueError("Invalid OIDC state")

    state_tenant_slug, _nonce = consumed
    tenant_slug = tenant_slug.strip().lower() if tenant_slug else state_tenant_slug
    if tenant_slug != state_tenant_slug:
        raise ValueError("OIDC state tenant mismatch")

    claims = exchange_oidc_code(code=code)
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    display_name = str(claims.get("name") or claims.get("preferred_username") or email).strip()
    if not subject or not email:
        raise ValueError("OIDC claims missing sub/email")

    role = role_from_oidc_claims(claims=claims, email=email)
    return sso_login(
        tenant_slug=tenant_slug,
        subject=subject,
        email=email,
        display_name=display_name,
        role=role,
    )


def _issue_refresh_session(*, tenant_id: str, user_id: str) -> tuple[str, int]:
    token = issue_refresh_token()
    token_hash = hash_refresh_token(token)
    expiry_dt = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
    repo.create_auth_session(
        tenant_id=tenant_id,
        user_id=user_id,
        refresh_token_hash=token_hash,
        expires_at=expiry_dt,
    )
    return token, int(expiry_dt.timestamp())


def refresh_access_token(*, refresh_token: str) -> dict[str, Any]:
    token_hash = hash_refresh_token(refresh_token)
    session = repo.get_active_auth_session_by_refresh_hash(refresh_token_hash=token_hash)
    if session is None:
        raise ValueError("Refresh session not found or revoked")

    now = datetime.now(UTC)
    expires_at = session["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        repo.revoke_auth_session(session_id=session["session_id"])
        raise ValueError("Refresh session expired")

    tenant_id = session["tenant_id"]
    user_id = session["user_id"]
    user_row = repo.get_user_by_id(tenant_id=tenant_id, user_id=user_id)
    if user_row is None:
        raise ValueError("User not found")

    access_token, access_exp = issue_access_token(
        tenant_id=tenant_id,
        user_id=user_id,
        subject=user_row["subject"],
        email=user_row["email"],
        role=user_row["role"],
    )
    new_refresh_token = issue_refresh_token()
    new_refresh_hash = hash_refresh_token(new_refresh_token)
    new_exp_dt = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
    ok = repo.rotate_auth_session(
        session_id=session["session_id"],
        refresh_token_hash=new_refresh_hash,
        expires_at=new_exp_dt,
    )
    if not ok:
        raise ValueError("Refresh session rotation failed")

    repo.append_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="auth.refresh",
        detail={"session_id": session["session_id"]},
    )
    return {
        "access_token": access_token,
        "expires_at": access_exp,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "refresh_token": new_refresh_token,
        "refresh_expires_at": int(new_exp_dt.timestamp()),
    }


def revoke_refresh_session(*, refresh_token: str) -> bool:
    token_hash = hash_refresh_token(refresh_token)
    session = repo.get_active_auth_session_by_refresh_hash(refresh_token_hash=token_hash)
    if session is None:
        return False
    ok = repo.revoke_auth_session(session_id=session["session_id"])
    if ok:
        repo.append_audit(
            tenant_id=session["tenant_id"],
            user_id=session["user_id"],
            event_type="auth.logout",
            detail={"session_id": session["session_id"]},
        )
    return ok


def _call_agent_runtime(target_agent: str, prompt: str) -> str:
    """Run the existing ALDE agent runtime with a robust fallback path."""
    try:
        from alde.agents_factory import execute_route_to_agent  # type: ignore

        message, route = execute_route_to_agent(
            {"target_agent": target_agent, "user_question": prompt},
        )
        if route is None:
            return message
        return f"{message}. Prepared routing payload for {route.get('agent_label', target_agent)}"
    except Exception as exc:
        return (
            "Agent runtime fallback path activated. "
            f"target={target_agent}; reason={type(exc).__name__}: {exc}"
        )


def run_agent(
    *,
    tenant_id: str,
    user_id: str,
    target_agent: str,
    prompt: str,
    metadata: dict[str, Any],
) -> AgentRun:
    output = _call_agent_runtime(target_agent=target_agent, prompt=prompt)
    run = AgentRun(
        tenant_id=tenant_id,
        user_id=user_id,
        target_agent=target_agent,
        prompt=prompt,
        status="completed",
        output=output,
        metadata={
            **metadata,
            "executed_at": datetime.now(UTC).isoformat(),
        },
    )
    return repo.store_run(run)


def queue_agent_run(*, tenant_id: str, user_id: str, target_agent: str, prompt: str, metadata: dict[str, Any]) -> tuple[str, str]:
    run = repo.create_run_placeholder(
        tenant_id=tenant_id,
        user_id=user_id,
        target_agent=target_agent,
        prompt=prompt,
        metadata={**metadata, "queued_at": datetime.now(UTC).isoformat()},
    )
    job_id = repo.create_async_job(tenant_id=tenant_id, user_id=user_id, run_id=run.id)
    repo.append_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="agent.run_queued",
        detail={"job_id": job_id, "run_id": run.id, "target_agent": target_agent},
    )
    return job_id, run.id


def get_run_status(*, tenant_id: str, run_id: str) -> AgentRun | None:
    return repo.get_run(tenant_id=tenant_id, run_id=run_id)


def get_job_status(*, tenant_id: str, job_id: str) -> dict | None:
    return repo.get_async_job(tenant_id=tenant_id, job_id=job_id)


def list_audit_events(*, tenant_id: str, limit: int = 100) -> list[dict]:
    return repo.list_audit(tenant_id=tenant_id, limit=limit)

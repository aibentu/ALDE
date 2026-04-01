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
from ..runtime_core import AgentRuntimeCoreService
from .security import hash_refresh_token, issue_access_token, issue_refresh_token
from .config import settings


_JWKS_CLIENT: PyJWKClient | None = None


class OidcIdentityService:
    def load_jwks_client(self) -> PyJWKClient:
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

    def verify_id_token(self, *, id_token: str) -> dict[str, Any]:
        audience = settings.oidc_audience or settings.oidc_client_id
        issuer = settings.oidc_issuer.rstrip("/") if settings.oidc_issuer else None
        if not audience:
            raise ValueError("OIDC audience/client id is missing")

        signing_key = self.load_jwks_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=audience,
            issuer=issuer,
            options={"verify_exp": settings.oidc_verify_exp},
        )
        return claims

    def build_authorize_url(self, *, tenant_slug: str, state: str, nonce: str) -> str:
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

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        if settings.oidc_dev_mock and code.startswith("mock-"):
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

            verified_claims = self.verify_id_token(id_token=str(id_token))

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

    def extract_claim_groups(self, claims: dict[str, Any]) -> set[str]:
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

    def resolve_role_from_claims(self, *, claims: dict[str, Any], email: str) -> str:
        admin_groups = {g.strip() for g in settings.oidc_admin_groups.split(",") if g.strip()}
        admin_domains = {d.strip().lower() for d in settings.oidc_admin_email_domains.split(",") if d.strip()}

        claim_groups = {g.lower() for g in self.extract_claim_groups(claims)}
        if any(group.lower() in claim_groups for group in admin_groups):
            return "tenant_admin"

        if "@" in email:
            domain = email.split("@", 1)[1].lower()
            if domain in admin_domains:
                return "tenant_admin"

        return "member"


class AuthSessionService:
    def issue_refresh_session(self, *, tenant_id: str, user_id: str) -> tuple[str, int]:
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

    def issue_user_tokens(
        self,
        *,
        tenant_id: str,
        user_id: str,
        subject: str,
        email: str,
        role: str,
    ) -> dict[str, Any]:
        access_token, access_exp = issue_access_token(
            tenant_id=tenant_id,
            user_id=user_id,
            subject=subject,
            email=email,
            role=role,
        )
        refresh_token, refresh_exp = self.issue_refresh_session(tenant_id=tenant_id, user_id=user_id)
        return {
            "access_token": access_token,
            "expires_at": access_exp,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "refresh_token": refresh_token,
            "refresh_expires_at": refresh_exp,
        }

    def append_auth_audit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        event_type: str,
        detail: dict[str, Any],
    ) -> None:
        repo.append_audit(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            detail=detail,
        )

    def register_object_tenant(
        self,
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
        self.append_auth_audit(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type="tenant.registered",
            detail={"slug": tenant.slug, "name": tenant.name},
        )
        return (
            repo.asdict_tenant(tenant),
            repo.asdict_user(user),
            self.issue_user_tokens(
                tenant_id=tenant.id,
                user_id=user.id,
                subject=user.subject,
                email=user.email,
                role=user.role,
            ),
        )

    def login_object_sso(
        self,
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
        self.append_auth_audit(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type="auth.sso_login",
            detail={"subject": subject, "email": email, "role": role},
        )
        return self.issue_user_tokens(
            tenant_id=tenant.id,
            user_id=user.id,
            subject=user.subject,
            email=user.email,
            role=user.role,
        )

    def login_object_oidc_callback(self, *, tenant_slug: str, state: str, code: str) -> dict[str, Any]:
        consumed = repo.consume_oidc_state_by_state(state=state)
        if consumed is None:
            raise ValueError("Invalid OIDC state")

        state_tenant_slug, _nonce = consumed
        tenant_slug = tenant_slug.strip().lower() if tenant_slug else state_tenant_slug
        if tenant_slug != state_tenant_slug:
            raise ValueError("OIDC state tenant mismatch")

        claims = OIDC_IDENTITY_SERVICE.exchange_code(code=code)
        subject = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip().lower()
        display_name = str(claims.get("name") or claims.get("preferred_username") or email).strip()
        if not subject or not email:
            raise ValueError("OIDC claims missing sub/email")

        role = OIDC_IDENTITY_SERVICE.resolve_role_from_claims(claims=claims, email=email)
        return self.login_object_sso(
            tenant_slug=tenant_slug,
            subject=subject,
            email=email,
            display_name=display_name,
            role=role,
        )

    def refresh_object_access_token(self, *, refresh_token: str) -> dict[str, Any]:
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

        self.append_auth_audit(
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

    def revoke_object_refresh_session(self, *, refresh_token: str) -> bool:
        token_hash = hash_refresh_token(refresh_token)
        session = repo.get_active_auth_session_by_refresh_hash(refresh_token_hash=token_hash)
        if session is None:
            return False
        ok = repo.revoke_auth_session(session_id=session["session_id"])
        if ok:
            self.append_auth_audit(
                tenant_id=session["tenant_id"],
                user_id=session["user_id"],
                event_type="auth.logout",
                detail={"session_id": session["session_id"]},
            )
        return ok


OIDC_IDENTITY_SERVICE = OidcIdentityService()
AUTH_SESSION_SERVICE = AuthSessionService()


class AuthenticationFacadeService:
    def register_object_tenant(
        self,
        *,
        slug: str,
        name: str,
        admin_subject: str,
        admin_email: str,
        admin_display_name: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return AUTH_SESSION_SERVICE.register_object_tenant(
            slug=slug,
            name=name,
            admin_subject=admin_subject,
            admin_email=admin_email,
            admin_display_name=admin_display_name,
        )

    def login_object_sso(
        self,
        *,
        tenant_slug: str,
        subject: str,
        email: str,
        display_name: str,
        role: str = "member",
    ) -> dict[str, Any]:
        return AUTH_SESSION_SERVICE.login_object_sso(
            tenant_slug=tenant_slug,
            subject=subject,
            email=email,
            display_name=display_name,
            role=role,
        )

    def load_jwks_client(self) -> PyJWKClient:
        return OIDC_IDENTITY_SERVICE.load_jwks_client()

    def verify_object_id_token(self, *, id_token: str) -> dict[str, Any]:
        return OIDC_IDENTITY_SERVICE.verify_id_token(id_token=id_token)

    def build_object_authorize_url(self, *, tenant_slug: str, state: str, nonce: str) -> str:
        return OIDC_IDENTITY_SERVICE.build_authorize_url(tenant_slug=tenant_slug, state=state, nonce=nonce)

    def exchange_object_code(self, *, code: str) -> dict[str, Any]:
        return OIDC_IDENTITY_SERVICE.exchange_code(code=code)

    def extract_object_claim_groups(self, claims: dict[str, Any]) -> set[str]:
        return OIDC_IDENTITY_SERVICE.extract_claim_groups(claims)

    def resolve_object_role_from_claims(self, *, claims: dict[str, Any], email: str) -> str:
        return OIDC_IDENTITY_SERVICE.resolve_role_from_claims(claims=claims, email=email)

    def login_object_oidc_callback(self, *, tenant_slug: str, state: str, code: str) -> dict[str, Any]:
        return AUTH_SESSION_SERVICE.login_object_oidc_callback(tenant_slug=tenant_slug, state=state, code=code)

    def issue_object_refresh_session(self, *, tenant_id: str, user_id: str) -> tuple[str, int]:
        return AUTH_SESSION_SERVICE.issue_refresh_session(tenant_id=tenant_id, user_id=user_id)

    def refresh_object_access_token(self, *, refresh_token: str) -> dict[str, Any]:
        return AUTH_SESSION_SERVICE.refresh_object_access_token(refresh_token=refresh_token)

    def revoke_object_refresh_session(self, *, refresh_token: str) -> bool:
        return AUTH_SESSION_SERVICE.revoke_object_refresh_session(refresh_token=refresh_token)


AUTHENTICATION_FACADE_SERVICE = AuthenticationFacadeService()


class WebappPublicFacadeService:
    def register_object_tenant(
        self,
        *,
        slug: str,
        name: str,
        admin_subject: str,
        admin_email: str,
        admin_display_name: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return AUTHENTICATION_FACADE_SERVICE.register_object_tenant(
            slug=slug,
            name=name,
            admin_subject=admin_subject,
            admin_email=admin_email,
            admin_display_name=admin_display_name,
        )

    def login_object_sso(
        self,
        *,
        tenant_slug: str,
        subject: str,
        email: str,
        display_name: str,
        role: str = "member",
    ) -> dict[str, Any]:
        return AUTHENTICATION_FACADE_SERVICE.login_object_sso(
            tenant_slug=tenant_slug,
            subject=subject,
            email=email,
            display_name=display_name,
            role=role,
        )

    def load_jwks_client(self) -> PyJWKClient:
        return AUTHENTICATION_FACADE_SERVICE.load_jwks_client()

    def verify_object_id_token(self, *, id_token: str) -> dict[str, Any]:
        return AUTHENTICATION_FACADE_SERVICE.verify_object_id_token(id_token=id_token)

    def build_object_authorize_url(self, *, tenant_slug: str, state: str, nonce: str) -> str:
        return AUTHENTICATION_FACADE_SERVICE.build_object_authorize_url(
            tenant_slug=tenant_slug,
            state=state,
            nonce=nonce,
        )

    def exchange_object_code(self, *, code: str) -> dict[str, Any]:
        return AUTHENTICATION_FACADE_SERVICE.exchange_object_code(code=code)

    def extract_object_claim_groups(self, claims: dict[str, Any]) -> set[str]:
        return AUTHENTICATION_FACADE_SERVICE.extract_object_claim_groups(claims)

    def resolve_object_role_from_claims(self, *, claims: dict[str, Any], email: str) -> str:
        return AUTHENTICATION_FACADE_SERVICE.resolve_object_role_from_claims(claims=claims, email=email)

    def login_object_oidc_callback(self, *, tenant_slug: str, state: str, code: str) -> dict[str, Any]:
        return AUTHENTICATION_FACADE_SERVICE.login_object_oidc_callback(
            tenant_slug=tenant_slug,
            state=state,
            code=code,
        )

    def issue_object_refresh_session(self, *, tenant_id: str, user_id: str) -> tuple[str, int]:
        return AUTHENTICATION_FACADE_SERVICE.issue_object_refresh_session(tenant_id=tenant_id, user_id=user_id)

    def refresh_object_access_token(self, *, refresh_token: str) -> dict[str, Any]:
        return AUTHENTICATION_FACADE_SERVICE.refresh_object_access_token(refresh_token=refresh_token)

    def revoke_object_refresh_session(self, *, refresh_token: str) -> bool:
        return AUTHENTICATION_FACADE_SERVICE.revoke_object_refresh_session(refresh_token=refresh_token)

    def load_workflow_status_view(
        self,
        *,
        target_agent: str | None = None,
        thread_id: int | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        return WEBAPP_OPERATIONS_FACADE_SERVICE.load_workflow_status_view(
            target_agent=target_agent,
            thread_id=thread_id,
            limit=limit,
        )

    def run_object_agent(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> AgentRun:
        return WEBAPP_OPERATIONS_FACADE_SERVICE.run_object_agent(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            metadata=metadata,
        )

    def queue_object_agent(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, str]:
        return WEBAPP_OPERATIONS_FACADE_SERVICE.queue_object_agent(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            metadata=metadata,
        )

    def load_run_status(self, *, tenant_id: str, run_id: str) -> AgentRun | None:
        return WEBAPP_OPERATIONS_FACADE_SERVICE.load_run_status(tenant_id=tenant_id, run_id=run_id)

    def load_job_status(self, *, tenant_id: str, job_id: str) -> dict | None:
        return WEBAPP_OPERATIONS_FACADE_SERVICE.load_job_status(tenant_id=tenant_id, job_id=job_id)

    def list_audit_events(self, *, tenant_id: str, limit: int = 100) -> list[dict]:
        return WEBAPP_OPERATIONS_FACADE_SERVICE.list_audit_events(tenant_id=tenant_id, limit=limit)


WEBAPP_PUBLIC_FACADE_SERVICE = WebappPublicFacadeService()


def register_tenant(
    *,
    slug: str,
    name: str,
    admin_subject: str,
    admin_email: str,
    admin_display_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.register_object_tenant(
        slug=slug,
        name=name,
        admin_subject=admin_subject,
        admin_email=admin_email,
        admin_display_name=admin_display_name,
    )


def sso_login(
    *,
    tenant_slug: str,
    subject: str,
    email: str,
    display_name: str,
    role: str = "member",
) -> dict[str, Any]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.login_object_sso(
        tenant_slug=tenant_slug,
        subject=subject,
        email=email,
        display_name=display_name,
        role=role,
    )


def _get_jwks_client() -> PyJWKClient:
    return WEBAPP_PUBLIC_FACADE_SERVICE.load_jwks_client()


def _verify_id_token(*, id_token: str) -> dict[str, Any]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.verify_object_id_token(id_token=id_token)


def build_oidc_authorize_url(*, tenant_slug: str, state: str, nonce: str) -> str:
    return WEBAPP_PUBLIC_FACADE_SERVICE.build_object_authorize_url(tenant_slug=tenant_slug, state=state, nonce=nonce)


def exchange_oidc_code(*, code: str) -> dict[str, Any]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.exchange_object_code(code=code)


def _extract_claim_groups(claims: dict[str, Any]) -> set[str]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.extract_object_claim_groups(claims)


def role_from_oidc_claims(*, claims: dict[str, Any], email: str) -> str:
    return WEBAPP_PUBLIC_FACADE_SERVICE.resolve_object_role_from_claims(claims=claims, email=email)


def oidc_callback_login(*, tenant_slug: str, state: str, code: str) -> dict[str, Any]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.login_object_oidc_callback(tenant_slug=tenant_slug, state=state, code=code)


def _issue_refresh_session(*, tenant_id: str, user_id: str) -> tuple[str, int]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.issue_object_refresh_session(tenant_id=tenant_id, user_id=user_id)


def refresh_access_token(*, refresh_token: str) -> dict[str, Any]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.refresh_object_access_token(refresh_token=refresh_token)


def revoke_refresh_session(*, refresh_token: str) -> bool:
    return WEBAPP_PUBLIC_FACADE_SERVICE.revoke_object_refresh_session(refresh_token=refresh_token)


class AgentRuntimeService(AgentRuntimeCoreService):
    def run_object(self, target_agent: str, prompt: str) -> str:
        """Run the existing ALDE agent runtime and return the final response text."""
        return self.run_chat_object(target_agent=target_agent, prompt=prompt)

    def store_object_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        output: str,
        metadata: dict[str, Any],
    ) -> AgentRun:
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


AGENT_RUNTIME_SERVICE = AgentRuntimeService()


def _call_agent_runtime(target_agent: str, prompt: str) -> str:
    return AGENT_RUNTIME_SERVICE.run_object(target_agent=target_agent, prompt=prompt)


class OperatorActivityViewService:
    def format_audit_item(self, entry: dict[str, Any]) -> dict[str, Any]:
        detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
        event_type = str(entry.get("event_type") or "audit.event")
        target_agent = str(detail.get("target_agent") or "")
        run_id = str(detail.get("run_id") or "")
        error = str(detail.get("error") or "")
        summary_parts = [part for part in [target_agent, run_id, error] if part]
        return {
            "timestamp": str(entry.get("created_at") or "n/a"),
            "source": "webapp",
            "kind": "audit_event",
            "title": event_type,
            "summary": " | ".join(summary_parts) or "webapp operator event",
            "status": event_type,
            "tenant_id": str(entry.get("tenant_id") or ""),
            "run_id": run_id,
            "target_agent": target_agent,
        }

    def load_activity_view(self, *, limit: int = 20) -> dict[str, Any]:
        items = [
            self.format_audit_item(entry)
            for entry in repo.list_recent_audit(limit=limit)
        ]
        return {
            "item_count": len(items),
            "items": items,
        }


OPERATOR_ACTIVITY_VIEW_SERVICE = OperatorActivityViewService()


def get_operator_activity_view(*, limit: int = 20) -> dict[str, Any]:
    return OPERATOR_ACTIVITY_VIEW_SERVICE.load_activity_view(limit=limit)


class WorkflowValidationService:
    def build_unavailable_report(self, exc: Exception) -> dict[str, Any]:
        return {
            "valid": False,
            "workflow_count": 0,
            "valid_count": 0,
            "invalid_count": 1,
            "mapping_errors": [f"workflow validation unavailable: {type(exc).__name__}: {exc}"],
            "workflows": [],
        }

    def load_report(self) -> dict[str, Any]:
        try:
            from alde.agents_config import validate_all_workflows  # type: ignore

            return validate_all_workflows()
        except Exception as exc:
            return self.build_unavailable_report(exc)


WORKFLOW_VALIDATION_SERVICE = WorkflowValidationService()


def get_workflow_validation_report() -> dict[str, Any]:
    return WORKFLOW_VALIDATION_SERVICE.load_report()


class WorkflowStatusViewService:
    def format_snapshot_view(self, workflow: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(workflow, dict):
            return None

        snapshot = workflow.get("snapshot") if isinstance(workflow.get("snapshot"), dict) else {}
        actor = snapshot.get("actor") if isinstance(snapshot.get("actor"), dict) else {}
        event = snapshot.get("event") if isinstance(snapshot.get("event"), dict) else {}
        workflow_name = str(snapshot.get("workflow_name") or workflow.get("workflow_name") or "").strip()
        current_state = str(snapshot.get("current_state") or workflow.get("current_state") or "").strip()
        actor_name = str(actor.get("name") or "").strip()
        event_name = str(event.get("name") or "").strip()

        if not workflow_name and not current_state and not actor_name and not event_name:
            return None

        tool_snapshot_config: dict[str, Any] = {}
        if actor_name:
            try:
                from alde.agents_config import get_tool_config  # type: ignore

                tool_snapshot_config = dict((get_tool_config(actor_name) or {}).get("snapshot_view") or {})
            except Exception:
                tool_snapshot_config = {}

        if tool_snapshot_config:
            action = str(event.get("action") or "").strip() or None
            correlation_id = str(event.get("correlation_id") or "").strip() or None
            summary_fields = [str(value) for value in (tool_snapshot_config.get("summary_fields") or []) if str(value).strip()]
            summary_values: list[str] = []
            for field_name in summary_fields:
                value = event.get(field_name)
                if value not in (None, "", [], {}):
                    summary_values.append(str(value).strip())
            return {
                "kind": str(tool_snapshot_config.get("kind") or "tool_action"),
                "title": str(tool_snapshot_config.get("title") or current_state or actor_name),
                "summary": " | ".join(summary_values) if summary_values else current_state or actor_name,
                "workflow_name": workflow_name,
                "state": current_state,
                "actor_name": actor_name,
                "action": action,
                "correlation_id": correlation_id,
                "event_name": event_name or None,
            }

        return {
            "kind": "workflow_state",
            "title": current_state or workflow_name or actor_name or event_name,
            "summary": actor_name or event_name or workflow_name,
            "workflow_name": workflow_name or None,
            "state": current_state or None,
            "actor_name": actor_name or None,
            "action": event.get("action"),
            "correlation_id": event.get("correlation_id"),
            "event_name": event_name or None,
        }

    def enrich_status_entry(self, entry: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return entry

        enriched = dict(entry)
        workflow = dict(enriched.get("workflow") or {})
        snapshot_view = self.format_snapshot_view(workflow)
        if snapshot_view is not None:
            workflow["snapshot_view"] = snapshot_view
        enriched["workflow"] = workflow
        return enriched

    def load_status_view(
        self,
        *,
        target_agent: str | None = None,
        thread_id: int | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        try:
            from alde.agents_factory import get_latest_workflow_status, get_workflow_history_entries  # type: ignore

            items = [
                self.enrich_status_entry(item)
                for item in get_workflow_history_entries(agent_label=target_agent, thread_id=thread_id, limit=limit)
            ]
            latest = self.enrich_status_entry(
                get_latest_workflow_status(agent_label=target_agent, thread_id=thread_id)
            )
            return {
                "latest": latest,
                "items": items,
                "validation": get_workflow_validation_report(),
            }
        except Exception as exc:
            return {
                "latest": None,
                "items": [],
                "validation": get_workflow_validation_report(),
                "error": f"workflow status unavailable: {type(exc).__name__}: {exc}",
            }


WORKFLOW_STATUS_VIEW_SERVICE = WorkflowStatusViewService()


def _format_workflow_snapshot_view(workflow: dict[str, Any] | None) -> dict[str, Any] | None:
    return WORKFLOW_STATUS_VIEW_SERVICE.format_snapshot_view(workflow)


def _enrich_workflow_status_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    return WORKFLOW_STATUS_VIEW_SERVICE.enrich_status_entry(entry)


def get_workflow_status_view(*, target_agent: str | None = None, thread_id: int | None = None, limit: int = 25) -> dict[str, Any]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.load_workflow_status_view(
        target_agent=target_agent,
        thread_id=thread_id,
        limit=limit,
    )


def run_agent(
    *,
    tenant_id: str,
    user_id: str,
    target_agent: str,
    prompt: str,
    metadata: dict[str, Any],
) -> AgentRun:
    return WEBAPP_PUBLIC_FACADE_SERVICE.run_object_agent(
        tenant_id=tenant_id,
        user_id=user_id,
        target_agent=target_agent,
        prompt=prompt,
        metadata=metadata,
    )


class AgentRunQueueService:
    def queue_object_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, str]:
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

    def load_run_status(self, *, tenant_id: str, run_id: str) -> AgentRun | None:
        return repo.get_run(tenant_id=tenant_id, run_id=run_id)

    def load_job_status(self, *, tenant_id: str, job_id: str) -> dict | None:
        return repo.get_async_job(tenant_id=tenant_id, job_id=job_id)

    def list_object_audit_events(self, *, tenant_id: str, limit: int = 100) -> list[dict]:
        return repo.list_audit(tenant_id=tenant_id, limit=limit)


AGENT_RUN_QUEUE_SERVICE = AgentRunQueueService()


class AgentRunLifecycleService:
    def run_object(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> AgentRun:
        output = _call_agent_runtime(target_agent=target_agent, prompt=prompt)
        return AGENT_RUNTIME_SERVICE.store_object_run(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            output=output,
            metadata=metadata,
        )

    def queue_object(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, str]:
        return AGENT_RUN_QUEUE_SERVICE.queue_object_run(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            metadata=metadata,
        )

    def load_run_status(self, *, tenant_id: str, run_id: str) -> AgentRun | None:
        return AGENT_RUN_QUEUE_SERVICE.load_run_status(tenant_id=tenant_id, run_id=run_id)

    def load_job_status(self, *, tenant_id: str, job_id: str) -> dict | None:
        return AGENT_RUN_QUEUE_SERVICE.load_job_status(tenant_id=tenant_id, job_id=job_id)

    def list_audit_entries(self, *, tenant_id: str, limit: int = 100) -> list[dict]:
        return AGENT_RUN_QUEUE_SERVICE.list_object_audit_events(tenant_id=tenant_id, limit=limit)


AGENT_RUN_LIFECYCLE_SERVICE = AgentRunLifecycleService()


class WebappOperationsFacadeService:
    def load_workflow_status_view(
        self,
        *,
        target_agent: str | None = None,
        thread_id: int | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        return WORKFLOW_STATUS_VIEW_SERVICE.load_status_view(
            target_agent=target_agent,
            thread_id=thread_id,
            limit=limit,
        )

    def run_object_agent(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> AgentRun:
        return AGENT_RUN_LIFECYCLE_SERVICE.run_object(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            metadata=metadata,
        )

    def queue_object_agent(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, str]:
        return AGENT_RUN_LIFECYCLE_SERVICE.queue_object(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            metadata=metadata,
        )

    def load_run_status(self, *, tenant_id: str, run_id: str) -> AgentRun | None:
        return AGENT_RUN_LIFECYCLE_SERVICE.load_run_status(tenant_id=tenant_id, run_id=run_id)

    def load_job_status(self, *, tenant_id: str, job_id: str) -> dict | None:
        return AGENT_RUN_LIFECYCLE_SERVICE.load_job_status(tenant_id=tenant_id, job_id=job_id)

    def list_audit_events(self, *, tenant_id: str, limit: int = 100) -> list[dict]:
        return AGENT_RUN_LIFECYCLE_SERVICE.list_audit_entries(tenant_id=tenant_id, limit=limit)

    def load_operator_activity_view(self, *, limit: int = 20) -> dict[str, Any]:
        return get_operator_activity_view(limit=limit)


WEBAPP_OPERATIONS_FACADE_SERVICE = WebappOperationsFacadeService()


def queue_agent_run(*, tenant_id: str, user_id: str, target_agent: str, prompt: str, metadata: dict[str, Any]) -> tuple[str, str]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.queue_object_agent(
        tenant_id=tenant_id,
        user_id=user_id,
        target_agent=target_agent,
        prompt=prompt,
        metadata=metadata,
    )


def get_run_status(*, tenant_id: str, run_id: str) -> AgentRun | None:
    return WEBAPP_PUBLIC_FACADE_SERVICE.load_run_status(tenant_id=tenant_id, run_id=run_id)


def get_job_status(*, tenant_id: str, job_id: str) -> dict | None:
    return WEBAPP_PUBLIC_FACADE_SERVICE.load_job_status(tenant_id=tenant_id, job_id=job_id)


def list_audit_events(*, tenant_id: str, limit: int = 100) -> list[dict]:
    return WEBAPP_PUBLIC_FACADE_SERVICE.list_audit_events(tenant_id=tenant_id, limit=limit)

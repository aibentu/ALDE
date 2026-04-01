from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, UTC

from sqlalchemy import desc, select

from .db import session_scope
from .entities import (
    AgentRunEntity,
    AsyncJobEntity,
    AuditEventEntity,
    AuthSessionEntity,
    OIDCStateEntity,
    TenantEntity,
    UserEntity,
)
from .models import AgentRun, Tenant, User


class SqlRepository:
    """Tenant-safe persistence and query layer backed by SQLAlchemy."""

    def create_tenant(self, slug: str, name: str) -> Tenant:
        with session_scope() as session:
            existing = session.scalar(select(TenantEntity).where(TenantEntity.slug == slug))
            if existing is not None:
                raise ValueError(f"Tenant already exists: {slug}")

            tenant = TenantEntity(slug=slug, name=name)
            session.add(tenant)
            session.flush()
            return Tenant(id=tenant.id, slug=tenant.slug, name=tenant.name, created_at=tenant.created_at)

    def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        with session_scope() as session:
            row = session.scalar(select(TenantEntity).where(TenantEntity.slug == slug))
            if row is None:
                return None
            return Tenant(id=row.id, slug=row.slug, name=row.name, created_at=row.created_at)

    def upsert_user(
        self,
        *,
        tenant_id: str,
        subject: str,
        email: str,
        display_name: str,
        role: str,
    ) -> User:
        with session_scope() as session:
            existing = session.scalar(
                select(UserEntity).where(UserEntity.tenant_id == tenant_id, UserEntity.subject == subject),
            )
            if existing is not None:
                existing.email = email
                existing.display_name = display_name
                existing.role = role
                session.flush()
                return User(
                    id=existing.id,
                    tenant_id=existing.tenant_id,
                    subject=existing.subject,
                    email=existing.email,
                    display_name=existing.display_name,
                    role=existing.role,
                    created_at=existing.created_at,
                )

            user = UserEntity(
                tenant_id=tenant_id,
                subject=subject,
                email=email,
                display_name=display_name,
                role=role,
            )
            session.add(user)
            session.flush()
            return User(
                id=user.id,
                tenant_id=user.tenant_id,
                subject=user.subject,
                email=user.email,
                display_name=user.display_name,
                role=user.role,
                created_at=user.created_at,
            )

    def store_run(self, run: AgentRun) -> AgentRun:
        with session_scope() as session:
            row = AgentRunEntity(
                id=run.id,
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                target_agent=run.target_agent,
                prompt=run.prompt,
                status=run.status,
                output=run.output,
                metadata_json=run.metadata,
                created_at=run.created_at,
            )
            session.add(row)
            session.flush()
            return run

    def create_run_placeholder(
        self,
        *,
        tenant_id: str,
        user_id: str,
        target_agent: str,
        prompt: str,
        metadata: dict,
    ) -> AgentRun:
        run = AgentRun(
            tenant_id=tenant_id,
            user_id=user_id,
            target_agent=target_agent,
            prompt=prompt,
            status="queued",
            output="",
            metadata=metadata,
        )
        return self.store_run(run)

    def update_run(self, *, run_id: str, status: str, output: str, metadata: dict) -> AgentRun | None:
        with session_scope() as session:
            row = session.scalar(select(AgentRunEntity).where(AgentRunEntity.id == run_id))
            if row is None:
                return None
            row.status = status
            row.output = output
            row.metadata_json = metadata
            session.flush()
            return AgentRun(
                id=row.id,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                target_agent=row.target_agent,
                prompt=row.prompt,
                status=row.status,
                output=row.output,
                metadata=row.metadata_json,
                created_at=row.created_at,
            )

    def get_run(self, *, tenant_id: str, run_id: str) -> AgentRun | None:
        with session_scope() as session:
            row = session.scalar(
                select(AgentRunEntity).where(AgentRunEntity.id == run_id, AgentRunEntity.tenant_id == tenant_id),
            )
            if row is None:
                return None
            return AgentRun(
                id=row.id,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                target_agent=row.target_agent,
                prompt=row.prompt,
                status=row.status,
                output=row.output,
                metadata=row.metadata_json,
                created_at=row.created_at,
            )

    def create_async_job(self, *, tenant_id: str, user_id: str, run_id: str) -> str:
        with session_scope() as session:
            job = AsyncJobEntity(tenant_id=tenant_id, user_id=user_id, run_id=run_id, status="queued")
            session.add(job)
            session.flush()
            return job.id

    def update_async_job(self, *, job_id: str, status: str, error: str | None = None) -> None:
        with session_scope() as session:
            row = session.scalar(select(AsyncJobEntity).where(AsyncJobEntity.id == job_id))
            if row is None:
                return
            row.status = status
            row.error = error
            row.updated_at = datetime.now(UTC)

    def get_async_job(self, *, tenant_id: str, job_id: str) -> dict | None:
        with session_scope() as session:
            row = session.scalar(
                select(AsyncJobEntity).where(AsyncJobEntity.id == job_id, AsyncJobEntity.tenant_id == tenant_id),
            )
            if row is None:
                return None
            return {
                "job_id": row.id,
                "run_id": row.run_id,
                "status": row.status,
                "error": row.error,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    def append_audit(self, *, tenant_id: str, user_id: str | None, event_type: str, detail: dict) -> None:
        with session_scope() as session:
            row = AuditEventEntity(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=event_type,
                detail_json=detail,
            )
            session.add(row)

    def list_audit(self, *, tenant_id: str, limit: int = 100) -> list[dict]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(AuditEventEntity)
                    .where(AuditEventEntity.tenant_id == tenant_id)
                    .order_by(desc(AuditEventEntity.created_at))
                    .limit(limit),
                ),
            )
            return [
                {
                    "id": r.id,
                    "tenant_id": r.tenant_id,
                    "user_id": r.user_id,
                    "event_type": r.event_type,
                    "detail": r.detail_json,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def list_recent_audit(self, *, limit: int = 100) -> list[dict]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(AuditEventEntity)
                    .order_by(desc(AuditEventEntity.created_at))
                    .limit(limit),
                ),
            )
            return [
                {
                    "id": r.id,
                    "tenant_id": r.tenant_id,
                    "user_id": r.user_id,
                    "event_type": r.event_type,
                    "detail": r.detail_json,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def save_oidc_state(self, *, tenant_slug: str, state: str, nonce: str) -> None:
        with session_scope() as session:
            row = OIDCStateEntity(tenant_slug=tenant_slug, state=state, nonce=nonce)
            session.add(row)

    def consume_oidc_state(self, *, tenant_slug: str, state: str) -> str | None:
        with session_scope() as session:
            row = session.scalar(
                select(OIDCStateEntity).where(OIDCStateEntity.state == state, OIDCStateEntity.tenant_slug == tenant_slug),
            )
            if row is None:
                return None
            nonce = row.nonce
            session.delete(row)
            session.flush()
            return nonce

    def consume_oidc_state_by_state(self, *, state: str) -> tuple[str, str] | None:
        with session_scope() as session:
            row = session.scalar(select(OIDCStateEntity).where(OIDCStateEntity.state == state))
            if row is None:
                return None
            tenant_slug = row.tenant_slug
            nonce = row.nonce
            session.delete(row)
            session.flush()
            return tenant_slug, nonce

    def asdict_tenant(self, tenant: Tenant) -> dict:
        return asdict(tenant)

    def asdict_user(self, user: User) -> dict:
        return asdict(user)

    def get_user_by_id(self, *, tenant_id: str, user_id: str) -> dict | None:
        with session_scope() as session:
            row = session.scalar(
                select(UserEntity).where(UserEntity.id == user_id, UserEntity.tenant_id == tenant_id),
            )
            if row is None:
                return None
            return {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "subject": row.subject,
                "email": row.email,
                "display_name": row.display_name,
                "role": row.role,
            }

    def create_auth_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> str:
        with session_scope() as session:
            row = AuthSessionEntity(
                tenant_id=tenant_id,
                user_id=user_id,
                refresh_token_hash=refresh_token_hash,
                expires_at=expires_at,
            )
            session.add(row)
            session.flush()
            return row.id

    def get_active_auth_session_by_refresh_hash(self, *, refresh_token_hash: str) -> dict | None:
        with session_scope() as session:
            row = session.scalar(
                select(AuthSessionEntity).where(
                    AuthSessionEntity.refresh_token_hash == refresh_token_hash,
                    AuthSessionEntity.revoked_at.is_(None),
                ),
            )
            if row is None:
                return None
            return {
                "session_id": row.id,
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "expires_at": row.expires_at,
            }

    def rotate_auth_session(
        self,
        *,
        session_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> bool:
        with session_scope() as session:
            row = session.scalar(
                select(AuthSessionEntity).where(AuthSessionEntity.id == session_id, AuthSessionEntity.revoked_at.is_(None)),
            )
            if row is None:
                return False
            row.refresh_token_hash = refresh_token_hash
            row.expires_at = expires_at
            session.flush()
            return True

    def revoke_auth_session(self, *, session_id: str) -> bool:
        with session_scope() as session:
            row = session.scalar(select(AuthSessionEntity).where(AuthSessionEntity.id == session_id))
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = datetime.now(UTC)
            session.flush()
            return True


repo = SqlRepository()

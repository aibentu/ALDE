"""create webapp tables

Revision ID: 20260221_0001
Revises: None
Create Date: 2026-02-21 18:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260221_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("tenant_id", sa.String(length=24), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
    op.create_index("ix_users_subject", "users", ["subject"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("tenant_id", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.String(length=24), nullable=False),
        sa.Column("target_agent", sa.String(length=128), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"], unique=False)
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"], unique=False)

    op.create_table(
        "async_jobs",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("tenant_id", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.String(length=24), nullable=False),
        sa.Column("run_id", sa.String(length=24), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_async_jobs_status", "async_jobs", ["status"], unique=False)
    op.create_index("ix_async_jobs_tenant_id", "async_jobs", ["tenant_id"], unique=False)
    op.create_index("ix_async_jobs_user_id", "async_jobs", ["user_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.String(length=24), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], unique=False)
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"], unique=False)
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"], unique=False)

    op.create_table(
        "oidc_states",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("tenant_slug", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_states_state", "oidc_states", ["state"], unique=True)
    op.create_index("ix_oidc_states_tenant_slug", "oidc_states", ["tenant_slug"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_oidc_states_tenant_slug", table_name="oidc_states")
    op.drop_index("ix_oidc_states_state", table_name="oidc_states")
    op.drop_table("oidc_states")

    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_async_jobs_user_id", table_name="async_jobs")
    op.drop_index("ix_async_jobs_tenant_id", table_name="async_jobs")
    op.drop_index("ix_async_jobs_status", table_name="async_jobs")
    op.drop_table("async_jobs")

    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_subject", table_name="users")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")

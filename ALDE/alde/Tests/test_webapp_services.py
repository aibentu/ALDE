from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

try:
    from alde.webapp import services
    _WEBAPP_SERVICES_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # optional module in some environments
    services = None
    _WEBAPP_SERVICES_IMPORT_ERROR = exc


@unittest.skipIf(
    services is None,
    f"alde.webapp.services unavailable: {_WEBAPP_SERVICES_IMPORT_ERROR}",
)
class TestWebappWorkflowStatusView(unittest.TestCase):
    def test_build_oidc_authorize_url_delegates_to_authentication_facade(self) -> None:
        with patch(
            "alde.webapp.services.AUTHENTICATION_FACADE_SERVICE.build_object_authorize_url",
            return_value="https://auth.example/authorize"
        ) as build_authorize_url:
            result = services.build_oidc_authorize_url(tenant_slug="acme", state="state-1", nonce="nonce-1")

        self.assertEqual(result, "https://auth.example/authorize")
        build_authorize_url.assert_called_once_with(tenant_slug="acme", state="state-1", nonce="nonce-1")

    def test_role_from_oidc_claims_delegates_to_authentication_facade(self) -> None:
        claims = {"groups": ["alde-admin"]}

        with patch(
            "alde.webapp.services.AUTHENTICATION_FACADE_SERVICE.resolve_object_role_from_claims",
            return_value="tenant_admin"
        ) as resolve_role:
            result = services.role_from_oidc_claims(claims=claims, email="admin@example.com")

        self.assertEqual(result, "tenant_admin")
        resolve_role.assert_called_once_with(claims=claims, email="admin@example.com")

    def test_call_agent_runtime_returns_fallback_text_on_runtime_error(self) -> None:
        with patch("alde.agents_config.normalize_agent_label", side_effect=RuntimeError("broken normalize")):
            result = services._call_agent_runtime(target_agent="_xworker", prompt="draft text")

        self.assertIn("Agent runtime fallback path activated.", result)
        self.assertIn("target=_xworker", result)
        self.assertIn("RuntimeError: broken normalize", result)

    def test_workflow_validation_report_returns_unavailable_report_on_error(self) -> None:
        with patch("alde.agents_config.validate_all_workflows", side_effect=RuntimeError("validation failed")):
            result = services.get_workflow_validation_report()

        self.assertFalse(result["valid"])
        self.assertEqual(result["workflow_count"], 0)
        self.assertIn("workflow validation unavailable", result["mapping_errors"][0])
        self.assertIn("RuntimeError: validation failed", result["mapping_errors"][0])

    def test_oidc_callback_login_delegates_claims_to_sso_login(self) -> None:
        claims = {"sub": "sub-1", "email": "admin@example.com", "name": "Admin User", "groups": ["alde-admin"]}

        with patch("alde.webapp.services.repo.consume_oidc_state_by_state", return_value=("acme", "nonce-1")), patch(
            "alde.webapp.services.OIDC_IDENTITY_SERVICE.exchange_code", return_value=claims
        ), patch(
            "alde.webapp.services.OIDC_IDENTITY_SERVICE.resolve_role_from_claims", return_value="tenant_admin"
        ), patch(
            "alde.webapp.services.AUTH_SESSION_SERVICE.login_object_sso", return_value={"access_token": "token"}
        ) as login_object_sso:
            result = services.oidc_callback_login(tenant_slug="acme", state="state-1", code="code-1")

        self.assertEqual(result["access_token"], "token")
        login_object_sso.assert_called_once_with(
            tenant_slug="acme",
            subject="sub-1",
            email="admin@example.com",
            display_name="Admin User",
            role="tenant_admin",
        )

    def test_revoke_refresh_session_logs_logout_when_revoked(self) -> None:
        session_row = {"session_id": "session-1", "tenant_id": "tenant-1", "user_id": "user-1"}

        with patch("alde.webapp.services.hash_refresh_token", return_value="hash-1"), patch(
            "alde.webapp.services.repo.get_active_auth_session_by_refresh_hash", return_value=session_row
        ), patch("alde.webapp.services.repo.revoke_auth_session", return_value=True), patch(
            "alde.webapp.services.repo.append_audit"
        ) as append_audit:
            result = services.revoke_refresh_session(refresh_token="refresh-token-1")

        self.assertTrue(result)
        append_audit.assert_called_once()

    def test_register_tenant_creates_admin_and_tokens(self) -> None:
        tenant = SimpleNamespace(id="tenant-1", slug="acme", name="Acme")
        user = SimpleNamespace(id="user-1", subject="sub-1", email="admin@example.com", role="tenant_admin")

        with patch("alde.webapp.services.repo.create_tenant", return_value=tenant), patch(
            "alde.webapp.services.repo.upsert_user", return_value=user
        ), patch("alde.webapp.services.repo.append_audit") as append_audit, patch(
            "alde.webapp.services.issue_access_token", return_value=("access-token", 111)
        ), patch("alde.webapp.services.AUTH_SESSION_SERVICE.issue_refresh_session", return_value=("refresh-token", 222)), patch(
            "alde.webapp.services.repo.asdict_tenant", return_value={"id": "tenant-1", "slug": "acme"}
        ), patch("alde.webapp.services.repo.asdict_user", return_value={"id": "user-1", "email": "admin@example.com"}):
            tenant_data, user_data, tokens = services.register_tenant(
                slug="acme",
                name="Acme",
                admin_subject="sub-1",
                admin_email="admin@example.com",
                admin_display_name="Admin",
            )

        self.assertEqual(tenant_data["slug"], "acme")
        self.assertEqual(user_data["email"], "admin@example.com")
        self.assertEqual(tokens["access_token"], "access-token")
        self.assertEqual(tokens["refresh_token"], "refresh-token")
        append_audit.assert_called_once()

    def test_register_tenant_delegates_to_public_facade(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_register_tenant(**kwargs: object) -> dict[str, object]:
            calls.append(("register_object_tenant", kwargs))
            return {"tenant_id": "tenant-42"}

        with patch.object(
            services.WEBAPP_PUBLIC_FACADE_SERVICE,
            "register_object_tenant",
            side_effect=fake_register_tenant,
        ):
            result = services.register_tenant(
                slug="alde",
                name="ALDE",
                admin_subject="sub-1",
                admin_email="admin@example.com",
                admin_display_name="Admin",
            )

        assert result == {"tenant_id": "tenant-42"}
        assert calls == [
            (
                "register_object_tenant",
                {
                    "slug": "alde",
                    "name": "ALDE",
                    "admin_subject": "sub-1",
                    "admin_email": "admin@example.com",
                    "admin_display_name": "Admin",
                },
            )
        ]

    def test_queue_agent_run_delegates_to_public_facade(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_queue_agent_run(**kwargs: object) -> dict[str, object]:
            calls.append(("queue_object_agent", kwargs))
            return {"run_id": "run-42", "status": "queued"}

        with patch.object(
            services.WEBAPP_PUBLIC_FACADE_SERVICE,
            "queue_object_agent",
            side_effect=fake_queue_agent_run,
        ):
            result = services.queue_agent_run(
                tenant_id="tenant-1",
                user_id="user-1",
                target_agent="_xworker",
                prompt="hello",
                metadata={"idempotency_key": "key-42"},
            )

        assert result == {"run_id": "run-42", "status": "queued"}
        assert calls == [
            (
                "queue_object_agent",
                {
                    "tenant_id": "tenant-1",
                    "user_id": "user-1",
                    "target_agent": "_xworker",
                    "prompt": "hello",
                    "metadata": {"idempotency_key": "key-42"},
                },
            )
        ]

    def test_refresh_access_token_rotates_session_and_logs_audit(self) -> None:
        future_expiry = datetime.now(UTC) + timedelta(days=1)
        session_row = {
            "session_id": "session-1",
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "expires_at": future_expiry,
        }
        user_row = {"subject": "sub-1", "email": "user@example.com", "role": "member"}

        with patch("alde.webapp.services.hash_refresh_token", return_value="hash-1"), patch(
            "alde.webapp.services.repo.get_active_auth_session_by_refresh_hash", return_value=session_row
        ), patch("alde.webapp.services.repo.get_user_by_id", return_value=user_row), patch(
            "alde.webapp.services.issue_access_token", return_value=("access-token", 111)
        ), patch("alde.webapp.services.issue_refresh_token", return_value="refresh-token-2"), patch(
            "alde.webapp.services.hash_refresh_token", side_effect=["hash-1", "hash-2"]
        ), patch("alde.webapp.services.repo.rotate_auth_session", return_value=True) as rotate_auth_session, patch(
            "alde.webapp.services.repo.append_audit"
        ) as append_audit:
            result = services.refresh_access_token(refresh_token="refresh-token-1")

        self.assertEqual(result["access_token"], "access-token")
        self.assertEqual(result["refresh_token"], "refresh-token-2")
        rotate_auth_session.assert_called_once()
        append_audit.assert_called_once()

    def test_call_agent_runtime_uses_chatcom_for_xplaner_xrouter(self) -> None:
        fake_agent_config = {"model": "gpt-4o-mini"}

        class _FakeChatCom:
            def __init__(self, *, _model: str, _input_text: str) -> None:
                self.model = _model
                self.input_text = _input_text

            def get_response(self) -> str:
                return f"primary:{self.model}:{self.input_text}"

        with patch("alde.agents_config.normalize_agent_label", return_value="_xplaner_xrouter"), patch(
            "alde.agents_config.get_agent_config", return_value=fake_agent_config
        ), patch("alde.agents_ccompletion.ChatCom", _FakeChatCom):
            result = services._call_agent_runtime(target_agent="_xplaner_xrouter", prompt="hello")

        self.assertEqual(result, "primary:gpt-4o-mini:hello")

    def test_call_agent_runtime_uses_forced_route_for_specialist_targets(self) -> None:
        with patch("alde.agents_config.normalize_agent_label", return_value="_xworker"), patch(
            "alde.agents_factory.execute_forced_route", return_value="writer response"
        ) as forced_route:
            result = services._call_agent_runtime(target_agent="_xworker", prompt="draft text")

        self.assertEqual(result, "writer response")
        forced_route.assert_called_once_with(
            {"target_agent": "_xworker", "user_question": "draft text"},
            ChatCom=unittest.mock.ANY,
            origin_agent_label="_xplaner_xrouter",
        )

    def test_run_agent_persists_runtime_output(self) -> None:
        with patch("alde.webapp.services._call_agent_runtime", return_value="runtime output"), patch(
            "alde.webapp.services.repo.store_run"
        ) as store_run:
            store_run.side_effect = lambda run: run
            run = services.run_agent(
                tenant_id="tenant-1",
                user_id="user-1",
                target_agent="_xworker",
                prompt="draft text",
                metadata={"source": "test"},
            )

        self.assertEqual(run.output, "runtime output")
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.metadata["source"], "test")
        self.assertIn("executed_at", run.metadata)

    def test_workflow_status_view_enriches_dispatcher_action_snapshot(self) -> None:
        item = {
            "message_id": 11,
            "role": "tool",
            "assistant_name": "_xworker",
            "thread_id": 100,
            "thread_name": "snapshot-thread",
            "time": "2025-03-01T10:00:02Z",
            "workflow": {
                "workflow_name": "data_dispatcher_chain",
                "agent_label": "_xworker",
                "current_state": "action_executed",
                "snapshot": {
                    "workflow_name": "data_dispatcher_chain",
                    "current_state": "action_executed",
                    "actor": {"kind": "tool", "name": "execute_action_request"},
                    "event": {
                        "name": "execute_action_request",
                        "action": "ingest_object",
                        "correlation_id": "platform:42",
                    },
                },
            },
        }

        with patch("alde.agents_factory.get_workflow_history_entries", return_value=[item]), patch(
            "alde.agents_factory.get_latest_workflow_status", return_value=item
        ), patch(
            "alde.webapp.services.get_workflow_validation_report",
            return_value={
                "valid": True,
                "workflow_count": 1,
                "valid_count": 1,
                "invalid_count": 0,
                "mapping_errors": [],
                "workflows": [],
            },
        ):
            result = services.get_workflow_status_view(target_agent="_xworker", thread_id=100, limit=10)

        latest = result["latest"]
        self.assertIsNotNone(latest)
        snapshot_view = latest["workflow"]["snapshot_view"]
        self.assertEqual(snapshot_view["kind"], "dispatcher_action")
        self.assertEqual(snapshot_view["title"], "Dispatcher action executed")
        self.assertEqual(snapshot_view["action"], "ingest_object")
        self.assertEqual(snapshot_view["correlation_id"], "platform:42")
        self.assertEqual(snapshot_view["summary"], "ingest_object | platform:42")
        self.assertEqual(result["items"][0]["workflow"]["snapshot_view"]["kind"], "dispatcher_action")

    def test_workflow_status_view_keeps_generic_snapshot_fallback(self) -> None:
        item = {
            "message_id": 21,
            "role": "assistant",
            "assistant_name": "_xworker",
            "thread_id": 200,
            "thread_name": "writer-thread",
            "time": "2025-03-01T10:02:00Z",
            "workflow": {
                "workflow_name": "writer_agent_leaf",
                "agent_label": "_xworker",
                "current_state": "writer_complete",
                "snapshot": {
                    "workflow_name": "writer_agent_leaf",
                    "current_state": "writer_complete",
                    "actor": {"kind": "state", "name": "workflow_complete"},
                    "event": {"name": "followup_complete"},
                },
            },
        }

        with patch("alde.agents_factory.get_workflow_history_entries", return_value=[item]), patch(
            "alde.agents_factory.get_latest_workflow_status", return_value=item
        ), patch(
            "alde.webapp.services.get_workflow_validation_report",
            return_value={
                "valid": True,
                "workflow_count": 1,
                "valid_count": 1,
                "invalid_count": 0,
                "mapping_errors": [],
                "workflows": [],
            },
        ):
            result = services.get_workflow_status_view(target_agent="_xworker", thread_id=200, limit=5)

        latest = result["latest"]
        self.assertIsNotNone(latest)
        snapshot_view = latest["workflow"]["snapshot_view"]
        self.assertEqual(snapshot_view["kind"], "workflow_state")
        self.assertEqual(snapshot_view["title"], "writer_complete")
        self.assertEqual(snapshot_view["summary"], "workflow_complete")

    def test_queue_agent_run_creates_job_and_appends_audit(self) -> None:
        run = SimpleNamespace(id="run-1")

        with patch("alde.webapp.services.repo.create_run_placeholder", return_value=run) as create_run, patch(
            "alde.webapp.services.repo.create_async_job", return_value="job-1"
        ) as create_async_job, patch("alde.webapp.services.repo.append_audit") as append_audit:
            job_id, run_id = services.queue_agent_run(
                tenant_id="tenant-1",
                user_id="user-1",
                target_agent="_xworker",
                prompt="draft text",
                metadata={"source": "test"},
            )

        self.assertEqual(job_id, "job-1")
        self.assertEqual(run_id, "run-1")
        create_run.assert_called_once()
        create_async_job.assert_called_once_with(tenant_id="tenant-1", user_id="user-1", run_id="run-1")
        append_audit.assert_called_once()

    def test_status_helpers_delegate_to_repo(self) -> None:
        run = SimpleNamespace(id="run-1", status="queued")
        job = {"id": "job-1", "status": "queued"}
        audit_items = [{"event_type": "agent.run_queued"}]

        with patch("alde.webapp.services.repo.get_run", return_value=run) as get_run, patch(
            "alde.webapp.services.repo.get_async_job", return_value=job
        ) as get_async_job, patch("alde.webapp.services.repo.list_audit", return_value=audit_items) as list_audit:
            result_run = services.get_run_status(tenant_id="tenant-1", run_id="run-1")
            result_job = services.get_job_status(tenant_id="tenant-1", job_id="job-1")
            result_audit = services.list_audit_events(tenant_id="tenant-1", limit=5)

        self.assertIs(result_run, run)
        self.assertIs(result_job, job)
        self.assertEqual(result_audit, audit_items)
        get_run.assert_called_once_with(tenant_id="tenant-1", run_id="run-1")
        get_async_job.assert_called_once_with(tenant_id="tenant-1", job_id="job-1")
        list_audit.assert_called_once_with(tenant_id="tenant-1", limit=5)

    def test_operator_activity_view_normalizes_recent_audit_entries(self) -> None:
        audit_items = [
            {
                "created_at": "2026-04-01T10:00:00+00:00",
                "tenant_id": "tenant-1",
                "event_type": "agent.run_completed",
                "detail": {"target_agent": "_xworker", "run_id": "run-1"},
            }
        ]

        with patch("alde.webapp.services.repo.list_recent_audit", return_value=audit_items) as list_recent_audit:
            result = services.get_operator_activity_view(limit=5)

        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["items"][0]["source"], "webapp")
        self.assertEqual(result["items"][0]["title"], "agent.run_completed")
        self.assertIn("_xworker", result["items"][0]["summary"])
        list_recent_audit.assert_called_once_with(limit=5)


if __name__ == "__main__":
    unittest.main()
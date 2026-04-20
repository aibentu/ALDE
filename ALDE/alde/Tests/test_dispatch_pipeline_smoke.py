from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from alde.agents_tools import DOCUMENT_REPOSITORY, dispatch_docs, execute_action_request_tool


# Tiny but valid single-page PDF fixture for end-to-end dispatch smoke tests.
_MINIMAL_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 50 100 Td (Dispatch Smoke) Tj ET\nendstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000062 00000 n \n0000000118 00000 n \n0000000205 00000 n \n"
    b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n300\n%%EOF\n"
)


class TestDispatchPipelineSmoke(unittest.TestCase):
    def test_dispatch_generates_parser_handoff_for_real_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            scan_dir = tmp_path / "scan"
            scan_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = scan_dir / "job_offer.pdf"
            pdf_path.write_bytes(_MINIMAL_PDF_BYTES)

            dispatcher_db_path = tmp_path / "dispatcher_doc_db.json"

            result = dispatch_docs(
                scan_dir=str(scan_dir),
                db_path=str(dispatcher_db_path),
                thread_id="thread-smoke",
                dispatcher_message_id="msg-smoke",
                recursive=False,
                dry_run=False,
            )

            self.assertEqual(result.get("job_name"), "document_dispatch")
            self.assertEqual(result.get("summary", {}).get("pdf_found"), 1)
            self.assertEqual(result.get("summary", {}).get("new"), 1)
            self.assertEqual(result.get("summary", {}).get("errors"), 0)

            forwarded = result.get("forwarded") or []
            self.assertEqual(len(forwarded), 1)
            correlation_id = str(forwarded[0].get("content_sha256") or "")
            self.assertTrue(correlation_id)

            handoff_messages = result.get("handoff_messages") or []
            self.assertEqual(len(handoff_messages), 1)
            handoff = handoff_messages[0] if isinstance(handoff_messages[0], dict) else {}
            self.assertEqual(handoff.get("protocol"), "agent_handoff_v1")

            payload = handoff.get("handoff_payload") if isinstance(handoff.get("handoff_payload"), dict) else {}
            metadata = handoff.get("metadata") if isinstance(handoff.get("metadata"), dict) else {}
            output = payload.get("output") if isinstance(payload.get("output"), dict) else {}

            self.assertEqual(payload.get("handoff_to"), "_xworker")
            self.assertEqual(output.get("type"), "file")
            self.assertEqual(output.get("correlation_id"), correlation_id)
            self.assertEqual(output.get("requested_actions"), ["parse", "extract_text", "store_object_result", "mark_processed_on_success"])
            self.assertEqual(metadata.get("correlation_id"), correlation_id)
            self.assertEqual(metadata.get("dispatcher_message_id"), "msg-smoke")
            self.assertEqual(metadata.get("dispatcher_db_path"), str(dispatcher_db_path.resolve()))
            self.assertEqual(metadata.get("obj_name"), "job_postings")

            dispatcher_record = DOCUMENT_REPOSITORY.get_dispatcher_record(
                correlation_id,
                db_path=str(dispatcher_db_path),
            )
            self.assertIsInstance(dispatcher_record, dict)
            self.assertEqual((dispatcher_record or {}).get("processing_state"), "queued")
            self.assertEqual((dispatcher_record or {}).get("processed"), False)

    def test_execute_action_request_accepts_legacy_document_dispatch_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            scan_dir = tmp_path / "scan"
            scan_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = scan_dir / "job_offer.pdf"
            pdf_path.write_bytes(_MINIMAL_PDF_BYTES)

            dispatcher_db_path = tmp_path / "dispatcher_doc_db.json"
            result_raw = execute_action_request_tool(
                action_request={
                    "action": "document_dispatch",
                    "scan_dir": str(scan_dir),
                    "db_path": str(dispatcher_db_path),
                    "thread_id": "thread-action",
                    "dispatcher_message_id": "msg-action",
                    "recursive": False,
                }
            )

            self.assertIsInstance(result_raw, str)
            result = json.loads(result_raw)
            self.assertEqual(result.get("job_name"), "document_dispatch")
            self.assertIsNone(result.get("error"))
            self.assertEqual(result.get("db", {}).get("reachable"), True)
            self.assertEqual(result.get("summary", {}).get("pdf_found"), 1)
            self.assertEqual(result.get("summary", {}).get("errors"), 0)


if __name__ == "__main__":
    unittest.main()

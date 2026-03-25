from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.chat_completion as chat_mod
import alde.agents_factory as agents_factory


SAMPLE_COVER_LETTER_GUIDE = "# Anschreiben Best Practices\n\nMotivation und Klarheit."
SAMPLE_JOB_POSTING = "Senior Python Developer mit FastAPI und PostgreSQL"
SAMPLE_PROFILE = "Senior Python Entwickler mit 6 Jahren Erfahrung"


class _FakeRagResult:
    def __init__(self, relevance_score: float) -> None:
        self.relevance_score = relevance_score


class _FakeRagSystem:
    def __init__(self) -> None:
        self.added_documents: list[dict[str, str]] = []

    def get_stats(self) -> dict[str, object]:
        return {
            "active_backend": "faiss",
            "total_chunks": len(self.added_documents),
            "indexed_sources": len(self.added_documents),
        }

    def add_document(self, content: str, source: str, title: str) -> int:
        self.added_documents.append({"content": content, "source": source, "title": title})
        return 2

    def retrieve(self, query: str, k: int = 2):
        return [_FakeRagResult(0.91)]


class _DeterministicDispatcherChatComE:
    def __init__(self, _model: str, _messages: list, tools: list[dict], tool_choice: str) -> None:
        self._model = _model

    def _response(self):
        message = SimpleNamespace(
            content=json.dumps(
                {
                    "cover_letter": {"full_text": "RAG-gestuetztes Anschreiben"},
                    "quality": {"language": "de", "word_count": 3},
                    "rag": {"used": True},
                },
                ensure_ascii=False,
            ),
            tool_calls=None,
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def setup_rag_documents(create_rag_system):
    rag = create_rag_system(store_path="AppData/VSM_1_Data")
    chunks = rag.add_document(
        content=SAMPLE_COVER_LETTER_GUIDE,
        source="guides/cover_letter_best_practices.md",
        title="Cover Letter Best Practices",
    )
    stats = rag.get_stats()
    results = rag.retrieve("How to write modern cover letter for Python developer?", k=2)
    return {
        "chunks": chunks,
        "stats": stats,
        "top_score": results[0].relevance_score if results else None,
    }


class TestWorkflowRagIntegration(unittest.TestCase):
    def setUp(self) -> None:
        chat_mod.ChatHistory._history_ = []
        agents_factory._WORKFLOW_SESSION_CACHE.clear()

    def test_rag_bootstrap_indexes_reference_document(self) -> None:
        fake_rag = _FakeRagSystem()

        summary = setup_rag_documents(lambda store_path: fake_rag)

        self.assertEqual(summary["chunks"], 2)
        self.assertEqual(summary["stats"]["active_backend"], "faiss")
        self.assertEqual(summary["top_score"], 0.91)
        self.assertEqual(fake_rag.added_documents[0]["source"], "guides/cover_letter_best_practices.md")

    def test_rag_workflow_uses_forced_route_and_returns_response(self) -> None:
        request = {
            "action": "generate_cover_letter",
            "job_posting": {"source": "text", "value": SAMPLE_JOB_POSTING},
            "applicant_profile": {"source": "text", "value": SAMPLE_PROFILE},
            "options": {"language": "de", "tone": "modern", "max_words": 350},
        }
        captured_execute_tool_calls: list[tuple[str, dict]] = []

        def _fake_execute_tool(name: str, args: dict, tool_call_id: str = None, source_agent_label: str = None):
            captured_execute_tool_calls.append((name, dict(args)))
            if name == "route_to_agent":
                return (
                    "Routing to _data_dispatcher",
                    {
                        "messages": [
                            {"role": "system", "content": "dispatcher system"},
                            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
                        ],
                        "agent_label": "_data_dispatcher",
                        "tools": [],
                        "model": "gpt-4o-mini",
                        "include_history": False,
                    },
                )
            raise AssertionError(f"Unexpected tool execution: {name}")

        chat = chat_mod.ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(request, ensure_ascii=False),
            _name="test_workflow_rag",
        )

        with patch("alde.chat_completion.ChatComE", _DeterministicDispatcherChatComE), patch(
            "alde.agents_factory.execute_tool",
            side_effect=_fake_execute_tool,
        ):
            response = chat.get_response()

        payload = json.loads(response)
        self.assertTrue(payload["rag"]["used"])
        self.assertEqual(payload["quality"]["language"], "de")
        self.assertEqual(
            captured_execute_tool_calls,
            [
                (
                    "route_to_agent",
                    {
                        "target_agent": "_data_dispatcher",
                        "user_question": json.dumps(request, ensure_ascii=False),
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()

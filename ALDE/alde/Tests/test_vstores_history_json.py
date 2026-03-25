from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

import alde.vstores as vstores_mod
from alde.vstores import VectorStore, _create_text_splitter, _document_key, _iter_documents, _load_json, _resolve_chunking_config


class _DeterministicEmbeddings:
    def __init__(self, size: int = 12) -> None:
        self.size = size

    def _encode(self, text: str) -> list[float]:
        vector = [0.0] * self.size
        for index, byte in enumerate((text or "").encode("utf-8", errors="ignore")):
            vector[index % self.size] += (byte % 53) / 53.0
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)

    def __call__(self, text: str) -> list[float]:
        return self.embed_query(text)


class _FakeFaissModule:
    class StandardGpuResources:
        pass

    def __init__(self, num_gpus: int = 1) -> None:
        self._num_gpus = num_gpus

    def get_num_gpus(self) -> int:
        return self._num_gpus

    def index_cpu_to_gpu(self, resources, device: int, index):
        return {"gpu": True, "device": device, "cpu_index": index}

    def index_gpu_to_cpu(self, index):
        return index["cpu_index"]


def _write_history_json(path: Path) -> None:
    payload = [
        {
            "message-id": 1,
            "role": "assistant",
            "content": None,
            "date": "2026-03-08",
            "time": "2026-03-08 10:00:00",
            "thread-name": "chat",
            "thread-id": 2324,
            "assistant-name": "_data_dispatcher",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "route_to_agent", "arguments": "{}"},
                    "type": "function",
                }
            ],
        },
        {
            "message-id": 2,
            "role": "tool",
            "content": "batch generated successfully",
            "date": "2026-03-08",
            "time": "2026-03-08 10:00:01",
            "thread-name": "chat",
            "thread-id": 2324,
            "assistant-name": "_data_dispatcher",
            "tool_call_id": "call_1",
            "name": "route_to_agent",
            "data": {"status": "ok"},
        },
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class TestVstoresHistoryJson(unittest.TestCase):
    def test_load_json_creates_one_document_per_history_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            history_path = tmp_path / "history.json"
            _write_history_json(history_path)

            docs = _load_json(tmp_path)

            self.assertEqual(len(docs), 2)
            self.assertEqual({doc.metadata["source"] for doc in docs}, {str(history_path)})
            self.assertEqual(len({_document_key(doc) for doc in docs}), 2)
            self.assertEqual(docs[0].metadata["titel"], "history.json")
            self.assertIn("tool_calls:", docs[0].page_content)
            self.assertIn("batch generated successfully", docs[1].page_content)


    def test_iter_documents_keeps_distinct_history_entries_from_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            history_path = tmp_path / "history.json"
            _write_history_json(history_path)

            docs = [doc for doc in _iter_documents(tmp_path) if doc.metadata.get("source") == str(history_path)]

            self.assertEqual(len(docs), 2)
            self.assertEqual(len({_document_key(doc) for doc in docs}), 2)


    def test_metadata_injection_tracks_json_entries_by_document_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            history_path = tmp_path / "history.json"
            _write_history_json(history_path)
            docs = _load_json(tmp_path)

            store_dir = tmp_path / "store"
            manifest_file = store_dir / "manifest.json"
            vector_store = VectorStore(store_path=str(store_dir), manifest_file=str(manifest_file))
            vector_store.manifest = {_document_key(docs[0])}

            injected_docs = vector_store.metadata_injection(docs)

            self.assertEqual(len(injected_docs), 1)
            self.assertEqual(injected_docs[0].metadata["message-id"], 2)
            self.assertIn("Metadata:", injected_docs[0].page_content)

    def test_build_and_query_history_json_with_temp_faiss_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            history_path = tmp_path / "history.json"
            _write_history_json(history_path)

            store_dir = tmp_path / "store"
            manifest_file = store_dir / "manifest.json"
            vector_store = VectorStore(store_path=str(store_dir), manifest_file=str(manifest_file))

            def _fake_initialize() -> None:
                if vector_store._initialized:
                    return
                vector_store._initialized = True
                vector_store.embeddings = _DeterministicEmbeddings()

            with patch.object(vector_store, "_initialize", _fake_initialize):
                vector_store.build(tmp_path)
                results = vector_store.query("batch generated successfully", k=2)

            self.assertTrue((store_dir / "index.faiss").exists())
            self.assertTrue((store_dir / "index.pkl").exists())
            self.assertTrue(manifest_file.exists())
            self.assertEqual(len(vector_store.manifest), 2)
            self.assertGreaterEqual(len(results), 1)
            self.assertTrue(any(item["source"] == str(history_path) for item in results))
            self.assertTrue(any("batch generated successfully" in item["content"] for item in results))
            self.assertTrue(all("distance" in item for item in results))
            self.assertTrue(all(item.get("score_kind") == "faiss_distance" for item in results))
            self.assertTrue(all(item.get("score") == item.get("distance") for item in results))
            self.assertTrue(all(item.get("entry_ref", "").startswith(str(history_path)) for item in results))

    def test_gpu_index_promotion_and_demotions_use_faiss_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vector_store = VectorStore(
                store_path=str(tmp_path / "store"),
                manifest_file=str(tmp_path / "store" / "manifest.json"),
            )
            vector_store.store = SimpleNamespace(index="cpu-index")
            fake_faiss = _FakeFaissModule(num_gpus=1)

            with patch.object(vstores_mod, "FAISS_USE_GPU", True), patch.object(
                vstores_mod, "FAISS_REQUIRE_GPU", False
            ), patch.object(vstores_mod, "FAISS_GPU_DEVICE", 0), patch.object(
                vstores_mod, "_load_faiss_module", return_value=fake_faiss
            ):
                vector_store._maybe_enable_gpu_index()
                self.assertTrue(vector_store._gpu_index_enabled)
                self.assertEqual(vector_store.store.index["device"], 0)
                self.assertEqual(vector_store.store.index["cpu_index"], "cpu-index")

                vector_store._ensure_cpu_index()
                self.assertFalse(vector_store._gpu_index_enabled)
                self.assertEqual(vector_store.store.index, "cpu-index")

    def test_gpu_required_raises_when_no_faiss_gpu_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vector_store = VectorStore(
                store_path=str(tmp_path / "store"),
                manifest_file=str(tmp_path / "store" / "manifest.json"),
            )
            vector_store.store = SimpleNamespace(index="cpu-index")
            fake_faiss = _FakeFaissModule(num_gpus=0)

            with patch.object(vstores_mod, "FAISS_USE_GPU", True), patch.object(
                vstores_mod, "FAISS_REQUIRE_GPU", True
            ), patch.object(vstores_mod, "_load_faiss_module", return_value=fake_faiss):
                with self.assertRaises(RuntimeError):
                    vector_store._maybe_enable_gpu_index()

    def test_resolve_chunking_config_accepts_character_strategy(self) -> None:
        strategy, chunk_size, overlap = _resolve_chunking_config(
            chunk_strategy="character",
            chunk_size=256,
            overlap=32,
        )

        self.assertEqual(strategy, "character")
        self.assertEqual(chunk_size, 256)
        self.assertEqual(overlap, 32)

    def test_create_text_splitter_returns_character_splitter(self) -> None:
        splitter = _create_text_splitter(chunk_strategy="character", chunk_size=128, overlap=16)

        self.assertEqual(type(splitter).__name__, "CharacterTextSplitter")
        self.assertEqual(splitter._chunk_size, 128)
        self.assertEqual(splitter._chunk_overlap, 16)

    def test_create_text_splitter_returns_markdown_splitter(self) -> None:
        splitter = _create_text_splitter(chunk_strategy="markdown", chunk_size=192, overlap=24)

        self.assertEqual(type(splitter).__name__, "MarkdownTextSplitter")
        self.assertEqual(splitter._chunk_size, 192)
        self.assertEqual(splitter._chunk_overlap, 24)

    def test_resolve_chunking_config_rejects_overlap_greater_than_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_chunking_config(chunk_strategy="recursive", chunk_size=64, overlap=64)


if __name__ == "__main__":
    unittest.main()
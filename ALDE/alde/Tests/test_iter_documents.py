from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from alde.iter_documents import iter_documents
import alde.vstores as vstores_mod


def _fake_loader(path: Path) -> list[SimpleNamespace]:
    return [SimpleNamespace(page_content=path.read_text(encoding="utf-8"), metadata={"source": str(path)})]


class TestIterDocuments(unittest.TestCase):
    def test_single_file_root_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_path = root / "single.md"
            file_path.write_text("single", encoding="utf-8")

            with patch("alde.iter_documents._load_text", side_effect=_fake_loader):
                docs = iter_documents(file_path)

            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].metadata["source"], str(file_path))

    def test_multiple_roots_and_doc_types_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()

            md_path = first / "notes.md"
            py_path = first / "script.py"
            pdf_path = second / "report.pdf"
            md_path.write_text("markdown", encoding="utf-8")
            py_path.write_text("print('x')", encoding="utf-8")
            pdf_path.write_text("fake-pdf", encoding="utf-8")

            with patch("alde.iter_documents._load_text", side_effect=_fake_loader), patch(
                "alde.iter_documents._load_pdf", side_effect=_fake_loader
            ):
                docs = iter_documents([first, second], doc_types=["md", "pdf"])

            self.assertEqual({doc.metadata["source"] for doc in docs}, {str(md_path), str(pdf_path)})

    def test_patterns_and_max_depth_limit_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docs_dir = root / "docs"
            nested_dir = docs_dir / "nested"
            docs_dir.mkdir()
            nested_dir.mkdir()

            top_level = docs_dir / "top.md"
            nested_markdown = nested_dir / "deep.md"
            nested_python = nested_dir / "deep.py"
            top_level.write_text("top", encoding="utf-8")
            nested_markdown.write_text("deep-md", encoding="utf-8")
            nested_python.write_text("deep-py", encoding="utf-8")

            with patch("alde.iter_documents._load_text", side_effect=_fake_loader):
                shallow_docs = iter_documents(docs_dir, doc_types="md", max_depth=0)
                nested_docs = iter_documents(docs_dir, doc_types="md", patterns="**/*.md", max_depth=1)
                non_recursive_docs = iter_documents(docs_dir, doc_types="py", recursive=False)

            self.assertEqual({doc.metadata["source"] for doc in shallow_docs}, {str(top_level)})
            self.assertEqual({doc.metadata["source"] for doc in nested_docs}, {str(top_level), str(nested_markdown)})
            self.assertEqual(non_recursive_docs, [])

    def test_vstores_private_iter_documents_respects_doc_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            markdown_path = root / "notes.md"
            txt_path = root / "notes.txt"
            py_path = root / "script.py"
            pdf_path = root / "report.pdf"
            json_path = root / "payload.json"

            markdown_path.write_text("markdown", encoding="utf-8")
            txt_path.write_text("text", encoding="utf-8")
            py_path.write_text("print('x')", encoding="utf-8")
            pdf_path.write_text("fake", encoding="utf-8")
            json_path.write_text('{"ok": true}', encoding="utf-8")

            def _fake_directory_loader(*args, **kwargs):
                class _Loader:
                    def load(self_inner):
                        return [SimpleNamespace(page_content="py", metadata={"source": str(py_path)})]
                return _Loader()

            class _FakeSafeTextLoader:
                def __init__(self, file_path: str, autodetect_encoding: bool = True) -> None:
                    self.file_path = file_path

                def load(self) -> list[SimpleNamespace]:
                    return [
                        SimpleNamespace(
                            page_content=Path(self.file_path).read_text(encoding="utf-8"),
                            metadata={"source": str(self.file_path)},
                        )
                    ]

            with patch.object(vstores_mod, "DirectoryLoader", side_effect=_fake_directory_loader), patch.object(
                vstores_mod,
                "SafeTextLoader",
                _FakeSafeTextLoader,
            ), patch.object(
                vstores_mod,
                "_load_pdf",
                return_value=[SimpleNamespace(page_content="pdf", metadata={"source": str(pdf_path)})],
            ), patch.object(
                vstores_mod,
                "_load_json",
                return_value=[SimpleNamespace(page_content="json", metadata={"source": str(json_path)})],
            ):
                docs = vstores_mod._iter_documents(root, doc_types=[".txt", ".md"])

            self.assertEqual({doc.metadata["source"] for doc in docs}, {str(markdown_path), str(txt_path)})


if __name__ == "__main__":
    unittest.main()
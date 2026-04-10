from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from alde.ai_ide_v1756 import ChatEditorPanel, ChatSegment, ChatWindow, CodeViewer, MsgWidget


APP = QApplication.instance() or QApplication([])


class TestChatWindowSegmentation(unittest.TestCase):
    def test_fenced_blocks_keep_language_and_indentation(self) -> None:
        raw = "Intro\n```python\n    def demo():\n        return 1\n```\nOutro"

        segments = ChatWindow._split_segments(raw)

        self.assertEqual(
            segments,
            [
                ChatSegment(kind="text", language="", block="Intro"),
                ChatSegment(kind="editor", language="python", block="    def demo():\n        return 1"),
                ChatSegment(kind="text", language="", block="Outro"),
            ],
        )

    def test_plain_python_blocks_are_promoted_to_editor(self) -> None:
        raw = "def demo():\n    return 1\n\nclass Box:\n    pass"

        segments = ChatWindow._split_segments(raw)

        self.assertEqual(segments, [ChatSegment(kind="editor", language="python", block=raw)])

    def test_short_markdown_reply_stays_text(self) -> None:
        raw = "Summary\n\nThis is a short answer.\n\n- first item"

        segments = ChatWindow._split_segments(raw)

        self.assertEqual(segments, [ChatSegment(kind="text", language="", block=raw)])

    def test_file_blocks_keep_source_path_for_save_action(self) -> None:
        raw = (
            "[FILE] demo.py (code)\n"
            "[SOURCE] /tmp/demo.py\n"
            "```python\n"
            "def demo():\n"
            "    return 1\n"
            "```"
        )

        segments = ChatWindow._split_segments(raw)

        self.assertEqual(
            segments,
            [
                ChatSegment(kind="text", language="", block="[FILE] demo.py (code)"),
                ChatSegment(
                    kind="editor",
                    language="python",
                    block="def demo():\n    return 1",
                    file_path="/tmp/demo.py",
                ),
            ],
        )

    def test_save_helper_writes_back_to_source_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "settings.yaml"
            target_path.write_text("old: value\n", encoding="utf-8")

            MsgWidget._write_editor_text_to_path(file_path=target_path, text="new: value\n")

            self.assertEqual(target_path.read_text(encoding="utf-8"), "new: value\n")

    def test_code_viewer_starts_read_only_and_can_enter_edit_mode(self) -> None:
        viewer = CodeViewer("print('demo')\n", language="python", editable=False)

        self.assertTrue(viewer.isReadOnly())
        self.assertEqual(viewer.objectName(), "chatCodeViewer")

        viewer.set_edit_mode(True)

        self.assertFalse(viewer.isReadOnly())
        self.assertEqual(viewer.objectName(), "aiInput")

    def test_code_viewer_edit_mode_keeps_dark_background_and_accent_border(self) -> None:
        viewer = CodeViewer(
            "print('demo')\n",
            language="python",
            editable=False,
            accent_color="#0fe913",
            accent_selection_color="#58ed5b",
        )

        viewer.set_edit_mode(True)

        self.assertIn("background:#111;", viewer.styleSheet())
        self.assertIn("border:1px solid #0fe913;", viewer.styleSheet())

    def test_code_viewer_uses_scrollbars_for_code_blocks(self) -> None:
        viewer = CodeViewer("print('demo')\n", language="python", editable=False)

        self.assertEqual(viewer.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        self.assertEqual(viewer.horizontalScrollBarPolicy(), Qt.ScrollBarAsNeeded)

    def test_code_viewer_wheel_event_scrolls_content(self) -> None:
        text = "\n".join(f"line {index} " + ("x" * 160) for index in range(180))
        viewer = CodeViewer(text, language="python", editable=False)
        viewer.resize(340, 180)
        viewer.show()
        APP.processEvents()

        scroll_bar = viewer.verticalScrollBar()
        before = scroll_bar.value()

        wheel = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(viewer.viewport(), wheel)
        APP.processEvents()

        self.assertGreater(scroll_bar.maximum(), 0)
        self.assertGreater(scroll_bar.value(), before)

    def test_code_viewer_wheel_event_scrolls_with_pixel_delta(self) -> None:
        text = "\n".join(f"line {index} " + ("x" * 160) for index in range(180))
        viewer = CodeViewer(text, language="python", editable=False)
        viewer.resize(340, 180)
        viewer.show()
        APP.processEvents()

        scroll_bar = viewer.verticalScrollBar()
        before = scroll_bar.value()

        wheel = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, -12),
            QPoint(0, 0),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(viewer.viewport(), wheel)
        APP.processEvents()

        self.assertGreater(scroll_bar.maximum(), 0)
        self.assertGreater(scroll_bar.value(), before)

    def test_editor_panel_reveals_controls_only_after_activation(self) -> None:
        panel = ChatEditorPanel(
            segment=ChatSegment(
                kind="editor",
                language="python",
                block="print('demo')\n",
                file_path="/tmp/demo.py",
            ),
            save_handler=lambda _viewer, _file_path: None,
        )

        self.assertTrue(panel.viewer.isReadOnly())
        self.assertTrue(panel._controls.isHidden())

        panel.viewer.editRequested.emit()

        self.assertFalse(panel.viewer.isReadOnly())
        self.assertFalse(panel._controls.isHidden())

    def test_chat_window_scrollbar_style_uses_control_plane_tokens(self) -> None:
        chat = ChatWindow(
            {
                "col9": "#101010",
                "col10": "#303030",
                "col1": "#3a5fff",
                "col2": "#6280ff",
            }
        )

        style = chat.styleSheet()
        self.assertIn("QScrollArea#chatHistoryScroller QScrollBar::handle:vertical", style)
        self.assertIn("background: #303030;", style)
        self.assertIn("background: #6280ff;", style)


if __name__ == "__main__":
    unittest.main()
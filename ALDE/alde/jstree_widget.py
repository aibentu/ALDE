"""  """
from __future__ import annotations

"""
Clean, import-safe implementation of ClosableTextEdit, JsonTreeWidget and
JsonHighlighter. This file replaces a broken version that caused import
failures due to stray top-level code and invalid references to `self`.

Features preserved:
- ClosableTextEdit: QTextEdit with a small toolbar button to load ChatHistory
- JsonTreeWidget: QTreeWidget that can display JSON/Python data structures
- JsonHighlighter: lightweight QSyntaxHighlighter for JSON-like text

This module intentionally keeps runtime behavior minimal so importing it
won't trigger heavy work. UI interactions (e.g. loading history) assume
`ChatHistory._history_` may exist in `chat_completion` module; if not,
buttons will show a placeholder message.
"""

from typing import Any
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPixmap,
    QTextCharFormat,
    QSyntaxHighlighter,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QToolButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QDockWidget,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
)

# Try to import ChatHistory if available; keep optional.
try:
    from .chat_completion import ChatHistory  # type: ignore
except Exception:  # allow running as script from repo root
    try:
        from alde.chat_completion import ChatHistory  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        ChatHistory = None  # type: ignore


# --------------------- Helper: icon loader (minimal) ---------------------
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def _tinted_icon(base: QIcon, *, color: QColor | str, size: int = 16) -> QIcon:
    """Return a tinted variant of `base`.

    This is used to colorize monochrome SVG icons to match the current accent.
    """
    if base.isNull() or QApplication.instance() is None:
        return base

    qcolor = QColor(color) if isinstance(color, str) else color
    pm = base.pixmap(size, size)
    if pm.isNull():
        return base

    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawPixmap(0, 0, pm)
    # colorize while keeping alpha from source icon
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), qcolor)
    p.end()
    return QIcon(out)


def _icon_with_marker(base: QIcon, *, marker_color: QColor | str, size: int = 16) -> QIcon:
    """Overlay a small accent marker ("fmarker") onto an icon."""
    if base.isNull() or QApplication.instance() is None:
        return base

    qcolor = QColor(marker_color) if isinstance(marker_color, str) else marker_color
    pm = base.pixmap(size, size)
    if pm.isNull():
        return base

    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawPixmap(0, 0, pm)

    # Bottom-right dot marker
    r = max(3, size // 5)
    margin = max(1, size // 12)
    cx = size - margin - r
    cy = size - margin - r
    p.setPen(Qt.NoPen)
    p.setBrush(qcolor)
    p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    p.end()
    return QIcon(out)


def _icon_with_badge_text(
    base: QIcon,
    *,
    text: str,
    badge_color: QColor | str,
    text_color: QColor | str = "#ffffff",
    size: int = 18,
) -> QIcon:
    """Overlay a small date badge onto an icon.

    Used for HISTORY root items (e.g. "Chat History") to show the last entry date.
    """
    if base.isNull() or QApplication.instance() is None:
        return base

    t = (text or "").strip()
    if not t:
        return base

    badge_qcolor = QColor(badge_color) if isinstance(badge_color, str) else badge_color
    text_qcolor = QColor(text_color) if isinstance(text_color, str) else text_color

    pm = base.pixmap(size, size)
    if pm.isNull():
        return base

    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawPixmap(0, 0, pm)

    # Badge geometry (bottom-right)
    font = QFont("Fira Code", max(6, size // 3))
    font.setBold(True)
    p.setFont(font)
    metrics = p.fontMetrics()
    pad_x = max(2, size // 10)
    pad_y = max(1, size // 12)
    text_w = metrics.horizontalAdvance(t)
    text_h = metrics.height()
    badge_w = min(size, text_w + 2 * pad_x)
    badge_h = min(size, text_h + 2 * pad_y)
    x = size - badge_w
    y = size - badge_h

    # badge background
    p.setPen(Qt.NoPen)
    p.setBrush(badge_qcolor)
    radius = max(2, badge_h // 3)
    p.drawRoundedRect(x, y, badge_w, badge_h, radius, radius)

    # badge text
    p.setPen(text_qcolor)
    p.drawText(x, y, badge_w, badge_h, Qt.AlignCenter, t)
    p.end()
    return QIcon(out)



SCROLLBAR_HOVER_ONLY_DARK = """
/* ==== generic dark style – hide until mouse-over, no arrows ==== */

/* --- shared  -------------------------------------------------- */
QScrollBar:horizontal, QScrollBar:vertical {
    background: transparent;          /* nothing until hover        */
    margin: 0px;                      /* no outer gaps              */
    border: none;
}

/* size while idle (almost invisible but still receives hover)   */
QScrollBar:vertical   { width: 4px;  }
QScrollBar:horizontal { height:50px;  }

/* grow a bit + colour when mouse enters the bar itself          */
QScrollBar:vertical:hover   { width: 4px; }
QScrollBar:horizontal:hover { height:50px; }

/* ----- handle (the draggable knob) --------------------------- */
QScrollBar::handle {
    background: rgba(120,120,120,0.0);   /* transparent while idle  */
    border-radius: 4px;
    min-width: 4px;
    min-height: 600px;
}
QScrollBar::handle:hover {
    background: rgba(120,120,120,0.6);   /* show on hover           */
}

/* ----- remove arrows & useless areas ------------------------- */
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;  border: none;  width:0px; height:0px;
}
"""

def _icon(name: str) -> QIcon:
    """Import-safe icon loader.

    Supports:
    - Local icons in the `symbols/` folder (current behavior)
    - Optional http(s) URLs (downloaded + cached on disk)

    Returns an empty QIcon before QApplication exists.
    """

    if QApplication.instance() is None:
        return QIcon()

    s = (name or "").strip()
    if not s:
        return QIcon()

    if s.startswith("http://") or s.startswith("https://"):
        return _icon_from_url(s)

    p = Path(__file__).with_name("symbols") / s
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def _icon_cache_dir() -> Path:
    # Allow override for privacy/offline control.
    override = os.environ.get("AI_IDE_ICON_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).parent.parent / "AppData" / "icon_cache"


def _icon_from_url(url: str, *, timeout_s: float = 3.0) -> QIcon:
    """Download an icon from the web and cache it locally.

    Notes:
    - This is best-effort: network failures simply return an empty icon.
    - Use only URLs you have rights to use (e.g. Material icons are Apache-2.0).
    """
    if QApplication.instance() is None:
        return QIcon()

    u = (url or "").strip()
    if not u:
        return QIcon()

    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return QIcon()

    cache_dir = _icon_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return QIcon()

    key = hashlib.sha256(u.encode("utf-8")).hexdigest()
    for ext in (".svg", ".png", ".jpg", ".jpeg"):
        candidate = cache_dir / f"{key}{ext}"
        if candidate.is_file():
            return QIcon(str(candidate))

    try:
        req = Request(u, headers={"User-Agent": "alde/1.0"})
        with urlopen(req, timeout=timeout_s) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except Exception:
        return QIcon()

    if not data:
        return QIcon()

    # Pick a file extension Qt can understand.
    ext = ".svg" if u.lower().endswith(".svg") else ""
    if "image/svg" in ctype:
        ext = ".svg"
    elif "image/png" in ctype:
        ext = ".png"
    elif "image/jpeg" in ctype or "image/jpg" in ctype:
        ext = ".jpg"
    else:
        head = data.lstrip()[:200].lower()
        if head.startswith(b"<svg") or b"<svg" in head or b"image/svg+xml" in head:
            ext = ".svg"
        elif data.startswith(b"\x89PNG"):
            ext = ".png"
        elif data.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"

    if not ext:
        return QIcon()

    path = cache_dir / f"{key}{ext}"
    tmp = cache_dir / f"{key}{ext}.tmp"
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return QIcon()

    return QIcon(str(path))


# ------------------------- JsonTreeWidgetWithToolbar -------------------------------
class JsonTreeWidgetWithToolbar(QWidget):
    """Wrapper widget that contains toolbar buttons above the JsonTreeWidget."""
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("JsonTreeWidgetWithToolbar")
        
        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create toolbar frame
        toolbar = QFrame(self)
        self._toolbar = toolbar
        toolbar.setFixedHeight(28)
        toolbar.setObjectName("JsonTreeToolbar")
        self._bg_color = "#1D1D1D"
        self._accent_color = "#3a5fff"
        self._toolbar_style_template = """
            QFrame#JsonTreeToolbar {{
                background: {bg};
                border-bottom: 1px solid #303030;
            }}
            QToolButton {{
                background: {bg};
                border: 1px solid #303030;
                border-radius: 3px;
                padding: 2px;
                max-width: 24px;
                max-height: 24px;
                color: #E3E3DED6;
            }}
            QToolButton:hover {{
                background: #303030;
                border: 1px solid {accent};
            }}
            QToolButton:pressed {{
                background: {accent};
            }}
        """
        self._apply_toolbar_style(toolbar)
        self._apply_wrapper_style()
        
        # Create toolbar layout
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 2, 4, 2)
        toolbar_layout.setSpacing(2)
        
        # Create tree widget
        self.tree = JsonTreeWidget(self)
        
        # Create buttons
        self._btn_load_history = QToolButton(toolbar)
        icon_hist = _icon("load_content.svg")
        if not icon_hist.isNull():
            self._btn_load_history.setIcon(icon_hist)
        else:
            self._btn_load_history.setText("📂")
        self._btn_load_history.setToolTip("Load project history")
        self._btn_load_history.setFixedSize(26, 26)
        self._btn_load_history.clicked.connect(self.tree._show_history_tree)
        
        self._btn_collapse_all = QToolButton(toolbar)
        icon_collapse = _icon("expansion_panels.svg")
        if not icon_collapse.isNull():
            self._btn_collapse_all.setIcon(icon_collapse)
        else:
            self._btn_collapse_all.setText("⬇")
        self._btn_collapse_all.setToolTip("Collapse all items")
        self._btn_collapse_all.setFixedSize(26, 26)
        self._btn_collapse_all.clicked.connect(self.tree.collapseAll)
        
        self._btn_add_project = QToolButton(toolbar)
        icon_add = _icon("deployed_code.svg")
        if not icon_add.isNull():
            self._btn_add_project.setIcon(icon_add)
        else:
            self._btn_add_project.setText("➕")
        self._btn_add_project.setToolTip("Add project root")
        self._btn_add_project.setFixedSize(26, 26)
        self._btn_add_project.clicked.connect(self.tree._add_project_root)
        
        self._btn_add_database = QToolButton(toolbar)
        icon_db = _icon("swap.svg")
        if not icon_db.isNull():
            self._btn_add_database.setIcon(icon_db)
        else:
            self._btn_add_database.setText("🗄")
        self._btn_add_database.setToolTip("Add database connection")
        self._btn_add_database.setFixedSize(26, 26)
        self._btn_add_database.clicked.connect(self.tree._add_database_root)
        
        self._btn_import_json = QToolButton(toolbar)
        # Use Material icons from symbols/ (avoid missing legacy filenames).
        icon_import = _icon("upload_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg")
        if not icon_import.isNull():
            self._btn_import_json.setIcon(icon_import)
        else:
            self._btn_import_json.setText("📥")
        self._btn_import_json.setToolTip("Import JSON file")
        self._btn_import_json.setFixedSize(26, 26)
        self._btn_import_json.clicked.connect(self.tree._import_json_file)
        
        self._btn_export_json = QToolButton(toolbar)
        icon_export = _icon("file_export_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg")
        if not icon_export.isNull():
            self._btn_export_json.setIcon(icon_export)
        else:
            self._btn_export_json.setText("📤")
        self._btn_export_json.setToolTip("Export to JSON file")
        self._btn_export_json.setFixedSize(26, 26)
        self._btn_export_json.clicked.connect(self.tree._export_json_file)
        
        self._btn_templates = QToolButton(toolbar)
        icon_template = _icon("toolbar_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg")
        if not icon_template.isNull():
            self._btn_templates.setIcon(icon_template)
        else:
            self._btn_templates.setText("📋")
        self._btn_templates.setToolTip("Load template")
        self._btn_templates.setFixedSize(26, 26)
        self._btn_templates.clicked.connect(self.tree._load_template)
        
        self._btn_save_template = QToolButton(toolbar)
        icon_save_template = _icon("save_.svg")
        if not icon_save_template.isNull():
            self._btn_save_template.setIcon(icon_save_template)
        else:
            self._btn_save_template.setText("💾")
        self._btn_save_template.setToolTip("Save as template")
        self._btn_save_template.setFixedSize(26, 26)
        self._btn_save_template.clicked.connect(self.tree._save_as_template)
        
        # Add buttons to toolbar
        toolbar_layout.addWidget(self._btn_load_history)
        toolbar_layout.addWidget(self._btn_collapse_all)
        toolbar_layout.addWidget(self._btn_add_project)
        toolbar_layout.addWidget(self._btn_add_database)
        toolbar_layout.addWidget(self._btn_import_json)
        toolbar_layout.addWidget(self._btn_export_json)
        toolbar_layout.addWidget(self._btn_templates)
        toolbar_layout.addWidget(self._btn_save_template)
        toolbar_layout.addStretch()
        
        # Add widgets to main layout
        layout.addWidget(toolbar)
        layout.addWidget(self.tree)

    def set_accent_color(self, color: QColor | str) -> None:
        """Update accent-dependent colors (toolbar + root icons)."""
        if isinstance(color, QColor):
            color_str = color.name(QColor.HexRgb)
        else:
            color_str = str(color).strip() or self._accent_color

        if color_str == self._accent_color:
            return
        self._accent_color = color_str
        self._apply_toolbar_style(self._toolbar)
        self.tree.set_accent_color(color_str)
    
    def _apply_wrapper_style(self) -> None:
        self.setStyleSheet(
            f"QWidget#JsonTreeWidgetWithToolbar {{ background: {self._bg_color}; }}"
        )

    def _apply_toolbar_style(self, toolbar: QFrame) -> None:
        toolbar.setStyleSheet(
            self._toolbar_style_template.format(bg=self._bg_color, accent=self._accent_color)
        )

    def set_text_color(self, color: QColor | str) -> None:
        self.tree.set_text_color(color)

    def set_background_color(self, color: QColor | str) -> None:
        self._bg_color = color.name(QColor.HexRgb) if isinstance(color, QColor) else str(color)
        self._apply_toolbar_style(self._toolbar)
        self._apply_wrapper_style()
        self.tree.set_background_color(color)

    def set_background_color(self, color: QColor | str) -> None:
        """Set tree and toolbar background to match outer widgets."""
        if isinstance(color, str):
            color = color.strip()
            if not color:
                return
            color_str = color
        elif isinstance(color, QColor):
            color_str = color.name(
                QColor.HexArgb if color.alpha() < 255 else QColor.HexRgb
            )
        else:
            return

        if color_str == self._bg_color:
            return

        self._bg_color = color_str
        self._apply_wrapper_style()
        # toolbar is first child; safe to re-apply via findChild
        toolbar = self.findChild(QFrame, "JsonTreeToolbar")
        if toolbar:
            self._apply_toolbar_style(toolbar)
        self.tree.set_background_color(color_str)

    def set_text_color(self, color: QColor | str) -> None:
        """Forward text color to inner tree."""
        self.tree.set_text_color(color)
    
    # Expose tree methods for convenience
    def add_to_section(self, section_name: str, key: str, value: Any, *, persist: bool = True) -> None:
        self.tree.add_to_section(section_name, key, value, persist=persist)
    
    def remove_from_section(self, section_name: str, item_name: str) -> bool:
        return self.tree.remove_from_section(section_name, item_name)
    
    def set_json(self, data: Any) -> None:
        self.tree.set_json(data)


# ------------------------- JsonTreeWidget -------------------------------
class JsonTreeWidget(QTreeWidget):
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setAnimated(True)

        # Guards / caches for persistence.
        self._initializing = True
        self._item_last_text: dict[QTreeWidgetItem, str] = {}
        self._last_saved_hash: str | None = None
        
        # Store data for each section separately
        self._data: dict[str, dict[str, Any]] = {}
        
        # Store multiple root categories (like VS Code sections)
        self._root_sections: dict[str, QTreeWidgetItem] = {}
        
        # Track which items belong to which section
        self._item_to_section: dict[QTreeWidgetItem, str] = {}
        self._item_to_key: dict[QTreeWidgetItem, str] = {}
        self._item_kind: dict[QTreeWidgetItem, str] = {}
        self._item_badge: dict[QTreeWidgetItem, str] = {}

        self._style_template = """
               QTreeWidget, QTreeView {{
                   background-color:{bg_color};
                   color:{text_color};
                   font-family:'Fira Code', monospace;
               }}
               QTreeWidget::item, QTreeView::item {{
                   padding: 2px;
                   background-color:{bg_color};
               }}
               QTreeWidget::branch, QTreeView::branch {{ color:{branch_color}; }}
               QTreeWidget::branch:has-children:!adjoins-item,
               QTreeView::branch:has-children:!adjoins-item {{
                   background-color:{bg_color};
               }}
               QTreeWidget::branch:closed:has-children:!adjoins-item,
               QTreeView::branch:closed:has-children:!adjoins-item {{
                   background-color:{bg_color};
               }}
               QTreeWidget::branch:open:has-children:!adjoins-item,
               QTreeView::branch:open:has-children:!adjoins-item {{
                   background-color:{bg_color};
               }}
               """
        self._branch_color = "#2d8cf0"
        self._text_color = "#d4d4d4"
        self._bg_color = "#1D1D1D"
        self._accent_color = "#3a5fff"

        # Typography
        self._section_header_font_size = 10
        self._section_item_font_size_small = 10
        self._apply_stylesheet()

        # NOTE: itemChanged is connected after initial population to avoid
        # triggering persistence while icons/fonts are being applied.
        
        # Enable context menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        
        # Initialize default root sections
        self._initialize_root_sections()

        # Connect signal for handling item edits (after initial load).
        self.itemChanged.connect(self._on_item_changed)
        self._remember_tree_texts()
        self._initializing = False

    def _remember_tree_texts(self) -> None:
        for section in self._root_sections.values():
            if section is None:
                continue
            self._remember_item_texts_recursive(section)

    def _remember_item_texts_recursive(self, item: QTreeWidgetItem) -> None:
        self._item_last_text[item] = item.text(0).strip()
        for i in range(item.childCount()):
            child = item.child(i)
            if child is not None:
                self._remember_item_texts_recursive(child)

    def _item_depth(self, item: QTreeWidgetItem) -> int:
        """Depth below a section header.

        Section header children => depth 1.
        """
        depth = 0
        cur = item
        while cur is not None:
            parent = cur.parent()
            if parent is None:
                break
            depth += 1
            if parent in self._root_sections.values():
                break
            cur = parent
        return max(depth, 0)

    def _item_base_icon_name(self, item: QTreeWidgetItem) -> str:
        kind = self._item_kind.get(item, "")
        depth = self._item_depth(item)

        # Special-case: items directly under the HISTORY section should use a history icon.
        try:
            parent = item.parent()
            if parent is not None and parent == self._root_sections.get("HISTORY"):
                return "load_content.svg"
        except Exception:
            pass

        # Containers
        if kind == "dict":
            return "explorer.svg" if depth <= 1 else "expansion_panels.svg"
        if kind == "list":
            return "compare_arrows_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"

        # Leaves (value types)
        if kind == "bool":
            return "check_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"
        if kind == "null":
            return "close.svg"
        if kind == "num":
            return "analyse.svg"
        if kind == "str":
            return "html_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"

        # Fallback
        return "open_file.svg" if depth <= 1 else "menu_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"

    def _apply_item_icon(self, item: QTreeWidgetItem) -> None:
        # Never override the section header icons.
        if item in self._root_sections.values():
            return

        base = _icon(self._item_base_icon_name(item))
        if base.isNull():
            return

        size = 18
        # Neutral icon tint.
        ico = _tinted_icon(base, color=self._text_color, size=size)

        # HISTORY root items: show date badge instead of dot marker
        badge = self._item_badge.get(item, "")
        if badge:
            ico = _icon_with_badge_text(
                ico,
                text=badge,
                badge_color=self._accent_color,
                text_color="#111111",
                size=size,
            )
        else:
            ico = _icon_with_marker(ico, marker_color=self._accent_color, size=size)
        item.setIcon(0, ico)

    @staticmethod
    def _format_date_badge(date_str: str) -> str:
        s = (date_str or "").strip()
        if not s:
            return ""

        # Accept compact numeric formats often found in persisted history.
        # Examples:
        # - ddmmyy    => 080120
        # - ddmmyyyy  => 08012026
        # - yyyymmdd  => 20260108
        digits = "".join(ch for ch in s if ch.isdigit())
        if digits:
            # If the value came from an int, leading zeros are lost (e.g. 080120 -> 80120).
            # Pad short sequences back to ddmmyy.
            if len(digits) in (4, 5):
                digits = digits.zfill(6)
            if len(digits) == 6:  # ddmmyy
                dd, mm = digits[:2], digits[2:4]
            elif len(digits) == 8:
                # Prefer yyyymmdd when it looks like a year prefix.
                if digits.startswith(("19", "20")):
                    dd, mm = digits[6:8], digits[4:6]
                else:  # ddmmyyyy
                    dd, mm = digits[:2], digits[2:4]
            elif len(digits) >= 10 and digits.startswith(("19", "20")):
                # e.g. 2026-01-08T... -> take leading yyyymmdd
                dd, mm = digits[6:8], digits[4:6]
            else:
                dd = mm = ""

            month = {
                "01": "Jan",
                "02": "Feb",
                "03": "Mar",
                "04": "Apr",
                "05": "May",
                "06": "Jun",
                "07": "Jul",
                "08": "Aug",
                "09": "Sep",
                "10": "Oct",
                "11": "Nov",
                "12": "Dec",
            }.get(mm, "")
            if dd and month:
                return f"{dd} {month}"

        # common format in this repo: dd.mm.yyyy -> show 'dd Mon'
        if len(s) >= 10 and s[2] == "." and s[5] == ".":
            dd = s[:2]
            mm = s[3:5]
            month = {
                "01": "Jan",
                "02": "Feb",
                "03": "Mar",
                "04": "Apr",
                "05": "May",
                "06": "Jun",
                "07": "Jul",
                "08": "Aug",
                "09": "Sep",
                "10": "Oct",
                "11": "Nov",
                "12": "Dec",
            }.get(mm, "")
            if month:
                return f"{dd} {month}"
            return dd

        # fallback: keep it short
        return s[:6]

    @staticmethod
    def _extract_history_badge(value: Any) -> str:
        """Try to extract a human-readable date badge from a history payload."""
        # expected shapes:
        # - list[dict] with dicts containing 'date'
        # - list[list[dict]] (some versions store sessions)
        # - dict with nested lists

        def _iter_entries(obj: Any):
            if isinstance(obj, list):
                for x in obj:
                    yield x
            elif isinstance(obj, dict):
                # try common containers
                for k in ("history", "messages", "items", "data"):
                    cand = obj.get(k)
                    if isinstance(cand, list):
                        for x in cand:
                            yield x

        last_date: str | None = None
        try:
            # Walk from the end so we pick the latest date.
            if isinstance(value, list):
                candidates = list(value)
            else:
                candidates = list(_iter_entries(value))

            for entry in reversed(candidates):
                if isinstance(entry, dict):
                    d = entry.get("date")
                    if d is not None:
                        ds = str(d).strip()
                        if ds:
                            last_date = ds
                        break
                elif isinstance(entry, list):
                    for sub in reversed(entry):
                        if isinstance(sub, dict):
                            d = sub.get("date")
                            if d is not None:
                                ds = str(d).strip()
                                if ds:
                                    last_date = ds
                                break
                    if last_date:
                        break
        except Exception:
            last_date = None

        if not last_date:
            return ""
        return JsonTreeWidget._format_date_badge(last_date)

    def _refresh_item_icons_recursive(self, parent: QTreeWidgetItem | None = None) -> None:
        if parent is None:
            for i in range(self.topLevelItemCount()):
                top = self.topLevelItem(i)
                if top is not None:
                    self._refresh_item_icons_recursive(top)
            return

        self._apply_item_icon(parent)
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child is not None:
                self._refresh_item_icons_recursive(child)

    def set_accent_color(self, color: QColor | str) -> None:
        if isinstance(color, QColor):
            color_str = color.name(QColor.HexRgb)
        else:
            color_str = str(color).strip()
        if not color_str or color_str == self._accent_color:
            return
        self._accent_color = color_str
        self._update_root_section_header_styles()
        self._update_root_section_icons()
        self._refresh_item_icons_recursive()
    
    def _apply_stylesheet(self) -> None:
        """Apply the current colors to the QTreeWidget stylesheet."""
        self.setStyleSheet(
            self._style_template.format(
                text_color=self._text_color,
                bg_color=self._bg_color,
                branch_color=self._branch_color,
            )
            + SCROLLBAR_HOVER_ONLY_DARK
        )

    def set_text_color(self, color: QColor | str) -> None:
        """Expose text color change so other widgets can match their palette."""
        if isinstance(color, str):
            color = color.strip()
            if not color:
                return
            color_str = color
        elif isinstance(color, QColor):
            color_str = color.name(
                QColor.HexArgb if color.alpha() < 255 else QColor.HexRgb
            )
        else:
            return

        if color_str == self._text_color:
            return

        self._text_color = color_str
        self._apply_stylesheet()
        self._update_root_section_header_styles()
        self._refresh_item_icons_recursive()

    def set_background_color(self, color: QColor | str) -> None:
        """Expose background change so parents can sync with chat prompt area."""
        if isinstance(color, str):
            color = color.strip()
            if not color:
                return
            color_str = color
        elif isinstance(color, QColor):
            color_str = color.name(
                QColor.HexArgb if color.alpha() < 255 else QColor.HexRgb
            )
        else:
            return

        if color_str == self._bg_color:
            return

        self._bg_color = color_str
        self._apply_stylesheet()
    

      
    def set_json(self, data: Any) -> None:
        """Rebuild tree from `data` and collapse to top level."""
        self._data = data  # Store for save logic
        self.clear()
        root_item = self._build_item("root", data, section_name=None)
        # move children of artificial root to top level
        while root_item.childCount():
            self.addTopLevelItem(root_item.takeChild(0))
        self.expandToDepth(0)

    def _build_item(self, key: str | int, value: Any, *, section_name: str | None = None) -> QTreeWidgetItem:
        section_upper = (section_name or "").upper()

        idx: int | None = None
        if isinstance(key, int):
            idx = key
            # HISTORY requested: no brackets around numeric indices.
            key_label = str(key) if section_upper == "HISTORY" else f"[{key}]"
        else:
            key_label = str(key)
            # Backward-compat: older persisted data may contain bracketed indices as strings.
            # e.g. "[1428]" -> "1428"
            if section_upper == "HISTORY":
                k = key_label.strip()
                if k.startswith("[") and k.endswith("]"):
                    inner = k[1:-1].strip()
                    if inner.isdigit():
                        key_label = inner

        if isinstance(value, dict):
            if section_upper == "HISTORY":
                # Requested: remove brackets/dots/braces. Keep it compact.
                d = value.get("date")
                badge = self._format_date_badge(str(d)) if d is not None else ""
                role = value.get("role")
                role_str = str(role).strip() if isinstance(role, str) else ""
                parts = [key_label]
                if badge:
                    parts.append(badge)
                if role_str:
                    parts.append(role_str)
                label = " ".join(p for p in parts if p)
            else:
                label = f"{key_label} {{...}}"

            item = QTreeWidgetItem([label])
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self._item_kind[item] = "dict"
            for k, v in value.items():
                item.addChild(self._build_item(k, v, section_name=section_name))
        elif isinstance(value, (list, tuple)):
            item = QTreeWidgetItem([f"{key_label} [{len(value)}]"])
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self._item_kind[item] = "list"
            for i, v in enumerate(value):
                item.addChild(self._build_item(i, v, section_name=section_name))
        else:
            text = json.dumps(value, ensure_ascii=False)
            item = QTreeWidgetItem([f"{key_label}: {text}"])
            item.setFlags(item.flags() | Qt.ItemIsEditable)

            if value is None:
                self._item_kind[item] = "null"
            elif isinstance(value, bool):
                self._item_kind[item] = "bool"
            elif isinstance(value, (int, float)):
                self._item_kind[item] = "num"
            elif isinstance(value, str):
                self._item_kind[item] = "str"
            else:
                self._item_kind[item] = "other"

        if section_upper in ("PROJECTS", "HISTORY"):
            f = item.font(0)
            f.setPointSize(self._section_item_font_size_small)
            item.setFont(0, f)

        self._apply_item_icon(item)
        return item

    @Slot(QTreeWidgetItem, int)
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle item edits by syncing changes back into the stored data."""
        # Block recursion
        if self.signalsBlocked():
            return

        # Ignore startup / programmatic updates that don't represent a real text edit.
        if self._initializing:
            return
            
        new_text = item.text(column).strip()
        if not new_text:
            return

        last_text = self._item_last_text.get(item)
        if last_text is not None and last_text == new_text:
            return

        # Update early so repeated non-text itemChanged events don't re-enter.
        self._item_last_text[item] = new_text
        
        # Check if this item belongs to a section
        section_name = self._item_to_section.get(item)
        if section_name is None:
            # Try to find section by walking up the tree
            parent = item.parent()
            while parent is not None:
                for sect_name, sect_item in self._root_sections.items():
                    if sect_item == parent:
                        section_name = sect_name
                        break
                if section_name:
                    break
                parent = parent.parent()
        
        if section_name is None or section_name not in self._data:
            return

        def extract_key(text: str) -> str:
            if ": " in text:
                return text.split(": ", 1)[0].strip()
            if text.endswith(" {...}"):
                return text[:-5].strip()
            if text.endswith(" [") and text.rsplit(" ", 1)[-1].endswith("]"):
                # fallback, although current formatter won't hit this
                return text.rsplit(" ", 1)[0].strip()
            if " [" in text and text.endswith("]"):
                return text.rsplit(" ", 1)[0].strip()
            return text.strip()

        def coerce_key(segment: str, container: Any) -> Any:
            if isinstance(container, (list, tuple)) and segment.startswith("[") and segment.endswith("]"):
                inner = segment[1:-1]
                if inner.isdigit():
                    return int(inner)
            return segment

        def parse_value(text: str) -> Any:
            try:
                return json.loads(text)
            except Exception:
                return text

        # Build the path from root to the edited item (skip section root)
        path_segments: list[str] = []
        current = item
        section_root = self._root_sections.get(section_name)
        
        while current is not None and current != section_root:
            path_segments.append(extract_key(current.text(column)))
            current = current.parent()
        path_segments.reverse()
        
        if not path_segments:
            return

        # Walk the stored data to reach the parent container of the edited key
        # Start from the section data
        parent_container: Any = self._data[section_name]
        for segment in path_segments[:-1]:
            key_obj = coerce_key(segment, parent_container)
            try:
                parent_container = parent_container[key_obj]
            except (KeyError, IndexError, TypeError):
                return

        last_segment = path_segments[-1]
        key_obj = coerce_key(last_segment, parent_container)

        if ": " not in new_text:
            return

        key_part, value_part = new_text.split(": ", 1)
        key_part = key_part.strip()
        value_part = value_part.strip()
        parsed_value = parse_value(value_part)

        if isinstance(parent_container, dict):
            # Handle key rename if needed
            if key_part != last_segment:
                try:
                    parent_container[key_part] = parent_container.pop(key_obj)
                except KeyError:
                    parent_container[key_part] = parsed_value
                key_obj = key_part
                last_segment = key_part
            parent_container[key_obj] = parsed_value
        elif isinstance(parent_container, list):
            if not isinstance(key_obj, int) or not (0 <= key_obj < len(parent_container)):
                return
            parent_container[key_obj] = parsed_value
            key_part = last_segment  # keep list index label
        else:
            return

        canonical_text = f"{key_part}: {json.dumps(parsed_value, ensure_ascii=False)}"
        if canonical_text != item.text(column):
            self.blockSignals(True)
            item.setText(column, canonical_text)
            self.blockSignals(False)
            self._item_last_text[item] = canonical_text.strip()
        
        # Persist changes to disk after successful edit
        self._save_data()
    
    def _initialize_root_sections(self) -> None:
        """Initialize default root sections like VS Code Explorer."""
        self._add_root_section("PROJECTS", collapsed=False)
        self._add_root_section("DATABASES", collapsed=True)
        self._add_root_section("HISTORY", collapsed=True)
        
        # Initialize empty data dictionaries for each section
        self._data["PROJECTS"] = {}
        self._data["DATABASES"] = {}
        self._data["HISTORY"] = {}
        
        # Load previously saved data if available
        self._load_data()

        # Ensure root headers match current theme settings.
        self._update_root_section_header_styles()
        self._update_section_item_font_sizes()

    def _update_section_item_font_sizes(self) -> None:
        """Apply per-section font sizing to already-built items."""

        def apply_recursive(parent: QTreeWidgetItem, point_size: int) -> None:
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child is None:
                    continue
                f = child.font(0)
                f.setPointSize(point_size)
                child.setFont(0, f)
                apply_recursive(child, point_size)

        for section_name in ("PROJECTS", "HISTORY"):
            root = self._root_sections.get(section_name)
            if root is not None:
                apply_recursive(root, self._section_item_font_size_small)

    def _update_root_section_header_styles(self) -> None:
        for section in self._root_sections.values():
            if section is None:
                continue
            font = section.font(0)
            font.setBold(True)
            font.setPointSize(self._section_header_font_size)
            section.setFont(0, font)
            section.setForeground(0, QColor(self._accent_color))
    
    def _add_root_section(self, name: str, collapsed: bool = False) -> QTreeWidgetItem:
        """Add a new root section (like 'PROJECTS' or 'DATABASES' in VS Code)."""
        if name in self._root_sections:
            return self._root_sections[name]
        
        section = QTreeWidgetItem([name.upper()])
        section.setFlags(section.flags() | Qt.ItemIsEditable)
        
        # Style for section headers (bold, slightly different color)
        font = section.font(0)
        font.setBold(True)
        font.setPointSize(self._section_header_font_size)
        section.setFont(0, font)
        section.setForeground(0, QColor(self._accent_color))

        # Accent-colored root icon + accent marker
        icon_name = {
            "PROJECTS": "deployed_code.svg",
            "DATABASES": "swap.svg",
            "HISTORY": "load_content.svg",
        }.get(name.upper())
        if icon_name:
            base = _icon(icon_name)
            if not base.isNull():
                ico = _icon_with_marker(_tinted_icon(base, color=self._accent_color, size=16), marker_color=self._accent_color, size=16)
                section.setIcon(0, ico)
        
        self.addTopLevelItem(section)
        self._root_sections[name] = section
        
        if not collapsed:
            section.setExpanded(True)
        
        return section

    def _update_root_section_icons(self) -> None:
        for name, section in self._root_sections.items():
            icon_name = {
                "PROJECTS": "deployed_code.svg",
                "DATABASES": "swap.svg",
                "HISTORY": "load_content.svg",
            }.get(name.upper())
            if not icon_name:
                continue
            base = _icon(icon_name)
            if base.isNull():
                continue
            ico = _icon_with_marker(_tinted_icon(base, color=self._accent_color, size=16), marker_color=self._accent_color, size=16)
            section.setIcon(0, ico)
    
    def add_to_section(self, section_name: str, key: str, value: Any, *, persist: bool = True) -> None:
        """Add data to a specific section (e.g., 'PROJECTS', 'DATABASES').

        Set persist=False for derived/ephemeral views (e.g. ChatHistory preview)
        to avoid bloating AppData/tree_data.json.
        """
        section = self._root_sections.get(section_name)
        if section is None:
            section = self._add_root_section(section_name)
            self._data[section_name] = {}
        
        # Store the data in our internal structure
        if section_name not in self._data:
            self._data[section_name] = {}
        self._data[section_name][key] = value
        
        item = self._build_item(key, value, section_name=section_name)
        section.addChild(item)

        # Remember baseline text for edit detection.
        self._remember_item_texts_recursive(item)

        # Ensure consistent font sizing for sections that use smaller typography.
        if section_name.upper() in ("PROJECTS", "HISTORY"):
            self._update_section_item_font_sizes()

        if section_name.upper() == "HISTORY":
            # Force history semantics for icon selection.
            self._item_kind[item] = "history"
            badge = self._extract_history_badge(value)
            if badge:
                self._item_badge[item] = badge
            self._apply_item_icon(item)
        
        # Track this item's section and key
        self._item_to_section[item] = section_name
        self._item_to_key[item] = key
        
        section.setExpanded(True)
        
        # Save after adding (unless this is a derived/ephemeral view)
        if persist:
            self._save_data()
    
    def remove_from_section(self, section_name: str, item_name: str) -> bool:
        """Remove an item from a section by name."""
        section = self._root_sections.get(section_name)
        if section is None:
            return False
        
        for i in range(section.childCount()):
            child = section.child(i)
            if child and item_name in child.text(0):
                section.removeChild(child)
                
                # Remove from data structure
                if section_name in self._data and item_name in self._data[section_name]:
                    del self._data[section_name][item_name]
                
                # Remove from tracking dicts
                if child in self._item_to_section:
                    del self._item_to_section[child]
                if child in self._item_to_key:
                    del self._item_to_key[child]

                if child in self._item_last_text:
                    del self._item_last_text[child]
                
                self._save_data()
                return True
        return False
    
    @Slot(bool)
    def _add_project_root(self, checked: bool = False) -> None:
        """Add a new project root to the PROJECTS section."""
        from PySide6.QtWidgets import QInputDialog
        
        name, ok = QInputDialog.getText(
            self, 
            "New Project", 
            "Enter project name:",
            text="New Project"
        )
        
        if ok and name:
            project_data = {
                "name": name,
                "path": "",
                "files": [],
                "settings": {}
            }
            self.add_to_section("PROJECTS", name, project_data)
    
    @Slot(bool)
    def _add_database_root(self, checked: bool = False) -> None:
        """Add a new database connection to the DATABASES section."""
        from PySide6.QtWidgets import QInputDialog
        
        name, ok = QInputDialog.getText(
            self, 
            "New Database Connection", 
            "Enter connection name:",
            text="New Connection"
        )
        
        if ok and name:
            db_data = {
                "name": name,
                "type": "PostgreSQL",
                "host": "localhost",
                "port": 5432,
                "database": "",
                "username": ""
            }
            self.add_to_section("DATABASES", name, db_data)
    
    def _save_data(self) -> None:
        """Save the current data structure to disk."""
        try:
            # Use AppData directory relative to the module
            app_data_dir = Path(__file__).parent.parent / "AppData"
            app_data_dir.mkdir(exist_ok=True)
            save_path = app_data_dir / "tree_data.json"

            payload = json.dumps(self._data, ensure_ascii=False, sort_keys=True)
            payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if self._last_saved_hash == payload_hash:
                return
            
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            self._last_saved_hash = payload_hash
            print(f"[INFO] Tree data saved to {save_path}")
        except Exception as e:
            print(f"[WARNING] Could not save tree data: {e}")
    
    def _load_data(self) -> None:
        """Load the data structure from disk."""
        try:
            # Use AppData directory relative to the module
            app_data_dir = Path(__file__).parent.parent / "AppData"
            load_path = app_data_dir / "tree_data.json"
            
            if load_path.exists():
                with open(load_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)

                # Restore internal data first so edits persist correctly.
                if isinstance(loaded_data, dict):
                    for section_name, section_data in loaded_data.items():
                        if isinstance(section_data, dict):
                            self._data[section_name] = section_data

                # Snapshot hash so we don't immediately re-save identical content.
                payload = json.dumps(self._data, ensure_ascii=False, sort_keys=True)
                self._last_saved_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    
                # Restore all sections
                self.blockSignals(True)
                for section_name, section_data in loaded_data.items():
                    if section_name not in self._root_sections:
                        self._add_root_section(section_name)
                    
                    if isinstance(section_data, dict):
                        for key, value in section_data.items():
                            # Don't call add_to_section during load to avoid saving again
                            section = self._root_sections.get(section_name)
                            if section:
                                item = self._build_item(key, value, section_name=section_name)
                                section.addChild(item)
                                self._item_to_section[item] = section_name
                                self._item_to_key[item] = key
                                self._remember_item_texts_recursive(item)
                                if section_name.upper() == "HISTORY":
                                    self._item_kind[item] = "history"
                                    badge = self._extract_history_badge(value)
                                    if badge:
                                        self._item_badge[item] = badge
                                    self._apply_item_icon(item)
                self.blockSignals(False)
                print(f"[INFO] Tree data loaded from {load_path}")
        except Exception as e:
            print(f"[INFO] Could not load tree data (this is normal on first run): {e}")
    
    @Slot(bool)
    def _import_json_file(self, checked: bool = False) -> None:
        """Import JSON data from a file."""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import JSON File",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)
            
            # Ask which section to add the data to
            sections = list(self._root_sections.keys())
            section_name, ok = QInputDialog.getItem(
                self,
                "Select Section",
                "Add imported data to section:",
                sections,
                0,
                False
            )
            
            if not ok or not section_name:
                return
            
            # Ask for a key name
            file_name = Path(file_path).stem
            key_name, ok = QInputDialog.getText(
                self,
                "Item Name",
                "Enter name for imported data:",
                text=file_name
            )
            
            if ok and key_name:
                self.add_to_section(section_name, key_name, imported_data)
                QMessageBox.information(
                    self,
                    "Import Success",
                    f"Data imported to {section_name}/{key_name}"
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import JSON file:\n{e}"
            )
    
    @Slot(bool)
    def _export_json_file(self, checked: bool = False) -> None:
        """Export current data to a JSON file with section selection."""
        from PySide6.QtWidgets import QFileDialog, QDialog, QVBoxLayout, QCheckBox, QPushButton, QDialogButtonBox
        
        # Create dialog for section selection
        dialog = QDialog(self)
        dialog.setWindowTitle("Export Sections")
        dialog.setMinimumWidth(300)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QMessageBox().information(None, "Info", "Select sections to export:") or QWidget())
        
        # Create checkboxes for each section
        checkboxes = {}
        for section_name in self._root_sections.keys():
            item_count = len(self._data.get(section_name, {}))
            cb = QCheckBox(f"{section_name} ({item_count} items)")
            cb.setChecked(True)
            checkboxes[section_name] = cb
            layout.addWidget(cb)
        
        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Get selected sections
        selected_sections = {
            name: self._data[name]
            for name, cb in checkboxes.items()
            if cb.isChecked() and name in self._data
        }
        
        if not selected_sections:
            QMessageBox.warning(self, "Export", "No sections selected")
            return
        
        # File dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON File",
            str(Path.home() / "tree_export.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(selected_sections, f, indent=2, ensure_ascii=False)
            
            section_names = ", ".join(selected_sections.keys())
            QMessageBox.information(
                self,
                "Export Success",
                f"Sections exported: {section_names}\nTo: {file_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export JSON file:\n{e}"
            )
    
    @Slot(bool)
    def _load_template(self, checked: bool = False) -> None:
        """Load predefined templates or custom configurations."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QDialogButtonBox, QFileDialog, QPushButton
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Template or Configuration")
        dialog.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        # List of built-in templates
        list_widget = QListWidget()
        templates = self._get_builtin_templates()
        for name in templates.keys():
            list_widget.addItem(name)
        layout.addWidget(list_widget)
        
        # Custom file button
        custom_btn = QPushButton("Load from file...")
        custom_btn.clicked.connect(lambda: dialog.done(2))  # Custom result code
        layout.addWidget(custom_btn)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        result = dialog.exec()
        
        if result == QDialog.Accepted:
            # Load selected template
            selected_item = list_widget.currentItem()
            if selected_item:
                template_name = selected_item.text()
                template_data = templates.get(template_name)
                if template_data:
                    self._apply_template(template_data, template_name)
        elif result == 2:
            # Load from custom file
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Load Configuration File",
                str(Path.home()),
                "JSON Files (*.json);;All Files (*)"
            )
            if file_path:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    self._apply_template(config_data, Path(file_path).stem)
                except Exception as e:
                    QMessageBox.critical(self, "Load Error", f"Failed to load file:\n{e}")
    
    def _get_builtin_templates(self) -> dict:
        """Return built-in templates and user-saved templates."""
        templates = {
            "Python Web Project": {
                "PROJECTS": {
                    "WebApp": {
                        "name": "Python Web Application",
                        "path": "",
                        "files": ["app.py", "requirements.txt", "config.py"],
                        "settings": {
                            "framework": "Flask",
                            "python_version": "3.11",
                            "debug": True
                        }
                    }
                },
                "DATABASES": {
                    "PostgreSQL-Dev": {
                        "type": "PostgreSQL",
                        "host": "localhost",
                        "port": 5432,
                        "database": "webapp_dev",
                        "username": "dev_user"
                    }
                }
            },
            "Data Science Project": {
                "PROJECTS": {
                    "DataAnalysis": {
                        "name": "Data Analysis Project",
                        "path": "",
                        "files": ["analysis.ipynb", "data_processing.py", "requirements.txt"],
                        "settings": {
                            "python_version": "3.11",
                            "libraries": ["pandas", "numpy", "matplotlib", "scikit-learn"]
                        }
                    }
                }
            },
            "Microservices Setup": {
                "PROJECTS": {
                    "API-Gateway": {
                        "name": "API Gateway Service",
                        "path": "",
                        "port": 8000,
                        "type": "gateway"
                    },
                    "Auth-Service": {
                        "name": "Authentication Service",
                        "path": "",
                        "port": 8001,
                        "type": "microservice"
                    },
                    "Data-Service": {
                        "name": "Data Processing Service",
                        "path": "",
                        "port": 8002,
                        "type": "microservice"
                    }
                },
                "DATABASES": {
                    "Redis-Cache": {
                        "type": "Redis",
                        "host": "localhost",
                        "port": 6379
                    },
                    "MongoDB-Main": {
                        "type": "MongoDB",
                        "host": "localhost",
                        "port": 27017,
                        "database": "microservices"
                    }
                }
            },
            "Empty Workspace": {
                "PROJECTS": {},
                "DATABASES": {},
                "HISTORY": {}
            }
        }
        
        # Load user-saved templates
        try:
            templates_dir = Path(__file__).parent.parent / "AppData" / "templates"
            if templates_dir.exists():
                for template_file in templates_dir.glob("*.json"):
                    try:
                        with open(template_file, 'r', encoding='utf-8') as f:
                            template_data = json.load(f)
                        template_name = f"📁 {template_file.stem}"
                        templates[template_name] = template_data
                    except Exception as e:
                        print(f"[WARNING] Could not load template {template_file}: {e}")
        except Exception as e:
            print(f"[WARNING] Could not scan templates directory: {e}")
        
        return templates
    
    def _apply_template(self, template_data: dict, template_name: str) -> None:
        """Apply template data to the tree."""
        from PySide6.QtWidgets import QInputDialog
        
        # Ask if user wants to replace or merge
        options = ["Merge with existing", "Replace all"]
        choice, ok = QInputDialog.getItem(
            self,
            "Apply Template",
            f"How to apply template '{template_name}'?",
            options,
            0,
            False
        )
        
        if not ok:
            return
        
        if choice == "Replace all":
            # Clear all sections
            for section_name in list(self._root_sections.keys()):
                section = self._root_sections[section_name]
                while section.childCount() > 0:
                    section.removeChild(section.child(0))
                self._data[section_name] = {}
        
        # Apply template data
        for section_name, section_data in template_data.items():
            if section_name not in self._root_sections:
                self._add_root_section(section_name)
            
            if isinstance(section_data, dict):
                for key, value in section_data.items():
                    self.add_to_section(section_name, key, value)
        
        QMessageBox.information(
            self,
            "Template Applied",
            f"Template '{template_name}' has been applied successfully"
        )
    
    @Slot(bool)
    def _save_as_template(self, checked: bool = False) -> None:
        """Save current workspace as a reusable template."""
        from PySide6.QtWidgets import QInputDialog, QFileDialog
        
        # Ask for template name
        template_name, ok = QInputDialog.getText(
            self,
            "Save as Template",
            "Enter template name:",
            text="My Custom Template"
        )
        
        if not ok or not template_name:
            return
        
        # Choose what to include
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Sections to Include")
        dialog.setMinimumWidth(300)
        
        layout = QVBoxLayout(dialog)
        
        checkboxes = {}
        for section_name in self._root_sections.keys():
            item_count = len(self._data.get(section_name, {}))
            cb = QCheckBox(f"{section_name} ({item_count} items)")
            cb.setChecked(True)
            checkboxes[section_name] = cb
            layout.addWidget(cb)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Build template data
        template_data = {
            name: self._data.get(name, {})
            for name, cb in checkboxes.items()
            if cb.isChecked()
        }
        
        # Save to templates directory
        try:
            templates_dir = Path(__file__).parent.parent / "AppData" / "templates"
            templates_dir.mkdir(exist_ok=True)
            
            safe_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in template_name)
            template_file = templates_dir / f"{safe_name}.json"
            
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=2, ensure_ascii=False)
            
            QMessageBox.information(
                self,
                "Template Saved",
                f"Template '{template_name}' saved to:\n{template_file}\n\nYou can now load it from the templates menu."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save template:\n{e}"
            )
    
    @Slot(object)
    def _show_context_menu(self, position) -> None:
        """Show context menu for tree items."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        
        item = self.itemAt(position)
        if not item:
            return
        
        menu = QMenu(self)
        
        # Check if this is a section header or a regular item
        is_section = item in self._root_sections.values()
        
        if is_section:
            # Section header menu
            section_name = None
            for name, sect_item in self._root_sections.items():
                if sect_item == item:
                    section_name = name
                    break
            
            if section_name:
                # Add item to section
                add_action = QAction(f"➕ Add item to {section_name}", self)
                add_action.triggered.connect(lambda: self._context_add_item(section_name))
                menu.addAction(add_action)
                
                menu.addSeparator()
                
                # Export section
                export_action = QAction(f"📤 Export {section_name}", self)
                export_action.triggered.connect(lambda: self._context_export_section(section_name))
                menu.addAction(export_action)
                
                # Import to section
                import_action = QAction(f"📥 Import to {section_name}", self)
                import_action.triggered.connect(lambda: self._context_import_to_section(section_name))
                menu.addAction(import_action)
                
                menu.addSeparator()
                
                # Clear section
                clear_action = QAction(f"🗑 Clear {section_name}", self)
                clear_action.triggered.connect(lambda: self._context_clear_section(section_name))
                menu.addAction(clear_action)
        else:
            # Regular item menu
            section_name = self._item_to_section.get(item)
            item_key = self._item_to_key.get(item)
            
            # Rename
            rename_action = QAction("✏️ Rename", self)
            rename_action.triggered.connect(lambda: self.editItem(item, 0))
            menu.addAction(rename_action)
            
            # Duplicate
            duplicate_action = QAction("📋 Duplicate", self)
            duplicate_action.triggered.connect(lambda: self._context_duplicate_item(item, section_name, item_key))
            menu.addAction(duplicate_action)
            
            menu.addSeparator()
            
            # Export item
            export_action = QAction("📤 Export item", self)
            export_action.triggered.connect(lambda: self._context_export_item(item, section_name, item_key))
            menu.addAction(export_action)
            
            # Copy as JSON
            copy_action = QAction("📄 Copy as JSON", self)
            copy_action.triggered.connect(lambda: self._context_copy_json(item, section_name, item_key))
            menu.addAction(copy_action)
            
            menu.addSeparator()
            
            # Delete
            delete_action = QAction("🗑 Delete", self)
            delete_action.triggered.connect(lambda: self._context_delete_item(item, section_name, item_key))
            menu.addAction(delete_action)
        
        menu.exec(self.viewport().mapToGlobal(position))
    
    def _context_add_item(self, section_name: str) -> None:
        """Add new item to section via context menu."""
        from PySide6.QtWidgets import QInputDialog
        
        key, ok = QInputDialog.getText(self, "New Item", f"Enter name for new item in {section_name}:")
        if ok and key:
            self.add_to_section(section_name, key, {"value": ""})
    
    def _context_export_section(self, section_name: str) -> None:
        """Export single section."""
        from PySide6.QtWidgets import QFileDialog
        
        if section_name not in self._data:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {section_name}",
            str(Path.home() / f"{section_name.lower()}_export.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._data[section_name], f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Export Success", f"{section_name} exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")
    
    def _context_import_to_section(self, section_name: str) -> None:
        """Import JSON to specific section."""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import to {section_name}",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            key, ok = QInputDialog.getText(
                self,
                "Item Name",
                "Enter name for imported data:",
                text=Path(file_path).stem
            )
            
            if ok and key:
                self.add_to_section(section_name, key, data)
                QMessageBox.information(self, "Import Success", f"Data imported to {section_name}/{key}")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import:\n{e}")
    
    def _context_clear_section(self, section_name: str) -> None:
        """Clear all items in section."""
        reply = QMessageBox.question(
            self,
            "Clear Section",
            f"Delete all items in {section_name}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            section = self._root_sections.get(section_name)
            if section:
                while section.childCount() > 0:
                    section.removeChild(section.child(0))
                self._data[section_name] = {}
                self._save_data()
                QMessageBox.information(self, "Cleared", f"{section_name} has been cleared")
    
    def _context_duplicate_item(self, item: QTreeWidgetItem, section_name: str, item_key: str) -> None:
        """Duplicate an item."""
        from PySide6.QtWidgets import QInputDialog
        
        if not section_name or not item_key:
            return
        
        original_data = self._data.get(section_name, {}).get(item_key)
        if original_data is None:
            return
        
        new_key, ok = QInputDialog.getText(
            self,
            "Duplicate Item",
            "Enter name for duplicated item:",
            text=f"{item_key}_copy"
        )
        
        if ok and new_key:
            import copy
            self.add_to_section(section_name, new_key, copy.deepcopy(original_data))
            QMessageBox.information(self, "Duplicated", f"Item duplicated as {new_key}")
    
    def _context_export_item(self, item: QTreeWidgetItem, section_name: str, item_key: str) -> None:
        """Export single item to JSON file."""
        from PySide6.QtWidgets import QFileDialog
        
        if not section_name or not item_key:
            return
        
        item_data = self._data.get(section_name, {}).get(item_key)
        if item_data is None:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Item",
            str(Path.home() / f"{item_key}.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(item_data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Export Success", f"Item exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")
    
    def _context_copy_json(self, item: QTreeWidgetItem, section_name: str, item_key: str) -> None:
        """Copy item as JSON to clipboard."""
        from PySide6.QtWidgets import QApplication
        
        if not section_name or not item_key:
            return
        
        item_data = self._data.get(section_name, {}).get(item_key)
        if item_data is None:
            return
        
        try:
            json_str = json.dumps(item_data, indent=2, ensure_ascii=False)
            clipboard = QApplication.clipboard()
            clipboard.setText(json_str)
            QMessageBox.information(self, "Copied", "JSON copied to clipboard")
        except Exception as e:
            QMessageBox.warning(self, "Copy Error", f"Failed to copy:\n{e}")
    
    def _context_delete_item(self, item: QTreeWidgetItem, section_name: str, item_key: str) -> None:
        """Delete an item."""
        if not section_name or not item_key:
            return
        
        reply = QMessageBox.question(
            self,
            "Delete Item",
            f"Delete '{item_key}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.remove_from_section(section_name, item_key)
            QMessageBox.information(self, "Deleted", f"'{item_key}' has been deleted")
    
    @Slot(bool)
    def _show_history_tree(self, checked: bool = False) -> None:
        if ChatHistory is None:
            QMessageBox.information(self, "History", "ChatHistory not available")
            return
        try:
            history = ChatHistory._load()
        except Exception as e:
            QMessageBox.warning(self, "History", f"Could not load history: {e}")
            return
        # Restore original behavior: show the full history structure.
        # Still do not persist it into tree_data.json (history can be huge).
        try:
            self.remove_from_section("HISTORY", "Chat History")
        except Exception:
            pass
        self.add_to_section("HISTORY", "Chat History", history, persist=False)


# ------------------------- JsonHighlighter ------------------------------
from PySide6.QtCore import QRegularExpression

# ─────────────────────── JsonHighlighter ───────────────────────
class JsonHighlighter(QSyntaxHighlighter):
    """
    Tiny JSON syntax highlighter (dark theme) used by ClosableTextEdit but
    can be reused on every QTextDocument.
    """

    def __init__(self, doc):
        super().__init__(doc)

        mono = QFont("Fira Code", 10)
        mono.setStyleHint(QFont.Monospace)

        def _fmt(color: str) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setFont(mono)
            f.setForeground(QColor(color))
            return f

        self._fmt_string = _fmt("#ce9178")
        self._fmt_number = _fmt("#b5cea8")
        self._fmt_bool   = _fmt("#4fc1ff")
        self._fmt_null   = _fmt("#c586c0")
        self._fmt_key    = _fmt("#569cd6")

        # regular expressions ---------------------------------------------
        self._rx_string = QRegularExpression(r'"([^"\\]|\\.)*"')
        self._rx_number = QRegularExpression(
            r"\b-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?\b")
        self._rx_bool   = QRegularExpression(r"\b(true|false)\b")
        self._rx_null   = QRegularExpression(r"\bnull\b")
        self._rx_key    = QRegularExpression(r'"([^"\\]|\\.)*"\s*:')

    # noinspection PyPep8Naming
    def highlightBlock(self, text: str) -> None:         # noqa: N802
        """Apply colour formats for each token type."""
        def _apply(fmt: QTextCharFormat, rx: QRegularExpression):
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        _apply(self._fmt_string, self._rx_string)
        _apply(self._fmt_number, self._rx_number)
        _apply(self._fmt_bool,   self._rx_bool)
        _apply(self._fmt_null,   self._rx_null)
        _apply(self._fmt_key,    self._rx_key)




# ─── constants.py  (new helper file – may also live at the top of the module)
SCROLLBAR_HOVER_ONLY_DARK = """
/* ==== generic dark style – hide until mouse-over, no arrows ==== */

/* --- shared  -------------------------------------------------- */
QScrollBar:horizontal, QScrollBar:vertical {
    background: transparent;          /* nothing until hover        */
    margin: 0px;                      /* no outer gaps              */
    border: none;
}

/* size while idle (almost invisible but still receives hover)   */
QScrollBar:vertical   { width: 4px;  }
QScrollBar:horizontal { height:50px;  }

/* grow a bit + colour when mouse enters the bar itself          */
QScrollBar:vertical:hover   { width: 4px; }
QScrollBar:horizontal:hover { height:50px; }

/* ----- handle (the draggable knob) --------------------------- */
QScrollBar::handle {
    background: rgba(120,120,120,0.0);   /* transparent while idle  */
    border-radius: 4px;
    min-width: 4px;
    min-height: 600px;
}
QScrollBar::handle:hover {
    background: rgba(120,120,120,0.6);   /* show on hover           */
}

/* ----- remove arrows & useless areas ------------------------- */
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;  border: none;  width:0px; height:0px;
}
"""

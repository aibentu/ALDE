from __future__ import annotations    ## ai_ide_v1756.py

# Maintainer contact: see repository README.

import PySide6
import os
import sys
import importlib
import base64
import binascii
import uuid
import html
import re
import subprocess
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone

# Keep both repository roots on sys.path so local imports work in direct-script
# mode and when the module is imported through the lowercase package alias.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_workspace_root = os.path.dirname(_repo_root)
if _workspace_root not in sys.path:
    sys.path.insert(0, _workspace_root)

# Workaround für GNOME GLib-GIO-ERROR mit antialiasing
# Verhindert Crash durch fehlende GNOME-Settings-Keys
os.environ.setdefault('GDK_BACKEND', 'x11')
os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

# Unterdrücke GLib Warnings (optional, falls sie stören)
import warnings
warnings.filterwarnings('ignore', category=Warning)
from pathlib import Path
from typing import Any, Callable, Final, List, Optional
from io import BytesIO
import mimetypes


def _shutdown_loky_runtime() -> None:
    """Best-effort cleanup for reusable loky executors before interpreter exit."""
    get_reusable_executor = None
    for module_name in ("joblib.externals.loky", "loky"):
        try:
            module = importlib.import_module(module_name)
            get_reusable_executor = getattr(module, "get_reusable_executor", None)
            if callable(get_reusable_executor):
                break
        except Exception:
            continue

    if not callable(get_reusable_executor):
        return

    try:
        executor = get_reusable_executor()
    except Exception:
        return

    if executor is None:
        return

    try:
        executor.shutdown(wait=True, kill_workers=True)
    except TypeError:
        try:
            executor.shutdown(wait=True)
        except Exception:
            pass
    except Exception:
        pass


def _split_data_uri(data: str) -> tuple[str | None, str]:
    """Split a possible data-URI into (mime, base64_payload).

    Accepts strings like: data:image/png;base64,AAAA...
    Returns (None, original) when it's not a data-URI.
    """
    s = data.strip()
    if not s.lower().startswith("data:"):
        return None, data
    try:
        header, payload = s.split(",", 1)
    except ValueError:
        return None, data
    mime = None
    # data:<mime>;base64
    try:
        meta = header[5:]
        parts = [p.strip() for p in meta.split(";") if p.strip()]
        if parts and "/" in parts[0]:
            mime = parts[0]
    except Exception:
        mime = None
    return mime, payload


def _infer_image_ext(image_bytes: bytes, mime: str | None = None) -> str:
    if mime:
        m = mime.lower()
        if "png" in m:
            return ".png"
        if "webp" in m:
            return ".webp"
        if "jpeg" in m or "jpg" in m:
            return ".jpg"

    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return ".webp"
    return ".bin"


def decode_image_payload(payload: object) -> tuple[bytes, str | None]:
    """Decode image payload to raw bytes.

    Supports:
    - bytes/bytearray
    - base64 string
    - data-URI (data:image/png;base64,....)
    - list/tuple where the first element is any of the above

    Returns (bytes, mime_if_known).
    """
    if payload is None:
        raise ValueError("No image payload")

    if isinstance(payload, (list, tuple)):
        if not payload:
            raise ValueError("Empty image payload list")
        payload = payload[0]

    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload), None

    if isinstance(payload, str):
        mime, b64 = _split_data_uri(payload)
        b64 = "".join(b64.split())
        if len(b64) % 4:
            b64 += "=" * (4 - (len(b64) % 4))
        try:
            return base64.b64decode(b64, validate=False), mime
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Invalid base64 image payload: {exc}") from exc

    raise TypeError(f"Unsupported image payload type: {type(payload)!r}")


def save_generated_image(image_bytes: bytes, *, mime: str | None = None) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "AppData" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = _infer_image_ext(image_bytes, mime=mime)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"gen_{stamp}_{uuid.uuid4().hex[:8]}{ext}"
    out_path = out_dir / name
    out_path.write_bytes(image_bytes)
    return out_path

# ---------------------------------------------------------------------------
#  external file viewer — provides widgets & helper used for the „open file“
#  feature below.  Keeping this import clustered here avoids a hard runtime
#  dependency for users of ai_ide_v1.7.5.py that never invoke “open file”.
# ---------------------------------------------------------------------------

try:
    try:
        from .file_viewer import (
            classify as _fv_classify,
            ImageWidget as _FVImageWidget,
            ChatImageWidget as _FVChatImageWidget,
            PdfWidget as _FVPdfWidget,
            MarkdownWidget as _FVMarkdownWidget,
            TextWidget as _FVTextWidget,
            ZoomImageWidget as _FVZoomImageWidget,
        )
    except Exception:
        # Fallback for historical “run as script” mode.
        from file_viewer import (  # type: ignore
            classify as _fv_classify,
            ImageWidget as _FVImageWidget,
            ChatImageWidget as _FVChatImageWidget,
            PdfWidget as _FVPdfWidget,
            MarkdownWidget as _FVMarkdownWidget,
            TextWidget as _FVTextWidget,
            ZoomImageWidget as _FVZoomImageWidget,
        )
except Exception:    # pragma: no cover – soft-fail, detailed handling below
    _fv_classify = None  # type: ignore
    _FVImageWidget = _FVPdfWidget = _FVMarkdownWidget = _FVTextWidget = None  # type: ignore
    _FVChatImageWidget = None  # type: ignore

from dotenv import load_dotenv
from PySide6.QtCore import( Qt, QSize, Signal, Slot, QTimer, QEvent,
                            QSettings, QByteArray )            # >>>  NEU ai_ide_v1.7.5.py
from PySide6 import QtCore

from PySide6.QtGui import (
    QAction,
    QIcon,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QTextCursor,
    QTextOption,
    QFontMetrics,
    QPixmap,
    QPainter,
    QColor,
    QPen,
    QPalette,
    QKeySequence,
)

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QInputDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QSplitter,
    QScrollArea,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QMenuBar,
    QStyle,
    QProxyStyle,
    QTextBrowser,

)

# --------------------------------------------------------------------------
#  3rd-party back-end  (neighbour module)
# --------------------------------------------------------------------------

try:
    if __package__:
        from .agents_ccompletion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore
    else:
        from alde.agents_ccompletion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from agents_ccompletion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore  # noqa: E402
    else:
        raise

try:
    if __package__:
        from .litehigh import QSHighlighter, MDHighlighter, JSONHighlighter, TOMLHighlighter, YAMLHighlighter  # type: ignore
    else:
        from alde.litehigh import QSHighlighter, MDHighlighter, JSONHighlighter, TOMLHighlighter, YAMLHighlighter  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from litehigh import QSHighlighter, MDHighlighter, JSONHighlighter, TOMLHighlighter, YAMLHighlighter  # type: ignore
    else:
        raise

try:
    if __package__:
        from .jstree_widget import JsonTreeWidgetWithToolbar  # type: ignore
    else:
        from alde.jstree_widget import JsonTreeWidgetWithToolbar  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from jstree_widget import JsonTreeWidgetWithToolbar  # type: ignore
    else:
        raise


# --------------------------------------------------------------------------
# Shutdown safety toggles
# --------------------------------------------------------------------------

_HISTORY_FLUSHED_ONCE = False


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() in {"1", "true", "True", "yes", "Yes", "on", "On"}


def _maybe_flush_history(chat_obj=None) -> None:
    """Flush history at most once. 

    Controlled by env var:
      - AI_IDE_DISABLE_HISTORY_FLUSH=1  (skip history persistence)
            - AI_IDE_ENABLE_HISTORY_FLUSH_ON_QUIT=1  (enable flush hooks on quit/close)
    """
    global _HISTORY_FLUSHED_ONCE
    if _HISTORY_FLUSHED_ONCE:
        return
    if _env_truthy("AI_IDE_DISABLE_HISTORY_FLUSH", "0"):
        return
        # PySide6 can segfault when flushing during Qt shutdown hooks on some
        # environments (observed as EXIT:139). Keep shutdown flush disabled unless
        # explicitly enabled.
        if not _env_truthy("AI_IDE_ENABLE_HISTORY_FLUSH_ON_QUIT", "0"):
                return

    _HISTORY_FLUSHED_ONCE = True
    try:
        if chat_obj is not None:
            chat_obj._flush()
        else:
            ChatHistory._flush()  # type: ignore[misc]
    except Exception:
        pass

# ═══════════════════════  Farben / Style  ══════════════════════════════════

SCHEME_BLUE  = {"col1": "#3a5fff", "col2": "#6280ff",
                "menu_bg": "#1D1D1D",            # NEW
                "menu_sel": "rgba(80,80,80,100)"   # NEW
               }


SCHEME_GREEN = {"col1": "#0fe913", "col2": "#58ed5b",
                "menu_bg": "#1D1D1D",
                "menu_sel": "rgba(80,80,80,100)"
               }


SCHEME_GREY = {
    "col5": "#181818",
    "col6": "#E3E3DED6",
    "col7": "#1D1D1D",
    "col8": "#E3E3DED6",
    "col9": "#181818",
    "col10":"#404040",
    "col11":"#505050",
    "px1": "6px",
    "col12": "rgba(120,120,120,40)"
}


SCHEME_DARK = {
    "col5": "#1D1D1D",
    "col6": "#E3E3DED6",
    "col7": "#181818",           # << the ‘dark-black’ that should dominate
    "col8": "#E3E3DED6",
    "col9": "#1D1D1D",
    "col10":"#303030",
    "col11":"#505050",
    "px1": "6px",
    "col12": "rgba(120,120,120,40)",
}


# ------------------------------------------------------------------ style --


_STYLE = """
QMainWindow, QStatusBar, QWidget {{
    background:  {col7};
    color:       {col6};
    font-size:   20px;
    }}

QStatusBar {{
    font-size: 16px;
    }}

QToolBar {{
border: 0px ;  
padding: 8px; 
    }}

QToolBar::handle {{
background: transparent;

    }}

/* Tab widget / pane + tabs  → all the same dark background */

QTabWidget:pane:radius {{
background: {col5};
border: 1px solid {col10};
border-top: 0px;
border-radius: 20px;
margin: 5px;
    }}


/* changes 10.07.2025 font size to 16px  */

QTabBar::tab {{
    /* alle Default-Ränder entfernen … */
     border-top: 1px {col1};                   /* <<<  bottom-line verschwindet   */
     background: {col5};
    /* … und nur den gewünschten rechten Trenner neu setzen */
    border-right: 1px solid {col10};
    border-top: 1px {col7};
    border-radius: 6px;
    padding: 5px;
    height: 20px;
    font: 15px
    }}

QTabBar::tab:hover {{ 
    border-right: 1px solid {col1};
    font: 15px
    }}    

QTabBar::tab:pressed {{ 
    background: {col1};
    border-right: 1px solid {col10};  
    padding: 5px;
    height: 24px;
    font: 17px
    }}

QTabBar::tab:selected {{ 
    background: {col10};    
    border-right: 1px solid {col1};
    font 16px
    }} 

QSplitter::handle:horizontal {{  
    border-left: 3px solid transparent; 
    }}

QSplitter::handle:vertical {{
    border-top: 3px transparent; 
    }}

QSplitter::handle:hover,
QSplitter::handle:pressed {{ 
    border-color: {col1}; 
    }}

QPushButton {{
    background: {col7};
    color: {col7};
    border-radius: 3px; 
    padding: 2px;
    border: 1px  {col8};
    }}

QPushButton:hover {{
    color: {col1};
    background: {col1};
    border: 1px solid {col1};
    }}

QTextEdit, QLineEdit {{
    background: {col7};
    color:{col6};
    border-top: 1px solid {col7};
    }}

QDockWidget::separator {{ 
    background: transparent; width: {px1} 
    }}

QDockWidget::separator:hover {{ 
    background: {col12} 
    }}


/*# <---- changes 15.07.2025 AI Chat I/O Widget */

 
#aiInput {{                 /* was  #aiInput  */
    background: {col10};
    border: 1px solid {col1};   /* 1 px, Akzentfarbe */
    border-radius: 15px;
    padding: 5px;
    margin     : 0px 0px 2px 0px;      /* ⇐ 2 px Lücke nach unten */

    }}

         
/* --- NEW: sichtbarer Rahmen um die AI-Ausgabe --- changes 15.07.2025 --- */

    #aiOutput {{
        background: {col9};
        border: 1px solid {col10};   /* 1 px, Akzentfarbe */
        border-radius: 5px;         /* leicht abgerundet */
        padding: 5px;               /* Luft innen */
        margin: 5px 10px 5px 5px;   /* etwas Abstand zu Nachbarn */   
    }}
  
 """

# ─── style‐erweiterung # <– 10.07.2025 ───────────────────────────────────────── ─────
#   
#   NEU: blendet alle QMainWindow-Separatoren (die „Dock-Splitter-Griffe“)
#       unsichtbar aus, erhält aber eine 6-px breite Drag-Fläche.

_SEP_QSS = """
/*  MainWindow-Splitter: unsichtbar, aber weiter greifbar  */
QMainWindow::separator              {{ background: transparent;   width: 3px; }}
QMainWindow::separator:horizontal   {{ background: transparent;   height: 6px;}}
QMainWindow::separator:hover        {{ background: {col1}; }}
"""

# ─── Tooltip-QSS  (schwarz, opacity 230, weiße Schrift, runde Ecken) ──────
# ─── Tooltip-QSS  –  schwarz (alpha≈200/255) + weiße Schrift ──────────────
_TT_QSS = """
QToolTip {{
    background-color: rgba(0, 0, 0, 200);   /* → sehr dunkles Grau, leicht transparent   */
    color            : #FFFFFF;             /* → reinweiß                                 */
    border           : 1px solid #FFFFFF;   /* → schmale, weiße Kontur                    */
    border-radius    : 6px;                 /* → dezente Abrundung                       */
    padding          : 4px 8px;             /* → Luft um den Text                         */
}}
"""


_MENU_STYLE = """

/* ───────────────────── Menus ─────────────────────────────────── */

QMenuBar {{
    font-size: 14px;
    icon-size: 14px;
}}

QMenu {{
    font-size: 14px;
    icon-size: 14px;
    border: 1px solid {col10};
    border-radius: 10px;
    padding: 5px;
}}

QMenu::item {{
    border-radius: 10px;
    padding: 5px 20px;
    margin: 0px 0px;
}}

QMenu::item:selected {{
    background-color: {menu_sel};
    border: none;
    margin: 3px 0px;
}} 

/* ───────── optional: add subtle hover to *bar* items ───────── */
QMenuBar::item:selected {{
    background: {menu_sel};
     border-radius:3px;
}}"""


def _build_scheme(accent: dict, base: dict) -> dict:
    return {**base, **accent}


def _color_with_alpha(color_value: str, alpha: int, *, fallback: str) -> str:
    """Convert a color token to rgba(...) with the requested alpha channel."""
    color = QColor(str(color_value or ""))
    if not color.isValid():
        return fallback
    alpha_clamped = max(0, min(255, int(alpha)))
    return f"rgba({color.red()},{color.green()},{color.blue()},{alpha_clamped})"


def _splitter_handle_palette(scheme: dict[str, str]) -> tuple[str, str, str]:
    """Return (idle, hover, pressed) colors for splitter handles."""
    base_color = str(scheme.get("col10") or "#404040")
    accent_color = str(scheme.get("col2") or scheme.get("col1") or "#6280ff")
    idle = _color_with_alpha(base_color, 96, fallback="rgba(64,64,64,96)")
    hover = _color_with_alpha(accent_color, 170, fallback="rgba(98,128,255,170)")
    pressed = _color_with_alpha(accent_color, 210, fallback="rgba(98,128,255,210)")
    return idle, hover, pressed

# ─── helper zum Aufbringen des Stylesheets  ───────────────────────────────

# --- 2. apply also to the QApplication so that QMenu benefits --------------
# --------------------------------------------------------------------------
#  erweitertes _apply_style() –  fügt das neue Fragment beim Zusammenbau an
# --------------------------------------------------------------------------
def _apply_style(widget, scheme, *, _qapp_apply=True):             # patched
    """
    Compile the global stylesheet from the template fragments
    and apply it to *widget* and – optionally – QApplication.
    """
    import string
    # Allow disabling stylesheet application for crash bisection
    if os.getenv("AI_IDE_NO_STYLE", "0") == "1":
        try:
            widget.setStyleSheet("")
            if _qapp_apply and QApplication.instance():
                QApplication.instance().setStyleSheet("")
        finally:
            return
    template = _STYLE + _MENU_STYLE + _SEP_QSS + _TT_QSS           #  ← NEU
    fmt      = string.Formatter()

    pieces: list[str] = []
    for txt, key, spec, conv in fmt.parse(template):
        pieces.append(txt)
        if key is None:
            continue
        pieces.append(str(scheme.get(key, "{"+key+"}")))

    qss = "".join(pieces)

    # Our templates historically used doubled braces (`{{` / `}}`) so they
    # could be fed through `str.format`. Since we now do a custom, key-safe
    # substitution, we need to unescape them back to normal QSS braces.
    qss = qss.replace("{{", "{").replace("}}", "}")

    widget.setStyleSheet(qss)
    if _qapp_apply and QApplication.instance():
        QApplication.instance().setStyleSheet(qss)


'''Patch – remove the duplicated helper and keep ONE really safe version
=====================================================================

The second definition of `_apply_style()` (≈ line 560) overwrites the
first, *robust* implementation.  
Because that late version still delegates the real work to
`str.format_map()`, any placeholder like  
def _apply_style(widget: QWidget, scheme: dict) -> None:
    """
    Globale Style-Applikation: Grund-QSS  + Menü-QSS + Separator-QSS
    """
    qss = (_STYLE + _MENU_STYLE + _SEP_QSS).format(**scheme)
    widget.setStyleSheet(qss)
'''
# ─── hardened stylesheet formatter ─────────────────────────────────────────
#
# put this right after the *_STYLE / _MENU_STYLE / _SEP_QSS* definitions
# (i.e. before the first call to `_apply_style`).

import string                                  # already imported once – harmless
from PySide6.QtWidgets import QWidget          # dito

# --- 2.  apply also to the QApplication so that QMenu benefits --------------

def _draw_fallback(symbol: str = "x") -> QIcon:
    """
    Paints a very small 32 × 32 px pixmap with either a  ❌  or  ➕  in the
    centre.  Used whenever no SVG file (and no theme-icon) exists.
    """
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    pen = QPen(QColor("#ffffff"))
    pen.setWidth(4)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(pen)

    if symbol == "+":
        p.drawLine(size // 2, 6, size // 2, size - 6)
        p.drawLine(6, size // 2, size - 6, size // 2)
    else:                             # default:  ❌
        p.drawLine(8, 8, size - 8, size - 8)
        p.drawLine(8, size - 8, size - 8, 8)
    p.end()
    return QIcon(pm)


def _draw_circle_icon() -> QIcon:
    """Paint a simple neutral circle icon for the color-scheme menu action."""
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    pen = QPen(QColor("#666666"))
    pen.setWidth(3)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(6, 6, size - 12, size - 12)
    p.end()
    return QIcon(pm)


def _icon(name: str) -> QIcon:
    """
    Robust icon loader.

    1. look for an SVG file in ./symbols/
    2. fall-back to the current icon theme (QIcon.fromTheme)
    3. fall-back to a Qt standard icon
    4. finally paint our own ❌ / ➕ so that *something* is always visible
    """
    # ----------------------------------------------------- 1.  local SVG
    p = Path(__file__).with_name("symbols") / name
    if p.is_file():
        return QIcon(str(p))

    # If no QApplication yet, avoid any calls that require a QGuiApplication
    # (QIcon.fromTheme, QApplication.style(), QPixmap painting, ...).
    # Returning an empty QIcon is safe at import-time; callers can replace
    # it later when the QApplication exists.
    if QApplication.instance() is None:
        return QIcon()

    # If no QApplication yet, avoid any calls that require a QGuiApplication
    # (QIcon.fromTheme, QApplication.style(), QPixmap painting, ...).
    # Returning an empty QIcon is safe at import-time; callers can replace
    # it later when the QApplication exists.
    if QApplication.instance() is None:
        return QIcon()

    # ----------------------------------------------------- 2.  theme icon
    themed = QIcon.fromTheme(name.removesuffix(".svg"))
    if not themed.isNull():
        return themed

    # ----------------------------------------------------- 3.  Qt fallback
    std = QApplication.style().standardIcon(QStyle.SP_FileIcon)
    if not std.isNull():
        return std

    # ----------------------------------------------------- 4.  painted pixmap
    return _draw_fallback("+" if "plus" in name else "x")


# <– 09.07.2025 –– 269 - 296 –––––––––––––––––––––––––––––––––––––––––––––––
# ─── NEW: helper to detect the file-type (text / image / binary) ───
# put this close to the other helper functions (e.g. below “_icon()”)

import mimetypes                 #  << already from std-lib, no extra dep.
 
def detect_file_format(path: str | os.PathLike) -> str:
    """
    Very small heuristic that distinguishes the **three** classes
    we are interested in for the editor:

        • 'image'    → image/…  (png, jpg, webp …)
        • 'text'     → text/…   (py, md, txt …)
        • 'binary'   → everything else

    Returned keyword is later used inside `_open_file()`
    to decide which widget type (QTextEdit vs. QLabel) is created.
    """
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        return "binary"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/"):
        return "text"
    return "binary"


class ChatAttachmentService:
    _MAX_TEXT_LINES = 240
    _MAX_TEXT_CHARS = 12000
    _INLINE_OBJECT_KINDS = {"code", "text", "markdown", "pdf"}
    _SOURCE_HEADER_PREFIX = "[SOURCE]"
    _LANGUAGE_BY_SUFFIX = {
        ".bat": "bat",
        ".c": "c",
        ".cpp": "cpp",
        ".css": "css",
        ".go": "go",
        ".h": "c",
        ".hpp": "cpp",
        ".html": "html",
        ".htm": "html",
        ".java": "java",
        ".js": "javascript",
        ".json": "json",
        ".jsx": "jsx",
        ".md": "markdown",
        ".markdown": "markdown",
        ".php": "php",
        ".ps1": "powershell",
        ".py": "python",
        ".rb": "ruby",
        ".rs": "rust",
        ".scss": "scss",
        ".sh": "bash",
        ".sql": "sql",
        ".toml": "toml",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".txt": "text",
        ".xml": "xml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".zsh": "bash",
    }

    def normalize_object_paths(self, paths: list[str] | None) -> list[str]:
        normalized_paths: list[str] = []
        seen_paths: set[str] = set()
        for raw_path in paths or []:
            candidate_path = str(raw_path or "").strip()
            if not candidate_path:
                continue
            try:
                resolved_path = str(Path(candidate_path).expanduser().resolve())
            except Exception:
                resolved_path = os.path.abspath(os.path.expanduser(candidate_path))
            if resolved_path in seen_paths or not os.path.exists(resolved_path):
                continue
            seen_paths.add(resolved_path)
            normalized_paths.append(resolved_path)
        return normalized_paths

    def classify_object(self, file_path: str | Path) -> str:
        path = Path(file_path)
        classified_kind = ""
        if callable(_fv_classify):
            try:
                classified_kind = str(_fv_classify(path) or "").strip().lower()
            except Exception:
                classified_kind = ""

        if classified_kind in {"code", "text", "markdown"} and not self._looks_like_text(path):
            classified_kind = "unknown"

        if classified_kind:
            return classified_kind

        if path.suffix.lower() == ".pdf":
            return "pdf"

        detected_kind = detect_file_format(path)
        if detected_kind == "image":
            return "image"

        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix in self._LANGUAGE_BY_SUFFIX:
            return "code"
        if detected_kind == "text" or self._looks_like_text(path):
            return "text"
        return "unknown"

    def load_image_object_paths(self, file_paths: list[str] | None) -> list[str]:
        return [
            file_path
            for file_path in self.normalize_object_paths(file_paths)
            if self.classify_object(file_path) == "image"
        ]

    def build_status_message(self, file_paths: list[str] | None) -> str:
        normalized_paths = self.normalize_object_paths(file_paths)
        if not normalized_paths:
            return ""
        attachment_labels = [
            f"{Path(file_path).name} ({self.classify_object(file_path)})"
            for file_path in normalized_paths
        ]
        prefix = "Attachment ready" if len(attachment_labels) == 1 else "Attachments ready"
        return f"{prefix}: {', '.join(attachment_labels)}"

    def build_prompt_payload(self, *, prompt_text: str, file_paths: list[str] | None) -> tuple[str, list[str]]:
        normalized_prompt = str(prompt_text or "").strip()
        normalized_paths = self.normalize_object_paths(file_paths)
        image_paths: list[str] = []
        attachment_lines: list[str] = []
        object_blocks: list[str] = []

        for file_path in normalized_paths:
            path = Path(file_path)
            object_kind = self.classify_object(path)
            if object_kind == "image":
                image_paths.append(file_path)
                attachment_lines.append(f"- {path.name} (image)")
                continue

            if object_kind in self._INLINE_OBJECT_KINDS:
                object_block = self._build_object_block(file_path=file_path, object_kind=object_kind)
                if object_block:
                    object_blocks.append(object_block)
                    attachment_lines.append(f"- {path.name} ({object_kind}, loaded)")
                else:
                    attachment_lines.append(f"- {path.name} ({object_kind}, unreadable)")
                continue

            attachment_lines.append(f"- {path.name} ({object_kind})")

        prompt_parts: list[str] = []
        if normalized_prompt:
            prompt_parts.append(normalized_prompt)
        if attachment_lines:
            prompt_parts.append("Attached files:\n" + "\n".join(attachment_lines))
        if object_blocks:
            prompt_parts.append("\n\n".join(object_blocks))

        return "\n\n".join(part for part in prompt_parts if part).strip(), image_paths

    def _looks_like_text(self, path: Path) -> bool:
        try:
            with open(path, "rb") as handle:
                sample = handle.read(2048)
        except OSError:
            return False

        if not sample:
            return True
        if b"\x00" in sample:
            return False

        printable_bytes = sum(byte >= 32 or byte in (9, 10, 13) for byte in sample)
        return printable_bytes / max(len(sample), 1) >= 0.9

    def load_object_text(self, *, file_path: str | Path, object_kind: str) -> str:
        path = Path(file_path)
        if object_kind == "pdf":
            return self._load_pdf_text(path)
        return path.read_text(encoding="utf-8", errors="replace")

    def _load_pdf_text(self, path: Path) -> str:
        read_document = None
        try:
            if __package__:
                from .tools import read_document  # type: ignore
            else:
                from alde.tools import read_document  # type: ignore
        except ImportError as e:
            msg = str(e)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from tools import read_document  # type: ignore
            else:
                raise

        extracted_text = str(read_document(str(path)) or "").strip()
        if extracted_text.startswith("Error"):
            return ""
        return extracted_text

    def _trim_object_text(self, text: str) -> tuple[str, bool]:
        trimmed_lines = str(text or "").splitlines()
        was_trimmed = False
        if len(trimmed_lines) > self._MAX_TEXT_LINES:
            trimmed_lines = trimmed_lines[: self._MAX_TEXT_LINES]
            was_trimmed = True

        trimmed_text = "\n".join(trimmed_lines)
        if len(trimmed_text) > self._MAX_TEXT_CHARS:
            trimmed_text = trimmed_text[: self._MAX_TEXT_CHARS].rstrip()
            was_trimmed = True

        return trimmed_text, was_trimmed

    def _load_code_language(self, *, path: Path, object_kind: str) -> str:
        if object_kind == "markdown":
            return "markdown"
        if object_kind in {"text", "pdf"}:
            return "text"
        return self._LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "")

    def _build_object_block(self, *, file_path: str, object_kind: str) -> str | None:
        path = Path(file_path)
        try:
            raw_text = self.load_object_text(file_path=path, object_kind=object_kind)
        except OSError:
            return None

        normalized_text = str(raw_text or "").strip("\n")
        if not normalized_text:
            normalized_text = "[empty file]"

        trimmed_text, was_trimmed = self._trim_object_text(normalized_text)
        header = f"[FILE] {path.name} ({object_kind})"
        if was_trimmed:
            header += " [truncated]"

        code_language = self._load_code_language(path=path, object_kind=object_kind)
        fence = f"```{code_language}" if code_language else "```"
        source_header = f"{self._SOURCE_HEADER_PREFIX} {path}"
        return f"{header}\n{source_header}\n{fence}\n{trimmed_text}\n```"


CHAT_ATTACHMENT_SERVICE = ChatAttachmentService()


@dataclass(frozen=True)
class ChatSegment:
    kind: str
    language: str
    block: str
    file_path: str = ""


@dataclass(frozen=True)
class ChatFileContext:
    header_line: str
    language: str
    file_path: str = ""
    body_start_index: int = 1

# ────────────────────────────────────────────────────────────────────────────
#  FIX: Tooltip-Schrift ist unsichtbar                                    (NEW)
#       Ursache: Qt 6 greift bei ToolTips nicht nur auf ToolTipText,
#       sondern – je nach Plattform-Style – auch auf WindowText / Text zu.
#       Wir setzen daher ALLE drei Rollen konsequent auf Weiß.
# ────────────────────────────────────────────────────────────────────────────

# -----------------------------------------------------------------
#  Beim Programmstart aktivieren  (einmal nach QApplication anrufen)
# -----------------------------------------------------------------


# <– changes 10.07.2025
# ───────────────────── 1. ToolButton – neue Version ──────────────────────

class ToolButton(QPushButton):
    """
    con-Button für die Corner-Leiste.
    Eigenes objectName (#cornerBtn) => Stylesheet hat höhere Priorität
    als die globale 'QPushButton:hover'-Regel.
    """
    _ICON_SIZE = 21

    def __init__(self, svg: str, tip: str = "", slot=None, parent=None):
        super().__init__(parent)

        self.setObjectName("cornerBtn")                 # <<< wichtig
        self.setIcon(_icon(svg))
        self.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        if tip:
            self.setToolTip(tip)
        if slot:
            self.clicked.connect(slot)

        # lokales Stylesheet überschreibt die globale Hover-Regel
        self.setStyleSheet("""
            QPushButton#cornerBtn {
                background: #181818;
                padding: 0px;
                
            }
            QPushButton#cornerBtn:hover {
                background: rgba(255,255,255,30);  /* alter Hover-Look  */
                border: none;                      /* entfernt col1-Rahmen */
            }
        """)

class NoTabScrollerStyle(QProxyStyle):

# <– changes 11.07.2025

    """
    Gibt für Pixel-Metriken der Scroll-Buttons den Wert 0 zurück.
    Dadurch legt Qt keine sichtbaren/anklickbaren Pfeil-Buttons an.
    Funktioniert in Qt-5 und Qt-6.
    """

    _METRICS: set[int] = set()

    # Gewünschte Metriken – einige gibt es nur in Qt-5, andere nur in Qt-6

    for name in (
        "PM_TabBarScrollButtonWidth",       # Qt-5
        "PM_TabBarScrollButtonHeight",      # Qt-5
        "PM_TabBarScrollButtonOverlap",     # Qt-5 + Qt-6
        "PM_TabBarScrollerWidth",           # Qt-6
    ):
        value = getattr(QStyle, name, None)
        if value is not None:           # nur wenn in dieser Qt-Version vorhanden
            _METRICS.add(value)
# <– changes 12.07.2025 (leagacy,removed) –––––––––––––––––––––––––––––––––
# ───────────────────────────────────── EditorTabs ────────────────────────
"""QTabWidget mit
        • versteckten Scroll-Buttons
        • Corner-Widget (+,×,dock)
        • *festem* Abstand (30 px) zwischen letztem Tab und Corner-Widget"""

        
"""erhält der letzte Tab einen rechten Außenabstand von genau 30 px.  
    Damit entsteht der gewünschte feste Abstand zwischen Tab-Leiste
    und dem Corner-Widget – unabhängig von Theme oder DPI-Skalierung."""


# <– changes 13.07.2025 ––––––––––––––––––––––––––––––––––––––––––––––––––––––––

""" 
 PATCH ― keep first tab always visible + insert new tabs right of the current one
================================================================================

The changes are **self-contained** – simply drop the snippet anywhere _below_ the
current imports (for example just after the existing `NoTabScrollerStyle`
class).  No other lines of the original file have to be touched.
"""
"""
# ── NEW ────────────────────────────────────────────────────────────────────────
#  FixedLeftTabBar  –  custom QTabBar that
#    • blocks wheel-scrolling further to the left once the first tab is flush
#      with the left border  (thus the very first tab is _always visible_)
#    • offers a helper to insert a tab right of the currently focused one
#      (used by our EditorTabs wrapper further below)
# ───────────────────────────────────────────────────────────────────────────────
"""

from PySide6.QtWidgets import QTabBar
from PySide6.QtCore    import QPoint
from PySide6.QtGui     import QWheelEvent



class FixedLeftTabBar(QTabBar):   # v23
    """
    #  <– changes - 14.07.2025

    Custom tab-bar that prevents the content from being scrolled further to the
    right than necessary – hence the first tab can **never disappear**.

    – wheelEvent()       blocks excessive wheel / touch scrolling
    – mouseMoveEvent()   is tapped to correct the scroll-offset *during* a
                         drag-operation
    – tabMoved() signal  guarantees the correct offset *after* the re-order
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setMovable(True)                       # tabs can be grabbed
        self.tabMoved.connect(self._ensure_first_visible)

    # ---------------------------------------------------------------- wheelEvent
    def wheelEvent(self, ev: QWheelEvent) -> None:
        if self.count() <= 0:
            return super().wheelEvent(ev)
        going_left = ev.angleDelta().y() > 0          # +Δ ⇒ scroll left
        first_visible = self.tabRect(0).left() >= 0

        if going_left and first_visible:              # already flush → block
            ev.ignore()
            return
        super().wheelEvent(ev)

    # ---------------------------------------------------------------- mouseMoveEvent
    # (gets called continuously while a tab is being dragged)
    def mouseMoveEvent(self, ev) -> None:             # noqa: D401  (Qt signature)
        super().mouseMoveEvent(ev)
        self._ensure_first_visible()                  # adjust on-the-fly

    # ---------------------------------------------------------------- helper
    def _ensure_first_visible(self) -> None:
        """
        If the left border of tab #0 is outside the visible area
        (x < 0) we pull the whole bar back so that x == 0.
        """
        if self.count() <= 0:
            return
        left_px = self.tabRect(0).left()              # may be negative
        if left_px >= 0:
            return                                    # already fine

        # scrollOffset() / setScrollOffset() are protected in C++
        # → directly available inside our subclass.
        new_off = max(0, self.scrollOffset() + left_px)
        if new_off != self.scrollOffset():
            self.setScrollOffset(new_off)


"""
# <- changes 14.07.2025

What changed / why it fixes the second half of the ticket
----------------------------------------------------------

1. `mouseMoveEvent()` is now re-implemented.  
   While the user drags a tab, Qt may auto-scroll the bar; every movement is
   followed by `_ensure_first_visible()` which instantly corrects the offset
   if the first tab slipped out of view.

2. The built-in `tabMoved(int, int)` signal is connected to the same helper.
   Even after the drag finished, we make one last check and – if required –
   nudge the bar back into the allowed range.

3. `_ensure_first_visible()` uses the protected
   `scrollOffset()` / `setScrollOffset()` API that Qt provides exactly for
   such custom scroll handling.  
   Calculation:  
     • `tabRect(0).left()`  → negative pixels that the first tab is hidden  
     • add that amount to the current offset (clamped ≥ 0)

The wheel / swipe logic from the earlier patch remains untouched; together
both parts guarantee that *no interaction* can ever hide the left-most tab.
"""


class EditorTabs(QTabWidget):
    """
    QTabWidget that

      • hides the built-in scroll buttons (handled by NoTabScrollerStyle)
      • guarantees that the *left-most* tab always remains visible
      • inserts newly created tabs directly **right of the active tab**
    """

    _PADDING_AFTER_LAST_TAB = 0          # fixed gap before the corner widget

    def __init__(self, parent: QTabWidget | None = None) -> None:
        super().__init__(parent)

        # Crash-isolation helper: use a minimal, vanilla tab widget.
        if _env_truthy("AI_IDE_SIMPLE_TABS", "0"):
            editor = QTextEdit("# notes.py", tabChangesFocus=True)
            self.addTab(editor, "notes.py")
            return

        # --- supply our customised tab-bar before doing anything else -------
        enable_custom_tabbar = _env_truthy("AI_IDE_TABS_ENABLE_CUSTOM_TABBAR", "0")
        disable_custom_tabbar = _env_truthy("AI_IDE_TABS_DISABLE_CUSTOM_TABBAR", "0") or (not enable_custom_tabbar)
        if not disable_custom_tabbar:
            self.setTabBar(FixedLeftTabBar())             # <── ① custom bar
            self.tabBar().setUsesScrollButtons(False)
            self.tabBar().setStyle(
                NoTabScrollerStyle(self.tabBar().style())
            )  # hide arrow buttons
        else:
            # Keep UI close to the intended design without using the custom
            # tab-bar code path that can segfault on some setups.
            self.tabBar().setUsesScrollButtons(False)
        self.setMovable(True)
        self.setDocumentMode(False)
    
        self.setTabsClosable(False)                    # we close via corner btn

        # --- corner widget ( +   ×   ◀ ) ------------------------------------
        corner = QWidget(self)
        lay = QHBoxLayout(corner)
        lay.setContentsMargins(20, 0, 4, 0)
        lay.setSpacing(0)

        self._btn_add   = ToolButton("plus.svg",        "Neuer Tab",
                                     slot=self._new_tab)
        self._btn_close = ToolButton("close_tab.svg",   "Tab schließen",
                                     slot=self._close_tab)
        self._btn_dock  = ToolButton("left_panel_close.svg",
                                     "Alle Tabs schließen",
                                     slot=self._close_all_tabs)

        for b in (self._btn_add, self._btn_close, self._btn_dock):
            lay.addWidget(b)

        self.setCornerWidget(corner, Qt.TopRightCorner)


       # ---- stylesheet to keep the 30 px gap between last tab & corner ----
        self.setStyleSheet(
          f"QTabBar::tab:last {{ margin-right:{self._PADDING_AFTER_LAST_TAB}px; }}")

        # ---- example start-tabs (can be removed at any time) ---------------
        first_editor = QTextEdit("# notes.py", tabChangesFocus=True)
        idx0 = self.addTab(first_editor, "")
        self.setTabText(idx0, "notes.py")
        self._bind_editor(first_editor)

        # Kontextmenü & Aktionen (Öffnen / Speichern / Speichern unter / Wiederherstellen / Encoding)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Kontextmenü auch direkt auf der Tab-Leiste anbieten
        self.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._show_context_menu_from_tabbar)

        self._act_open = QAction("Öffnen...", self)
        self._act_open.setShortcut(QKeySequence.Open)
        self._act_open.triggered.connect(self._open_file_dialog)

        self._act_open_with_enc = QAction("Öffnen mit Encoding...", self)
        self._act_open_with_enc.triggered.connect(self._open_file_dialog_with_encoding)

        self._act_save = QAction("Speichern", self)
        self._act_save.setShortcut(QKeySequence.Save)
        self._act_save.triggered.connect(self._save_current_tab)

        self._act_save_as = QAction("Speichern unter...", self)
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_as.triggered.connect(self._save_current_tab_as)

        self._act_reopen_closed = QAction("Geschlossenen Tab wiederherstellen", self)
        self._act_reopen_closed.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self._act_reopen_closed.triggered.connect(self._reopen_closed_tab)

        self._act_set_encoding = QAction("Encoding setzen...", self)
        self._act_set_encoding.triggered.connect(self._set_current_tab_encoding)

        for a in (self._act_open, self._act_open_with_enc, self._act_save, self._act_save_as, self._act_reopen_closed, self._act_set_encoding):
            self.addAction(a)

        # State for optional features
        self._default_encoding = "utf-8"
        self._closed_tabs_stack: list[tuple[str, str, str, str]] = []  # (title, content, file_path, encoding)
        self._recent_files: list[str] = []
        self._recent_max = 10
        self._load_recent_files()

    # ─────────────────────────── slots ──────────────────────────────────────

    @Slot()
    def _new_tab(self) -> None:
        """
        Create a fresh untitled editor **right of the tab that currently has
        the focus** instead of always appending it at the very end.
        """
        current = self.currentIndex()
        if current < 0:                                   # no tab open
            current = self.count() - 1

        index = self.insertTab(current + 1,
                               QTextEdit("# new file …"),
                               f"untitled_{self.count() + 1}.py")
        self.widget(index).setProperty("file_path", "")
        self._bind_editor(self.widget(index))
        # Highlighter anwenden (Standard-Dateiname endet auf .py → Python)
        self._apply_highlighter(self.widget(index), f"untitled_{self.count()}.py")
        self.setCurrentIndex(index)

    @Slot()
    def _close_tab(self) -> None:
        """
        Schliesst den aktuell aktiven Tab dieser EditorTabs-Instanz.

        – Existiert kein Tab, passiert nichts  
        – Nach dem Entfernen wird automatisch der linke Nachbar aktiviert
        """
        idx = self.currentIndex()
        if idx < 0:
            return
        w = self.widget(idx)
        # snapshot for reopen (before possibly saving)
        self._snapshot_current_tab()
        if isinstance(w, (QPlainTextEdit, QTextEdit)) and w.document().isModified():
            choice = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Dieser Tab hat ungespeicherte Änderungen. Jetzt speichern?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if choice == QMessageBox.StandardButton.Save:
                self._save_current_tab()
                if w.document().isModified():
                    return
            elif choice == QMessageBox.StandardButton.Cancel:
                return
        self.removeTab(idx)
        # Seite explizit zerstören, um Artefakte zu vermeiden
        try:
            if w is not None:
                w.deleteLater()
        except Exception:
            pass
        # Wenn keine Tabs mehr vorhanden sind, das umschließende Dock schließen
        if self.count() == 0:
            dock = self._parent_dock()
            if dock is not None:
                dock.close()

    @Slot()
    def _save_current_tab(self) -> None:
        """Speichert den aktuellen Tab dieser EditorTabs-Instanz."""
        idx = self.currentIndex()
        if idx < 0:
            return
        widget = self.widget(idx)
        if not isinstance(widget, (QPlainTextEdit, QTextEdit)):
            QMessageBox.information(self, "Info", "Dieser Tab kann nicht gespeichert werden.")
            return
        path = widget.property("file_path") or ""
        if not path:
            fname, _ = QFileDialog.getSaveFileName(
                self,
                "Datei speichern",
                str(Path.home()),
                "Textdateien (*.txt *.md *.py);;Alle Dateien (*)",
            )
            if not fname:
                return
            path = fname
            widget.setProperty("file_path", path)
            self.setTabText(idx, Path(path).name)
        try:
            enc = widget.property("file_encoding") or "utf-8"
            Path(path).write_text(widget.toPlainText(), encoding=str(enc))
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))
            return
        if isinstance(widget, (QPlainTextEdit, QTextEdit)):
            widget.document().setModified(False)
        self._update_tab_title_for_idx(idx)
        # Statusbar-Nachricht über MainWindow
        main_window = self.window()
        if hasattr(main_window, 'statusBar'):
            main_window.statusBar().showMessage(f"{path} gespeichert", 3000)

    @Slot()
    def _save_current_tab_as(self) -> None:
        """Speichert den aktuellen Tab immer unter neuem Namen (Speichern unter)."""
        idx = self.currentIndex()
        if idx < 0:
            return
        widget = self.widget(idx)
        if not isinstance(widget, (QPlainTextEdit, QTextEdit)):
            QMessageBox.information(self, "Info", "Dieser Tab kann nicht gespeichert werden.")
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Datei speichern unter",
            str(Path.home()),
            "Textdateien (*.txt *.md *.py);;Alle Dateien (*)",
        )
        if not fname:
            return
        try:
            enc = widget.property("file_encoding") or "utf-8"
            Path(fname).write_text(widget.toPlainText(), encoding=str(enc))
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))
            return
        widget.setProperty("file_path", fname)
        if isinstance(widget, (QPlainTextEdit, QTextEdit)):
            widget.document().setModified(False)
        self._update_tab_title_for_idx(idx)
        main_window = self.window()
        if hasattr(main_window, 'statusBar'):
            main_window.statusBar().showMessage(f"{fname} gespeichert", 3000)

    def _show_context_menu(self, pos: QPoint) -> None:  # noqa: D401
        """Zeigt das allgemeine Kontextmenü (Speichern / Speichern unter)."""
        menu = QMenu(self)
        recent_menu = self._build_recent_menu()
        if recent_menu is not None:
            menu.addMenu(recent_menu)
        menu.addAction(self._act_open)
        menu.addAction(self._act_open_with_enc)
        menu.addAction(self._act_save)
        menu.addAction(self._act_save_as)
        menu.addSeparator()
        menu.addAction(self._act_reopen_closed)
        menu.addAction(self._act_set_encoding)
        menu.exec(self.mapToGlobal(pos))

    def _show_context_menu_from_tabbar(self, pos: QPoint) -> None:
        """Kontextmenü, wenn auf der Tab-Leiste rechts geklickt wurde."""
        menu = QMenu(self)
        recent_menu = self._build_recent_menu()
        if recent_menu is not None:
            menu.addMenu(recent_menu)
        menu.addAction(self._act_open)
        menu.addAction(self._act_open_with_enc)
        menu.addAction(self._act_save)
        menu.addAction(self._act_save_as)
        menu.addSeparator()
        menu.addAction(self._act_reopen_closed)
        menu.addAction(self._act_set_encoding)
        menu.exec(self.tabBar().mapToGlobal(pos))

    # --------------------- Datei-Öffnen + Dirty-Indicator ------------------
    @Slot()
    def _open_file_dialog(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Datei öffnen",
            str(Path.home()),
            "Textdateien (*.txt *.md *.py);;Alle Dateien (*)",
        )
        if not fname:
            return
        text, enc = self._read_with_fallbacks(fname)
        if text is None:
            return
        current = self.currentIndex()
        if current < 0:
            current = self.count() - 1
        editor = QTextEdit()
        editor.setPlainText(text)
        editor.setProperty("file_path", fname)
        editor.setProperty("file_encoding", enc)
        editor.document().setModified(False)
        self._bind_editor(editor)
        idx = self.insertTab(current + 1, editor, Path(fname).name)
        # Syntax-Highlighter anwenden
        self._apply_highlighter(editor, fname)
        self.setCurrentIndex(idx)
        self._add_recent_file(fname)

    @Slot()
    def _open_file_dialog_with_encoding(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Datei öffnen",
            str(Path.home()),
            "Alle Dateien (*)",
        )
        if not fname:
            return
        enc = self._prompt_encoding()
        if not enc:
            return
        try:
            text = Path(fname).read_text(encoding=enc)
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))
            return
        self._open_from_text(fname, text, enc)
        self._add_recent_file(fname)

    def _bind_editor(self, widget: QTextEdit | QPlainTextEdit) -> None:
        doc = widget.document()
        doc.modificationChanged.connect(lambda _m, w=widget: self._on_doc_modified(w))
        # Beim ersten Binden direkt versuchen einen passenden Highlighter
        # zu setzen (Dateipfad kann bei neuen Tabs leer sein).
        path = widget.property("file_path") or ""
        self._apply_highlighter(widget, str(path) or None)

    # --------------------- Highlighter / Klassifizierung -----------------
    def _classify_for_highlighter(self, path: str | None) -> str:
        """Einfache Klassifizierung anhand der Dateiendung.

        Gibt einen Typ zurück, der zur Wahl eines Syntax-Highlighters genutzt
        werden kann. Fällt auf "text" zurück, wenn nichts erkannt wird.
        """
        if not path:
            return "text"
        ext = Path(path).suffix.lower()
        mapping = {
            ".py": "python",
            ".md": "markdown",
            ".json": "json",
            ".toml": "toml",
            ".yaml": "yaml",
            ".yml": "yaml",
        }
        return mapping.get(ext, "text")

    def _apply_highlighter(self, editor: QTextEdit | QPlainTextEdit, path: str | None) -> None:
        """Wendet – falls verfügbar – einen passenden Highlighter an.

        Unterstützt derzeit: Python, Markdown, JSON. Idempotent: ersetzt nur,
        wenn sich der benötigte Highlighter-Typ unterscheidet.
        """
        kind = self._classify_for_highlighter(path)
        cls = None
        if kind == "python":
            cls = QSHighlighter
        elif kind == "markdown":
            cls = MDHighlighter
        elif kind == "json":
            cls = JSONHighlighter
        elif kind == "toml":
            cls = TOMLHighlighter
        elif kind == "yaml":
            cls = YAMLHighlighter

        if cls is None:
            return

        try:
            existing = editor.property("_highlighter")
            if existing is not None and isinstance(existing, cls):
                return
            hl = cls(editor.document())
            editor.setProperty("_highlighter", hl)
        except Exception:
            pass

    def _on_doc_modified(self, widget: QTextEdit | QPlainTextEdit) -> None:
        idx = self.indexOf(widget)
        if idx != -1:
            self._update_tab_title_for_idx(idx)

    def _update_tab_title_for_idx(self, idx: int) -> None:
        w = self.widget(idx)
        base = None
        if isinstance(w, (QPlainTextEdit, QTextEdit)):
            fp = w.property("file_path") or ""
            if fp:
                base = Path(str(fp)).name
        if not base:
            base = self.tabText(idx).lstrip("*") or f"untitled_{idx+1}.py"
        # add encoding suffix
        enc = None
        if isinstance(w, (QPlainTextEdit, QTextEdit)):
            enc = w.property("file_encoding") or self._default_encoding
        suffix = f" [{str(enc).upper()}]" if enc else ""
        title = f"{base}{suffix}"
        if isinstance(w, (QPlainTextEdit, QTextEdit)) and w.document().isModified():
            self.setTabText(idx, f"*{title}")
        else:
            self.setTabText(idx, title)

    # --------------------- Encoding helpers -------------------------------
    def _prompt_encoding(self) -> str | None:
        options = ["utf-8", "latin-1", "cp1252", "utf-16", "utf-8-sig"]
        enc, ok = QInputDialog.getItem(self, "Encoding wählen", "Encoding:", options, 0, False)
        return enc if ok else None

    def _read_with_fallbacks(self, path: str) -> tuple[str | None, str]:
        # Try editor default, then latin-1 as safe fallback
        for enc in (self._default_encoding, "utf-8", "utf-8-sig", "latin-1"):
            try:
                return Path(path).read_text(encoding=enc), enc
            except Exception:
                continue
        QMessageBox.critical(self, "Fehler", f"Konnte Datei nicht lesen: {path}")
        return None, self._default_encoding

    def _open_from_text(self, path: str, text: str, enc: str) -> None:
        current = self.currentIndex()
        if current < 0:
            current = self.count() - 1
        editor = QTextEdit()
        editor.setPlainText(text)
        editor.setProperty("file_path", path)
        editor.setProperty("file_encoding", enc)
        editor.document().setModified(False)
        self._bind_editor(editor)
        idx = self.insertTab(current + 1, editor, Path(path).name)
        self._apply_highlighter(editor, path)
        self.setCurrentIndex(idx)

    @Slot()
    def _set_current_tab_encoding(self) -> None:
        idx = self.currentIndex()
        if idx < 0:
            return
        w = self.widget(idx)
        if not isinstance(w, (QPlainTextEdit, QTextEdit)):
            return
        enc = self._prompt_encoding()
        if not enc:
            return
        w.setProperty("file_encoding", enc)
        # Optional: nothing else changes until save/open

    # --------------------- Recent files -----------------------------------
    def _add_recent_file(self, path: str) -> None:
        path = str(Path(path))
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        if len(self._recent_files) > self._recent_max:
            self._recent_files = self._recent_files[: self._recent_max]
        self._save_recent_files()

    def _build_recent_menu(self):
        if not self._recent_files:
            return None
        m = QMenu("Zuletzt geöffnet", self)
        for p in self._recent_files:
            act = QAction(str(Path(p).name), self)
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, path=p: self._open_recent(path))
            m.addAction(act)
        return m

    def _open_recent(self, path: str) -> None:
        text, enc = self._read_with_fallbacks(path)
        if text is None:
            return
        self._open_from_text(path, text, enc)

    def _load_recent_files(self) -> None:
        try:
            s = QSettings()
            arr = s.value("EditorTabs/RecentFiles", [])
            if isinstance(arr, list):
                self._recent_files = [str(x) for x in arr]
        except Exception:
            self._recent_files = []

    def _save_recent_files(self) -> None:
        try:
            s = QSettings()
            s.setValue("EditorTabs/RecentFiles", self._recent_files)
        except Exception:
            pass

    # --------------------- Reopen closed tab ------------------------------
    def _snapshot_current_tab(self) -> None:
        idx = self.currentIndex()
        if idx < 0:
            return
        w = self.widget(idx)
        if isinstance(w, (QPlainTextEdit, QTextEdit)):
            title = self.tabText(idx).lstrip("*")
            content = w.toPlainText()
            path = w.property("file_path") or ""
            enc = w.property("file_encoding") or self._default_encoding
            self._closed_tabs_stack.append((title, content, str(path), str(enc)))

    @Slot()
    def _reopen_closed_tab(self) -> None:
        if not self._closed_tabs_stack:
            return
        title, content, path, enc = self._closed_tabs_stack.pop()
        editor = QTextEdit()
        editor.setPlainText(content)
        if path:
            editor.setProperty("file_path", path)
        editor.setProperty("file_encoding", enc)
        editor.document().setModified(False)
        self._bind_editor(editor)
        idx = self.insertTab(self.currentIndex() + 1, editor, title or "wiederhergestellt")
        self.setCurrentIndex(idx)

    @Slot()
    def _close_all_tabs(self) -> None:
        """Schließt alle Tabs in diesem TabWidget."""
        # wiederhole das Schließen mit Guard; Abbruch bei Cancel
        while self.count() > 0:
            self.setCurrentIndex(0)
            before = self.count()
            self._close_tab()
            if self.count() == before:
                # abgebrochen
                break
        # Falls nach dem Vorgang keine Tabs mehr vorhanden sind: Dock schließen
        if self.count() == 0:
            dock = self._parent_dock()
            if dock is not None:
                dock.close()
    
    @Slot()
    def _close_dock(self) -> None:
        """Schließt das gesamte Dock-Widget."""
        dock = self._parent_dock()
        if dock:
            dock.close()

    # ---------------------------- helpers -----------------------------------

    def _parent_dock(self) -> QDockWidget | None:
        w = self.parentWidget()
        while w and not isinstance(w, QDockWidget):
            w = w.parentWidget()
        return w


    """
    What is fixed / how to test
        ---------------------------

        1. Run the application and open enough documents to exceed the tab-bar width.  
        • Scroll right with the mouse wheel → tabs move.  
        • Scroll left → the movement stops precisely when the first tab touches the
            left margin; it never disappears again.

        2. Activate an arbitrary tab and press the **“+”** button (or `Ctrl+N` if you
        already mapped it).  
        • The brand-new “untitled_…” tab now appears directly to the _right_ of the
            one that had the focus, not at the very end of the list.

        Both requirements from the user story are therefore fulfilled while keeping the
        original look-&-feel and without introducing any new dependencies."""

# ═══════════════════════  drag-and-drop QTextEdit  ════════════════════════

class FileDropTextEdit(QTextEdit):
    filesDropped = Signal(list)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)

    def dropEvent(self, ev: QDropEvent):
        if ev.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in ev.mimeData().urls()]
            self.filesDropped.emit(paths)
            ev.acceptProposedAction()
        else:
            super().dropEvent(ev)

# ═══════ << changes 09.11.2025
'''DROP-IN PATCH – 1 px linke Rahmenlinie am Chat-Dock  
===================================================  
Die Änderung betrifft ausschließlich die `ChatDock`-Klasse.  
            _sys:bool = None) -> None:

        """
        Logging message and response to context cache.
        Parameter format: List[Tuple(role, content, object, data, thread-name, assistant_name, _dev, _sys)]
        """
Ersetzen Sie den bisherigen `setStyleSheet( … )`-Block in `ChatDock.__init__`  
durch den folgenden Code (oder fügen Sie ihn als Patch darunter ein):
'''
# -------------------------------------------------------------------- ChatDock

class ChatDock(QDockWidget):
    """
    • keine Titelzeile / Buttons
    • unsichtbarer, aber benutzbarer Split-Handle
    • NEU: 1 px linke Rahmenlinie als optische Trennung
    """
    def __init__(self, accent: dict, base: dict, parent=None) -> None:
        super().__init__("AI Chat", parent)

        self.setObjectName("ChatDock")                      # wichtig für QSS
        self.setTitleBarWidget(QWidget())                   # Titelzeile ausblenden
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.scheme = _build_scheme(accent, base)                # Farbschema mergen

        #self.setWidgetResizable(True)
        # ---- Stylesheet ----------------------------------------------------
        self.setStyleSheet(f"""
            /* feste 1-px-Linie links */
            QDockWidget#ChatDock {{
              
                border : 1px solid grey;
            }}

            /* Split-Handle: unsichtbar aber greifbar */
            QDockWidget::separator {{
                background : grey;
                width      : 6px;
            }}
            QDockWidget::separator:hover {{
                background : {self.scheme['col12']};
            }}
        """)

        # ---- eigentlicher Inhalt ------------------------------------------
        self.setWidget(AIWidget(accent, base))

# ═══════════════════════  AI chat dock  ═══════════════════════════════════

class AIWidget(QWidget):
    '''AI-Chat-Dock – fehlerbereinigte Version'''

    _PROMPT_SNAP_HEIGHT = 90

    def __init__(self,
        accent, 
        base, 
        parent=None):    

        super().__init__(parent,)

        self.api_key: str = self._read_api_key()
        self._api_key_missing: bool = not bool(self.api_key)
        self._model:   str = "o3-2025-04-16"                 # <<< zentrales Modell
        self._dropped_files: List[str] = []
        self.scheme = _build_scheme(accent, base)                # Farbschema mergen
        self._build_ui()
        self._wire()

        if self._api_key_missing:
            try:
                for btn in (getattr(self, "btn_send", None), getattr(self, "btn_img_analyse", None), getattr(self, "btn_img_create", None)):
                    if btn is not None:
                        btn.setEnabled(False)
            except Exception:
                pass
            try:
                self._append("System", "OPENAI_API_KEY not found. Set it in your environment or a .env file to enable chat.")
            except Exception:
                pass
        
        # Hover-Events aktivieren
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        # ScrollBar stylen (Pfeile ausblenden)
        css = """
            QScrollBar:vertical {
                background: {col9};  /* unsichtbar bis Hover */
            width: 4px;
        }
        QScrollBar::add-line, QScrollBar::sub-line { height:0px; }  /* Pfeile */
        QScrollBar:hover { background: rgba(0,0,0,0.12); }          /* bei Hover */
        QScrollBar::handle:hover { background: #7a7a7a; }

        """
        self.setStyleSheet(css)
        
    # ---------------------------------------------------------------- ENV
    @staticmethod
    def _read_api_key() -> str:
        root_env  = Path(__file__).resolve().parents[1] / ".env"
        local_env = Path(__file__).with_suffix(".env")
        for f in (root_env, local_env):
            if f.exists():
                load_dotenv(f, override=False)
                
        load_dotenv()
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        return key
    
    def _build_ui(self) -> None:
        """Erstellt die Oberfläche des AI-Docks.

        • oben:   Chat-History  (ChatWindow → zeigt Text + Code farbig)
        • unten:  Eingabefeld   (FileDropTextEdit)
        • footer: Tool-Buttons
        """
        # 1)  Chat-History (read-only)
        self.chat_view = ChatWindow(self.scheme)

        # 2)  Prompt-Editor  (Drag-&-Drop + Multiline)
        self.prompt_edit = FileDropTextEdit(               # neu: nur EIN Editor
            placeholderText="Prompt …",
            objectName="aiInput"       )
        self.prompt_edit.setAttribute(Qt.WA_StyledBackground, True)
        self.prompt_edit.setMinimumHeight(self._PROMPT_SNAP_HEIGHT )
        self.prompt_edit.setStyleSheet("QTextEdit#aiInput { font-size: 15px; }")

        # 3) Splitter  ▌ ChatHistory ▌ Prompt ▌
        splitter = QSplitter(Qt.Vertical, self)
        splitter.setObjectName("chatPaneSplitter")
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(7)
        splitter.setOpaqueResize(True)
        handle_idle, handle_hover, handle_pressed = _splitter_handle_palette(self.scheme)
        splitter.setStyleSheet(
            f"""
            QSplitter#chatPaneSplitter::handle {{
                background: {handle_idle};
                margin: 2px 0;
                border-radius: 6px;
            }}
            QSplitter#chatPaneSplitter::handle:hover {{
                background: {handle_hover};
            }}
            QSplitter#chatPaneSplitter::handle:pressed {{
                background: {handle_pressed};
            }}
            """
        )
        splitter.addWidget(self.chat_view)
        splitter.addWidget(self.prompt_edit)
        splitter.setSizes([400, self._PROMPT_SNAP_HEIGHT ])

        # 4) Footer-Buttons
        footer = QWidget(self, objectName="footer")
        flay   = QHBoxLayout(footer)
        flay.setContentsMargins(0, 0, 0, 0)

        self.btn_img_create  = ToolButton("photo.svg",   "Create image",
                                          slot=self._create_img)
        self.btn_img_analyse = ToolButton("analyse.svg", "Analyse image",
                                          slot=self._send_img)
        self.btn_send        = ToolButton("send.svg",    "Send",
                                          slot=self._send)
        self.btn_mic         = ToolButton("mic.svg",     "Record speech")

        for w in (self.btn_img_create,
                  self.btn_img_analyse,
                  self.btn_send,
                  self.btn_mic):
            flay.addWidget(w, 0, Qt.AlignLeft)
        flay.addStretch()

        # 5) Gesamtlayout
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(splitter, 1)
        vbox.addWidget(footer)
        # ------------------------------------------------------------------- SIGNALS

        # ---------------------------------------------------------------------------
        #  SIGNAL-VERDRAHTUNG   (nur noch das Prompt-Feld liefert FilesDropped)
        # ---------------------------------------------------------------------------
    def _wire(self) -> None:
            self.prompt_edit.filesDropped.connect(
               self. _remember_files)
    @Slot(list)
    def _remember_files(self, paths:list|None) -> None:
                self._dropped_files = CHAT_ATTACHMENT_SERVICE.normalize_object_paths(paths)
                status_message = CHAT_ATTACHMENT_SERVICE.build_status_message(self._dropped_files)
                if not status_message:
                    return
                try:
                    window = self.window()
                    status_bar = window.statusBar() if window is not None and hasattr(window, "statusBar") else None
                    if status_bar is not None:
                        status_bar.showMessage(status_message, 6000)
                except Exception:
                    pass
    # ---------------------------------------------------------------------------
    #  CHAT – Text-Prompt
    # ---------------------------------------------------------------------------
    @Slot()
    def _send(self) -> None:
        if getattr(self, "_api_key_missing", False):
            try:
                self._append("System", "Chat is disabled because OPENAI_API_KEY is not set.")
            except Exception:
                pass
            return
        prompt, image_paths = CHAT_ATTACHMENT_SERVICE.build_prompt_payload(
            prompt_text=self.prompt_edit.toPlainText(),
            file_paths=self._dropped_files,
        )
        if not prompt and not image_paths:
            return

        self._append("You", prompt)
        self.prompt_edit.clear()
        
        try:
            reply = ChatCom(
                _model=self._model,
                _url=image_paths or None,
                _input_text=prompt
            ).get_response()
        except Exception as exc:
            reply = f"[ERROR] {exc}"

        self._append("AI", str(reply))
        self._dropped_files = []

    # ---------------------------------------------------------------------------
    #  CHAT – Bild analysieren
    # ---------------------------------------------------------------------------
    @Slot()
    def _send_img(self) -> None:
        if getattr(self, "_api_key_missing", False):
            try:
                self._append("System", "Image analysis is disabled because OPENAI_API_KEY is not set.")
            except Exception:
                pass
            return
        prompt = self.prompt_edit.toPlainText().strip()
        image_paths = CHAT_ATTACHMENT_SERVICE.load_image_object_paths(self._dropped_files)
        if not (prompt and image_paths):
            QMessageBox.warning(self, "Info",
                "Ziehe ein Bild in das Chat-Fenster und gib anschließend deinen Prompt ein.")
            return

        self._append("You", prompt)
        self.prompt_edit.clear()
        url = image_paths[0]

        try:
            resp = ImageDescription(
                _model="gpt-5",
                _url=url,
                _input_text=prompt
            ).get_descript()

            if hasattr(resp, 'choices') and resp.choices:
                reply = (resp.choices[0].message.content or "")
            elif hasattr(resp, 'content'):
                reply = (resp.content or "")
            else:
                reply = str(resp)
        except Exception as exc:
            reply = f"[ERROR] {exc}"

        self._append("AI", reply)
        self._dropped_files = []

    # ---------------------------------------------------------------------------
    #  CHAT – Bild generieren
    # ---------------------------------------------------------------------------
    @Slot()
    def _create_img(self) -> None:
        if getattr(self, "_api_key_missing", False):
            try:
                self._append("System", "Image creation is disabled because OPENAI_API_KEY is not set.")
            except Exception:
                pass
            return
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Info", "Bitte Prompt eingeben.")
            return  
        self._append("You", prompt)
        self.prompt_edit.clear()    

        try:
            raw = ImageCreate(
                _model="gpt-5",
                _input_text=prompt
            ).get_img()
        except Exception as exc:
            self._append("AI", f"[ERROR] {exc}")
            return

        try:
            img_bytes, mime = decode_image_payload(raw)
            path = save_generated_image(img_bytes, mime=mime)
        except Exception as exc:
            self._append("AI", f"[ERROR] Image decode/save failed: {exc}")
            return

        # Open in a new tab in the (focused) tab-dock
        win = self.window()
        opener = getattr(win, "_open_path_in_focused_tab", None)
        if callable(opener):
            opener(path, title=path.name)
            self._append("AI", f"[IMAGE] {path}")
        else:
            self._append("AI", f"[IMAGE SAVED] {path}")

    # ---------------------------------------------------------------------------
    #  HILFSFUNKTION – Nachricht an ChatWindow anhängen
    # ---------------------------------------------------------------------------
    def _append(self, who: str, txt: str) -> None:
        """legt eine neue Nachricht im Chat-Viewport an"""
        self.chat_view.add_message(who, txt)

    def open_agent_system_builder_panel(
        self,
        *,
        initial_payload: dict[str, Any],
        build_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        previous_row = getattr(self, "_agent_builder_panel_row", None)
        if previous_row is not None:
            self.chat_view.remove_inline_panel(previous_row)
            self._agent_builder_panel_row = None

        panel = QFrame(self.chat_view.viewport)
        panel.setObjectName("chatInlineBuilderPanel")
        panel.setStyleSheet(
            """
            QFrame#chatInlineBuilderPanel {
                background: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 10px;
            }
            QLabel#builderSectionTitle {
                color: #d7d7d7;
                font-weight: 700;
            }
            QLabel#builderSectionText {
                color: #c2c2c2;
            }
            QPushButton#builderPrimaryButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 1px;
                min-width: 22px;
                min-height: 22px;
            }
            QPushButton#builderPrimaryButton:hover {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.18);
            }
            QPushButton#builderIconButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 1px;
                min-width: 22px;
                min-height: 22px;
            }
            QPushButton#builderIconButton:hover {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.18);
            }
            """
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)

        top_buttons = QHBoxLayout()
        top_buttons.setContentsMargins(0, 0, 0, 0)
        top_buttons.setSpacing(6)
        btn_template = QPushButton("", panel)
        btn_build = QPushButton("", panel)
        btn_template.setIcon(_icon("open_file.svg"))
        btn_build.setIcon(_icon("deployed_code.svg"))
        btn_template.setToolTip("Template laden")
        btn_build.setToolTip("Sync Build starten")
        btn_template.setIconSize(QSize(18, 18))
        btn_build.setIconSize(QSize(18, 18))
        btn_template.setCursor(Qt.PointingHandCursor)
        btn_build.setCursor(Qt.PointingHandCursor)
        btn_template.setObjectName("builderPrimaryButton")
        btn_build.setObjectName("builderPrimaryButton")
        top_buttons.addWidget(btn_template, 0)
        top_buttons.addWidget(btn_build, 0)
        top_buttons.addStretch(1)
        panel_layout.addLayout(top_buttons)

        editor = CodeViewer(
            json.dumps(initial_payload, ensure_ascii=False, indent=2),
            panel,
            language="json",
            editable=True,
            auto_fit=False,
            accent_color=self.scheme.get("col1", "#3a5fff"),
            accent_selection_color=self.scheme.get("col2", "#6280ff"),
            surface_color=self.scheme.get("col10", "#404040"),
            font_size_px=17,
        )
        editor.setMinimumHeight(260)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(editor)

        status_text = QLabel("Status: Bereit", panel)
        status_text.setObjectName("builderSectionText")
        status_text.setWordWrap(True)
        panel_layout.addWidget(status_text)

        bottom_buttons = QHBoxLayout()
        bottom_buttons.setContentsMargins(0, 0, 0, 0)
        bottom_buttons.setSpacing(6)
        btn_post = QPushButton("", panel)
        btn_copy = QPushButton("", panel)
        btn_close = QPushButton("", panel)
        btn_post.setIcon(_icon("send.svg"))
        btn_copy.setIcon(_icon("file_export_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"))
        btn_close.setIcon(_icon("close.svg"))
        btn_post.setToolTip("Ergebnis in Chat verschieben")
        btn_copy.setToolTip("JSON exportieren")
        btn_close.setToolTip("Panel schliessen")
        btn_post.setIconSize(QSize(18, 18))
        btn_copy.setIconSize(QSize(18, 18))
        btn_close.setIconSize(QSize(18, 18))
        btn_post.setCursor(Qt.PointingHandCursor)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_post.setObjectName("builderIconButton")
        btn_copy.setObjectName("builderIconButton")
        btn_close.setObjectName("builderIconButton")
        bottom_buttons.addWidget(btn_post, 0)
        bottom_buttons.addWidget(btn_copy, 0)
        bottom_buttons.addWidget(btn_close, 0)
        bottom_buttons.addStretch(1)
        panel_layout.addLayout(bottom_buttons)

        panel_row = self.chat_view.add_inline_panel(panel)
        self._agent_builder_panel_row = panel_row
        latest_result: dict[str, Any] = {}

        def _load_template() -> None:
            editor.setPlainText(json.dumps(initial_payload, ensure_ascii=False, indent=2))
            status_text.setText("Status: Template geladen")

        def _run_build() -> None:
            nonlocal latest_result
            raw_text = editor.toPlainText().strip()
            if not raw_text:
                status_text.setText("Status: Payload ist leer")
                return

            try:
                payload = json.loads(raw_text)
            except Exception as exc:
                status_text.setText(f"Status: JSON-Fehler ({type(exc).__name__})")
                return

            if not isinstance(payload, dict):
                status_text.setText("Status: Payload muss JSON-Objekt sein")
                return

            btn_build.setEnabled(False)
            try:
                latest_result = dict(build_handler(payload) or {})
                validation = dict(latest_result.get("validation") or {})
                status_text.setText(
                    f"Status: Build abgeschlossen (valid={bool(validation.get('valid', True))})"
                )
            except Exception as exc:
                status_text.setText(f"Status: Build fehlgeschlagen ({type(exc).__name__})")
                latest_result = {}
            finally:
                btn_build.setEnabled(True)

        def _post_result() -> None:
            if not latest_result:
                self._append("System", "Kein Build-Ergebnis vorhanden. Bitte zuerst Sync Build starten.")
                return
            self._append("AI", json.dumps(latest_result, ensure_ascii=False, indent=2))

        def _copy_json() -> None:
            payload_text = editor.toPlainText()
            try:
                QApplication.clipboard().setText(payload_text)
                status_text.setText("Status: JSON in Zwischenablage")
            except Exception as exc:
                status_text.setText(f"Status: Kopieren fehlgeschlagen ({type(exc).__name__})")

        def _close_panel() -> None:
            self.chat_view.remove_inline_panel(panel_row)
            self._agent_builder_panel_row = None

        btn_template.clicked.connect(_load_template)
        btn_build.clicked.connect(_run_build)
        btn_post.clicked.connect(_post_result)
        btn_copy.clicked.connect(_copy_json)
        btn_close.clicked.connect(_close_panel)

# ---------------------------------------------------------------------------
#  HILFSFUNKTION – Nachricht an ChatWindow anhängen
# ---------------------------------------------------------------------------

'''
Kurzerklärung
─────────────
1. Das neue  ChatWindow  (inkl. MsgWidget/CodeViewer) rendert Text-Blöcke
   und ```-Fenced-Code``` separat – Code erscheint syntax-gehiglightet.

2. AIWidget benutzt jetzt
      • self.chat_view   für den gesamten Verlauf  
      • self.prompt_edit für die Eingabe
   Dadurch verschwinden veraltete Attribute (`inp_edit`, `out_edit` …).

3. Alle Chat-Routinen (_send, _send_img, _create_img) rufen intern `_append`,
   welches direkt `chat_view.add_message()` verwendet.

Der Patch ist vollständig lauffähig und benötigt lediglich die bestehenden
Hilfsklassen (FileDropTextEdit, ToolButton, ChatCom …) aus deinem Projekt.'''

# ────────────────────────────────────────────────────────────────────────────
#  2)  NEUER  CodeViewer  –  editierbare Chat-Bloecke mit Highlighting
# ────────────────────────────────────────────────────────────────────────────
class CodeViewer(QPlainTextEdit):
    """Editierbarer Chat-Block fuer Code, Konfiguration und Dateiinhalt."""

    editRequested = Signal()

    _PADDING = 20
    _MIN_HEIGHT = 88
    _MAX_HEIGHT = 420
    _LANGUAGE_ALIASES = {
        "": "",
        "md": "markdown",
        "py": "python",
        "plaintext": "text",
        "text/plain": "text",
        "yml": "yaml",
    }
    _HIGHLIGHTERS = {
        "json": JSONHighlighter,
        "markdown": MDHighlighter,
        "python": QSHighlighter,
        "toml": TOMLHighlighter,
        "yaml": YAMLHighlighter,
    }
    _VIEW_BORDER_COLOR = "#2e2e2e"
    _BACKGROUND_COLOR = "#111"
    _TEXT_COLOR = "#DDD"

    def __init__(
        self,
        code: str,
        parent: QWidget | None = None,
        *,
        language: str = "",
        editable: bool = True,
        auto_fit: bool = True,
        accent_color: str = "#3a5fff",
        accent_selection_color: str = "#6280ff",
        surface_color: str = "#404040",
        font_size_px: int | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._language = self._normalize_language(language)
        self._highlighter = None
        self._edit_mode = False
        self._accent_color = str(accent_color or "#3a5fff")
        self._accent_selection_color = str(accent_selection_color or self._accent_color)
        self._surface_color = str(surface_color or "#404040")
        self._font_size_px = int(font_size_px) if font_size_px is not None else None
        self._uses_wrapped_layout = self._language in {"markdown", "text"}
        self._auto_fit = bool(auto_fit)

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setUndoRedoEnabled(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed if self._auto_fit else QSizePolicy.Expanding,
        )
        self.setTabStopDistance(max(32, QFontMetrics(self.font()).horizontalAdvance("    ")))

        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if self._uses_wrapped_layout else QPlainTextEdit.NoWrap)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere if self._uses_wrapped_layout else QTextOption.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if self._uses_wrapped_layout else Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if self._uses_wrapped_layout else Qt.ScrollBarAsNeeded)
        self.viewport().installEventFilter(self)
        self.setPlainText(code.rstrip("\n"))
        self._install_highlighter()
        self.set_edit_mode(editable)

        if self._auto_fit:
            self.textChanged.connect(self._schedule_autofit)
            try:
                self.document().documentLayout().documentSizeChanged.connect(lambda _size: self._schedule_autofit())
            except Exception:
                pass
            self._schedule_autofit()
        else:
            self.setMinimumHeight(max(220, self._MIN_HEIGHT))
            self.setMaximumHeight(16777215)

    @classmethod
    def _normalize_language(cls, language: str | None) -> str:
        normalized = str(language or "").strip().lower()
        return cls._LANGUAGE_ALIASES.get(normalized, normalized)

    def _install_highlighter(self) -> None:
        highlighter_class = self._HIGHLIGHTERS.get(self._language)
        if highlighter_class is None:
            return
        try:
            self._highlighter = highlighter_class(self.document())
        except Exception:
            self._highlighter = None

    def _schedule_autofit(self) -> None:
        if not self._auto_fit:
            return
        QTimer.singleShot(0, self._autofit)

    def set_edit_mode(self, active: bool) -> None:
        self._edit_mode = bool(active)
        self.setReadOnly(not self._edit_mode)
        self.setTextInteractionFlags(
            Qt.TextEditorInteraction
            if self._edit_mode
            else Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.setObjectName("aiInput" if self._edit_mode else "chatCodeViewer")
        self.setStyleSheet(self._build_style(edit_mode=self._edit_mode))

        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.viewport().update()
        self.update()
        if self._auto_fit:
            self._schedule_autofit()

    def _build_style(self, *, edit_mode: bool) -> str:
        border_color = self._accent_color if edit_mode else self._VIEW_BORDER_COLOR
        border_radius = 15 if edit_mode else 8
        selection_color = self._accent_selection_color if edit_mode else "#264f78"
        scrollbar_hover_color = self._surface_color
        scrollbar_pressed_color = self._accent_selection_color
        font_size_rule = f" font-size:{self._font_size_px}px;" if self._font_size_px is not None else ""
        return (
            f"QPlainTextEdit#{self.objectName()} {{"
            f" background:{self._BACKGROUND_COLOR};"
            f" color:{self._TEXT_COLOR};"
            " padding:12px;"
            f" border:1px solid {border_color};"
            f" border-radius:{border_radius}px;"
            f" selection-background-color:{selection_color};"
            f"{font_size_rule}"
            " font-family:'Fira Code','DejaVu Sans Mono','Liberation Mono',monospace;"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar:vertical {{"
            " background:transparent;"
            " width:6px;"
            " margin:0px;"
            " border:none;"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar:horizontal {{"
            " background:transparent;"
            " height:6px;"
            " margin:0px;"
            " border:none;"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:horizontal {{"
            " background:transparent;"
            " min-height:24px;"
            " min-width:24px;"
            " border-radius:3px;"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:vertical:hover,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:horizontal:hover,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:hover:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:hover:horizontal {{"
            f" background:{scrollbar_hover_color};"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:vertical:pressed,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:horizontal:pressed,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:pressed:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::handle:pressed:horizontal {{"
            f" background:{scrollbar_pressed_color};"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::add-line:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::sub-line:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::add-line:horizontal,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::sub-line:horizontal {{"
            " width:0px;"
            " height:0px;"
            " border:none;"
            " background:transparent;"
            "}"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::add-page:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::sub-page:vertical,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::add-page:horizontal,"
            f"QPlainTextEdit#{self.objectName()} QScrollBar::sub-page:horizontal {{"
            " background:transparent;"
            "}"
        )

    def mousePressEvent(self, ev):  # noqa: N802
        if self.isReadOnly():
            self.editRequested.emit()
        super().mousePressEvent(ev)

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.viewport() and ev.type() == QEvent.Wheel:
            self.wheelEvent(ev)
            return bool(ev.isAccepted())
        return super().eventFilter(obj, ev)

    def wheelEvent(self, ev: QWheelEvent) -> None:
        angle_delta = ev.angleDelta()
        pixel_delta = ev.pixelDelta()
        delta_y = angle_delta.y() if angle_delta.y() else pixel_delta.y()
        delta_x = angle_delta.x() if angle_delta.x() else pixel_delta.x()

        use_horizontal = bool(delta_x) or bool(ev.modifiers() & Qt.ShiftModifier)
        target_bar = self.horizontalScrollBar() if use_horizontal else self.verticalScrollBar()
        delta = delta_x if use_horizontal and delta_x else delta_y

        if target_bar is not None and target_bar.maximum() > target_bar.minimum() and delta:
            direction = -1 if delta > 0 else 1
            step = max(target_bar.singleStep(), 24)
            target_bar.setValue(target_bar.value() + direction * step)
            ev.accept()
            return

        super().wheelEvent(ev)

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        if self._auto_fit:
            self._schedule_autofit()

    def _autofit(self) -> None:
        document = self.document()
        if self.lineWrapMode() == QPlainTextEdit.WidgetWidth:
            document.setTextWidth(max(1, self.viewport().width()))
        else:
            document.setTextWidth(-1)

        layout = document.documentLayout()
        content_height = layout.documentSize().height() if layout is not None else document.size().height()
        target_height = int(content_height) + self._PADDING
        target_height = max(self._MIN_HEIGHT, min(target_height, self._MAX_HEIGHT))
        self.setFixedHeight(target_height)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if self._uses_wrapped_layout else Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if self._uses_wrapped_layout else Qt.ScrollBarAsNeeded)


class ChatEditorPanel(QWidget):
    """Editor-Panel fuer Chat-Bloecke mit Klick-aktiviertem Edit-Mode."""

    def __init__(
        self,
        *,
        segment: ChatSegment,
        parent: QWidget | None = None,
        save_handler: Callable[[QPlainTextEdit, str], None] | None = None,
        scheme: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_path = str(segment.file_path or "")
        self._save_handler = save_handler
        self._scheme = dict(scheme or {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._controls = QWidget(self)
        controls_layout = QHBoxLayout(self._controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.addStretch(1)

        self._save_btn: QToolButton | None = None
        if self._file_path:
            self._save_btn = QToolButton(self._controls)
            self._save_btn.setText("Save to source")
            self._save_btn.setToolTip(self._file_path)
            self._save_btn.setEnabled(False)
            controls_layout.addWidget(self._save_btn)

        self._done_btn = QToolButton(self._controls)
        self._done_btn.setText("Done")
        controls_layout.addWidget(self._done_btn)

        self.viewer = CodeViewer(
            segment.block.rstrip("\n"),
            self,
            language=segment.language,
            editable=False,
            accent_color=self._scheme.get("col1", "#3a5fff"),
            accent_selection_color=self._scheme.get("col2", self._scheme.get("col1", "#6280ff")),
            surface_color=self._scheme.get("col10", "#404040"),
            font_size_px=14,
        )
        self.viewer.setProperty("file_path", self._file_path)

        layout.addWidget(self._controls)
        layout.addWidget(self.viewer)

        self._controls.hide()
        self.viewer.editRequested.connect(self._enter_edit_mode)
        self._done_btn.clicked.connect(lambda _checked=False: self.set_edit_mode(False))

        if self._save_btn is not None:
            self.viewer.document().modificationChanged.connect(self._save_btn.setEnabled)
            self._save_btn.clicked.connect(self._save_to_source)

    def _enter_edit_mode(self) -> None:
        self.set_edit_mode(True)

    def set_edit_mode(self, active: bool) -> None:
        self._controls.setVisible(bool(active))
        self.viewer.set_edit_mode(active)
        if active:
            self.viewer.setFocus(Qt.MouseFocusReason)
        else:
            self.viewer.clearFocus()

    def _save_to_source(self) -> None:
        if self._save_handler is None or not self._file_path:
            return
        self._save_handler(self.viewer, self._file_path)


class MsgWidget(QWidget):
    """Chat-Bubble mit Text-, Bild- und editierbaren Block-Segmenten."""

    def __init__(
        self,
        who: str,
        segments: list[ChatSegment],
        parent: QWidget | None = None,
        *,
        scheme: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self.setStyleSheet("MsgWidget { background: transparent; }")
        self._scheme = dict(scheme or {})

        h_layout = QHBoxLayout(self)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.setSpacing(0)

        bubble = QWidget()
        bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._bubble = bubble

        v_layout = QVBoxLayout(bubble)
        v_layout.setContentsMargins(14, 10, 14, 10)
        v_layout.setSpacing(6)

        from PySide6.QtWidgets import QLabel
        bubble.setStyleSheet(
            """
            QWidget {
                background: #2a2a2a;
                border: none;
                border-radius: 10px;
                padding: 10px 14px;
                color: #e0e0e0;
            }
            QWidget * {
                border: none;
                outline: none;
            }
            """
        )

        username_label = QLabel(f"<small style='opacity:0.6; color:#e0e0e0;'>{who}</small>")
        if who == "AI":
            v_layout.addWidget(username_label, 0, Qt.AlignLeft)
            h_layout.addWidget(bubble, 1)
        else:
            v_layout.addWidget(username_label, 0, Qt.AlignRight)
            h_layout.addWidget(bubble, 1)

        for segment in segments:
            kind = segment.kind
            language = segment.language
            block = segment.block
            if not str(block or "").strip():
                continue

            if kind == "editor":
                editor_panel = ChatEditorPanel(
                    segment=segment,
                    parent=bubble,
                    save_handler=self._save_editor_block if segment.file_path else None,
                    scheme=self._scheme,
                )
                v_layout.addWidget(editor_panel)
                continue

            first = block.splitlines()[0].strip()
            image_match = re.match(r'!\[.*?\]\((.*?)\)', first)
            if first.startswith("[IMAGE]") or image_match:
                path_str = None
                if first.startswith("[IMAGE]"):
                    parts = first.split(None, 1)
                    if len(parts) > 1:
                        path_str = parts[1].strip()
                elif image_match:
                    path_str = image_match.group(1)

                if path_str:
                    try:
                        p = Path(path_str)
                    except Exception:
                        p = None

                    if p and p.exists():
                        ctrl = QWidget(bubble)
                        hctrl = QHBoxLayout(ctrl)
                        hctrl.setContentsMargins(0, 0, 0, 0)
                        hctrl.addStretch(1)
                        save_btn = QToolButton(ctrl)
                        save_btn.setText("Save as")
                        export_btn = QToolButton(ctrl)
                        export_btn.setText("Export to tab")
                        hctrl.addWidget(save_btn)
                        hctrl.addWidget(export_btn)

                        img_widget = None
                        if '_FVChatImageWidget' in globals() and _FVChatImageWidget is not None:
                            try:
                                img_widget = _FVChatImageWidget(p, parent=bubble)
                            except Exception:
                                img_widget = None
                        if img_widget is None and _FVImageWidget is not None:
                            try:
                                img_widget = _FVImageWidget(p, parent=bubble)
                            except Exception:
                                img_widget = None

                        if img_widget is None:
                            lbl = QLabel(bubble, alignment=Qt.AlignCenter)
                            pix = QPixmap(str(p))
                            if not pix.isNull():
                                lbl.setPixmap(pix.scaledToWidth(400, Qt.SmoothTransformation))
                            v_layout.addWidget(lbl)
                        else:
                            cont = QWidget(bubble)
                            vbox_img = QVBoxLayout(cont)
                            vbox_img.setContentsMargins(0, 0, 0, 0)
                            vbox_img.setSpacing(4)
                            vbox_img.addWidget(ctrl)
                            vbox_img.addWidget(img_widget)
                            v_layout.addWidget(cont)

                            def _on_save() -> None:
                                fname, _ = QFileDialog.getSaveFileName(self, "Save image as", str(Path.home()))
                                if fname:
                                    try:
                                        shutil.copy(str(p), fname)
                                        QMessageBox.information(self, "Saved", f"Saved to {fname}")
                                    except Exception as exc:
                                        QMessageBox.critical(self, "Error", str(exc))

                            def _on_export() -> None:
                                win = self.window()
                                opener = getattr(win, "_open_path_in_focused_tab", None)
                                if callable(opener):
                                    opener(p, title=p.name)
                                else:
                                    QMessageBox.information(self, "Info", "No tab-dock available to export image")

                            save_btn.clicked.connect(_on_save)
                            export_btn.clicked.connect(_on_export)
                            continue

            br = QTextBrowser(bubble)
            br.setFrameShape(QFrame.NoFrame)
            br.setOpenExternalLinks(True)
            br.setMarkdown(block)
            br.document().setDocumentMargin(0)
            br.setStyleSheet("QTextBrowser { background: transparent; color: #e0e0e0; font-size: 14px; }")
            br.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            br.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            br.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._fit_browser(br)
            v_layout.addWidget(br)
            QTimer.singleShot(0, lambda b=br: self._fit_browser(b))

            try:
                br.document().documentLayout().documentSizeChanged.connect(lambda _sz, b=br: self._fit_browser(b))
            except Exception:
                pass

        v_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed))

    @staticmethod
    def _write_editor_text_to_path(*, file_path: str | Path, text: str) -> None:
        target_path = Path(file_path).expanduser()
        if not target_path.parent.exists():
            raise FileNotFoundError(f"Zielpfad nicht gefunden: {target_path.parent}")
        target_path.write_text(text, encoding="utf-8")

    def _save_editor_block(self, viewer: QPlainTextEdit, file_path: str) -> None:
        try:
            self._write_editor_text_to_path(file_path=file_path, text=viewer.toPlainText())
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))
            return

        viewer.document().setModified(False)
        message = f"{file_path} gespeichert"
        window = self.window()
        status_bar_getter = getattr(window, "statusBar", None)
        if callable(status_bar_getter):
            try:
                status_bar = status_bar_getter()
            except Exception:
                status_bar = None
            if status_bar is not None:
                status_bar.showMessage(message, 3000)
                return
        QMessageBox.information(self, "Gespeichert", message)

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        try:
            max_w = max(1, self.width() - 16)
            if max_w > 0 and hasattr(self, "_bubble") and self._bubble is not None:
                self._bubble.setMaximumWidth(max_w)
        except Exception:
            pass

    def _fit_browser(self, br: QTextBrowser) -> None:
        doc = br.document()
        w = max(1, br.viewport().width())
        doc.setTextWidth(w)

        h_doc = int(doc.size().height()) + 2
        font_h = QFontMetrics(br.font()).height()
        h_min = max(3, 3 * font_h)
        br.setFixedHeight(max(h_doc, h_min))


class ChatInlinePanelSlot(QFrame):
    """Inline chat slot with vertical resize handle."""

    def __init__(self, panel: QWidget, *, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chatInlineSlot")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Vertical, self)
        self.splitter.setObjectName("chatInlineSlotSplitter")
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(7)
        self.splitter.setOpaqueResize(True)

        self.content_host = QWidget(self.splitter)
        content_layout = QVBoxLayout(self.content_host)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(0)
        panel.setParent(self.content_host)
        content_layout.addWidget(panel, 1)

        self.resize_buffer = QWidget(self.splitter)
        self.resize_buffer.setObjectName("chatInlineSlotResizeBuffer")
        self.resize_buffer.setMinimumHeight(22)
        self.resize_buffer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self.splitter.addWidget(self.content_host)
        self.splitter.addWidget(self.resize_buffer)
        self.splitter.setSizes([max(220, panel.sizeHint().height() + 20), 1])
        root.addWidget(self.splitter, 1)


class ChatWindow(QWidget):
    """Container fuer den kompletten Chat-Verlauf."""

    _FILE_HEADER_PATTERN = re.compile(
        r"^\[FILE\]\s+(?P<name>.+?)\s+\((?P<kind>[^)]+)\)(?:\s+\[truncated\])?$"
    )
    _SOURCE_HEADER_PATTERN = re.compile(
        rf"^{re.escape(ChatAttachmentService._SOURCE_HEADER_PREFIX)}\s+(?P<path>.+?)\s*$"
    )
    _LANGUAGE_BY_SUFFIX = dict(ChatAttachmentService._LANGUAGE_BY_SUFFIX)

    def __init__(self, scheme: dict[str, str] | None = None):
        super().__init__()
        self._scheme = dict(scheme or {})
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.setObjectName("chatHistoryWindow")

        from PySide6.QtWidgets import QScrollArea

        self.scroller = QScrollArea(self)
        self.scroller.setObjectName("chatHistoryScroller")
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QFrame.NoFrame)
        self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroller.viewport().setObjectName("chatHistoryScrollViewport")
        root.addWidget(self.scroller, 1)

        self.viewport = QWidget()
        self.viewport.setObjectName("chatHistoryViewport")
        self.vlayout = QVBoxLayout(self.viewport)
        self.vlayout.setContentsMargins(8, 8, 8, 8)
        self.vlayout.setSpacing(2)
        self.vlayout.setAlignment(Qt.AlignTop)
        self.scroller.setWidget(self.viewport)
        self._apply_history_style()

    def _apply_history_style(self) -> None:
        history_bg = self._scheme.get("col9", "#181818")
        history_border = self._scheme.get("col10", "#404040")
        history_accent = self._scheme.get("col2", self._scheme.get("col1", "#6280ff"))
        slot_handle_idle, slot_handle_hover, slot_handle_pressed = _splitter_handle_palette(self._scheme)
        self.setStyleSheet(
            f"""
            QWidget#chatHistoryWindow {{
                background: transparent;
            }}
            QScrollArea#chatHistoryScroller {{
                background: {history_bg};
                border: 1px solid {history_border};
                border-radius: 12px;
            }}
            QWidget#chatHistoryScrollViewport {{
                background: {history_bg};
                border-radius: 12px;
            }}
            QWidget#chatHistoryViewport {{
                background: {history_bg};
                border-radius: 12px;
            }}
            QScrollArea#chatHistoryScroller QScrollBar:vertical,
            QScrollArea#chatHistoryScroller QScrollBar:horizontal {{
                background: transparent;
                margin: 0px;
                border: none;
            }}
            QScrollArea#chatHistoryScroller QScrollBar:vertical {{
                width: 6px;
            }}
            QScrollArea#chatHistoryScroller QScrollBar:horizontal {{
                height: 6px;
            }}
            QScrollArea#chatHistoryScroller QScrollBar::handle:vertical,
            QScrollArea#chatHistoryScroller QScrollBar::handle:horizontal {{
                background: transparent;
                border-radius: 3px;
                min-height: 28px;
                min-width: 28px;
            }}
            QScrollArea#chatHistoryScroller QScrollBar::handle:vertical:hover,
            QScrollArea#chatHistoryScroller QScrollBar::handle:horizontal:hover,
            QScrollArea#chatHistoryScroller QScrollBar::handle:hover:vertical,
            QScrollArea#chatHistoryScroller QScrollBar::handle:hover:horizontal {{
                background: {history_border};
            }}
            QScrollArea#chatHistoryScroller QScrollBar::handle:vertical:pressed,
            QScrollArea#chatHistoryScroller QScrollBar::handle:horizontal:pressed,
            QScrollArea#chatHistoryScroller QScrollBar::handle:pressed:vertical,
            QScrollArea#chatHistoryScroller QScrollBar::handle:pressed:horizontal {{
                background: {history_accent};
            }}
            QScrollArea#chatHistoryScroller QScrollBar::add-line,
            QScrollArea#chatHistoryScroller QScrollBar::sub-line,
            QScrollArea#chatHistoryScroller QScrollBar::add-page,
            QScrollArea#chatHistoryScroller QScrollBar::sub-page {{
                background: none;
                border: none;
                width: 5px;
                height:40px;
            }}
            QFrame#chatInlineSlot {{
                border: 1px solid {history_border};
                border-radius: 10px;
                background: transparent;
            }}
            QSplitter#chatInlineSlotSplitter::handle {{
                background: {slot_handle_idle};
                min-height: 7px;
            }}
            QSplitter#chatInlineSlotSplitter::handle:hover {{
                background: {slot_handle_hover};
            }}
            QSplitter#chatInlineSlotSplitter::handle:pressed {{
                background: {slot_handle_pressed};
            }}
            """
        )

    def add_message(self, who: str, text: str) -> None:
        msg = MsgWidget(who, self._split_segments(text), self.viewport, scheme=self._scheme)
        self.vlayout.addWidget(msg)
        bar = self.scroller.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_inline_panel(self, panel: QWidget) -> QWidget:
        slot = ChatInlinePanelSlot(panel, parent=self.viewport)
        self.vlayout.addWidget(slot)
        bar = self.scroller.verticalScrollBar()
        bar.setValue(bar.maximum())
        return slot

    def remove_inline_panel(self, row: QWidget | None) -> None:
        if row is None:
            return
        self.vlayout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    @staticmethod
    def _split_segments(raw: str) -> list[ChatSegment]:
        out: list[ChatSegment] = []
        buf: list[str] = []
        mode = "text"
        fence_language = ""
        pending_file_context: ChatFileContext | None = None

        for ln in raw.splitlines():
            stripped = ln.strip()
            if stripped.startswith("```"):
                if mode == "text":
                    if buf:
                        plain_segments, pending_file_context = ChatWindow._split_plain_segment(
                            "\n".join(buf),
                            allow_file_context=True,
                        )
                        out.extend(plain_segments)
                    buf = []
                    mode = "code"
                    fence_language = stripped[3:].strip()
                else:
                    out.append(
                        ChatSegment(
                            kind="editor",
                            language=ChatWindow._normalize_language(fence_language)
                            or (pending_file_context.language if pending_file_context else ""),
                            block="\n".join(buf).rstrip("\n"),
                            file_path=pending_file_context.file_path if pending_file_context else "",
                        )
                    )
                    buf = []
                    mode = "text"
                    fence_language = ""
                    pending_file_context = None
                continue
            buf.append(ln)

        if buf:
            if mode == "code":
                out.append(
                    ChatSegment(
                        kind="editor",
                        language=ChatWindow._normalize_language(fence_language)
                        or (pending_file_context.language if pending_file_context else ""),
                        block="\n".join(buf).rstrip("\n"),
                        file_path=pending_file_context.file_path if pending_file_context else "",
                    )
                )
            else:
                plain_segments, _ = ChatWindow._split_plain_segment("\n".join(buf), allow_file_context=False)
                out.extend(plain_segments)
        return out

    @classmethod
    def _split_plain_segment(
        cls,
        raw_block: str,
        *,
        allow_file_context: bool,
    ) -> tuple[list[ChatSegment], ChatFileContext | None]:
        normalized = str(raw_block or "").strip("\n")
        if not normalized.strip():
            return [], None

        lines = normalized.splitlines()
        file_context = cls._parse_file_context(lines)
        if file_context is not None:
            body = "\n".join(lines[file_context.body_start_index:]).strip("\n")
            segments: list[ChatSegment] = [ChatSegment(kind="text", language="", block=file_context.header_line)]
            if body:
                segments.append(
                    ChatSegment(
                        kind="editor",
                        language=file_context.language,
                        block=body,
                        file_path=file_context.file_path,
                    )
                )
                return segments, None
            return segments, file_context if allow_file_context else None

        language = cls._infer_plain_block_language(normalized)
        if cls._should_use_editor(normalized, language):
            return [ChatSegment(kind="editor", language=language, block=normalized)], None
        return [ChatSegment(kind="text", language="", block=normalized)], None

    @classmethod
    def _parse_file_context(cls, lines: list[str]) -> ChatFileContext | None:
        if not lines:
            return None

        header_line = lines[0].strip()
        header_match = cls._FILE_HEADER_PATTERN.match(header_line)
        if header_match is None:
            return None

        body_start_index = 1
        file_path = ""
        if len(lines) > 1:
            source_match = cls._SOURCE_HEADER_PATTERN.match(lines[1].strip())
            if source_match is not None:
                file_path = source_match.group("path").strip()
                body_start_index = 2

        language = cls._language_from_file_header(
            file_name=header_match.group("name"),
            object_kind=header_match.group("kind"),
        )
        return ChatFileContext(
            header_line=header_line,
            language=language,
            file_path=file_path,
            body_start_index=body_start_index,
        )

    @classmethod
    def _normalize_language(cls, language: str | None) -> str:
        return CodeViewer._normalize_language(language)

    @classmethod
    def _language_from_file_header(cls, *, file_name: str, object_kind: str) -> str:
        normalized_kind = str(object_kind or "").strip().lower()
        if normalized_kind == "markdown":
            return "markdown"
        if normalized_kind in {"pdf", "text"}:
            return "text"
        suffix = Path(str(file_name or "").strip()).suffix.lower()
        return cls._normalize_language(cls._LANGUAGE_BY_SUFFIX.get(suffix, ""))

    @classmethod
    def _infer_plain_block_language(cls, block: str) -> str:
        lines = [line.rstrip() for line in str(block or "").splitlines() if line.strip()]
        if not lines:
            return ""

        stripped = "\n".join(lines).strip()
        if (stripped.startswith("{") or stripped.startswith("[")) and re.search(r'"[^"\\]+"\s*:', stripped):
            return "json"

        if any(re.match(r"^\s*\[[^\]]+\]\s*$", line) for line in lines) and any(
            re.match(r"^\s*[A-Za-z0-9_.-]+\s*=\s*.+$", line) for line in lines
        ):
            return "toml"

        yaml_hits = sum(1 for line in lines if re.match(r"^\s*[A-Za-z0-9_.-]+\s*:\s*.+$", line))
        if yaml_hits >= 2 or (yaml_hits >= 1 and any(re.match(r"^\s*-\s+.+$", line) for line in lines)):
            return "yaml"

        python_hits = sum(
            1
            for line in lines
            if re.match(r"^\s*(def|class|from|import|if|elif|else|for|while|try|except|with|return|async|await|yield|pass)\b", line)
        )
        if python_hits >= 2:
            return "python"

        js_hits = sum(
            1
            for line in lines
            if re.match(r"^\s*(const|let|var|function|export|import|interface|type)\b", line)
            or "=>" in line
        )
        if js_hits >= 2:
            return "javascript"

        if any(line.startswith("#!/") for line in lines):
            return "bash"

        if any(re.match(r"^\s*<[^>]+>\s*$", line) for line in lines) and any("</" in line for line in lines):
            return "html"

        return ""

    @classmethod
    def _should_use_editor(cls, block: str, language: str) -> bool:
        normalized_language = cls._normalize_language(language)
        if normalized_language and normalized_language != "markdown":
            return True
        if normalized_language == "markdown":
            return False

        lines = [line.rstrip() for line in str(block or "").splitlines() if line.strip()]
        if len(lines) < 4:
            return False

        structured_hits = sum(
            1
            for line in lines
            if re.match(r"^\s*([A-Za-z0-9_.-]+\s*[:=].+|Traceback|File \".+\")", line)
            or re.match(r"^\s*[{}\[\]<>].*$", line)
            or re.match(r"^\s*(#include|SELECT\b|INSERT\b|UPDATE\b|DELETE\b)", line, re.IGNORECASE)
        )
        sentence_hits = sum(1 for line in lines if re.search(r"[.!?]\s*$", line) and len(line.split()) > 4)
        blank_ratio = 1 - (len(lines) / max(len(str(block or "").splitlines()), 1))

        if structured_hits >= 2:
            return True
        if len(lines) >= 8 and sentence_hits * 2 < len(lines) and blank_ratio < 0.35:
            return True
        return False
        
# ───────────────────────────────────────────────────────────────
# PATCH: Mindesthöhe für QTextBrowser-Segmente im Chat
#        height = rows × font_height  + 5 px
# ───────────────────────────────────────────────────────────────
from PySide6.QtGui     import QFontMetrics
from PySide6.QtWidgets import QTextBrowser

def _autofit_browser(self, br: QTextBrowser) -> None:          # pylint: disable=unused-argument
    """
    Setzt eine **Mindesthöhe** für jedes Markdown-Segment im Chat:

        min_h =  (Zeilen × 2 × Fontsize) + margin_top + margin_bottom

    Enthält das Dokument (Bilder, Tabellen …) mehr Inhalt als der
    Zeilenzähler vermuten lässt, wird automatisch der größere Wert
    verwendet, so dass nichts abgeschnitten wird.
    """
    doc = br.document()
    doc.setDocumentMargin(0)

    w = max(1, br.viewport().width())
    doc.setTextWidth(w)

    h_doc = int(doc.size().height()) + 4
    font_h = QFontMetrics(br.font()).height()
    h_min = max(3,3 * font_h )

    br.setFixedHeight(max(h_doc, h_min))

# -- bestehende Klasse zur Laufzeit patchen -------------------------------
import types, inspect, sys

# MsgWidget befindet sich bereits im globalen Namespace des Hauptskripts
MsgWidget = next(                       # type: ignore  # noqa: N806
    obj for obj in globals().values()
    if inspect.isclass(obj) and obj.__name__ == "MsgWidget"
)

# Methode als ungebundene Funktion ersetzen (wird bei Aufruf korrekt an Instanz gebunden)
MsgWidget._fit_browser = _autofit_browser
'''
Kurzerklärung  
─────────────  
1. Ein robuster Ersatz-`__init__` für `QSHighlighter` sorgt dafür,  
   dass immer ein gültiges `QTextDocument` existiert und der
   Highlighter nicht doppelt initialisiert wird – dadurch funktioniert
   **jegliches Syntax-Highlighting** (ExplorerDock, CodeViewer, …) wieder.

2. `CodeViewer` berechnet seine Mindesthöhe nur aus der Zeilenzahl und
   nutzt `QSizePolicy.Expanding`.  Er stellt jetzt Quellcode in voller
   Breite mit korrektem Highlighting dar.

3. `MsgWidget` verwendet `QTextBrowser` mit `AdjustToContents`.
   Die Mindesthöhe wird automatisch ermittelt – dadurch werden Text-
   Nachrichten **vollständig** angezeigt (keine abges        except Exception as exc:
chnittenen Zeilen mehr).

4. Ein gepatchtes `ChatWindow` ersetzt die Originalklasse im laufenden
   Programm, ohne andere Teile der Anwendung zu verändern.

Der Patch erfordert keine weiteren Abhängigkeiten und kann jederzeit
wieder entfernt werden, um den Ursprungszustand herzustellen.
'''  



from PySide6.QtCore import Qt, QSize, QTimer, Slot
from PySide6.QtGui  import (QIcon, QTextOption, QTextCursor)
from PySide6.QtWidgets import (QMainWindow,
    QTreeWidget, QTreeWidgetItem,               #  NEU
    QDockWidget, QToolButton, QTextEdit,QWidget
)
import json
import typing as _t
from pathlib import Path
try:
    if __package__:
        from .litehigh import QSHighlighter  # type: ignore
    else:
        from alde.litehigh import QSHighlighter  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from litehigh import QSHighlighter  # type: ignore
    else:
        raise
from PySide6.QtCore import (
     Qt,
     QSize,
     Signal,
     Slot,
     QTimer,
     QSettings,
     QByteArray,
     QRegularExpression,
     QRegularExpressionMatch,
 )

# -----------------------------------------------------------

class ControlPlaneWidget(QWidget):
    snapshotChanged = Signal(dict)
    _OPERATOR_FILTER_SETTINGS_PREFIX = "ControlPlane/OperatorFilters"

    def __init__(self, accent: dict[str, str], base: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = accent
        self._base = base
        self.scheme = _build_scheme(accent, base)
        self._metric_labels: dict[str, QLabel] = {}
        self._last_snapshot: dict[str, Any] = {}
        self._operator_log_entries: list[dict[str, Any] | str] = []
        self._operator_filter_preferences = self._load_operator_filter_preferences()
        self._agent_rows_by_label: dict[str, dict[str, Any]] = {}
        self._build_ui()
        self.update_scheme(accent, base)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(15000)
        self._refresh_timer.timeout.connect(self.refresh_view)
        self._refresh_timer.start()
        self.refresh_view()

    def _control_plane_settings(self) -> QSettings:
        try:
            settings = QSettings(MainAIEditor.ORG_NAME, MainAIEditor.APP_NAME)
        except Exception:
            settings = QSettings()
        settings.setFallbacksEnabled(False)
        return settings

    def _load_operator_filter_preferences(self) -> dict[str, str]:
        settings = self._control_plane_settings()
        prefix = self._OPERATOR_FILTER_SETTINGS_PREFIX
        return {
            "status": str(settings.value(f"{prefix}/status", "All statuses") or "All statuses"),
            "audit_type": str(settings.value(f"{prefix}/audit_type", "All action types") or "All action types"),
            "action_group": str(settings.value(f"{prefix}/action_group", "All action groups") or "All action groups"),
            "source": str(settings.value(f"{prefix}/source", "All sources") or "All sources"),
        }

    def _current_operator_filter_preferences(self) -> dict[str, str]:
        return {
            "status": self.operator_status_selector.currentText().strip() or "All statuses",
            "audit_type": self.operator_audit_selector.currentText().strip() or "All action types",
            "action_group": self.operator_group_selector.currentText().strip() or "All action groups",
            "source": self.operator_source_selector.currentText().strip() or "All sources",
        }

    def _save_operator_filter_preferences(self) -> None:
        settings = self._control_plane_settings()
        prefix = self._OPERATOR_FILTER_SETTINGS_PREFIX
        settings.setValue(f"{prefix}/status", self._operator_filter_preferences.get("status") or "All statuses")
        settings.setValue(f"{prefix}/audit_type", self._operator_filter_preferences.get("audit_type") or "All action types")
        settings.setValue(f"{prefix}/action_group", self._operator_filter_preferences.get("action_group") or "All action groups")
        settings.setValue(f"{prefix}/source", self._operator_filter_preferences.get("source") or "All sources")
        try:
            settings.sync()
        except Exception:
            pass

    def _handle_operator_filter_change(self, _text: str = "") -> None:
        self._operator_filter_preferences = self._current_operator_filter_preferences()
        self._save_operator_filter_preferences()
        self._render_operator_log()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.primary_splitter = self._create_viewport_splitter(self)
        self.primary_splitter.setObjectName("controlPrimarySplitter")

        hero = QFrame(self)
        hero.setObjectName("controlHero")
        hero.setMinimumHeight(0)
        hero.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        title = QLabel("Agentic Control Plane", hero)
        title.setObjectName("controlTitle")
        subtitle = QLabel(
            "Industrial workspace for agent configuration, workflow governance, and runtime monitoring.",
            hero,
        )
        subtitle.setObjectName("controlSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header_row.addLayout(title_box, 1)

        header_meta = QVBoxLayout()
        header_meta.setContentsMargins(0, 0, 0, 0)
        header_meta.setSpacing(4)
        self._last_refresh_label = QLabel("Refresh pending", hero)
        self._last_refresh_label.setObjectName("controlMeta")
        self._runtime_hint_label = QLabel("Auto refresh: 15s", hero)
        self._runtime_hint_label.setObjectName("controlMeta")
        header_meta.addWidget(self._last_refresh_label, 0, Qt.AlignRight)
        header_meta.addWidget(self._runtime_hint_label, 0, Qt.AlignRight)
        header_row.addLayout(header_meta)

        self.btn_refresh = ToolButton(
            "reload_.svg",
            "Control Plane aktualisieren",
            slot=self.refresh_view,
            parent=hero,
        )
        header_row.addWidget(self.btn_refresh, 0, Qt.AlignTop)

        hero_layout.addLayout(header_row)

        metrics_row = QHBoxLayout()
        metrics_row.setContentsMargins(0, 0, 0, 0)
        metrics_row.setSpacing(8)
        for metric_key, metric_label in (
            ("agents", "Agents"),
            ("workflows", "Workflows"),
            ("sessions", "Sessions"),
            ("failures", "Failures"),
        ):
            card, value_label = self._create_metric_card(metric_label)
            self._metric_labels[metric_key] = value_label
            metrics_row.addWidget(card, 1)
        hero_layout.addLayout(metrics_row)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("controlPlaneTabs")
        self.tabs.setMinimumSize(0, 0)
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.ElideRight)
        self.tabs.tabBar().setExpanding(False)

        config_tab = QWidget(self.tabs)
        self._config_tab = config_tab
        config_tab.setMinimumSize(0, 0)
        config_tab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        config_layout = QVBoxLayout(config_tab)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(8)

        self.config_summary_view = QTextBrowser(config_tab)
        self.config_summary_view.setObjectName("controlBrowser")
        self.config_summary_view.setOpenExternalLinks(False)
        self.config_summary_view.setMinimumHeight(0)
        self.config_summary_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.config_manifest_view = QTextBrowser(config_tab)
        self.config_manifest_view.setObjectName("controlBrowser")
        self.config_manifest_view.setOpenExternalLinks(False)
        self.config_manifest_view.setMinimumHeight(0)
        self.config_manifest_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.config_splitter = self._create_viewport_splitter(config_tab)
        self.config_splitter.addWidget(self.config_summary_view)
        self.config_splitter.addWidget(self.config_manifest_view)
        self.config_splitter.setSizes([140, 280])
        self.config_splitter.setStretchFactor(0, 1)
        self.config_splitter.setStretchFactor(1, 2)

        self.config_builder_container = QFrame(config_tab)
        self.config_builder_container.setObjectName("controlBuilderContainer")
        self.config_builder_container.setMinimumSize(0, 0)
        self.config_builder_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.config_builder_layout = QVBoxLayout(self.config_builder_container)
        self.config_builder_layout.setContentsMargins(0, 0, 0, 0)
        self.config_builder_layout.setSpacing(0)
        self._config_builder_panel: QWidget | None = None

        self.config_root_splitter = self._create_viewport_splitter(config_tab)
        self.config_root_splitter.addWidget(self.config_splitter)
        self.config_root_splitter.addWidget(self.config_builder_container)
        self.config_root_splitter.setSizes([1, 0])
        self.config_root_splitter.setStretchFactor(0, 3)
        self.config_root_splitter.setStretchFactor(1, 2)
        config_layout.addWidget(self.config_root_splitter, 1)

        monitor_tab = QWidget(self.tabs)
        monitor_tab.setMinimumSize(0, 0)
        monitor_tab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        monitor_layout = QVBoxLayout(monitor_tab)
        monitor_layout.setContentsMargins(0, 0, 0, 0)
        monitor_layout.setSpacing(8)

        self.monitor_summary_view = QTextBrowser(monitor_tab)
        self.monitor_summary_view.setObjectName("controlBrowser")
        self.monitor_summary_view.setOpenExternalLinks(False)
        self.monitor_summary_view.setMinimumHeight(0)
        self.monitor_summary_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.monitor_filter_panel = QWidget(monitor_tab)
        self.monitor_filter_panel.setMinimumSize(0, 0)
        self.monitor_filter_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        drilldown_layout = QVBoxLayout(self.monitor_filter_panel)
        drilldown_layout.setContentsMargins(0, 0, 0, 0)
        drilldown_layout.setSpacing(6)

        drilldown_form = QFormLayout()
        drilldown_form.setContentsMargins(0, 0, 0, 0)
        drilldown_form.setSpacing(8)
        drilldown_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        agent_label = QLabel("Agent", monitor_tab)
        agent_label.setObjectName("controlMeta")

        self.agent_selector = QComboBox(monitor_tab)
        self.agent_selector.setObjectName("controlSelector")
        self.agent_selector.setMinimumContentsLength(10)
        self.agent_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.agent_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.agent_selector.currentTextChanged.connect(self._refresh_drilldown_views)
        drilldown_form.addRow(agent_label, self.agent_selector)

        workflow_label = QLabel("Workflow", monitor_tab)
        workflow_label.setObjectName("controlMeta")

        self.workflow_selector = QComboBox(monitor_tab)
        self.workflow_selector.setObjectName("controlSelector")
        self.workflow_selector.setMinimumContentsLength(10)
        self.workflow_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.workflow_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.workflow_selector.currentTextChanged.connect(self._refresh_drilldown_views)
        drilldown_form.addRow(workflow_label, self.workflow_selector)

        drilldown_layout.addLayout(drilldown_form)

        trace_filter_form = QFormLayout()
        trace_filter_form.setContentsMargins(0, 0, 0, 0)
        trace_filter_form.setSpacing(8)
        trace_filter_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        trace_agent_label = QLabel("Trace Agent", monitor_tab)
        trace_agent_label.setObjectName("controlMeta")
        self.trace_agent_selector = QComboBox(monitor_tab)
        self.trace_agent_selector.setObjectName("controlSelector")
        self.trace_agent_selector.setMinimumContentsLength(10)
        self.trace_agent_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.trace_agent_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.trace_agent_selector.currentTextChanged.connect(self._refresh_monitoring_views)
        trace_filter_form.addRow(trace_agent_label, self.trace_agent_selector)

        trace_workflow_label = QLabel("Trace Workflow", monitor_tab)
        trace_workflow_label.setObjectName("controlMeta")
        self.trace_workflow_selector = QComboBox(monitor_tab)
        self.trace_workflow_selector.setObjectName("controlSelector")
        self.trace_workflow_selector.setMinimumContentsLength(10)
        self.trace_workflow_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.trace_workflow_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.trace_workflow_selector.currentTextChanged.connect(self._refresh_monitoring_views)
        trace_filter_form.addRow(trace_workflow_label, self.trace_workflow_selector)

        trace_tool_label = QLabel("Trace Tool", monitor_tab)
        trace_tool_label.setObjectName("controlMeta")
        self.trace_tool_selector = QComboBox(monitor_tab)
        self.trace_tool_selector.setObjectName("controlSelector")
        self.trace_tool_selector.setMinimumContentsLength(10)
        self.trace_tool_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.trace_tool_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.trace_tool_selector.currentTextChanged.connect(self._refresh_monitoring_views)
        trace_filter_form.addRow(trace_tool_label, self.trace_tool_selector)

        trace_handoff_label = QLabel("Trace Handoff", monitor_tab)
        trace_handoff_label.setObjectName("controlMeta")
        self.trace_handoff_selector = QComboBox(monitor_tab)
        self.trace_handoff_selector.setObjectName("controlSelector")
        self.trace_handoff_selector.setMinimumContentsLength(10)
        self.trace_handoff_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.trace_handoff_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.trace_handoff_selector.currentTextChanged.connect(self._refresh_monitoring_views)
        trace_filter_form.addRow(trace_handoff_label, self.trace_handoff_selector)

        drilldown_layout.addLayout(trace_filter_form)

        detail_action_row = QHBoxLayout()
        detail_action_row.setContentsMargins(0, 0, 0, 0)
        detail_action_row.setSpacing(8)

        self.btn_refresh_detail = ToolButton(
            "reload_.svg",
            "Monitor-Detail aktualisieren",
            slot=self._refresh_drilldown_views,
            parent=monitor_tab,
        )
        self.btn_refresh_detail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        detail_action_row.addWidget(self.btn_refresh_detail, 0)
        detail_action_row.addStretch(1)
        drilldown_layout.addLayout(detail_action_row)

        self.monitor_detail_view = QTextBrowser(monitor_tab)
        self.monitor_detail_view.setObjectName("controlBrowser")
        self.monitor_detail_view.setOpenExternalLinks(False)
        self.monitor_detail_view.setMinimumHeight(0)
        self.monitor_detail_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.monitor_timeline_view = QTextBrowser(monitor_tab)
        self.monitor_timeline_view.setObjectName("controlBrowser")
        self.monitor_timeline_view.setOpenExternalLinks(False)
        self.monitor_timeline_view.setMinimumHeight(0)
        self.monitor_timeline_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.monitor_trace_view = QTextBrowser(monitor_tab)
        self.monitor_trace_view.setObjectName("controlBrowser")
        self.monitor_trace_view.setOpenExternalLinks(False)
        self.monitor_trace_view.setMinimumHeight(0)
        self.monitor_trace_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.monitor_header_splitter = self._create_viewport_splitter(monitor_tab)
        self.monitor_header_splitter.addWidget(self.monitor_summary_view)
        self.monitor_header_splitter.addWidget(self.monitor_filter_panel)
        self.monitor_header_splitter.setSizes([130, 170])

        self.monitor_splitter = self._create_viewport_splitter(monitor_tab)
        self.monitor_splitter.addWidget(self.monitor_header_splitter)
        self.monitor_splitter.addWidget(self.monitor_detail_view)
        self.monitor_splitter.addWidget(self.monitor_timeline_view)
        self.monitor_splitter.addWidget(self.monitor_trace_view)
        self.monitor_splitter.setSizes([300, 200, 170, 280])
        monitor_layout.addWidget(self.monitor_splitter, 1)

        operations_tab = QWidget(self.tabs)
        operations_tab.setMinimumSize(0, 0)
        operations_tab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        operations_layout = QVBoxLayout(operations_tab)
        operations_layout.setContentsMargins(0, 0, 0, 0)
        operations_layout.setSpacing(8)

        operator_actions_label = QLabel("Operator Tools", operations_tab)
        operator_actions_label.setObjectName("controlMeta")
        operations_layout.addWidget(operator_actions_label, 0)

        operator_actions_grid = QGridLayout()
        operator_actions_grid.setContentsMargins(0, 0, 0, 0)
        operator_actions_grid.setHorizontalSpacing(8)
        operator_actions_grid.setVerticalSpacing(8)

        action_specs = [
            ("reload_.svg", "Health Checks", "Alle Operator-Checks aktualisieren", self._run_operator_health_checks, "btn_refresh_health"),
            ("swap_horiz_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg", "Queue Probe", "Queue-Backend pruefen", self._probe_queue_health, "btn_probe_queue"),
            ("check_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg", "Dispatcher Probe", "Dispatcher-Store pruefen", self._probe_dispatcher_health, "btn_probe_dispatcher"),
            ("settings_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg", "Dispatcher Repair", "Dispatcher-Store reparieren", self._repair_dispatcher_store, "btn_repair_dispatcher"),
            ("deployed_code.svg", "MCP Probe", "MCP-Konfiguration pruefen", self._probe_mcp_health, "btn_probe_mcp"),
            ("file_export_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg", "Export Snapshot", "Control-Plane-Snapshot exportieren", self._export_runtime_snapshot_report, "btn_export_runtime"),
        ]
        for index, (icon_name, label_text, tooltip, slot, attr_name) in enumerate(action_specs):
            tile, button = self._create_operator_action_tile(
                icon_name,
                label_text,
                tooltip,
                slot,
                operations_tab,
            )
            setattr(self, attr_name, button)
            operator_actions_grid.addWidget(tile, index // 3, index % 3)
        operations_layout.addLayout(operator_actions_grid)

        operator_filter_form = QFormLayout()
        operator_filter_form.setContentsMargins(0, 0, 0, 0)
        operator_filter_form.setSpacing(8)
        operator_filter_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        operator_status_label = QLabel("Action Status", operations_tab)
        operator_status_label.setObjectName("controlMeta")
        self.operator_status_selector = QComboBox(operations_tab)
        self.operator_status_selector.setObjectName("controlSelector")
        self.operator_status_selector.setMinimumContentsLength(10)
        self.operator_status_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.operator_status_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.operator_status_selector.currentTextChanged.connect(self._handle_operator_filter_change)
        operator_filter_form.addRow(operator_status_label, self.operator_status_selector)

        operator_audit_label = QLabel("Action Type", operations_tab)
        operator_audit_label.setObjectName("controlMeta")
        self.operator_audit_selector = QComboBox(operations_tab)
        self.operator_audit_selector.setObjectName("controlSelector")
        self.operator_audit_selector.setMinimumContentsLength(10)
        self.operator_audit_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.operator_audit_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.operator_audit_selector.currentTextChanged.connect(self._handle_operator_filter_change)
        operator_filter_form.addRow(operator_audit_label, self.operator_audit_selector)

        operator_group_label = QLabel("Action Group", operations_tab)
        operator_group_label.setObjectName("controlMeta")
        self.operator_group_selector = QComboBox(operations_tab)
        self.operator_group_selector.setObjectName("controlSelector")
        self.operator_group_selector.setMinimumContentsLength(10)
        self.operator_group_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.operator_group_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.operator_group_selector.currentTextChanged.connect(self._handle_operator_filter_change)
        operator_filter_form.addRow(operator_group_label, self.operator_group_selector)

        operator_source_label = QLabel("Action Source", operations_tab)
        operator_source_label.setObjectName("controlMeta")
        self.operator_source_selector = QComboBox(operations_tab)
        self.operator_source_selector.setObjectName("controlSelector")
        self.operator_source_selector.setMinimumContentsLength(10)
        self.operator_source_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.operator_source_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.operator_source_selector.currentTextChanged.connect(self._handle_operator_filter_change)
        operator_filter_form.addRow(operator_source_label, self.operator_source_selector)

        operations_layout.addLayout(operator_filter_form)

        self.operator_summary_view = QTextBrowser(operations_tab)
        self.operator_summary_view.setObjectName("controlBrowser")
        self.operator_summary_view.setOpenExternalLinks(False)
        self.operator_summary_view.setMinimumHeight(0)
        self.operator_summary_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.operator_log_view = QTextBrowser(operations_tab)
        self.operator_log_view.setObjectName("controlBrowser")
        self.operator_log_view.setOpenExternalLinks(False)
        self.operator_log_view.setMinimumHeight(0)
        self.operator_log_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.operations_splitter = self._create_viewport_splitter(operations_tab)
        self.operations_splitter.addWidget(self.operator_summary_view)
        self.operations_splitter.addWidget(self.operator_log_view)
        self.operations_splitter.setSizes([220, 160])
        operations_layout.addWidget(self.operations_splitter, 1)

        self.tabs.addTab(config_tab, "Configuration")
        self.tabs.addTab(monitor_tab, "Monitoring")
        self.tabs.addTab(operations_tab, "Operations")
        self.primary_splitter.addWidget(self.tabs)
        self.primary_splitter.addWidget(hero)
        self.primary_splitter.setSizes([560, 170])
        self.primary_splitter.setStretchFactor(0, 4)
        self.primary_splitter.setStretchFactor(1, 1)
        root.addWidget(self.primary_splitter, 1)
        self._render_operator_log()
        self._open_agent_system_builder_in_configuration_tab()
        self._set_config_builder_visible(False)

    def _create_metric_card(self, title: str) -> tuple[QFrame, QLabel]:
        card = QFrame(self)
        card.setObjectName("controlMetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)

        title_label = QLabel(title, card)
        title_label.setObjectName("controlMetricLabel")
        value_label = QLabel("--", card)
        value_label.setObjectName("controlMetricValue")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch(1)
        return card, value_label

    def _create_viewport_splitter(self, parent: QWidget) -> QSplitter:
        splitter = QSplitter(Qt.Vertical, parent)
        splitter.setObjectName("controlViewportSplitter")
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(7)
        splitter.setOpaqueResize(True)
        splitter.setMinimumSize(0, 0)
        splitter.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        return splitter

    def _create_operator_action_tile(
        self,
        icon_name: str,
        label_text: str,
        tooltip: str,
        slot,
        parent: QWidget,
    ) -> tuple[QFrame, ToolButton]:
        tile = QFrame(parent)
        tile.setObjectName("controlMetricCard")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        button = ToolButton(icon_name, tooltip, slot=slot, parent=tile)
        button.setFixedSize(32, 32)
        layout.addWidget(button, 0, Qt.AlignHCenter)

        label = QLabel(label_text, tile)
        label.setObjectName("controlMeta")
        label.setAlignment(Qt.AlignHCenter)
        label.setWordWrap(True)
        layout.addWidget(label, 0, Qt.AlignHCenter)
        return tile, button

    def _set_config_builder_visible(self, visible: bool) -> None:
        if not hasattr(self, "config_root_splitter"):
            return
        if not visible:
            self.config_root_splitter.setSizes([1, 0])
            return

        sizes = self.config_root_splitter.sizes()
        if len(sizes) == 2:
            total = max(520, sizes[0] + sizes[1])
        else:
            total = max(520, self.height())
        builder_height = max(220, min(420, total // 2))
        self.config_root_splitter.setSizes([total - builder_height, builder_height])

    def _clear_config_builder_panel(self) -> None:
        panel = getattr(self, "_config_builder_panel", None)
        if panel is None:
            return
        self.config_builder_layout.removeWidget(panel)
        panel.setParent(None)
        panel.deleteLater()
        self._config_builder_panel = None

    def _close_config_builder_panel(self) -> None:
        # Legacy wrapper: keep the panel mounted and collapse via splitter only.
        self._set_config_builder_visible(False)

    def _mount_config_builder_panel(self, panel: QWidget) -> None:
        self._clear_config_builder_panel()
        self._config_builder_panel = panel
        self.config_builder_layout.addWidget(panel, 1)
        self.tabs.setCurrentWidget(self._config_tab)

    def _create_agent_system_builder_config_panel(
        self,
        *,
        initial_payload: dict[str, Any],
        build_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> QWidget:
        panel = QFrame(self.config_builder_container)
        panel.setObjectName("controlBuilderPanel")
        panel.setStyleSheet(
            f"""
            QFrame#controlBuilderPanel {{
                background: {self.scheme['col5']};
                border: 1px solid {self.scheme['col10']};
                border-radius: 10px;
            }}
            QLabel#builderSectionText {{
                color: #c2c2c2;
            }}
            QPushButton#builderPrimaryButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 1px;
                min-width: 22px;
                min-height: 22px;
            }}
            QPushButton#builderPrimaryButton:hover {{
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.18);
            }}
            QPushButton#builderIconButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 1px;
                min-width: 22px;
                min-height: 22px;
            }}
            QPushButton#builderIconButton:hover {{
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.18);
            }}
            """
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)

        top_buttons = QHBoxLayout()
        top_buttons.setContentsMargins(0, 0, 0, 0)
        top_buttons.setSpacing(6)
        btn_template = QPushButton("", panel)
        btn_build = QPushButton("", panel)
        btn_template.setIcon(_icon("open_file.svg"))
        btn_build.setIcon(_icon("deployed_code.svg"))
        btn_template.setToolTip("Template laden")
        btn_build.setToolTip("Sync Build starten")
        btn_template.setIconSize(QSize(18, 18))
        btn_build.setIconSize(QSize(18, 18))
        btn_template.setCursor(Qt.PointingHandCursor)
        btn_build.setCursor(Qt.PointingHandCursor)
        btn_template.setObjectName("builderPrimaryButton")
        btn_build.setObjectName("builderPrimaryButton")
        top_buttons.addWidget(btn_template, 0)
        top_buttons.addWidget(btn_build, 0)
        top_buttons.addStretch(1)
        panel_layout.addLayout(top_buttons)

        editor = CodeViewer(
            json.dumps(initial_payload, ensure_ascii=False, indent=2),
            panel,
            language="json",
            editable=True,
            auto_fit=False,
            accent_color=self.scheme.get("col1", "#3a5fff"),
            accent_selection_color=self.scheme.get("col2", "#6280ff"),
            surface_color=self.scheme.get("col10", "#404040"),
            font_size_px=14,
        )
        editor.setMinimumHeight(260)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(editor)

        status_text = QLabel("Status: Bereit", panel)
        status_text.setObjectName("builderSectionText")
        status_text.setWordWrap(True)
        panel_layout.addWidget(status_text)

        bottom_buttons = QHBoxLayout()
        bottom_buttons.setContentsMargins(0, 0, 0, 0)
        bottom_buttons.setSpacing(6)
        btn_post = QPushButton("", panel)
        btn_copy = QPushButton("", panel)
        btn_post.setIcon(_icon("send.svg"))
        btn_copy.setIcon(_icon("file_export_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"))
        btn_post.setToolTip("Ergebnis ins Operations-Log schreiben")
        btn_copy.setToolTip("JSON exportieren")
        btn_post.setIconSize(QSize(18, 18))
        btn_copy.setIconSize(QSize(18, 18))
        btn_post.setCursor(Qt.PointingHandCursor)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_post.setObjectName("builderIconButton")
        btn_copy.setObjectName("builderIconButton")
        bottom_buttons.addWidget(btn_post, 0)
        bottom_buttons.addWidget(btn_copy, 0)
        bottom_buttons.addStretch(1)
        panel_layout.addLayout(bottom_buttons)

        latest_result: dict[str, Any] = {}

        def _load_template() -> None:
            editor.setPlainText(json.dumps(initial_payload, ensure_ascii=False, indent=2))
            status_text.setText("Status: Template geladen")

        def _run_build() -> None:
            nonlocal latest_result
            raw_text = editor.toPlainText().strip()
            if not raw_text:
                status_text.setText("Status: Payload ist leer")
                return

            try:
                payload = json.loads(raw_text)
            except Exception as exc:
                status_text.setText(f"Status: JSON-Fehler ({type(exc).__name__})")
                return

            if not isinstance(payload, dict):
                status_text.setText("Status: Payload muss JSON-Objekt sein")
                return

            btn_build.setEnabled(False)
            try:
                latest_result = dict(build_handler(payload) or {})
                validation = dict(latest_result.get("validation") or {})
                status_text.setText(
                    f"Status: Build abgeschlossen (valid={bool(validation.get('valid', True))})"
                )
            except Exception as exc:
                status_text.setText(f"Status: Build fehlgeschlagen ({type(exc).__name__})")
                latest_result = {}
            finally:
                btn_build.setEnabled(True)

        def _post_result() -> None:
            if not latest_result:
                self._append_operator_log("Agent builder has no result yet. Run Sync Build first.")
                status_text.setText("Status: Kein Ergebnis zum Loggen")
                return
            validation = dict(latest_result.get("validation") or {})
            system_name = str(latest_result.get("system_name") or "agent_system")
            self._append_operator_log(
                f"Agent builder completed: system={system_name} valid={bool(validation.get('valid', True))}"
            )
            status_text.setText("Status: Ergebnis im Operations-Log vermerkt")

        def _copy_json() -> None:
            payload_text = editor.toPlainText()
            try:
                QApplication.clipboard().setText(payload_text)
                status_text.setText("Status: JSON in Zwischenablage")
            except Exception as exc:
                status_text.setText(f"Status: Kopieren fehlgeschlagen ({type(exc).__name__})")

        btn_template.clicked.connect(_load_template)
        btn_build.clicked.connect(_run_build)
        btn_post.clicked.connect(_post_result)
        btn_copy.clicked.connect(_copy_json)
        return panel

    def _open_agent_system_builder_in_configuration_tab(self) -> None:
        if self._config_builder_panel is not None:
            self.tabs.setCurrentWidget(self._config_tab)
            return
        template = self._build_agent_system_template("agent_system", "/create agents")
        panel = self._create_agent_system_builder_config_panel(
            initial_payload=template,
            build_handler=self._execute_agent_system_builder_payload,
        )
        self._mount_config_builder_panel(panel)

    def _build_agent_system_template(self, system_name: str, route_prefix: str) -> dict[str, Any]:
        resolved_system_name = str(system_name or "agent_system").strip() or "agent_system"
        resolved_route_prefix = str(route_prefix or "/create agents").strip() or "/create agents"

        try:
            if __package__:
                from .agents_config import AgentSystemBuilderRequestObject  # type: ignore
            else:
                from alde.agents_config import AgentSystemBuilderRequestObject  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from agents_config import AgentSystemBuilderRequestObject  # type: ignore
            else:
                raise

        request_object = AgentSystemBuilderRequestObject(
            resolved_system_name,
            {
                "system_name": resolved_system_name,
                "route_prefix": resolved_route_prefix,
            },
        )
        request_config = request_object.to_config_dict()
        integration_targets = dict(request_config.get("integration_targets") or {})
        persisted_target = str(integration_targets.get("persisted_config_target") or "").strip()

        return {
            "action": "build_agent_system_configs",
            "section_identity": {
                "system_name": request_config.get("system_name"),
                "system_slug": request_config.get("system_slug"),
                "route_prefix": request_config.get("route_prefix"),
                "route_name": request_config.get("route_name"),
            },
            "section_agents": {
                "assistant_agent_name": request_config.get("assistant_agent_name"),
                "planner_agent_name": request_config.get("planner_agent_name"),
                "worker_agent_name": request_config.get("worker_agent_name"),
                "planner_prompt_name": request_config.get("planner_prompt_name"),
                "worker_prompt_name": request_config.get("worker_prompt_name"),
                "planner_model": request_config.get("planner_model"),
                "worker_model": request_config.get("worker_model"),
                "agent_specs": request_config.get("agent_specs"),
            },
            "section_workflows": {
                "planner_workflow_name": request_config.get("planner_workflow_name"),
                "builder_workflow_name": request_config.get("builder_workflow_name"),
                "workflow_specs": request_config.get("workflow_specs"),
            },
            "section_handoff_and_action": {
                "primary_to_planner_schema_name": request_config.get("primary_to_planner_schema_name"),
                "planner_to_builder_schema_name": request_config.get("planner_to_builder_schema_name"),
                "action_request_schema_name": request_config.get("action_request_schema_name"),
                "action_tool_name": request_config.get("action_tool_name"),
            },
            "section_planning": {
                "planning_schema": request_config.get("planning_schema"),
            },
            "section_integration": {
                "integration_targets": integration_targets,
            },
            "section_execution": {
                "write_file": False,
                "persist_path": persisted_target,
            },
        }

    def _resolve_builder_request_from_sections(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        request_payload = dict(payload or {})
        execution_payload: dict[str, Any] = {}

        section_names = (
            "section_identity",
            "section_agents",
            "section_workflows",
            "section_handoff_and_action",
            "section_planning",
            "section_integration",
            "section_execution",
        )

        for section_name in section_names:
            section_value = request_payload.pop(section_name, None)
            if not isinstance(section_value, dict):
                continue
            if section_name == "section_execution":
                execution_payload.update(section_value)
                continue
            for key, value in section_value.items():
                if key not in request_payload or request_payload.get(key) in (None, "", [], {}):
                    request_payload[key] = value

        return request_payload, execution_payload

    def _run_agent_system_builder_sync(
        self,
        *,
        system_name: str,
        request_payload: dict[str, Any],
        write_file: bool,
        persist_path: str | None,
    ) -> dict[str, Any]:
        try:
            if __package__:
                from .tools import build_agent_system_configs_tool  # type: ignore
            else:
                from alde.tools import build_agent_system_configs_tool  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from tools import build_agent_system_configs_tool  # type: ignore
            else:
                raise

        result_text = build_agent_system_configs_tool(
            system_name=system_name,
            action_request=request_payload,
            persist_path=persist_path,
            write_file=write_file,
        )

        if isinstance(result_text, str):
            try:
                result = json.loads(result_text)
            except Exception as exc:
                raise ValueError(f"Builder returned non-JSON output: {exc}") from exc
        elif isinstance(result_text, dict):
            result = result_text
        else:
            raise ValueError("Builder returned unsupported result type")

        if isinstance(result, dict) and result.get("ok") is False:
            error_text = str(result.get("error") or "unknown_builder_error")
            raise ValueError(error_text)

        return dict(result) if isinstance(result, dict) else {"result": result}

    def _execute_agent_system_builder_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload, execution_payload = self._resolve_builder_request_from_sections(payload)
        system_name = str(request_payload.get("system_name") or "agent_system").strip() or "agent_system"
        request_payload.setdefault("system_name", system_name)
        request_payload.setdefault("route_prefix", "/create agents")

        write_file = bool(execution_payload.get("write_file"))
        persist_path_text = str(execution_payload.get("persist_path") or "").strip()
        persist_path = persist_path_text or None

        return self._run_agent_system_builder_sync(
            system_name=system_name,
            request_payload=request_payload,
            write_file=write_file,
            persist_path=persist_path,
        )

    def _resolve_ai_widget(self) -> AIWidget | None:
        window = self.window()
        chat_dock = getattr(window, "chat_dock", None)
        chat_widget = chat_dock.widget() if chat_dock is not None and hasattr(chat_dock, "widget") else None
        if isinstance(chat_widget, AIWidget):
            return chat_widget
        return None

    def _open_agent_system_builder_in_ai_chat(self) -> None:
        try:
            self._open_agent_system_builder_in_configuration_tab()
            self._append_operator_log("Agent builder panel opened in Configuration tab")
        except Exception as exc:
            self._append_operator_log(f"Agent builder panel failed: {type(exc).__name__}: {exc}")
            self._open_agent_system_builder_dialog()

    def _open_agent_system_builder_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Agent System Builder (Sync, lokal)")
        dialog.resize(980, 760)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        intro = QLabel(
            "Builder-Dict in Sections bearbeiten und synchron lokal ausfuehren. Async folgt spaeter.",
            dialog,
        )
        intro.setWordWrap(True)
        intro.setObjectName("controlMeta")
        root.addWidget(intro)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        system_name_edit = QLineEdit("agent_system", dialog)
        route_prefix_edit = QLineEdit("/create agents", dialog)
        persist_path_edit = QLineEdit("", dialog)
        write_file_box = QCheckBox("Persisted module auf Disk schreiben", dialog)

        form.addRow("System Name", system_name_edit)
        form.addRow("Route Prefix", route_prefix_edit)
        form.addRow("Persist Path", persist_path_edit)
        form.addRow("Sync Build", write_file_box)
        root.addLayout(form)

        editor_label = QLabel("Builder Dict (sectioned)", dialog)
        editor_label.setObjectName("controlMeta")
        root.addWidget(editor_label)

        payload_editor = QPlainTextEdit(dialog)
        payload_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        payload_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        payload_editor.setStyleSheet("QPlainTextEdit { font-size: 17px; }")
        root.addWidget(payload_editor, 1)

        result_label = QLabel("Build Result", dialog)
        result_label.setObjectName("controlMeta")
        root.addWidget(result_label)

        result_view = QPlainTextEdit(dialog)
        result_view.setReadOnly(True)
        result_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        result_view.setFixedHeight(180)
        root.addWidget(result_view)

        button_box = QDialogButtonBox(dialog)
        btn_template = button_box.addButton("Template laden", QDialogButtonBox.ActionRole)
        btn_build = button_box.addButton("Sync Build starten", QDialogButtonBox.AcceptRole)
        btn_close = button_box.addButton(QDialogButtonBox.Close)
        root.addWidget(button_box)

        def load_template() -> None:
            try:
                template = self._build_agent_system_template(
                    system_name_edit.text().strip() or "agent_system",
                    route_prefix_edit.text().strip() or "/create agents",
                )
                payload_editor.setPlainText(json.dumps(template, ensure_ascii=False, indent=2))
                exec_section = dict(template.get("section_execution") or {})
                if not persist_path_edit.text().strip():
                    persist_path_edit.setText(str(exec_section.get("persist_path") or ""))
                write_file_box.setChecked(bool(exec_section.get("write_file")))
                result_view.setPlainText("Template geladen.")
            except Exception as exc:
                result_view.setPlainText(f"Template konnte nicht geladen werden:\n{type(exc).__name__}: {exc}")

        def run_build_sync() -> None:
            raw_text = payload_editor.toPlainText().strip()
            if not raw_text:
                result_view.setPlainText("Builder Dict ist leer. Bitte Template laden oder JSON einfuegen.")
                return

            try:
                payload = json.loads(raw_text)
            except Exception as exc:
                result_view.setPlainText(f"Ungueltiges JSON:\n{type(exc).__name__}: {exc}")
                return

            if not isinstance(payload, dict):
                result_view.setPlainText("Builder Dict muss ein JSON-Objekt sein.")
                return

            request_payload, execution_payload = self._resolve_builder_request_from_sections(payload)
            system_name = str(
                request_payload.get("system_name")
                or system_name_edit.text().strip()
                or "agent_system"
            ).strip() or "agent_system"
            request_payload.setdefault("system_name", system_name)
            request_payload.setdefault(
                "route_prefix",
                str(route_prefix_edit.text().strip() or "/create agents").strip() or "/create agents",
            )

            write_file = bool(
                execution_payload.get("write_file")
                if "write_file" in execution_payload
                else write_file_box.isChecked()
            )
            persist_path = str(
                execution_payload.get("persist_path")
                or persist_path_edit.text().strip()
                or ""
            ).strip()
            resolved_persist_path = persist_path or None

            dialog.setCursor(Qt.WaitCursor)
            btn_build.setEnabled(False)
            try:
                result = self._run_agent_system_builder_sync(
                    system_name=system_name,
                    request_payload=request_payload,
                    write_file=write_file,
                    persist_path=resolved_persist_path,
                )
                result_view.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
                validation = dict(result.get("validation") or {}) if isinstance(result, dict) else {}
                is_valid = bool(validation.get("valid", True))
                self._append_operator_log(
                    f"Agent builder completed: system={system_name} valid={is_valid} write_file={write_file}"
                )
            except Exception as exc:
                result_view.setPlainText(f"Sync Build fehlgeschlagen:\n{type(exc).__name__}: {exc}")
                self._append_operator_log(
                    f"Agent builder failed: system={system_name} error={type(exc).__name__}: {exc}"
                )
            finally:
                dialog.unsetCursor()
                btn_build.setEnabled(True)

        btn_template.clicked.connect(load_template)
        btn_build.clicked.connect(run_build_sync)
        btn_close.clicked.connect(dialog.reject)

        load_template()
        dialog.exec()

    def _render_operator_status_row(self, title: str, chip_html: str, detail: str, note: str = "") -> str:
        note_html = (
            f"<br><span style=\"color:{self.scheme['col8']};\">{html.escape(note)}</span>"
            if note else ""
        )
        return (
            f"<li><b>{html.escape(title)}:</b> {chip_html} {html.escape(detail)}{note_html}</li>"
        )

    def _trace_entry_agent_label(self, trace_entry: dict[str, Any]) -> str:
        return str(trace_entry.get("agent_label") or trace_entry.get("assistant_name") or "").strip()

    def _trace_entry_workflow_name(self, trace_entry: dict[str, Any]) -> str:
        return str(trace_entry.get("workflow_name") or "").strip()

    def _trace_entry_tool_names(self, trace_entry: dict[str, Any]) -> list[str]:
        tool_names: list[str] = []
        direct_tool = str(trace_entry.get("tool_name") or "").strip()
        if direct_tool:
            tool_names.append(direct_tool)
        for tool_call in trace_entry.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function_object = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
            tool_name = str(function_object.get("name") or tool_call.get("name") or "").strip()
            if tool_name:
                tool_names.append(tool_name)
        return sorted({name for name in tool_names if name})

    def _trace_entry_handoff_value(self, trace_entry: dict[str, Any]) -> str:
        handoff = trace_entry.get("handoff") if isinstance(trace_entry.get("handoff"), dict) else {}
        source_agent = str(handoff.get("source_agent") or "").strip() or "unknown"
        target_agent = str(handoff.get("target_agent") or "").strip()
        if not target_agent:
            return ""
        protocol = str(handoff.get("protocol") or "").strip()
        suffix = f" [{protocol}]" if protocol else ""
        return f"{source_agent}->{target_agent}{suffix}"

    def _filtered_trace_entries(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        selected_agent = self.trace_agent_selector.currentText().strip()
        selected_workflow = self.trace_workflow_selector.currentText().strip()
        selected_tool = self.trace_tool_selector.currentText().strip()
        selected_handoff = self.trace_handoff_selector.currentText().strip()

        filtered_entries: list[dict[str, Any]] = []
        for trace_entry in snapshot.get("trace") or []:
            if not isinstance(trace_entry, dict):
                continue
            agent_label = self._trace_entry_agent_label(trace_entry)
            workflow_name = self._trace_entry_workflow_name(trace_entry)
            tool_names = self._trace_entry_tool_names(trace_entry)
            handoff_value = self._trace_entry_handoff_value(trace_entry)

            if selected_agent and selected_agent != "All agents" and agent_label != selected_agent:
                continue
            if selected_workflow and selected_workflow != "All workflows" and workflow_name != selected_workflow:
                continue
            if selected_tool and selected_tool != "All tools" and selected_tool not in tool_names:
                continue
            if selected_handoff:
                if selected_handoff == "All handoffs":
                    pass
                elif selected_handoff == "Handoff only":
                    if not handoff_value:
                        continue
                elif handoff_value != selected_handoff:
                    continue
            filtered_entries.append(trace_entry)
        return filtered_entries

    def _refresh_monitoring_views(self) -> None:
        monitoring_snapshot = dict(self._last_snapshot.get("monitoring") or {})
        if monitoring_snapshot:
            self._render_monitoring_snapshot(monitoring_snapshot)

    def _render_monitor_trace_block(self, label: str, value: Any) -> str:
        if value in (None, "", {}, []):
            return ""
        if isinstance(value, str):
            body = html.escape(value)
        else:
            body = html.escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return f"<h5>{html.escape(label)}</h5><pre>{body}</pre>"

    def _render_monitor_trace_entry(self, trace_entry: dict[str, Any]) -> str:
        meta_parts = [
            f"kind={html.escape(str(trace_entry.get('trace_kind') or 'message'))}",
            f"role={html.escape(str(trace_entry.get('role') or 'n/a'))}",
            f"agent={html.escape(str(trace_entry.get('agent_label') or trace_entry.get('assistant_name') or 'n/a'))}",
            f"workflow={html.escape(str(trace_entry.get('workflow_name') or 'n/a'))}",
        ]
        if trace_entry.get("tool_name"):
            meta_parts.append(f"tool={html.escape(str(trace_entry.get('tool_name')))}")
        if trace_entry.get("tool_call_id"):
            meta_parts.append(f"tool_call_id={html.escape(str(trace_entry.get('tool_call_id')))}")
        return "".join(
            [
                f"<h4>{html.escape(str(trace_entry.get('timestamp') or 'n/a'))}</h4>",
                f"<p><b>{html.escape(str(trace_entry.get('summary') or 'trace'))}</b><br><span style=\"color:{self.scheme['col8']};\">{' | '.join(meta_parts)}</span></p>",
                self._render_monitor_trace_block("content", trace_entry.get("content")),
                self._render_monitor_trace_block("tool_calls", trace_entry.get("tool_calls")),
                self._render_monitor_trace_block("handoff", trace_entry.get("handoff")),
                self._render_monitor_trace_block("workflow_payload", trace_entry.get("workflow_payload")),
                self._render_monitor_trace_block("workflow", trace_entry.get("workflow")),
                self._render_monitor_trace_block("workflow_snapshot", trace_entry.get("workflow_snapshot")),
                self._render_monitor_trace_block("data", trace_entry.get("data")),
            ]
        )

    def update_scheme(self, accent: dict[str, str], base: dict[str, str]) -> None:
        self._accent = accent
        self._base = base
        self.scheme = _build_scheme(accent, base)
        handle_idle, handle_hover, handle_pressed = _splitter_handle_palette(self.scheme)
        self.setStyleSheet(
            f"""
            QFrame#controlHero, QFrame#controlMetricCard {{
                background: {self.scheme['col5']};
                border: 1px solid {self.scheme['col10']};
                border-radius: 14px;
            }}
            QFrame#controlBuilderContainer {{
                background: {self.scheme['col7']};
                border: none;
            }}
            QLabel#controlTitle {{
                color: {self.scheme['col6']};
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel#controlSubtitle, QLabel#controlMeta, QLabel#controlMetricLabel {{
                color: {self.scheme['col8']};
                font-size: 12px;
            }}
            QLabel#controlMetricValue {{
                color: {self.scheme['col1']};
                font-size: 24px;
                font-weight: 700;
            }}
            QTextBrowser#controlBrowser {{
                background: {self.scheme['col9']};
                border: 1px solid {self.scheme['col10']};
                border-radius: 12px;
                padding: 8px;
                font-size: 13px;
            }}
            QTextBrowser#controlBrowser QScrollBar:vertical,
            QTextBrowser#controlBrowser QScrollBar:horizontal {{
                background: transparent;
                margin: 0px;
                border: none;
            }}
            QTextBrowser#controlBrowser QScrollBar:vertical {{
                width: 6px;
            }}
            QTextBrowser#controlBrowser QScrollBar:horizontal {{
                height: 6px;
            }}
            QTextBrowser#controlBrowser QScrollBar:hover,
            QTextBrowser#controlBrowser QScrollBar:vertical:hover,
            QTextBrowser#controlBrowser QScrollBar:horizontal:hover {{
                background: transparent;
            }}
            QTextBrowser#controlBrowser QScrollBar::handle:vertical,
            QTextBrowser#controlBrowser QScrollBar::handle:horizontal {{
                background: rgba(0, 0, 0, 0.0);
                border-radius: 3px;
                min-height: 28px;
                min-width: 28px;
            }}
            QTextBrowser#controlBrowser QScrollBar::handle:vertical:hover,
            QTextBrowser#controlBrowser QScrollBar::handle:horizontal:hover,
            QTextBrowser#controlBrowser QScrollBar::handle:hover:vertical,
            QTextBrowser#controlBrowser QScrollBar::handle:hover:horizontal {{
                background: {self.scheme['col10']};
            }}
            QTextBrowser#controlBrowser QScrollBar::handle:vertical:pressed,
            QTextBrowser#controlBrowser QScrollBar::handle:horizontal:pressed,
            QTextBrowser#controlBrowser QScrollBar::handle:pressed:vertical,
            QTextBrowser#controlBrowser QScrollBar::handle:pressed:horizontal {{
                background: {self.scheme['col2']};
            }}
            QTextBrowser#controlBrowser QScrollBar::add-line,
            QTextBrowser#controlBrowser QScrollBar::sub-line,
            QTextBrowser#controlBrowser QScrollBar::add-page,
            QTextBrowser#controlBrowser QScrollBar::sub-page {{
                background: none;
                border: none;
                width: 0px;
                height: 0px;
            }}
            QSplitter#controlViewportSplitter::handle {{
                background: {handle_idle};
                margin: 2px 0;
                border-radius: 6px;
            }}
            QSplitter#controlViewportSplitter::handle:hover {{
                background: {handle_hover};
            }}
            QSplitter#controlViewportSplitter::handle:pressed {{
                background: {handle_pressed};
            }}
            QSplitter#controlPrimarySplitter::handle {{
                background: {handle_idle};
                margin: 2px 0;
                border-radius: 6px;
            }}
            QSplitter#controlPrimarySplitter::handle:hover {{
                background: {handle_hover};
            }}
            QSplitter#controlPrimarySplitter::handle:pressed {{
                background: {handle_pressed};
            }}
            QComboBox#controlSelector {{
                background: {self.scheme['col9']};
                color: {self.scheme['col6']};
                border: 1px solid {self.scheme['col10']};
                border-radius: 10px;
                padding: 6px 10px;
                min-height: 18px;
            }}
            QPushButton#controlRefresh {{
                background: {self.scheme['col1']};
                color: {self.scheme['col7']};
                border: 1px solid {self.scheme['col1']};
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QPushButton#controlRefresh:hover {{
                background: {self.scheme['col2']};
                border-color: {self.scheme['col2']};
            }}
            QPushButton#controlAction {{
                background: {self.scheme['col5']};
                color: {self.scheme['col6']};
                border: 1px solid {self.scheme['col10']};
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QPushButton#controlAction:hover {{
                border-color: {self.scheme['col2']};
                color: {self.scheme['col2']};
            }}
            """
        )

    def refresh_view(self) -> None:
        try:
            configuration_snapshot = self._load_configuration_snapshot()
            monitoring_snapshot = self._load_monitoring_snapshot()
            operator_snapshot = self._load_operator_snapshot()
            self._populate_trace_filter_selectors(monitoring_snapshot)
            self._populate_operator_filter_selectors(operator_snapshot)
            self._render_configuration_snapshot(configuration_snapshot)
            self._render_monitoring_snapshot(monitoring_snapshot)
            self._render_operator_snapshot(operator_snapshot)
            self._populate_drilldown_selectors(configuration_snapshot)
            self._refresh_drilldown_views()
            self._last_snapshot = {
                "configuration": configuration_snapshot,
                "monitoring": monitoring_snapshot,
                "operations": operator_snapshot,
            }
            self._render_operator_log()
            self._last_refresh_label.setText(
                f"Updated {datetime.now().strftime('%H:%M:%S')}"
            )
            self.snapshotChanged.emit(dict(self._last_snapshot))
        except Exception as exc:
            error_text = html.escape(f"{type(exc).__name__}: {exc}")
            self.config_summary_view.setHtml(f"<h3>Configuration unavailable</h3><p>{error_text}</p>")
            self.config_manifest_view.setHtml(
                "<h3>Manifest projection failed</h3><p>Check agents_config.py imports and runtime state.</p>"
            )
            self.monitor_summary_view.setHtml(f"<h3>Monitoring unavailable</h3><p>{error_text}</p>")
            self.monitor_detail_view.setHtml(
                "<h3>Drill-down unavailable</h3><p>Workflow status detail could not be projected.</p>"
            )
            self.monitor_timeline_view.setHtml(
                "<h3>Timeline unavailable</h3><p>Runtime event projection could not be loaded.</p>"
            )
            self.monitor_trace_view.setHtml(
                "<h3>Trace unavailable</h3><p>Detailed chat/tool/handoff projection could not be loaded.</p>"
            )
            self.trace_agent_selector.clear()
            self.trace_workflow_selector.clear()
            self.trace_tool_selector.clear()
            self.trace_handoff_selector.clear()
            self.operator_status_selector.clear()
            self.operator_audit_selector.clear()
            self.operator_group_selector.clear()
            self.operator_source_selector.clear()
            self.operator_summary_view.setHtml(f"<h3>Operations unavailable</h3><p>{error_text}</p>")
            self._last_snapshot = {
                "configuration": {"agent_count": 0, "workflow_count": 0},
                "monitoring": {"session_count": 0, "failure_count": 0},
                "operations": {"queue_backend": "n/a", "queue_healthy": False},
            }
            self._render_operator_log()
            self.snapshotChanged.emit(dict(self._last_snapshot))

    def _load_configuration_snapshot(self) -> dict[str, Any]:
        try:
            if __package__:
                from .agents_config import (  # type: ignore
                    get_agent_manifests,
                    get_tool_configs,
                    get_tool_group_configs,
                    get_workflow_configs,
                )
            else:
                from alde.agents_config import (  # type: ignore
                    get_agent_manifests,
                    get_tool_configs,
                    get_tool_group_configs,
                    get_workflow_configs,
                )
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from agents_config import (  # type: ignore
                    get_agent_manifests,
                    get_tool_configs,
                    get_tool_group_configs,
                    get_workflow_configs,
                )
            else:
                raise

        manifests = get_agent_manifests()
        workflows = get_workflow_configs()
        tool_configs = get_tool_configs()
        tool_groups = get_tool_group_configs()

        role_counts: dict[str, int] = {}
        workflow_usage: dict[str, int] = {}
        agent_rows: list[dict[str, Any]] = []

        for agent_label, manifest in sorted(manifests.items()):
            role = str(manifest.get("role") or "worker")
            workflow_name = str(manifest.get("workflow_name") or "unassigned")
            role_counts[role] = role_counts.get(role, 0) + 1
            workflow_usage[workflow_name] = workflow_usage.get(workflow_name, 0) + 1
            agent_rows.append(
                {
                    "agent_label": agent_label,
                    "role": role,
                    "model": str(manifest.get("model") or "unspecified"),
                    "workflow_name": workflow_name,
                    "tool_count": len(manifest.get("tools") or []),
                    "instance_policy": str(manifest.get("instance_policy") or "ephemeral"),
                }
            )

        providers: list[str] = []
        if os.getenv("OPENAI_API_KEY"):
            providers.append("OpenAI")
        if os.getenv("ANTHROPIC_API_KEY"):
            providers.append("Anthropic")
        if os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_ENDPOINT"):
            providers.append("Azure OpenAI")
        if os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL"):
            providers.append("Ollama")

        env_rows = [
            ("OpenAI key", bool(os.getenv("OPENAI_API_KEY"))),
            ("Mongo knowledge", bool(os.getenv("AI_IDE_KNOWLEDGE_MONGO_URI"))),
            ("GPU vstore", os.getenv("AI_IDE_VSTORE_GPU_ONLY", "0") in {"1", "true", "True"}),
            ("Verbose HTTP", os.getenv("AI_IDE_VERBOSE_HTTP", "0") in {"1", "true", "True"}),
        ]

        return {
            "agent_count": len(agent_rows),
            "workflow_count": len(workflows),
            "tool_count": len(tool_configs),
            "tool_group_count": len(tool_groups),
            "providers": providers,
            "role_counts": role_counts,
            "workflow_usage": workflow_usage,
            "workflow_names": sorted(name for name in workflow_usage if name and name != "unassigned"),
            "agent_labels": [str(row.get("agent_label") or "") for row in agent_rows],
            "agent_rows_by_label": {
                str(row.get("agent_label") or ""): dict(row) for row in agent_rows if str(row.get("agent_label") or "")
            },
            "agent_rows": agent_rows,
            "env_rows": env_rows,
        }

    def _load_monitoring_snapshot(self) -> dict[str, Any]:
        try:
            if __package__:
                from .control_plane_runtime import load_desktop_monitoring_snapshot  # type: ignore
            else:
                from alde.control_plane_runtime import load_desktop_monitoring_snapshot  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from control_plane_runtime import load_desktop_monitoring_snapshot  # type: ignore
            else:
                raise

        return load_desktop_monitoring_snapshot(event_limit=40, trace_limit=80)

    def _load_agent_drilldown_snapshot(self, agent_label: str) -> dict[str, Any]:
        try:
            if __package__:
                from .control_plane_runtime import get_workflow_status_view  # type: ignore
            else:
                from alde.control_plane_runtime import get_workflow_status_view  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from control_plane_runtime import get_workflow_status_view  # type: ignore
            else:
                raise

        detail = get_workflow_status_view(target_agent=agent_label, limit=8)
        detail["agent_label"] = agent_label
        return detail

    def _load_workflow_drilldown_snapshot(self, workflow_name: str) -> dict[str, Any]:
        try:
            if __package__:
                from .control_plane_runtime import get_workflow_status_view  # type: ignore
            else:
                from alde.control_plane_runtime import get_workflow_status_view  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from control_plane_runtime import get_workflow_status_view  # type: ignore
            else:
                raise

        detail = get_workflow_status_view(workflow_name=workflow_name, limit=8)
        detail["workflow_name"] = workflow_name
        return detail

    def _load_operator_snapshot(self) -> dict[str, Any]:
        try:
            if __package__:
                from .control_plane_runtime import load_operator_status_snapshot  # type: ignore
            else:
                from alde.control_plane_runtime import load_operator_status_snapshot  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from control_plane_runtime import load_operator_status_snapshot  # type: ignore
            else:
                raise

        previous_operations = dict(self._last_snapshot.get("operations") or {})
        return load_operator_status_snapshot(
            mcp_probe=dict(previous_operations.get("mcp_probe") or {}),
            recent_action_entries=list(self._operator_log_entries),
        )

    def _render_configuration_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._set_metric_value("agents", snapshot.get("agent_count", 0))
        self._set_metric_value("workflows", snapshot.get("workflow_count", 0))

        env_rows_html = "".join(
            f"<li><b>{html.escape(label)}:</b> {self._render_bool_chip(bool(value))}</li>"
            for label, value in snapshot.get("env_rows") or []
        )
        role_rows_html = "".join(
            f"<li><b>{html.escape(role)}:</b> {count}</li>"
            for role, count in sorted((snapshot.get("role_counts") or {}).items())
        )
        provider_text = ", ".join(snapshot.get("providers") or []) or "No provider credentials detected"
        self.config_summary_view.setHtml(
            "".join(
                [
                    "<h3>Configuration Readiness</h3>",
                    "<p>Canonical data source: <code>agents_config.py</code>. This panel projects manifests, workflows, tools, and critical runtime flags into a single operational view.</p>",
                    f"<p><b>Providers:</b> {html.escape(provider_text)}</p>",
                    f"<p><b>Tool catalog:</b> {snapshot.get('tool_count', 0)} tools across {snapshot.get('tool_group_count', 0)} tool groups.</p>",
                    "<h4>Environment Gate</h4>",
                    f"<ul>{env_rows_html}</ul>",
                    "<h4>Role Mix</h4>",
                    f"<ul>{role_rows_html or '<li>No agents materialized</li>'}</ul>",
                ]
            )
        )

        manifest_blocks: list[str] = []
        for row in (snapshot.get("agent_rows") or [])[:10]:
            manifest_blocks.append(
                "".join(
                    [
                        f"<h4>{html.escape(str(row.get('agent_label') or 'unknown'))}</h4>",
                        "<ul>",
                        f"<li><b>Role:</b> {html.escape(str(row.get('role') or 'worker'))}</li>",
                        f"<li><b>Workflow:</b> {html.escape(str(row.get('workflow_name') or 'unassigned'))}</li>",
                        f"<li><b>Model:</b> {html.escape(str(row.get('model') or 'unspecified'))}</li>",
                        f"<li><b>Tools:</b> {int(row.get('tool_count') or 0)}</li>",
                        f"<li><b>Instance policy:</b> {html.escape(str(row.get('instance_policy') or 'ephemeral'))}</li>",
                        "</ul>",
                    ]
                )
            )
        self.config_manifest_view.setHtml(
            "<h3>Manifest Preview</h3>" + "".join(manifest_blocks or ["<p>No manifests available.</p>"])
        )

    def _render_monitoring_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._set_metric_value("sessions", snapshot.get("session_count", 0))
        self._set_metric_value("failures", snapshot.get("failure_count", 0))

        latest_session = snapshot.get("latest_session") or {}
        latest_state = (latest_session.get("latest_workflow_state") or {}) if isinstance(latest_session, dict) else {}
        latest_handoff = (latest_session.get("latest_handoff") or {}) if isinstance(latest_session, dict) else {}
        filtered_trace_entries = self._filtered_trace_entries(snapshot)
        active_trace_filters = [
            selector.currentText().strip()
            for selector in (
                self.trace_agent_selector,
                self.trace_workflow_selector,
                self.trace_tool_selector,
                self.trace_handoff_selector,
            )
            if selector.currentText().strip()
            and selector.currentText().strip() not in {"All agents", "All workflows", "All tools", "All handoffs"}
        ]
        active_filter_text = ", ".join(active_trace_filters) if active_trace_filters else "none"
        alerts_html = "".join(
            f"<li>{html.escape(str(alert))}</li>" for alert in (snapshot.get("alerts") or [])
        )
        self.monitor_summary_view.setHtml(
            "".join(
                [
                    "<h3>Runtime Monitoring</h3>",
                    f"<p><b>Projected sessions:</b> {snapshot.get('session_count', 0)} | <b>events:</b> {snapshot.get('event_count', 0)}</p>",
                    f"<p><b>Detailed trace entries:</b> {snapshot.get('trace_count', 0)} total | <b>visible:</b> {len(filtered_trace_entries)} | <b>filters:</b> {html.escape(active_filter_text)}</p>",
                    f"<p><b>Control-plane health:</b> {html.escape('ready' if bool(snapshot.get('healthy')) else 'attention required')} | <b>Queue:</b> {html.escape(str(snapshot.get('queue_backend') or 'n/a'))} ({'ok' if bool(snapshot.get('queue_healthy')) else 'degraded'}) | <b>Active sessions:</b> {int(snapshot.get('active_session_count') or 0)} | <b>Validation issues:</b> {int(snapshot.get('validation_issue_count') or 0)}</p>",
                    f"<p><b>Success:</b> {snapshot.get('success_count', 0)} | <b>Failures:</b> {snapshot.get('failure_count', 0)} | <b>Avg latency:</b> {snapshot.get('average_latency_ms', 0.0):.0f} ms</p>",
                    f"<p><b>Latest workflow state:</b> {html.escape(str(latest_state.get('summary') or 'n/a'))}</p>",
                    f"<p><b>Latest handoff:</b> {html.escape(str(latest_handoff.get('summary') or 'n/a'))}</p>",
                    "<p><b>Drill-downs:</b> Use the selectors below to inspect the latest workflow state per agent and per workflow definition. Use Export Runtime for the full JSON trace.</p>",
                    "<h4>Alerts</h4>",
                    f"<ul>{alerts_html or '<li>No active alerts in the current projection.</li>'}</ul>",
                ]
            )
        )

        timeline_rows: list[str] = []
        timeline_rows: list[str] = []
        for event_object in reversed(snapshot.get("events") or []):
            timeline_rows.append(
                "".join(
                    [
                        f"<p><b>{html.escape(str(event_object.get('timestamp') or 'n/a'))}</b><br>",
                        f"{html.escape(str(event_object.get('summary') or event_object.get('event_type') or 'event'))}<br>",
                        f"<span style=\"color:{self.scheme['col8']};\">agent={html.escape(str(event_object.get('agent_label') or 'n/a'))} | workflow={html.escape(str(event_object.get('workflow_name') or 'n/a'))}</span></p>",
                    ]
                )
            )
        self.monitor_timeline_view.setHtml(
            "<h3>Recent Event Timeline</h3>" + "".join(timeline_rows or ["<p>No runtime events available.</p>"])
        )

        trace_rows = [
            self._render_monitor_trace_entry(trace_entry)
            for trace_entry in reversed(filtered_trace_entries)
            if isinstance(trace_entry, dict)
        ]
        self.monitor_trace_view.setHtml(
            "<h3>Trace Detail</h3>"
            "<p>Normalized runtime trace across chat messages, tool calls, tool results, handoffs, and workflow payloads.</p>"
            + "".join(trace_rows or ["<p>No trace entries match the active filters.</p>"])
        )

    def _render_operator_snapshot(self, snapshot: dict[str, Any]) -> None:
        service_rows = [row for row in (snapshot.get("service_rows") or []) if isinstance(row, dict)]
        audit_summary = dict(snapshot.get("audit_summary") or snapshot.get("recent_item_summary") or {})
        status_counts = dict(audit_summary.get("status_counts") or {})
        audit_type_counts = dict(audit_summary.get("audit_type_counts") or {})
        action_group_counts = dict(audit_summary.get("action_group_counts") or {})
        source_counts = dict(audit_summary.get("source_counts") or {})
        validation_error_items = [str(item) for item in (snapshot.get("validation_errors") or []) if str(item)]
        validation_errors = "".join(
            f"<li>{html.escape(str(item))}</li>"
            for item in validation_error_items
        )
        status_rows_html: list[str] = []
        for row in service_rows:
            state = str(row.get("state") or "unknown").strip().lower()
            if state == "pass":
                chip_html = self._render_status_chip("pass", self.scheme["col1"])
            elif state == "not-run":
                chip_html = self._render_status_chip("not-run", "#7a6f4b")
            elif state == "fail":
                chip_html = self._render_status_chip("fail", "#b04848")
            else:
                chip_html = self._render_status_chip(state or "unknown", self.scheme["col8"])
            status_rows_html.append(
                self._render_operator_status_row(
                    str(row.get("title") or "service"),
                    chip_html,
                    str(row.get("detail") or "n/a"),
                    str(row.get("note") or ""),
                )
            )

        attention_html = "".join(
            f"<li>{html.escape(str(item))}</li>" for item in (snapshot.get("alerts") or [])[:6]
        )
        recent_actions = [item for item in (snapshot.get("recent_actions") or []) if isinstance(item, dict)]
        latest_action = recent_actions[0] if recent_actions else {}
        audit_types_text = ", ".join(f"{key}={value}" for key, value in list(audit_type_counts.items())[:4])
        action_groups_text = ", ".join(f"{key}={value}" for key, value in list(action_group_counts.items())[:4])
        sources_text = ", ".join(f"{key}={value}" for key, value in list(source_counts.items())[:3])
        self.operator_summary_view.setHtml(
            "".join(
                [
                    "<h3>Operator Status</h3>",
                    "<p>Focused view of queue health, dispatcher readiness, MCP availability, and workflow validation.</p>",
                    f"<p><b>Control-plane health:</b> {html.escape('ready' if bool(snapshot.get('healthy')) else 'attention required')} | <b>Healthy checks:</b> {int(snapshot.get('healthy_service_count') or 0)}/{int(snapshot.get('service_count') or 0)} | <b>Queue:</b> {html.escape(str(snapshot.get('queue_backend') or 'n/a'))} ({'ok' if bool(snapshot.get('queue_healthy')) else 'degraded'}) | <b>Validation issues:</b> {int(snapshot.get('validation_issue_count') or 0)} | <b>Alerts:</b> {int(snapshot.get('attention_count') or 0)}</p>",
                    f"<p><b>Recent actions:</b> {int(snapshot.get('recent_item_count') or 0)} | <b>Pass:</b> {int(status_counts.get('pass') or 0)} | <b>Fail:</b> {int(status_counts.get('fail') or 0)} | <b>Latest:</b> {html.escape(str(latest_action.get('summary') or 'n/a'))}</p>",
                    f"<p><b>Audit types:</b> {html.escape(audit_types_text or 'n/a')} | <b>Groups:</b> {html.escape(action_groups_text or 'n/a')} | <b>Sources:</b> {html.escape(sources_text or 'n/a')}</p>",
                    "<h4>Service Status</h4>",
                    f"<ul>{''.join(status_rows_html) or '<li>No operator checks projected.</li>'}</ul>",
                    "<h4>Attention</h4>",
                    f"<ul>{attention_html or '<li>No immediate operator action required.</li>'}</ul>",
                    "<h4>Validation Errors</h4>",
                    f"<ul>{validation_errors or '<li>No active workflow validation errors.</li>'}</ul>",
                ]
            )
        )

    def _populate_drilldown_selectors(self, configuration_snapshot: dict[str, Any]) -> None:
        agent_labels = [label for label in (configuration_snapshot.get("agent_labels") or []) if label]
        workflow_names = [name for name in (configuration_snapshot.get("workflow_names") or []) if name]
        self._agent_rows_by_label = dict(configuration_snapshot.get("agent_rows_by_label") or {})

        current_agent = self.agent_selector.currentText().strip()
        current_workflow = self.workflow_selector.currentText().strip()

        agent_blocker = QtCore.QSignalBlocker(self.agent_selector)
        workflow_blocker = QtCore.QSignalBlocker(self.workflow_selector)
        self.agent_selector.clear()
        self.workflow_selector.clear()
        self.agent_selector.addItems(agent_labels)
        self.workflow_selector.addItems(workflow_names)

        if current_agent and current_agent in agent_labels:
            self.agent_selector.setCurrentText(current_agent)
        elif agent_labels:
            self.agent_selector.setCurrentIndex(0)

        if current_workflow and current_workflow in workflow_names:
            self.workflow_selector.setCurrentText(current_workflow)
        elif workflow_names:
            self.workflow_selector.setCurrentIndex(0)

        del agent_blocker
        del workflow_blocker

    def _populate_trace_filter_selectors(self, monitoring_snapshot: dict[str, Any]) -> None:
        filter_options = dict(monitoring_snapshot.get("trace_filter_options") or {})
        current_agent = self.trace_agent_selector.currentText().strip()
        current_workflow = self.trace_workflow_selector.currentText().strip()
        current_tool = self.trace_tool_selector.currentText().strip()
        current_handoff = self.trace_handoff_selector.currentText().strip()

        trace_agent_options = ["All agents"] + [str(item) for item in filter_options.get("agents") or [] if str(item)]
        trace_workflow_options = ["All workflows"] + [str(item) for item in filter_options.get("workflows") or [] if str(item)]
        trace_tool_options = ["All tools"] + [str(item) for item in filter_options.get("tools") or [] if str(item)]
        trace_handoff_options = ["All handoffs", "Handoff only"] + [str(item) for item in filter_options.get("handoffs") or [] if str(item)]

        agent_blocker = QtCore.QSignalBlocker(self.trace_agent_selector)
        workflow_blocker = QtCore.QSignalBlocker(self.trace_workflow_selector)
        tool_blocker = QtCore.QSignalBlocker(self.trace_tool_selector)
        handoff_blocker = QtCore.QSignalBlocker(self.trace_handoff_selector)

        self.trace_agent_selector.clear()
        self.trace_workflow_selector.clear()
        self.trace_tool_selector.clear()
        self.trace_handoff_selector.clear()

        self.trace_agent_selector.addItems(trace_agent_options)
        self.trace_workflow_selector.addItems(trace_workflow_options)
        self.trace_tool_selector.addItems(trace_tool_options)
        self.trace_handoff_selector.addItems(trace_handoff_options)

        self.trace_agent_selector.setCurrentText(current_agent if current_agent in trace_agent_options else "All agents")
        self.trace_workflow_selector.setCurrentText(current_workflow if current_workflow in trace_workflow_options else "All workflows")
        self.trace_tool_selector.setCurrentText(current_tool if current_tool in trace_tool_options else "All tools")
        self.trace_handoff_selector.setCurrentText(current_handoff if current_handoff in trace_handoff_options else "All handoffs")

        del agent_blocker
        del workflow_blocker
        del tool_blocker
        del handoff_blocker

    def _populate_operator_filter_selectors(self, operator_snapshot: dict[str, Any]) -> None:
        filter_options = dict(operator_snapshot.get("recent_action_filters") or operator_snapshot.get("recent_item_filters") or {})
        current_status = self.operator_status_selector.currentText().strip() or str(self._operator_filter_preferences.get("status") or "")
        current_audit = self.operator_audit_selector.currentText().strip() or str(self._operator_filter_preferences.get("audit_type") or "")
        current_group = self.operator_group_selector.currentText().strip() or str(self._operator_filter_preferences.get("action_group") or "")
        current_source = self.operator_source_selector.currentText().strip() or str(self._operator_filter_preferences.get("source") or "")

        status_options = ["All statuses"] + [str(item) for item in filter_options.get("statuses") or [] if str(item)]
        audit_options = ["All action types"] + [str(item) for item in filter_options.get("audit_types") or [] if str(item)]
        group_options = ["All action groups"] + [str(item) for item in filter_options.get("action_groups") or [] if str(item)]
        source_options = ["All sources"] + [str(item) for item in filter_options.get("sources") or [] if str(item)]

        status_blocker = QtCore.QSignalBlocker(self.operator_status_selector)
        audit_blocker = QtCore.QSignalBlocker(self.operator_audit_selector)
        group_blocker = QtCore.QSignalBlocker(self.operator_group_selector)
        source_blocker = QtCore.QSignalBlocker(self.operator_source_selector)

        self.operator_status_selector.clear()
        self.operator_audit_selector.clear()
        self.operator_group_selector.clear()
        self.operator_source_selector.clear()

        self.operator_status_selector.addItems(status_options)
        self.operator_audit_selector.addItems(audit_options)
        self.operator_group_selector.addItems(group_options)
        self.operator_source_selector.addItems(source_options)

        self.operator_status_selector.setCurrentText(current_status if current_status in status_options else "All statuses")
        self.operator_audit_selector.setCurrentText(current_audit if current_audit in audit_options else "All action types")
        self.operator_group_selector.setCurrentText(current_group if current_group in group_options else "All action groups")
        self.operator_source_selector.setCurrentText(current_source if current_source in source_options else "All sources")
        self._operator_filter_preferences = self._current_operator_filter_preferences()
        self._save_operator_filter_preferences()

        del status_blocker
        del audit_blocker
        del group_blocker
        del source_blocker

    def _filtered_operator_actions(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        selected_status = self.operator_status_selector.currentText().strip()
        selected_audit = self.operator_audit_selector.currentText().strip()
        selected_group = self.operator_group_selector.currentText().strip()
        selected_source = self.operator_source_selector.currentText().strip()

        filtered_entries: list[dict[str, Any]] = []
        for action_entry in snapshot.get("recent_actions") or []:
            if not isinstance(action_entry, dict):
                continue
            action_status = str(action_entry.get("status") or "").strip()
            audit_type = str(action_entry.get("audit_type") or "").strip()
            action_group = str(action_entry.get("action_group") or "").strip()
            source = str(action_entry.get("source") or "").strip()

            if selected_status and selected_status != "All statuses" and action_status != selected_status:
                continue
            if selected_audit and selected_audit != "All action types" and audit_type != selected_audit:
                continue
            if selected_group and selected_group != "All action groups" and action_group != selected_group:
                continue
            if selected_source and selected_source != "All sources" and source != selected_source:
                continue
            filtered_entries.append(action_entry)
        return filtered_entries

    def _refresh_drilldown_views(self) -> None:
        agent_label = self.agent_selector.currentText().strip()
        workflow_name = self.workflow_selector.currentText().strip()

        agent_row = dict(self._agent_rows_by_label.get(agent_label) or {})
        mapped_workflow = str(agent_row.get("workflow_name") or "").strip()
        if mapped_workflow and mapped_workflow != "unassigned" and mapped_workflow != workflow_name:
            blocker = QtCore.QSignalBlocker(self.workflow_selector)
            self.workflow_selector.setCurrentText(mapped_workflow)
            del blocker
            workflow_name = self.workflow_selector.currentText().strip() or mapped_workflow

        agent_snapshot: dict[str, Any] | None = None
        workflow_snapshot: dict[str, Any] | None = None

        try:
            if agent_label:
                agent_snapshot = self._load_agent_drilldown_snapshot(agent_label)
                agent_snapshot["manifest"] = agent_row
            if workflow_name:
                workflow_snapshot = self._load_workflow_drilldown_snapshot(workflow_name)
            self._render_drilldown_snapshot(agent_snapshot, workflow_snapshot)
        except Exception as exc:
            error_text = html.escape(f"{type(exc).__name__}: {exc}")
            self.monitor_detail_view.setHtml(f"<h3>Drill-down unavailable</h3><p>{error_text}</p>")

    def _render_drilldown_snapshot(
        self,
        agent_snapshot: dict[str, Any] | None,
        workflow_snapshot: dict[str, Any] | None,
    ) -> None:
        agent_section = self._render_drilldown_section(
            title=f"Agent Focus: {str((agent_snapshot or {}).get('agent_label') or 'n/a')}",
            latest=(agent_snapshot or {}).get("latest"),
            items=(agent_snapshot or {}).get("items") or [],
            validation=(agent_snapshot or {}).get("validation") or {},
            error=(agent_snapshot or {}).get("error"),
            manifest=(agent_snapshot or {}).get("manifest"),
            empty_message="No workflow history for the selected agent.",
        )
        workflow_section = self._render_drilldown_section(
            title=f"Workflow Focus: {str((workflow_snapshot or {}).get('workflow_name') or 'n/a')}",
            latest=(workflow_snapshot or {}).get("latest"),
            items=(workflow_snapshot or {}).get("items") or [],
            validation=(workflow_snapshot or {}).get("validation") or {},
            error=(workflow_snapshot or {}).get("error"),
            manifest=None,
            empty_message="No workflow history for the selected workflow.",
        )
        self.monitor_detail_view.setHtml("".join([agent_section, workflow_section]))

    def _render_drilldown_section(
        self,
        *,
        title: str,
        latest: dict[str, Any] | None,
        items: list[dict[str, Any]],
        validation: dict[str, Any],
        error: Any,
        manifest: dict[str, Any] | None,
        empty_message: str,
    ) -> str:
        latest_view = self._summarize_workflow_entry(latest)
        activity = self._derive_activity_signal(latest_view)
        recovery_actions = self._derive_recovery_actions(latest_view, items, manifest, activity)
        manifest_html = ""
        if manifest:
            manifest_html = "".join(
                [
                    "<h4>Assigned Manifest</h4>",
                    "<ul>",
                    f"<li><b>Role:</b> {html.escape(str(manifest.get('role') or 'worker'))}</li>",
                    f"<li><b>Workflow:</b> {html.escape(str(manifest.get('workflow_name') or 'unassigned'))}</li>",
                    f"<li><b>Model:</b> {html.escape(str(manifest.get('model') or 'unspecified'))}</li>",
                    f"<li><b>Tools:</b> {int(manifest.get('tool_count') or 0)}</li>",
                    f"<li><b>Instance policy:</b> {html.escape(str(manifest.get('instance_policy') or 'ephemeral'))}</li>",
                    "</ul>",
                ]
            )
        latest_health_html = self._render_health_signal(latest_view, items)
        activity_html = self._render_activity_signal(activity)
        recovery_html = "".join(
            f"<li>{html.escape(str(item))}</li>" for item in recovery_actions
        )
        history_rows = "".join(
            "".join(
                [
                    f"<li><b>{html.escape(str(entry_view.get('title') or 'workflow event'))}</b> ",
                    f"{html.escape(str(entry_view.get('summary') or 'n/a'))}<br>",
                    f"<span style=\"color:{self.scheme['col8']};\">",
                    f"state={html.escape(str(entry_view.get('state') or 'n/a'))} | ",
                    f"actor={html.escape(str(entry_view.get('actor') or 'n/a'))} | ",
                    f"time={html.escape(str(entry_view.get('timestamp') or 'n/a'))}",
                    "</span></li>",
                ]
            )
            for entry_view in [self._summarize_workflow_entry(item) for item in items]
        )
        validation_errors = "".join(
            f"<li>{html.escape(str(item))}</li>"
            for item in (validation.get("errors") or [])[:5]
        )
        error_html = f"<p>{html.escape(str(error))}</p>" if error else ""
        latest_html = "".join(
            [
                f"<p><b>Latest:</b> {html.escape(str(latest_view.get('title') or 'n/a'))}<br>",
                f"{html.escape(str(latest_view.get('summary') or 'n/a'))}<br>",
                f"<span style=\"color:{self.scheme['col8']};\">state={html.escape(str(latest_view.get('state') or 'n/a'))} | workflow={html.escape(str(latest_view.get('workflow_name') or 'n/a'))} | actor={html.escape(str(latest_view.get('actor') or 'n/a'))}</span></p>",
            ]
        ) if latest else f"<p>{html.escape(empty_message)}</p>"
        return "".join(
            [
                f"<h3>{html.escape(title)}</h3>",
                error_html,
                manifest_html,
                latest_html,
                latest_health_html,
                activity_html,
                "<h4>Recent History</h4>",
                f"<ul>{history_rows or f'<li>{html.escape(empty_message)}</li>'}</ul>",
                "<h4>Recovery</h4>",
                f"<ul>{recovery_html or '<li>No immediate operator action suggested.</li>'}</ul>",
                "<h4>Validation</h4>",
                f"<p>{self._render_bool_chip(bool(validation.get('valid', True)))}</p>",
                f"<ul>{validation_errors or '<li>No validation errors reported.</li>'}</ul>",
            ]
        )

    def _summarize_workflow_entry(self, entry: dict[str, Any] | None) -> dict[str, str]:
        if not isinstance(entry, dict):
            return {}

        workflow = entry.get("workflow") if isinstance(entry.get("workflow"), dict) else {}
        snapshot_view = workflow.get("snapshot_view") if isinstance(workflow.get("snapshot_view"), dict) else {}
        snapshot = workflow.get("snapshot") if isinstance(workflow.get("snapshot"), dict) else {}
        actor = snapshot.get("actor") if isinstance(snapshot.get("actor"), dict) else {}
        event = snapshot.get("event") if isinstance(snapshot.get("event"), dict) else {}

        return {
            "title": str(snapshot_view.get("title") or workflow.get("current_state") or entry.get("event_name") or "workflow event"),
            "summary": str(snapshot_view.get("summary") or event.get("name") or workflow.get("workflow_name") or "n/a"),
            "state": str(snapshot_view.get("state") or workflow.get("current_state") or entry.get("state") or "n/a"),
            "workflow_name": str(snapshot_view.get("workflow_name") or workflow.get("workflow_name") or entry.get("workflow_name") or "n/a"),
            "actor": str(snapshot_view.get("actor_name") or actor.get("name") or entry.get("agent_label") or "n/a"),
            "timestamp": str(entry.get("timestamp") or workflow.get("updated_at") or snapshot.get("timestamp") or "n/a"),
            "retry_attempts": str((workflow.get("retry") or {}).get("attempt_count") or 0),
            "retry_remaining": str((workflow.get("retry") or {}).get("remaining_attempts") or 0),
            "retry_exhausted": str(bool((workflow.get("retry") or {}).get("exhausted"))),
        }

    def _derive_activity_signal(self, latest_view: dict[str, str]) -> dict[str, Any]:
        timestamp = self._parse_timestamp(latest_view.get("timestamp"))
        if timestamp is None:
            return {
                "last_seen": "unknown",
                "age_minutes": None,
                "escalation": "unknown",
                "chip_color": "#7a6f4b",
                "detail": "No reliable timestamp is available for this workflow focus.",
            }

        age_seconds = max((datetime.now(timezone.utc) - timestamp).total_seconds(), 0.0)
        age_minutes = int(age_seconds // 60)
        if age_minutes >= 60:
            escalation = "critical"
            chip_color = "#b04848"
        elif age_minutes >= 15:
            escalation = "elevated"
            chip_color = "#b36b2c"
        elif age_minutes >= 5:
            escalation = "watch"
            chip_color = "#7a6f4b"
        else:
            escalation = "fresh"
            chip_color = self.scheme["col1"]

        return {
            "last_seen": timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
            "age_minutes": age_minutes,
            "escalation": escalation,
            "chip_color": chip_color,
            "detail": f"Last workflow activity was {self._format_elapsed(age_seconds)} ago.",
        }

    def _render_activity_signal(self, activity: dict[str, Any]) -> str:
        age_minutes = activity.get("age_minutes")
        age_label = f"{age_minutes} min" if isinstance(age_minutes, int) else "n/a"
        return "".join(
            [
                "<h4>Activity</h4>",
                f"<p><b>Last seen:</b> {html.escape(str(activity.get('last_seen') or 'unknown'))}</p>",
                f"<p><b>Inactivity:</b> {html.escape(age_label)} | <b>Escalation:</b> {self._render_status_chip(str(activity.get('escalation') or 'unknown'), str(activity.get('chip_color') or '#7a6f4b'))}</p>",
                f"<p>{html.escape(str(activity.get('detail') or ''))}</p>",
            ]
        )

    def _derive_recovery_actions(
        self,
        latest_view: dict[str, str],
        items: list[dict[str, Any]],
        manifest: dict[str, Any] | None,
        activity: dict[str, Any],
    ) -> list[str]:
        actions: list[str] = []
        state_text = str(latest_view.get("state") or "").lower()
        summary_text = str(latest_view.get("summary") or "").lower()
        workflow_name = str((manifest or {}).get("workflow_name") or latest_view.get("workflow_name") or "workflow")
        retry_exhausted = str(latest_view.get("retry_exhausted") or "False").lower() == "true"
        retry_remaining = int(str(latest_view.get("retry_remaining") or 0) or 0)
        age_minutes = activity.get("age_minutes")

        if retry_exhausted:
            actions.append(f"Retry budget for {workflow_name} is exhausted. Re-run the originating request or raise the retry policy ceiling before restarting.")
        elif "retry" in state_text and retry_remaining > 0:
            actions.append(f"Workflow is in a retry state with {retry_remaining} attempts left. Inspect the last tool failure before forcing another run.")

        if any(token in state_text for token in ("failed", "error", "blocked")) or any(token in summary_text for token in ("failed", "error", "blocked")):
            actions.append("Latest state indicates failure or blockage. Probe queue and dispatcher first, then trigger a fresh workflow run from the originating agent.")

        if isinstance(age_minutes, int) and age_minutes >= 15:
            actions.append("Workflow focus is stale. Compare the last activity timestamp with current queue health and confirm whether the session is abandoned.")

        if manifest and str(manifest.get("workflow_name") or "") == "unassigned":
            actions.append("Selected agent is not bound to a workflow definition. Assign a workflow before expecting runtime transitions.")

        if not items:
            actions.append("No history entries are projected for this focus. Start or replay a workflow run to establish runtime evidence.")

        return actions[:4]

    def _parse_timestamp(self, value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw or raw == "n/a":
            return None
        try:
            if raw.endswith("Z"):
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            parsed = datetime.fromisoformat(raw)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _format_elapsed(self, age_seconds: float) -> str:
        if age_seconds < 60:
            return f"{int(age_seconds)}s"
        if age_seconds < 3600:
            return f"{int(age_seconds // 60)}m"
        hours = int(age_seconds // 3600)
        minutes = int((age_seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

    def _render_health_signal(self, latest_view: dict[str, str], items: list[dict[str, Any]]) -> str:
        state_text = str(latest_view.get("state") or "").lower()
        summary_text = str(latest_view.get("summary") or "")
        if not latest_view:
            return f"<p><b>Health:</b> {self._render_status_chip('cold', '#7a6f4b')}</p>"

        if any(token in state_text for token in ("fail", "error", "blocked")):
            return f"<p><b>Health:</b> {self._render_status_chip('attention', '#b04848')} {html.escape(summary_text)}</p>"

        if len(items) <= 1:
            return f"<p><b>Health:</b> {self._render_status_chip('warming', '#7a6f4b')} recent history is still sparse</p>"

        return f"<p><b>Health:</b> {self._render_status_chip('stable', self.scheme['col1'])} workflow transitions are present</p>"

    def _run_operator_health_checks(self) -> None:
        try:
            snapshot = self._load_operator_snapshot()
            self._last_snapshot["operations"] = snapshot
            self._render_operator_snapshot(snapshot)
            self._append_operator_log("Health checks refreshed.")
        except Exception as exc:
            self._append_operator_log(f"Health checks failed: {type(exc).__name__}: {exc}")

    def _probe_queue_health(self) -> None:
        try:
            try:
                if __package__:
                    from .control_plane_runtime import get_queue_health  # type: ignore
                else:
                    from alde.control_plane_runtime import get_queue_health  # type: ignore
            except ImportError as exc:
                msg = str(exc)
                if "attempted relative import" in msg or "no known parent package" in msg:
                    from control_plane_runtime import get_queue_health  # type: ignore
                else:
                    raise

            queue_backend, queue_healthy = get_queue_health()
            self._append_operator_log(
                f"Queue probe: backend={queue_backend} healthy={queue_healthy}"
            )
            operations = self._load_operator_snapshot()
            self._last_snapshot["operations"] = operations
            self._render_operator_snapshot(operations)
        except Exception as exc:
            self._append_operator_log(f"Queue probe failed: {type(exc).__name__}: {exc}")

    def _probe_dispatcher_health(self) -> None:
        try:
            try:
                if __package__:
                    from .tools import DOCUMENT_DISPATCH_SERVICE, _default_dispatcher_db_path  # type: ignore
                else:
                    from alde.tools import DOCUMENT_DISPATCH_SERVICE, _default_dispatcher_db_path  # type: ignore
            except ImportError as exc:
                msg = str(exc)
                if "attempted relative import" in msg or "no known parent package" in msg:
                    from tools import DOCUMENT_DISPATCH_SERVICE, _default_dispatcher_db_path  # type: ignore
                else:
                    raise

            dispatcher_db_path = _default_dispatcher_db_path()
            dispatcher_error = DOCUMENT_DISPATCH_SERVICE.check_dispatcher_access(
                resolved_db_path=dispatcher_db_path
            )
            operations = dict(self._last_snapshot.get("operations") or {})
            operations.update(
                {
                    "dispatcher_db_path": dispatcher_db_path,
                    "dispatcher_healthy": dispatcher_error is None,
                    "dispatcher_error": dispatcher_error,
                }
            )
            self._last_snapshot["operations"] = operations
            refreshed_operations = self._load_operator_snapshot()
            self._last_snapshot["operations"] = refreshed_operations
            self._render_operator_snapshot(refreshed_operations)
            if dispatcher_error is None:
                self._append_operator_log(f"Dispatcher probe passed: {dispatcher_db_path}")
            else:
                self._append_operator_log(f"Dispatcher probe failed: {dispatcher_error}")
        except Exception as exc:
            self._append_operator_log(f"Dispatcher probe failed: {type(exc).__name__}: {exc}")

    def _repair_dispatcher_store(self) -> None:
        try:
            result = self._repair_dispatcher_store_path()
            operations = dict(self._last_snapshot.get("operations") or {})
            operations.update(
                {
                    "dispatcher_db_path": result.get("dispatcher_db_path"),
                    "dispatcher_healthy": bool(result.get("dispatcher_healthy")),
                    "dispatcher_error": result.get("dispatcher_error"),
                }
            )
            self._last_snapshot["operations"] = operations
            refreshed_operations = self._load_operator_snapshot()
            self._last_snapshot["operations"] = refreshed_operations
            self._render_operator_snapshot(refreshed_operations)
            backup_text = f" backup={result.get('backup_path')}" if result.get("backup_path") else ""
            self._append_operator_log(f"Dispatcher repair completed:{backup_text}")
        except Exception as exc:
            self._append_operator_log(f"Dispatcher repair failed: {type(exc).__name__}: {exc}")

    def _repair_dispatcher_store_path(self, dispatcher_db_path: str | None = None) -> dict[str, Any]:
        try:
            if __package__:
                from .tools import DOCUMENT_DISPATCH_SERVICE, DOCUMENT_REPOSITORY, _default_dispatcher_db_path  # type: ignore
            else:
                from alde.tools import DOCUMENT_DISPATCH_SERVICE, DOCUMENT_REPOSITORY, _default_dispatcher_db_path  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from tools import DOCUMENT_DISPATCH_SERVICE, DOCUMENT_REPOSITORY, _default_dispatcher_db_path  # type: ignore
            else:
                raise

        resolved_path = str(dispatcher_db_path or _default_dispatcher_db_path())
        backup_path: str | None = None
        if os.path.isfile(resolved_path):
            backup_path = f"{resolved_path}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            shutil.copy2(resolved_path, backup_path)

        db = DOCUMENT_REPOSITORY.load_db(resolved_path, db_name="dispatcher_documents")
        if not isinstance(db, dict):
            db = {"schema": "dispatcher_doc_db_v1", "documents": {}}
        if not isinstance(db.get("documents"), dict):
            db["documents"] = {}
        if not str(db.get("schema") or "").strip():
            db["schema"] = "dispatcher_doc_db_v1"
        DOCUMENT_REPOSITORY.save_db(resolved_path, db, db_name="dispatcher_documents")

        dispatcher_error = DOCUMENT_DISPATCH_SERVICE.check_dispatcher_access(
            resolved_db_path=resolved_path
        )
        return {
            "dispatcher_db_path": resolved_path,
            "dispatcher_healthy": dispatcher_error is None,
            "dispatcher_error": dispatcher_error,
            "backup_path": backup_path,
        }

    def _probe_mcp_health(self) -> None:
        try:
            probe = self._run_mcp_health_probe()
            operations = dict(self._last_snapshot.get("operations") or {})
            operations["mcp_probe"] = probe
            self._last_snapshot["operations"] = operations
            refreshed_operations = self._load_operator_snapshot()
            self._last_snapshot["operations"] = refreshed_operations
            self._render_operator_snapshot(refreshed_operations)
            if probe.get("ok"):
                self._append_operator_log("MCP probe passed.")
            else:
                self._append_operator_log(
                    f"MCP probe failed: {str(probe.get('stderr') or probe.get('stdout') or 'unknown error')[:180]}"
                )
        except Exception as exc:
            self._append_operator_log(f"MCP probe failed: {type(exc).__name__}: {exc}")

    def _run_mcp_health_probe(self) -> dict[str, Any]:
        probe_path = Path(__file__).with_name("mcp_health.py")
        if not probe_path.is_file():
            return {
                "ok": False,
                "returncode": None,
                "stdout": "",
                "stderr": f"{probe_path.name} not found",
            }

        completed = subprocess.run(
            [sys.executable, str(probe_path)],
            capture_output=True,
            text=True,
            timeout=12,
            cwd=str(probe_path.parent),
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }

    def _export_runtime_snapshot_report(self) -> None:
        try:
            if __package__:
                from .control_plane_runtime import export_control_plane_snapshot  # type: ignore
            else:
                from alde.control_plane_runtime import export_control_plane_snapshot  # type: ignore
        except ImportError as exc:
            msg = str(exc)
            if "attempted relative import" in msg or "no known parent package" in msg:
                from control_plane_runtime import export_control_plane_snapshot  # type: ignore
            else:
                raise

        try:
            operations_snapshot = dict(self._last_snapshot.get("operations") or {})
            export_path = export_control_plane_snapshot(
                event_limit=80,
                trace_limit=400,
                mcp_probe=operations_snapshot.get("mcp_probe") if isinstance(operations_snapshot.get("mcp_probe"), dict) else None,
                recent_action_entries=list(self._operator_log_entries),
            )
            self._append_operator_log(f"Control-plane snapshot exported to {export_path}")
            QMessageBox.information(self, "Control-Plane Snapshot", f"Control-plane snapshot exported to:\n{export_path}")
        except Exception as exc:
            self._append_operator_log(f"Runtime export failed: {type(exc).__name__}: {exc}")
            QMessageBox.warning(self, "Control-Plane Snapshot", f"Export failed:\n{type(exc).__name__}: {exc}")

    def _append_operator_log(self, message: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        lowered_message = message.lower()
        if any(token in lowered_message for token in ("failed", "error", "missing", "unreachable", "degraded", "locked")):
            status = "fail"
        elif any(token in lowered_message for token in ("completed", "passed", "refreshed", "ready", "healthy")):
            status = "pass"
        else:
            status = "info"
        title = message.split(":", 1)[0].strip() or "operator.action"
        self._operator_log_entries.append(
            {
                "timestamp": timestamp,
                "title": title,
                "summary": message,
                "source": "desktop_operator",
                "status": status,
            }
        )
        self._operator_log_entries = self._operator_log_entries[-12:]
        try:
            operations_snapshot = self._load_operator_snapshot()
            self._last_snapshot["operations"] = operations_snapshot
            self._populate_operator_filter_selectors(operations_snapshot)
            self._render_operator_snapshot(operations_snapshot)
        except Exception:
            pass
        self._render_operator_log()

    def _render_operator_log(self) -> None:
        operations_snapshot = dict(self._last_snapshot.get("operations") or {})
        recent_actions = [item for item in (operations_snapshot.get("recent_actions") or []) if isinstance(item, dict)]
        filtered_actions = self._filtered_operator_actions(operations_snapshot) if operations_snapshot else []
        active_filter_parts = [
            f"status={self.operator_status_selector.currentText().strip() or 'All statuses'}",
            f"type={self.operator_audit_selector.currentText().strip() or 'All action types'}",
            f"group={self.operator_group_selector.currentText().strip() or 'All action groups'}",
            f"source={self.operator_source_selector.currentText().strip() or 'All sources'}",
        ]
        rows = "".join(
            "".join(
                [
                    f"<li><b>{html.escape(str(item.get('timestamp') or 'n/a'))}</b><br>",
                    f"{html.escape(str(item.get('title') or 'operator.action'))}<br>",
                    f"<span style=\"color:{self.scheme['col8']};\">{html.escape(str(item.get('summary') or ''))} | group={html.escape(str(item.get('action_group') or 'operator'))} | audit={html.escape(str(item.get('audit_type') or 'action'))} | source={html.escape(str(item.get('source') or 'desktop_operator'))} | status={html.escape(str(item.get('status') or 'info'))}</span></li>",
                ]
            )
            for item in filtered_actions
        )
        if not rows:
            if recent_actions:
                rows = "<li>No operator actions match the active filters.</li>"
            else:
                rows = "".join(
                    f"<li>{html.escape(str(item))}</li>" for item in reversed(self._operator_log_entries)
                )
        self.operator_log_view.setHtml(
            "<h3>Recent Operator Actions</h3>"
            + f"<p><b>Visible:</b> {len(filtered_actions) if recent_actions else len(self._operator_log_entries)} / <b>Total:</b> {len(recent_actions) if recent_actions else len(self._operator_log_entries)} | {' | '.join(html.escape(part) for part in active_filter_parts)}</p>"
            + (
                f"<ul>{rows}</ul>"
                if rows
                else "<p>Probe, repair, and export results appear here.</p>"
            )
        )

    def _render_status_chip(self, label: str, color: str) -> str:
        return (
            f"<span style=\"display:inline-block;padding:2px 8px;border-radius:999px;"
            f"background:{color};color:{self.scheme['col7']};font-weight:600;\">{html.escape(label)}</span>"
        )

    def _set_metric_value(self, key: str, value: Any) -> None:
        label = self._metric_labels.get(key)
        if label is not None:
            label.setText(str(value))

    def _render_bool_chip(self, value: bool) -> str:
        chip_color = self.scheme["col1"] if value else "#b04848"
        chip_text = "ready" if value else "missing"
        return (
            f"<span style=\"display:inline-block;padding:2px 8px;border-radius:999px;"
            f"background:{chip_color};color:{self.scheme['col7']};font-weight:600;\">{chip_text}</span>"
        )

class MainAIEditor(QMainWindow):
    ORG_NAME: Final = "ai.bentu"

    APP_NAME: Final = "AI-Editor"
    _SCHEMA:  Final = 2

    # ---------------------------------------------------------------- init --

    def __init__(self):
        super().__init__()
        self._accent, self._base = SCHEME_BLUE, SCHEME_DARK
        self._tab_docks: List[QDockWidget] = []          # store all tab docks

        # Crash-isolation helper: progressively enable init steps.
        # Default is "full" (999). Smaller numbers build less UI.
        try:
            init_level = int(os.getenv("AI_IDE_INIT_LEVEL", "999") or "999")
        except Exception:
            init_level = 999

        self.setWindowTitle("AI Editor – Synergetic")
        self.resize(1280, 800)
        #self.showFullScreen
        # ---- create primary widgets/layout --------------------------------
        if init_level >= 1:
            self._create_side_widgets()
        if init_level >= 2:
            self._create_central_splitters()
        else:
            # Keep a simple central widget so the window is valid.
            te = QTextEdit()
            te.setPlainText("AI_IDE_INIT_LEVEL < 2 (central UI skipped)")
            self.setCentralWidget(te)
        if init_level >= 3:
            self._create_actions()
        if init_level >= 4:
            self._create_toolbars()
        if init_level >= 5:
            self._create_menu()
        if init_level >= 6:
            self._create_status()
        if init_level >= 7:
            self._wire_vis()
        # -----------------------------------------------------------------
   
        if init_level >= 8:
            _apply_style(self, _build_scheme(self._accent, self._base))

        if init_level >= 9:
            self._load_ui_state()

        # -----------------------------------------------------------------
        # <- changes 31.07.2025

        # 1) create persistence helper
        if init_level >= 10:
            self._chat = ChatHistory()
            ChatHistory._history_ = self._chat._load()
        # 2)the chat history will be load  from disk and 
        # log to cache right after the UI is set up

        # ~> loaded = True !
        
        # ~> object = chat 
    
    # ====================== helper: remove title-bars & buttons ============

    def _strip_dock_decoration(self, dock: QDockWidget) -> None:
         """remove title-bar & buttons, give uniform bg-colour (col7)"""
         dock.setTitleBarWidget(QWidget())                       # hide bar
         dock.setFeatures(QDockWidget.NoDockWidgetFeatures)      # no btns
         dock.setStyleSheet(f"""
            background:{_build_scheme(self._accent, self._base)['col7']};
                                /* ← remove remaining frame   */
        """)

    def _editor_surface_enabled(self) -> bool:
        return _env_truthy("AI_IDE_ENABLE_EDITOR_SURFACE", "0")

    def _terminal_surface_enabled(self) -> bool:
        return _env_truthy("AI_IDE_ENABLE_TERMINAL_SURFACE", "0")

    def _configure_workspace_actions(self) -> None:
        editor_enabled = self._editor_surface_enabled()
        terminal_enabled = self._terminal_surface_enabled()

        for action in (
            self.act_new_tab,
            self.act_close_tab,
            self.act_save_tab,
            self.act_save_tab_as,
            self.act_open,
            self.act_toggle_tabdock,
            self.act_clone_tabdock,
        ):
            action.setEnabled(editor_enabled)

        self.act_toggle_console.setEnabled(terminal_enabled)
        if not editor_enabled:
            self.act_toggle_tabdock.setChecked(False)
        if not terminal_enabled:
            self.act_toggle_console.setChecked(False)
    # ================================================= seitliche Widgets ===

    def _create_side_widgets(self):

        # ---------- Explorer-Dock (multi-root) -------------------------------

        self.files_dock = QDockWidget("Explorer", self)
        self.files_dock.setObjectName("FilesDock")

        disable_explorer = _env_truthy("AI_IDE_DISABLE_EXPLORER", "0")
        if not disable_explorer:
            # Use new multi-root tree widget with toolbar
            self.explorer = JsonTreeWidgetWithToolbar()
            self.explorer.tree.setEditTriggers(
                QTreeWidget.DoubleClicked | QTreeWidget.EditKeyPressed
            )
            self.files_dock.setWidget(self.explorer)
        else:
            self.explorer = None
            self.files_dock.setWidget(QWidget())
        self._strip_dock_decoration(self.files_dock)

        # Add example workspace structure
        self._initialize_explorer_workspace()
              
        # ----------- set highlighting for QTextEdit Widget (self) ---------
        # ---------- Chat-Dock  --------------------------------------------

        disable_chat = _env_truthy("AI_IDE_DISABLE_CHAT", "0")
        if not disable_chat:
            self.chat_dock = ChatDock(self._accent, self._base, self)
        else:
            # Minimal placeholder to keep layout + settings code intact.
            self.chat_dock = QDockWidget("AI Chat", self)
            self.chat_dock.setObjectName("ChatDock")
            self.chat_dock.setTitleBarWidget(QWidget())
            self.chat_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
            self.chat_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.chat_dock.setWidget(QWidget())
        chat_widget = self.chat_dock.widget()
        if isinstance(chat_widget, AIWidget):
            placeholder_color = chat_widget.prompt_edit.palette().color(QPalette.PlaceholderText)
            if self.explorer is not None:
                # Align explorer text tone with the chat prompt placeholder
                self.explorer.set_text_color(placeholder_color)
                # Use the same background as the chat prompt (col9 from the current scheme)
                scheme = _build_scheme(self._accent, self._base)
                self.explorer.set_background_color(scheme.get("col9", "#1D1D1D"))
                # Keep explorer icons/markers in sync with the current accent
                self.explorer.set_accent_color(scheme.get("col1", "#3a5fff"))

        disable_control_plane = _env_truthy("AI_IDE_DISABLE_CONTROL_PLANE", "0")
        self.control_plane_dock = QDockWidget("Control Plane", self)
        self.control_plane_dock.setObjectName("ControlPlaneDock")
        self.control_plane_dock.setTitleBarWidget(QWidget())
        self.control_plane_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.control_plane_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        if not disable_control_plane:
            self.control_plane_widget = ControlPlaneWidget(self._accent, self._base, self)
            self.control_plane_dock.setWidget(self.control_plane_widget)
        else:
            self.control_plane_widget = None
            self.control_plane_dock.setWidget(QWidget())
        if self.control_plane_widget is not None:
            self.control_plane_widget.snapshotChanged.connect(self._update_control_plane_status)
            self.control_plane_widget.refresh_view()
    
    def _initialize_explorer_workspace(self):
        """Initialize example workspace structure in the explorer."""
        import os

        if getattr(self, "explorer", None) is None:
            return
        
        # Add current project
        project_path = os.path.dirname(os.path.abspath(__file__))
        project_name = os.path.basename(os.path.dirname(project_path))
        
        self.explorer.add_to_section("PROJECTS", project_name, {
            "path": project_path,
            "files": ["ai_ide_v1756.py", "jstree_widget.py", "chat_completion.py"],
            "type": "Python Project"
        })

    # ================================================= zentraler Splitter ==
    
    def _create_central_splitters(self):
        self._strip_dock_decoration(self.files_dock)
        self._strip_dock_decoration(self.chat_dock)
        self._strip_dock_decoration(self.control_plane_dock)
        self.main_split = QSplitter(Qt.Horizontal, self)
        self.main_split.setObjectName("mainHorizontalSplitter")
        self.main_split.setChildrenCollapsible(False)
        self.main_split.setHandleWidth(7)
        self.main_split.setOpaqueResize(True)
        self.main_split.addWidget(self.files_dock)       # links
        self.main_split.addWidget(self.chat_dock)        # mitte
        self.main_split.addWidget(self.control_plane_dock)  # rechts
        self.main_split.setStretchFactor(0, 1)
        self.main_split.setStretchFactor(1, 3)
        self.main_split.setStretchFactor(2, 2)
        self.main_split.setSizes([280, 760, 460])
        self._apply_main_splitter_style()

        self.setCentralWidget(self.main_split)

        self._create_console_dock()
        self.console_dock.hide()

    # ----------------------------------------------------------------------
    
    def _create_console_dock(self):
        """
        Creates and configures the console dock widget for the application.

        This method initializes a QDockWidget labeled "Console", sets its object name,
        creates a QTextEdit widget for displaying console output, and adds it to the dock.
        It also removes the dock's default decorations. The dock stays detached from the
        active workspace layout while the terminal surface is temporarily disabled.

        Side Effects:
            - Modifies self.console_dock and self.console_widget attributes.
        """
        self.console_dock = QDockWidget("Console", self)
        self.console_dock.setObjectName("ConsoleDock")
        self.console_widget = QTextEdit("Console temporarily disabled")
        self.console_widget.setReadOnly(True)
        self.console_dock.setWidget(self.console_widget)
        self._strip_dock_decoration(self.console_dock)

    def _apply_main_splitter_style(self) -> None:
        splitter = getattr(self, "main_split", None)
        if splitter is None:
            return

        scheme = _build_scheme(self._accent, self._base)
        handle_idle, _, _ = _splitter_handle_palette(scheme)
        handle_hover = str(scheme.get("col2") or scheme.get("col1") or "#6280ff")
        handle_pressed = str(scheme.get("col2") or scheme.get("col1") or "#6280ff")
        splitter.setStyleSheet(
            f"""
            QSplitter#mainHorizontalSplitter::handle {{
                background: {handle_idle};
                margin: 2px 0;
                border-radius: 6px;
            }}
            QSplitter#mainHorizontalSplitter::handle:hover {{
                background: {handle_hover};
            }}
            QSplitter#mainHorizontalSplitter::handle:pressed {{
                background: {handle_pressed};
            }}
            """
        )

    # ----------------------------------------------------------------------
    """ URGENTLY SET FOCUS ON DOCS AND TABS """             """TODO File operations musst be processes on focused tab & doc
                                                            def _clone_tab_dock(self, set_current: bool = False) -> None:
                                                            current content have to be reloaded at next start up, there fore using path param
                                                            and tab doc id stored in history within a massage object] """
    def _add_initial_tab_dock(self):
        self._clone_tab_dock(set_current = True)

    # ================================================= actions ============
    
    def _create_actions(self):
        """
        Creates and initializes all QAction objects used in the application's UI, including file operations,
        UI toggles, and tool actions. Sets up icons, tooltips, checkable states, and connects actions to their
        respective slots or visibility toggles. Actions include:
        - Opening and closing tabs
        - Toggling accent color
        - Showing/hiding the AI chat dock
        - Enabling/disabling greyscale mode
        - Showing/hiding the project explorer, tab dock, and console
        - Cloning the tab dock
        - Opening files and displaying the About dialog
        Also connects toggled signals to the appropriate UI components to manage their visibility.
        """
        sty = self.style()

        # ---- file / misc -------------------------------------------------
       
        self.act_new_tab = QAction(
            _icon("open_file.svg"),
            "",
            self,
            triggered=self._new_tab,
        )
        self.act_save_tab = QAction(
            _icon("save.svg"),
            "",
            self,
            triggered=self._save_current_tab,
        )
        self.act_close_tab = QAction(
            _icon("close.svg"), 
            "", self, 
            triggered = self.
            _close_tab
            )

        self.act_toggle_accent = QAction(
            _draw_circle_icon(),
            "Color Scheme", self,
            triggered = self.
            _toggle_accent
            )

        self.act_toggle_accent.setToolTip("Farbschema wechseln")

        # ---------- NEU: Chat-Toggle --------------- # <– 10.07.2025 ---------

        self.act_toggle_chat = QAction(
            _icon("chat.svg"),     # passendes Symbol im Ordner symbols/
            "Chat", self, 
            checkable = True, 
            checked = True
            )

        self.act_toggle_chat.setToolTip("AI-Chat anzeigen/ausblenden")

        self.act_toggle_control_plane = QAction(
            _icon("menu_24.svg"),
            "Control Plane",
            self,
            checkable=True,
            checked=True,
        )
        self.act_toggle_control_plane.setToolTip("Configuration- und Monitoring-Panel anzeigen/ausblenden")
        self.act_toggle_control_plane.toggled.connect(self.control_plane_dock.setVisible)

        self.act_refresh_control_plane = QAction(
            _icon("reload_.svg"),
            "Refresh Control Plane",
            self,
            triggered=self._refresh_control_plane,
        )
        self.act_refresh_control_plane.setToolTip("Control Plane aktualisieren")

        # ---------- Sichtbarkeit verknüpfen --------- # <– 10.07.2025 --------
        self.act_toggle_chat.toggled.connect(self.chat_dock.setVisible)

        # ---------- Right-Dock Toggle (for right side-toolbar) --------------
        # Uses panel-style icons instead of the chat glyph.
        self.act_toggle_right_dock = QAction(
            _icon("right_panel_close_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"),
            "Monitor",
            self,
            checkable=True,
            checked=True,
        )
        self.act_toggle_right_dock.setToolTip("Monitor anzeigen/ausblenden")
        self.act_toggle_right_dock.toggled.connect(self.control_plane_dock.setVisible)

        # Greyscale toggle ----------------------------------------------------
        self.act_grey = QAction(
            "Greyscale", self, 
            checkable=True, 
            toggled=self
            ._toggle_grey
            )

        # ---- hide or view toggles ---------------------------------------
        # toolbar shows only icons – menu still shows the descriptive text
        
        # ---- project-overview / explorer ---------------------------------
        self.act_toggle_explorer = QAction(
               _icon("explorer.svg"),
             "Explorer", self,
             checkable=True, checked=True
             )

        self.act_toggle_explorer.setToolTip("Project-Explorer anzeigen")

        # ---- tabable dock ------------------------------------------------
        self.act_toggle_tabdock = QAction(
             _icon("add_tab_dock.svg"),              # Symbols/tabs.svg
             "Tab-Dock", self,
             checkable=True, checked=True
             )
        
        # self.act_toggle_tabdock.setToolTip("Tab-Dock anzeigen")
        self.act_toggle_console = QAction(
            _icon("console.svg"),                    # Symbols/console.svg
            "Console", self,
            checkable=True, checked=False
            )
        
        self.act_toggle_console.setToolTip("Konsole anzeigen")      

        # ---- clone -------------------------------------------------------
        self.act_clone_tabdock = QAction(
            _icon("add_tab_dock.svg"), "", 
            self, triggered = self._clone_tab_dock
            )

        # ---- open / about ------------------------------------------------
        self.act_open = QAction(_icon("explorer.svg"),
            "", triggered=self
            ._open_file,
            )
        
         # ---------- SAVE / SAVE-AS ---------------------------------------------
        #  NEU  –  Speichern unter …

        self.act_save_tab = QAction(
            _icon("save_.svg"), "", self,
            shortcut="Ctrl+S",
            triggered=self._save_current_tab
        )

        self.act_save_tab.setToolTip("save")

        #  NEU  –  Speichern unter …
        self.act_save_tab_as = QAction(
            _icon("save_as_.svg"), "", self,
            shortcut="Ctrl+Shift+S",
            triggered=self._save_current_tab_as
        )

        self.act_save_tab_as.setToolTip("save as")

        self.act_about = QAction(sty.standardIcon(
                QStyle.SP_MessageBoxInformation), "",
                self, triggered = self
                ._about
                )
        # connect visibility actions
        self.act_toggle_explorer.toggled.connect(
            self.files_dock
                                     .setVisible
                                                 )
        
        self.act_toggle_tabdock.toggled.connect(
            lambda v:[ 
            d.setVisible(v) for d in self._tab_docks]
                                                )
        
        self.act_toggle_console.toggled.connect(
            self.console_dock
                                     .setVisible
                                                )
        
        self.act_clone_tabdock.triggered.connect(
            self._clone_tab_dock)

        self._configure_workspace_actions()

    # <– changes 10.07.2025
    # ================================================= toolbars ===========

    def _create_toolbars(self):
        """
        Creates and configures the main and side toolbars for the application window.
        - Initializes the top toolbar (`tb_top`) with a custom icon size (3 pixels larger than the default).
        - Adds a set of predefined actions to the top toolbar.
        - Initializes left (`tb_left`) and right (`tb_right`) vertical toolbars, applying the same icon size as the top toolbar.
        - Adds specific actions to the side toolbars and places them in the appropriate toolbar areas.
        """
        self.tb_top = QToolBar("Main", self)
        # QMainWindow.saveState/restoreState rely on unique objectName values.
        self.tb_top.setObjectName("ToolbarTop")

        """ +3 px auf die Standard-Icongröße der Toolbar addieren """

        base = self.tb_top.iconSize()                   # z. B. 24 px
        self.tb_top.setIconSize(QSize(base.width() + 3,
                                      base.height() + 3))

        self.addToolBar(Qt.TopToolBarArea, self.tb_top)
        self.tb_top.addActions([
            self.act_toggle_explorer,
            self.act_toggle_chat,
        ])

        # ---------------- seitliche Toolbars ------------------------------- 

        self.tb_left  = QToolBar(self, orientation=Qt.Vertical)
        self.tb_right = QToolBar(self, orientation=Qt.Vertical)
        self.tb_left.setObjectName("ToolbarLeft")
        self.tb_right.setObjectName("ToolbarRight")

        # auch hier die größere Icongröße übernehmen

        for bar in (self.tb_left, self.tb_right):
            bar.setIconSize(self.tb_top.iconSize())
            bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
            bar.setMovable(False)
            bar.setFloatable(False)
            bar.setStyleSheet(
                "QToolButton {"
                " min-width: 34px;"
                " min-height: 34px;"
                " padding: 0px;"
                " margin: 0px;"
                " }"
            )
            self.addToolBar(Qt.LeftToolBarArea if bar is self.tb_left
                            else Qt.RightToolBarArea, bar)

        # Left toolbar: Explorer toggle (JsonTree / project explorer dock)
        if hasattr(self, "act_toggle_explorer"):
            self.tb_left.addSeparator()
            self.tb_left.addAction(self.act_toggle_explorer)

        # Right toolbar: Agentic Control Plane toggle + refresh
        if hasattr(self, "act_toggle_control_plane"):
            self.tb_right.addSeparator()
            self.tb_right.addAction(self.act_toggle_control_plane)
        if hasattr(self, "act_refresh_control_plane"):
            self.tb_right.addAction(self.act_refresh_control_plane)

    # ─────────────────────────  menu bar  ────────────────────────────────────
    
    def _create_menu(self) -> None:
        # ------------------------------------------------------------------ ui
        mbar: QMenuBar = QMenuBar(self)               # own menu-bar instance
        self.setMenuBar(mbar)                         # make it the window bar
        # -------------- FILE ------------------------------------------------
        filem = mbar.addMenu("File")

        act_open_txt = QAction("Öffnen…", self, shortcut=QKeySequence.Open, triggered=self._file_open_text)
        act_open_enc = QAction("Öffnen mit Encoding…", self, triggered=self._file_open_with_encoding)
        act_new      = QAction("Neu", self, shortcut=QKeySequence.New, triggered=self._new_tab)
        act_save     = QAction("Speichern", self, shortcut=QKeySequence.Save, triggered=self._file_save_tab_via_tabs)
        act_save_as  = QAction("Speichern unter…", self, shortcut=QKeySequence("Ctrl+Shift+S"), triggered=self._file_save_as_tab_via_tabs)
        act_reopen   = QAction("Geschlossenen Tab wiederherstellen", self, shortcut=QKeySequence("Ctrl+Shift+T"), triggered=self._file_reopen_closed_tab)
        act_set_enc  = QAction("Encoding setzen…", self, triggered=self._file_set_encoding)
        editor_enabled = self._editor_surface_enabled()
        for action in (act_open_txt, act_open_enc, act_new, act_save, act_save_as, act_reopen, act_set_enc):
            action.setEnabled(editor_enabled)

        # Recent submenu: rebuild on show
        self._file_recent_menu = filem.addMenu("Zuletzt geöffnet")
        self._file_recent_menu.aboutToShow.connect(self._rebuild_recent_menu)

        filem.addAction(act_new)
        filem.addAction(act_open_txt)
        filem.addAction(act_open_enc)
        filem.addSeparator()
        filem.addAction(act_save)
        filem.addAction(act_save_as)
        filem.addSeparator()
        filem.addAction(act_reopen)
        filem.addAction(act_set_enc)
        # -------------- VIEW ------------------------------------------------
        view = mbar.addMenu("View")

        self.menu_visible_action = QAction("Menubar", self, 
                                           checkable = True, 
                                           checked = True,
                                           toggled = mbar
                                           .setVisible
                                           )
        # helper to insert action + separator (except after the last one)
        action_list: list = \
            [
             self.act_toggle_chat,                        # <– 10.07.2025 
             self.act_toggle_control_plane,
             self.act_toggle_explorer,
             self.act_toggle_accent,
             self.menu_visible_action,
             self.act_grey
            ]

        if self._editor_surface_enabled():
            action_list.insert(3, self.act_toggle_tabdock)
        if self._terminal_surface_enabled():
            action_list.insert(4, self.act_toggle_console)
        
        def _addActions(act: QAction, last: bool = False) -> None:
            for act in action_list:
                view.addAction(act)
                if not last:
                    view.addSeparator()
        
        _addActions(action_list) 
        
        # -------------- TOOLS ------------------------------------------------
        
        tools = mbar.addMenu("Tools")
        tools.addAction(self.act_refresh_control_plane)
        if self._editor_surface_enabled():
            tools.addSeparator()
            tools.addAction(self.act_clone_tabdock)
   
    # ================================================= status =============
    
    def _create_status(self):
        st = QStatusBar(self)
        st.showMessage("Ready")
        self._st_agents = QLabel("0 agents")
        self._st_workflows = QLabel("0 workflows")
        self._st_sessions = QLabel("0 sessions")
        self._st_runtime = QLabel("runtime n/a")
        self._st_enc = QLabel("UTF-8")
        for label in (
            self._st_agents,
            self._st_workflows,
            self._st_sessions,
            self._st_runtime,
            self._st_enc,
        ):
            label.setStyleSheet("font-size: 12px;")
        st.addPermanentWidget(self._st_agents)
        st.addPermanentWidget(self._st_workflows)
        st.addPermanentWidget(self._st_sessions)
        st.addPermanentWidget(self._st_runtime)
        # permanenter Encoding-Indikator
        st.addPermanentWidget(self._st_enc)
        self.setStatusBar(st)
        self._update_control_plane_status(getattr(getattr(self, "control_plane_widget", None), "_last_snapshot", {}))

    # ================================================= misc helpers =======
    
    def _wire_vis(self):
        self.files_dock.visibilityChanged.connect(
            self.act_toggle_explorer.setChecked
            )
        self.console_dock.visibilityChanged.connect(
            self.act_toggle_console.setChecked
            )
        self.chat_dock.visibilityChanged.connect(        #  << NEU
            self.act_toggle_chat.setChecked)
        self.control_plane_dock.visibilityChanged.connect(
            self.act_toggle_control_plane.setChecked
        )
        self.files_dock.visibilityChanged.connect(lambda _v: self._rebalance_workspace_columns())
        self.chat_dock.visibilityChanged.connect(lambda _v: self._rebalance_workspace_columns())
        self.control_plane_dock.visibilityChanged.connect(lambda _v: self._rebalance_workspace_columns())

        if hasattr(self, "act_toggle_right_dock"):
            self.control_plane_dock.visibilityChanged.connect(self.act_toggle_right_dock.setChecked)
            self.control_plane_dock.visibilityChanged.connect(self._update_right_dock_icon)
            # Initialize icon state
            self._update_right_dock_icon(self.control_plane_dock.isVisible())
        self._rebalance_workspace_columns()

    @Slot()
    def _refresh_control_plane(self) -> None:
        if getattr(self, "control_plane_widget", None) is None:
            self.statusBar().showMessage("Control Plane disabled", 2500)
            return
        self.control_plane_widget.refresh_view()
        self.statusBar().showMessage("Control Plane refreshed", 2500)

    def _update_control_plane_status(self, snapshot: dict[str, Any] | None) -> None:
        configuration_snapshot = (snapshot or {}).get("configuration") if isinstance(snapshot, dict) else {}
        monitoring_snapshot = (snapshot or {}).get("monitoring") if isinstance(snapshot, dict) else {}
        if hasattr(self, "_st_agents"):
            self._st_agents.setText(f"{int((configuration_snapshot or {}).get('agent_count') or 0)} agents")
        if hasattr(self, "_st_workflows"):
            self._st_workflows.setText(f"{int((configuration_snapshot or {}).get('workflow_count') or 0)} workflows")
        if hasattr(self, "_st_sessions"):
            self._st_sessions.setText(f"{int((monitoring_snapshot or {}).get('session_count') or 0)} sessions")
        if hasattr(self, "_st_runtime"):
            failure_count = int((monitoring_snapshot or {}).get("failure_count") or 0)
            runtime_text = "runtime healthy" if failure_count == 0 else f"{failure_count} failures"
            self._st_runtime.setText(runtime_text)

    def _update_right_dock_icon(self, visible: bool) -> None:
        """Update the right-toolbar icon depending on monitor visibility."""
        if not hasattr(self, "act_toggle_right_dock"):
            return
        self.act_toggle_right_dock.setIcon(
            _icon("right_panel_close_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg")
        )

    def _update_tabdock_toggle_state(self) -> None:
        """
        Keep the View menu toggle aligned with the actual tab-dock visibility.
        """
        act = getattr(self, "act_toggle_tabdock", None)
        if act is None:
            return
        state = bool(self._tab_docks) and all(td.isVisible() for td in self._tab_docks)
        prev = act.blockSignals(True)
        act.setChecked(state)
        act.blockSignals(prev)

    def _rebalance_workspace_columns(self) -> None:
        splitter = getattr(self, "main_split", None)
        if splitter is None:
            return

        column_specs = [
            (getattr(self, "files_dock", None), 280),
            (getattr(self, "chat_dock", None), 760),
            (getattr(self, "control_plane_dock", None), 460),
        ]
        sizes: list[int] = []
        visible_found = False
        for widget, preferred_width in column_specs:
            is_visible = bool(widget is not None and widget.isVisible())
            visible_found = visible_found or is_visible
            sizes.append(preferred_width if is_visible else 0)
        if not visible_found:
            sizes = [280, 760, 460]
        splitter.setSizes(sizes)

    # ------------------------------------------------ tab-dock clone ------

    def _clone_tab_dock(self, set_current: bool = True):
        dock_id = len(self._tab_docks) + 1
        dock = QDockWidget(f"Tab-Dock {dock_id}", self)
        dock.setObjectName(f"TabDock_{dock_id}")
        tabs = EditorTabs()
        dock.setWidget(tabs)
        # Update Status-Enc when switching tabs
        tabs.currentChanged.connect(lambda _i, s=self: s._update_status_encoding())

        self._strip_dock_decoration(dock)

        # Insert above the lower work-surface panel so tabs remain the primary focus.
        anchor = self.control_plane_dock if self.right_split.indexOf(self.control_plane_dock) >= 0 else self.console_dock
        self.right_split.insertWidget(max(0, self.right_split.indexOf(anchor)), dock)

        self._tab_docks.append(dock)
        dock.visibilityChanged.connect(
            lambda v, s=self: s._update_tabdock_toggle_state())


        if set_current:
            tabs.setCurrentIndex(0)

        # Keep the menu action in sync with the actual dock visibility.
        if hasattr(self, "act_toggle_tabdock"):
            self._update_tabdock_toggle_state()
    
    # ------------------------------------------------ Slot's -- api -------
    # ------------------------------------------------ new file tab --------
    
    @Slot()
    def _new_tab(self) -> None:
        """
        Öffnet einen neuen, noch ungespeicherten Tab im **ersten** Tab-Dock
        und setzt die benötigten run-time-Properties.
    
        – Greift sicher auf `self._tab_docks[0]` zu  
        – benutzt die korrekte Variable `idx` (statt des nicht existierenden
          Namens `index`)  
        – aktiviert den neuen Tab sofort
        """
        if not self._tab_docks:           # noch kein Tab-Dock vorhanden
            return

        tabs: EditorTabs = self._tab_docks[0].widget()

        idx = tabs.addTab(                        # Tab anlegen
            QTextEdit("# new file …"),
            f"untitled_{tabs.count() + 1}.py"
        )

        tabs.widget(idx).setProperty("file_path", "")   # wichtig für Save-Logik
        tabs.setCurrentIndex(idx)
    
        # ------------------------------------------------ close tab -----------

    @Slot()
    def _close_tab(self):
        if not self._tab_docks:
            return
        tabs: EditorTabs = self._tab_docks[0].widget()
        i = tabs.currentIndex()
        if i >= 0:tabs.removeTab(i)
    
    # ------------------------------------------------ close dock -----------

    @Slot()
    def _close_dock(self):
        """
        Sucht den umgebenden QDockWidget und schließt ihn.
        Dadurch verschwindet das komplette Tab-Dock inklusive aller Tabs.
        """
        dock = self._parent_dock()
        if dock:
            dock.close()

    # ------------------------------------------------- helper ---------------
    
    def _parent_dock(self) -> QDockWidget | None:
        w = self.parentWidget()
        while w and not isinstance(w, QDockWidget):
            w = w.parentWidget()
        return w
    
    # -------------------------------------------------file open -------------

    # <– 10.07.2025
    # ─── RE-WRITE of MainAIEditor._open_file() ────────────────────────────────
    #   (old implementation is replaced completely)


    @Slot()
    def _save_current_tab(self) -> None:
        """
        Speichert den Inhalt des aktiven Tabs.
        Existiert noch kein Dateiname, wird automatisch »Speichern unter …«
        ausgeführt.
        """
        if not self._tab_docks:
            return

        tabs: EditorTabs = self._tab_docks[0].widget()
        idx               = tabs.currentIndex()
        if idx < 0:
            return

        widget = tabs.widget(idx)
        if not isinstance(widget, (QPlainTextEdit, QTextEdit)):
            QMessageBox.information(self, "Info",
                                    "Dieser Tab enthält keine editierbare Textdatei.")
            return

        path: str = widget.property("file_path") or ""
        if not path:
            # Kein Pfad vorhanden  →  gleich Speichern unter …
            self._save_current_tab_as()
            return

        try:
            Path(path).write_text(widget.toPlainText(), encoding="utf-8")
        except Exception as exc:          # noqa: BLE001
            QMessageBox.critical(self, "Fehler", str(exc))
            return

        self.statusBar().showMessage(f"{path} gespeichert", 3000)

    # ---------------------------------------------------------------------------
    @Slot()
    def _save_current_tab_as(self) -> None:
        """
        Öffnet immer den Dateidialog „Speichern unter …“, schreibt den Inhalt
        und aktualisiert Tab-Titel & file_path-Property.
        """
        if not self._tab_docks:
            return

        tabs: EditorTabs = self._tab_docks[0].widget()
        idx               = tabs.currentIndex()
        if idx < 0:
            return

        widget = tabs.widget(idx)
        if not isinstance(widget, (QPlainTextEdit, QTextEdit)):
            QMessageBox.information(self, "Info",
                                    "Dieser Tab enthält keine editierbare Textdatei.")
            return

        fname, _ = QFileDialog.getSaveFileName(
            self, "Speichern unter …", str(Path.home()),
            "Textdateien (*.txt *.md *.py);;Alle Dateien (*)"
        )
        if not fname:
            return

        try:
            Path(fname).write_text(widget.toPlainText(), encoding="utf-8")
        except Exception as exc:          # noqa: BLE001
            QMessageBox.critical(self, "Fehler", str(exc))
            return

        widget.setProperty("file_path", fname)
        tabs.setTabText(idx, Path(fname).name)
        self.statusBar().showMessage(f"{fname} gespeichert", 3000)


    @Slot()
    def _get_focused_tab_dock(self) -> EditorTabs | None:
        """Findet das aktuell fokussierte TabDock oder gibt das erste zurück."""
        # Versuche das fokussierte Widget zu finden
        focused = QApplication.focusWidget()
        
        # Gehe den Widget-Baum hoch und suche nach EditorTabs
        current = focused
        while current:
            if isinstance(current, EditorTabs):
                return current
            current = current.parentWidget()
        
        # Fallback: Suche nach dem Dock, das sichtbar und aktiv ist
        for dock in self._tab_docks:
            if dock.isVisible() and not dock.isFloating():
                tabs = dock.widget()
                if isinstance(tabs, EditorTabs):
                    return tabs
        
        # Letzter Fallback: erstes Dock
        if self._tab_docks:
            return self._tab_docks[0].widget()
        
        return None

    # -------------------- File menu wrappers for EditorTabs --------------
    @Slot()
    def _file_open_text(self) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._open_file_dialog()
            self._update_status_encoding()

    @Slot()
    def _file_open_with_encoding(self) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._open_file_dialog_with_encoding()
            self._update_status_encoding()

    @Slot()
    def _file_save_tab_via_tabs(self) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._save_current_tab()
            self._update_status_encoding()

    @Slot()
    def _file_save_as_tab_via_tabs(self) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._save_current_tab_as()
            self._update_status_encoding()

    @Slot()
    def _file_reopen_closed_tab(self) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._reopen_closed_tab()
            self._update_status_encoding()

    @Slot()
    def _file_set_encoding(self) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._set_current_tab_encoding()
            self._update_status_encoding()

    def _rebuild_recent_menu(self) -> None:
        if not hasattr(self, "_file_recent_menu"):
            return
        m = self._file_recent_menu
        m.clear()
        # Read the same QSettings key used by EditorTabs
        try:
            s = QSettings()
            arr = s.value("EditorTabs/RecentFiles", [])
            paths = [str(x) for x in arr] if isinstance(arr, list) else []
        except Exception:
            paths = []
        if not paths:
            dummy = QAction("(leer)", self)
            dummy.setEnabled(False)
            m.addAction(dummy)
            return
        for p in paths:
            act = QAction(str(Path(p).name), self)
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, path=p: self._file_open_recent(path))
            m.addAction(act)

    def _file_open_recent(self, path: str) -> None:
        tabs = self._get_focused_tab_dock()
        if tabs is not None:
            tabs._open_recent(path)
            self._update_status_encoding()

    def _update_status_encoding(self) -> None:
        tabs = self._get_focused_tab_dock()
        enc_text = ""
        if tabs is not None and isinstance(tabs, QTabWidget):
            idx = tabs.currentIndex()
            if idx >= 0:
                w = tabs.widget(idx)
                enc = getattr(w, 'property', lambda _k: None)("file_encoding") if hasattr(w, 'property') else None
                if not enc:
                    enc = "utf-8"
                dirty = "*" if hasattr(w, 'document') and w.document() and w.document().isModified() else ""
                enc_text = f"{dirty}{enc.upper()}"
        if hasattr(self, '_st_enc'):
            self._st_enc.setText(enc_text or "UTF-8")

    def _open_path_in_focused_tab(self, path: Path, *, title: str | None = None) -> None:
        """Open an existing file path in the currently focused tab dock."""
        if not isinstance(path, Path):
            path = Path(str(path))
        if not path.exists():
            QMessageBox.warning(self, "Fehler", f"Datei nicht gefunden: {path}")
            return

        if _fv_classify is None:
            self._open_file_fallback(str(path))
            return

        ftype = _fv_classify(path)
        try:
            if ftype == "image":
                widget = _FVImageWidget(path)
            elif ftype == "pdf":
                widget = _FVPdfWidget(path)
            elif ftype == "markdown":
                widget = _FVMarkdownWidget(path)
            elif ftype in ("text", "code"):
                widget = _FVTextWidget(path, highlight=(ftype == "code"))
            else:
                raise RuntimeError("Dieser Dateityp wird nicht unterstützt.")
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))
            return

        tabs = self._get_focused_tab_dock()
        if not tabs:
            QMessageBox.warning(self, "Fehler", "Kein Tab-Dock verfügbar")
            return

        tab_title = title or path.name
        idx = tabs.addTab(widget, tab_title)
        widget.setProperty("file_path", str(path))
        tabs.setCurrentIndex(idx)
        self._update_status_encoding()

    def _open_file(self) -> None:

        """Open a file and display it inside the **focused** tab-dock.

        The heavy-lifting – i.e. figuring out *how* the file should be
        presented (text editor, image label, PDF view, …) – is delegated to
        the external :pymod:`file_viewer` helper module.  This keeps the
        MainAIEditor lean while giving us a single, well-tested
        implementation to render a broad set of file types.
        """

        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Open file",
            str(Path.home()),
            "All files (*)",
        )
        if not fname:
            return

        if _fv_classify is None:

            # file_viewer could not be imported at start-up → fall back to the
            # previous minimal implementation and support only text/images.
            # The original logic has been moved into a helper so that the
            # overall user-experience is preserved even without file_viewer.
            
            self._open_file_fallback(fname)
            return

        path = Path(fname)
        ftype = _fv_classify(path)

        try:
            if ftype == "image":
                widget = _FVImageWidget(path)
            elif ftype == "pdf":
                widget = _FVPdfWidget(path)
            elif ftype == "markdown":           
                widget = _FVMarkdownWidget(path)
            elif ftype in ("text", "code"):
                widget = _FVTextWidget(path, highlight=(ftype == "code"))
            else:
                raise RuntimeError("Dieser Dateityp wird nicht unterstützt.")
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))
            return

        # Öffne im fokussierten Dock statt immer im ersten
        tabs = self._get_focused_tab_dock()
        if not tabs:
            QMessageBox.warning(self, "Fehler", "Kein Tab-Dock verfügbar")
            return
            
        idx = tabs.addTab(widget, path.name)
        widget.setProperty("file_path", str(path))
        tabs.setCurrentIndex(idx)
        self._update_status_encoding()

    # -------------------- legacy fallback (text / images only) ------------
    
    def _open_file_fallback(self, fname: str) -> None:  # pragma: no cover
        """Original, reduced implementation – kept as safety-net."""
        file_kind = detect_file_format(fname)

        # Öffne im fokussierten Dock
        tabs = self._get_focused_tab_dock()
        if not tabs:
            QMessageBox.warning(self, "Error", "Kein Tab-Dock verfügbar")
            return

        if file_kind == "text":
            try:
                txt = Path(fname).read_text(encoding="utf-8")
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Cannot read file:\n{e}")
                return
            idx = tabs.addTab(QTextEdit(txt), Path(fname).name)
            tabs.widget(idx).setProperty("file_path", fname)
        elif file_kind == "image":
            pix = QPixmap(fname)
            if pix.isNull():
                QMessageBox.warning(self, "Error", "Unable to load the selected image.")
                return
            lbl = QLabel(alignment=Qt.AlignCenter)
            lbl.setPixmap(pix.scaledToWidth(512, Qt.SmoothTransformation))
            idx = tabs.addTab(lbl, Path(fname).name)
        else:
            QMessageBox.information(
                self,
                "Unsupported type",           
                "This file type cannot be displayed inside the editor.",
            )
            return

        tabs.setCurrentIndex(idx)
        self._update_status_encoding()


    # ------------------------------------------------ about --------------

    @Slot()
    def _about(self):
        QMessageBox.information(
            self, "About",
            "AI Python3 Multi-Agent-Env v0.6\n"            

            "Fully refactored layout – © ai.bentu\nPowered by Qt / PySide6"
        )

    # ------------------------------------------------ view ---------------

    @Slot()
    def _toggle_accent(self):
        self._accent = SCHEME_GREEN if self._accent is SCHEME_BLUE else SCHEME_BLUE
        _apply_style(self, _build_scheme(self._accent, self._base))
        self._apply_main_splitter_style()
        self._sync_explorer_scheme()
        self._sync_control_plane_scheme()

    @Slot(bool)
    def _toggle_grey(self, on: bool):
        self._base = SCHEME_GREY if on else SCHEME_DARK
        _apply_style(self, _build_scheme(self._accent, self._base))
        self._apply_main_splitter_style()
        self._sync_explorer_scheme()
        self._sync_control_plane_scheme()

    def _sync_explorer_scheme(self) -> None:
        """Keep explorer colors/icons synced after scheme changes."""
        try:
            if not hasattr(self, "explorer") or self.explorer is None:
                return
            scheme = _build_scheme(self._accent, self._base)
            self.explorer.set_background_color(scheme.get("col9", "#1D1D1D"))
            self.explorer.set_accent_color(scheme.get("col1", "#3a5fff"))
        except Exception:
            pass

    def _sync_control_plane_scheme(self) -> None:
        try:
            if getattr(self, "control_plane_widget", None) is None:
                return
            self.control_plane_widget.update_scheme(self._accent, self._base)
        except Exception:
            pass

    # ──────────────────────── Persistence-Helpers ───────────────────────

    def _settings(self) -> QSettings:  # >>>
        s = QSettings(MainAIEditor.ORG_NAME, MainAIEditor.APP_NAME)
        s.setFallbacksEnabled(False)   # keine systemweiten Defaults
        return s

    # ---------------------------------------------------------------- load

    def _load_ui_state(self):          # >>>
        s = self._settings()
        if s.value("schema", 0, int) != self._SCHEMA:
            return                     # erste Ausführung oder inkompatibel

        g  = s.value("geometry", type=QByteArray)
        st = s.value("state",    type=QByteArray)
        disable_qt_state = os.getenv("AI_IDE_DISABLE_QT_STATE", "0").strip() in {"1", "true", "True"}
        if (not disable_qt_state) and g and st:
            self.restoreGeometry(g)
            self.restoreState(st)

        # eigene Felder ---------------------------------------------------

        self._accent = SCHEME_GREEN if s.value("accent") == "green" else SCHEME_BLUE
        self._base   = SCHEME_GREY  if s.value("base")   == "grey"  else SCHEME_DARK
        _apply_style(self, _build_scheme(self._accent, self._base))
        self._apply_main_splitter_style()
        self._sync_explorer_scheme()
        
        self.chat_dock.setVisible(s.value("showChat", True,  bool))
        self.control_plane_dock.setVisible(s.value("showControlPlane", True, bool))

        
        self.files_dock.setVisible(s.value("showExplorer", True,  bool))
        self.console_dock.setVisible(False)
        tab_on = False
        for d in self._tab_docks:
            d.setVisible(False)

        # Tabs rekonstruieren (optional)

        opened = s.value("openTabs", [])
        if self._editor_surface_enabled() and opened:
            self._tab_docks.clear()
            self._clone_tab_dock(set_current=False)
            tabs: EditorTabs = self._tab_docks[0].widget()
            tabs.clear()
            for name in opened:
                tabs.addTab(QTextEdit(f"# {name}\n"), name)
            tabs.setCurrentIndex(0)

    # ---------------------------------------------------------------- save
    
    def _save_ui_state(self):         
        s = self._settings()
        s.clear()                      # sauberer Neu-Write
        s.setValue("schema",   self._SCHEMA)
        # Workaround: on some Qt/PySide6 combinations, saveGeometry/saveState
        # can crash (native segfault) during shutdown. Allow disabling.
        disable_qt_state = os.getenv("AI_IDE_DISABLE_QT_STATE", "0").strip() in {"1", "true", "True"}
        if not disable_qt_state:
            s.setValue("geometry", self.saveGeometry())
            s.setValue("state",    self.saveState())

        s.setValue("accent", "green" if self._accent is SCHEME_GREEN else "blue")
        s.setValue("base",   "grey"  if self._base   is SCHEME_GREY  else "dark")
        s.setValue("showExplorer", self.files_dock.isVisible())
        s.setValue("showConsole",  False)
        s.setValue("showChat", self.chat_dock.isVisible())   
        s.setValue("showControlPlane", self.control_plane_dock.isVisible())
        s.setValue("showTabDock",  False)

        if self._editor_surface_enabled() and self._tab_docks:
            tabs: EditorTabs = self._tab_docks[0].widget()
            s.setValue("openTabs", [tabs.tabText(i) for i in range(tabs.count())])
        else:
            s.setValue("openTabs", [])

        # Force write to disk (helps if the process crashes later).
        try:
            s.sync()
        except Exception:
            pass

    # -- <- changes 27.07.2025 ------------------------------------- closeEvent

    def closeEvent(self, ev):        # >>>
        # 1) save chat history to disk
        try:
            if hasattr(self, "_chat"):
                _maybe_flush_history(self._chat)
        except Exception:
            pass

        # 2) save the (unrelated) UI state
        try:
            self._save_ui_state()
        except Exception:
            pass

        try:
            _shutdown_loky_runtime()
        except Exception:
            pass

        super().closeEvent(ev)
    
# ═════════════════════════════  main()  ════════════════════════════════════

def _install_crash_logging(log_path: str) -> None:
    try:
        import faulthandler
        lf = open(log_path, "a", buffering=1)
        faulthandler.enable(file=lf)  # dump Python stack on segfault
        def _qt_handler(msg_type, context, message):  # type: ignore
            try:
                lf.write(f"[QT] {message}\n")
            except Exception:
                pass
        try:
            QtCore.qInstallMessageHandler(_qt_handler)
        except Exception:
            pass
        def _excepthook(exc_type, exc, tb):
            import traceback
            traceback.print_exception(exc_type, exc, tb, file=lf)
        sys.excepthook = _excepthook
    except Exception:
        pass


def main() -> None:
    # Diagnostics: enable when AI_IDE_SAFE or AI_IDE_QT_DEBUG env vars are set
    # Keep crash logs inside the workspace by default so they're easy to find.
    # You can override the directory via AI_IDE_CRASH_LOG_DIR.
    crash_dir_env = os.getenv("AI_IDE_CRASH_LOG_DIR", "").strip()
    crash_dir = Path(crash_dir_env).expanduser() if crash_dir_env else (Path(__file__).resolve().parent / "AppData")
    crash_dir.mkdir(parents=True, exist_ok=True)
    crash_log = str(crash_dir / "qt_crash.log")
    _install_crash_logging(crash_log)
    if os.getenv("AI_IDE_QT_DEBUG", "0") == "1":
        os.environ.setdefault("QT_DEBUG_PLUGINS", "1")

    safe = os.getenv("AI_IDE_SAFE", "0") == "1"
    minimal = os.getenv("AI_IDE_MINIMAL", "0") == "1"

    # ------------------------------------------------------------------
    # Headless/CI helper: run one prompt through the same ChatCom wrapper
    # and tool-calling loop the GUI uses (AIWidget._send -> ChatCom.get_response).
    # This avoids starting a Qt event loop and is safe for terminal testing.
    #
    # Usage:
    #   AI_IDE_ONE_SHOT_PROMPT='@_data_dispatcher ...' python alde/ai_ide_v1756.py
    # ------------------------------------------------------------------
    one_shot = os.getenv("AI_IDE_ONE_SHOT_PROMPT", "").strip()
    if one_shot:
        try:
            # Import locally to keep Qt startup out of the path.
            try:
                from .agents_ccompletion import ChatCom  # type: ignore
            except Exception:
                from agents_ccompletion import ChatCom  # type: ignore

            model_name = os.getenv("AI_IDE_MODEL", "").strip() or "gpt-4.1-mini-2025-04-14"
            reply = ChatCom(_model=model_name, _input_text=one_shot).get_response()
            print(str(reply))
        except Exception as exc:
            print(f"[ONE_SHOT_ERROR] {exc}")
            raise
        finally:
            # One-shot mode returns before Qt hooks (closeEvent/aboutToQuit)
            # have a chance to persist chat history.
            try:
                _maybe_flush_history()
            except Exception:
                pass
            try:
                _shutdown_loky_runtime()
            except Exception:
                pass
        return

    app = QApplication(sys.argv)

    # Persist chat history on clean shutdown even if MainAIEditor.closeEvent
    # is not reached (e.g. alternative quit paths).
    # History flush during Qt shutdown can segfault in some environments.
    # Keep it opt-in via AI_IDE_ENABLE_HISTORY_FLUSH_ON_QUIT=1.
    if _env_truthy("AI_IDE_ENABLE_HISTORY_FLUSH_ON_QUIT", "0"):
        try:
            # Wrap in a lambda so PySide doesn't have to bind a classmethod directly.
            app.aboutToQuit.connect(lambda: _maybe_flush_history())
        except Exception:
            pass
    try:
        app.aboutToQuit.connect(_shutdown_loky_runtime)
    except Exception:
        pass

    # Remove system/Qt drop shadows on context menus and ensure true rounded corners
    # (otherwise a dark rectangle can remain visible behind the radius).
    def _install_menu_no_shadow(qapp: QApplication) -> None:
        from PySide6.QtCore import QObject, QEvent
        from PySide6.QtWidgets import QMenu

        class _MenuShadowFilter(QObject):
            def eventFilter(self, obj, event):  # noqa: N802
                try:
                    if isinstance(obj, QMenu) and event.type() in (QEvent.Polish, QEvent.Show):
                        obj.setWindowFlag(Qt.NoDropShadowWindowHint, True)
                        obj.setAttribute(Qt.WA_TranslucentBackground, True)
                        obj.setAttribute(Qt.WA_StyledBackground, True)
                        obj.setAutoFillBackground(False)
                except Exception:
                    pass
                return super().eventFilter(obj, event)

        filt = _MenuShadowFilter(qapp)
        qapp.installEventFilter(filt)
        # keep reference alive
        setattr(qapp, "_menu_shadow_filter", filt)

    _install_menu_no_shadow(app)

    # Crash-isolation helper: allow automated runs that start and quit quickly
    # (useful with QT_QPA_PLATFORM=offscreen).
    try:
        autoquit_ms = int(os.getenv("AI_IDE_AUTOQUIT_MS", "0") or "0")
    except Exception:
        autoquit_ms = 0
    if autoquit_ms > 0:
        try:
            QtCore.QTimer.singleShot(autoquit_ms, app.quit)
        except Exception:
            pass

    if minimal:
        mini = QMainWindow()
        mini.setWindowTitle("AI IDE – Minimal Mode")
        te = QTextEdit()
        te.setPlainText("Minimal mode active. Use normal mode to reproduce crashes.\n\nEnv flags:\n- AI_IDE_SAFE=1\n- AI_IDE_NO_STYLE=1\n- AI_IDE_QT_DEBUG=1")
        mini.setCentralWidget(te)
        mini.resize(800, 500)
        mini.show()
        try:
            exit_code = app.exec()
        finally:
            _shutdown_loky_runtime()
        sys.exit(exit_code)

    win = MainAIEditor()
    if safe:
        try:
            # Minimal safe tweaks: hide heavy docks by default
            if hasattr(win, "console_dock"):
                win.console_dock.hide()
            if hasattr(win, "chat_dock"):
                win.chat_dock.hide()
        except Exception:
            pass
    win.show()
    try:
        exit_code = app.exec()
    finally:
        _shutdown_loky_runtime()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()

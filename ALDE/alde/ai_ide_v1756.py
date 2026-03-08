from __future__ import annotations    ## ai_ide_v1756.py

# Maintainer contact: see repository README.

import PySide6
import os
import sys
import base64
import binascii
import uuid
from datetime import datetime

# If this file is executed directly (e.g. `python alde/ai_ide_v1756.py`),
# Python sets sys.path[0] to the package directory, which can break
# absolute imports like `import alde.<module>`.
if not __package__:
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    # Make top-level package imports work too (ALDE.*)
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
from typing import Final, List, Optional
from io import BytesIO
import mimetypes


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
        # fix missing padding
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
    QFileDialog,
    QInputDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    
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
        from .chat_completion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore
    else:
        from alde.chat_completion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from chat_completion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore  # noqa: E402
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
    background: {col9};
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
        self.chat_view = ChatWindow()

        # 2)  Prompt-Editor  (Drag-&-Drop + Multiline)
        self.prompt_edit = FileDropTextEdit(               # neu: nur EIN Editor
            placeholderText="Prompt …",
            objectName="aiInput"       )
        self.prompt_edit.setAttribute(Qt.WA_StyledBackground, True)
        self.prompt_edit.setMinimumHeight(110)

        # 3) Splitter  ▌ ChatHistory ▌ Prompt ▌
        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(self.chat_view)
        splitter.addWidget(self.prompt_edit)
        splitter.setSizes([400, 140]) # Anfangsgröße

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
                self._dropped_files = paths
                self.prompt_edit.append(f'{paths}')
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
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            return

        url = self._dropped_files[:] 
        self._append("You", prompt)
        self.prompt_edit.clear()
        
        try:
            reply = ChatCom(
                _model=self._model,
                _url=url,
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
        if not (prompt and self._dropped_files):
            QMessageBox.warning(self, "Info",
                "Ziehe ein Bild in das Chat-Fenster und gib anschließend deinen Prompt ein.")
            return

        self._append("You", prompt)
        self.prompt_edit.clear()
        url = self._dropped_files[0]

        try:
            resp = ImageDescription(
                _model="gpt-image-1-mini",
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
                _model="gpt-image-1-mini",
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
#  2)  NEUER  CodeViewer  –  richtiges Highlighting, flexible Größe
# ───
# -----------------------------------------------------------------
class CodeViewer(QPlainTextEdit,QSHighlighter):
    """
    Read-only Code-Viewer ohne eigene Scrollbars.
    Höhe = Zeilenanzahl  ×  Zeilenhöhe  (+ Padding)
    """
    _PADDING = 12          # px  – ober/unter­halb des Codes

    def __init__(self, code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        QSHighlighter(self.document())

        # Keine Scrollbars innerhalb des Widgets
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setPlainText(code.rstrip("\n"))
        self.setStyleSheet(
            "background:#111; color:#DDD; padding:12px; border-radius:8px;"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._autofit()

    # ----------------------------------------------------------------
    # Höhe bei jeder Größen­änderung nachstellen
    def resizeEvent(self, ev):                         # noqa: N802
        super().resizeEvent(ev)
        QTimer.singleShot(0, self._autofit)

    # ----------------------------------------------------------------
    def _autofit(self) -> None:
        line_h = QFontMetrics(self.font()).height()
        line_h = max(18, line_h)          # Mindesthöhe
        # Höhe am Inhalt ausrichten, aber mind. 2 Zeilen
        lines  = max(2, self.blockCount())
        self.setFixedHeight(lines * line_h + self._PADDING)

# -----------------------------------------------------------------
class MsgWidget(QWidget):
    """
    Chat-Bubble im iMessage/WhatsApp-Stil:
    • AI-Nachrichten: grau, linksbündig
    • User-Nachrichten: blau, rechtsbündig
    • max-width 65% für Bubble-Effekt
    • abgerundete Ecken mit Schatten
    """

    def __init__(self, who: str,
                 segments: list[tuple[str, str]],
                 parent: QWidget | None = None):
        super().__init__(parent)
        
        # Transparenter Hintergrund für äußeren Container
        self.setStyleSheet("MsgWidget { background: transparent; }")

        # Haupt-Layout (horizontal für Links/Rechts-Ausrichtung)
        h_layout = QHBoxLayout(self)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.setSpacing(0)

        # Bubble-Container (begrenzte Breite auf 90% der Gesamtbreite)
        bubble = QWidget()
        bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._bubble = bubble
        
        v_layout = QVBoxLayout(bubble)
        v_layout.setContentsMargins(14, 10, 14, 10)
        v_layout.setSpacing(6)

        # Styling & Ausrichtung je nach Sender
        from PySide6.QtWidgets import QLabel
        if who == "AI":
            bubble.setStyleSheet("""
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
            """)
            # Username klein links
            username_label = QLabel(f"<small style='opacity:0.6; color:#e0e0e0;'>{who}</small>")
            v_layout.addWidget(username_label, 0, Qt.AlignLeft)
            h_layout.addWidget(bubble, 95)  # 95% Stretch
            h_layout.addStretch(5)  # 5% rechts frei
        else:  # "You"
            bubble.setStyleSheet("""
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
            """)
            # Username klein rechts
            username_label = QLabel(f"<small style='opacity:0.6; color:#e0e0e0;'>{who}</small>")
            v_layout.addWidget(username_label, 0, Qt.AlignRight)
            h_layout.addStretch(5)  # 5% links frei
            h_layout.addWidget(bubble, 95)  # 95% Stretch

        # Segmente rendern (Code + Text)
        import re, shutil
        for kind, block in segments:
            block = block.strip()
            if not block:
                continue
            if kind == "code":
                code_viewer = CodeViewer(block, bubble)
                v_layout.addWidget(code_viewer)
            else:

                # Detect image markers: either markdown ![alt](path) or
                # a literal line starting with "[IMAGE] <path>"
                first = block.splitlines()[0].strip()
                m = re.match(r'!\[.*?\]\((.*?)\)', first)
                if first.startswith("[IMAGE]") or m:
                    path_str = None
                    if first.startswith("[IMAGE]"):
                        parts = first.split(None, 1)
                        if len(parts) > 1:
                            path_str = parts[1].strip()
                    elif m:
                        path_str = m.group(1)

                    if path_str:
                        try:
                            p = Path(path_str)
                        except Exception:
                            p = None

                        if p and p.exists():
                            # Controls row (buttons similar to JsonTree toolbar)
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

                            # Image viewer (prefer ZoomImageWidget)
                            img_widget = None
                            # In chat bubbles, prefer a compact auto-fit preview.
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
                                # fallback: simple QLabel
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

                                # Button actions
                                def _on_save():
                                    fname, _ = QFileDialog.getSaveFileName(self, "Save image as", str(Path.home()))
                                    if fname:
                                        try:
                                            shutil.copy(str(p), fname)
                                            QMessageBox.information(self, "Saved", f"Saved to {fname}")
                                        except Exception as exc:
                                            QMessageBox.critical(self, "Error", str(exc))

                                def _on_export():
                                    # open in focused tab dock
                                    win = self.window()
                                    opener = getattr(win, "_open_path_in_focused_tab", None)
                                    if callable(opener):
                                        opener(p, title=p.name)
                                    else:
                                        QMessageBox.information(self, "Info", "No tab-dock available to export image")

                                save_btn.clicked.connect(_on_save)
                                export_btn.clicked.connect(_on_export)
                                # done with image handling – continue to next segment
                                continue

                # Regular text / markdown fallback
                br = QTextBrowser(bubble)
                br.setFrameShape(QFrame.NoFrame)
                br.setOpenExternalLinks(True)
                br.setMarkdown(block)

                # möglichst "tight": keine Dokument-Margins
                br.document().setDocumentMargin(0)

                # Transparenter Hintergrund für Text
                br.setStyleSheet("QTextBrowser { background: transparent; color: #e0e0e0; }")

                # Scrollbars unterbinden
                br.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                br.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

                # Automatische Höhe (strict am Inhalt, min. 2 Zeilen)
                br.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._fit_browser(br)
                v_layout.addWidget(br)
                
                # Verzögerte Höhenanpassung nach Layout-Pass
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda b=br: self._fit_browser(b))

                # Bei Reflow (z.B. Zeilenumbruch) erneut fitten
                try:
                    br.document().documentLayout().documentSizeChanged.connect(
                        lambda _sz, b=br: self._fit_browser(b)
                    )
                except Exception:
                    pass

        # Kein Extra-Spacer, sonst wird die Bubble künstlich höher
        v_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed))

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        # Clamp bubble width for a chat-like layout and to keep images readable.
        try:
            max_w = int(self.width() * 0.95)
            if max_w > 0 and hasattr(self, "_bubble") and self._bubble is not None:
                self._bubble.setMaximumWidth(max_w)
        except Exception:
            pass

    # ----------------------------------------------------------------
    def _fit_browser(self, br: QTextBrowser) -> None:
        """
        Passt die Höhe des QTextBrowser an (am Inhalt, min. 2 Zeilen).
        """
        from PySide6.QtGui import QFontMetrics
        doc = br.document()

        # Textbreite an Viewport anpassen, damit doc.size().height() korrekt ist
        w = max(1, br.viewport().width())
        doc.setTextWidth(w)

        h_doc = int(doc.size().height()) + 2
        font_h = QFontMetrics(br.font()).height()
        h_min = max(3,3 * font_h)

        br.setFixedHeight(max(h_doc, h_min))


# -----------------------------------------------------------------
class ChatWindow(QWidget):
    """
    Container für den kompletten Chat-Verlauf.
    Jede Nachricht ist ein MsgWidget.  
    Nur dieser Bereich besitzt Scrollbars.
    """
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QScrollArea
        self.scroller = QScrollArea(self)
        self.scroller.setWidgetResizable(True)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroller, 1)

        # Nachricht-Viewport
        self.viewport = QWidget()
        self.vlayout  = QVBoxLayout(self.viewport)
        self.vlayout.setAlignment(Qt.AlignTop)
        self.scroller.setWidget(self.viewport)

    # ----------------------------------------------------------------
    def add_message(self, who: str, text: str):
        msg = MsgWidget(who, self._split_segments(text), self.viewport)
        self.vlayout.addWidget(msg)

        # nach unten scrollen
        bar = self.scroller.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ----------------------------------------------------------------
    @staticmethod
    def _split_segments(raw: str) -> list[tuple[str, str]]:
        """
        Zerlegt den Roh-Text in («text» | «code» , Block)-Paare anhand
        von ```-Fenced Code Blocks.
        """
        out, buf, mode = [], [], "text"
        for ln in raw.splitlines():
            if ln.strip().startswith("```"):
                if buf:
                    out.append((mode, "\n".join(buf)))
                buf, mode = [], ("code" if mode == "text" else "text")
            else:
                buf.append(ln)
        if buf:
            out.append((mode, "\n".join(buf)))
        return out
        
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

class MainAIEditor(QMainWindow):
    ORG_NAME: Final = "ai.bentu"

    APP_NAME: Final = "AI-Editor"
    _SCHEMA:  Final = 1

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
        self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
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

        # ----------- rechter vertikaler Splitter -------------------------

        self.right_split = QSplitter(Qt.Vertical, self)

        disable_console = _env_truthy("AI_IDE_DISABLE_CONSOLE", "0")
        disable_tabs = _env_truthy("AI_IDE_DISABLE_TABS", "0")

        if not disable_console:
            self._create_console_dock()      # unten
        else:
            self.console_dock = QDockWidget("Console", self)
            self.console_dock.setObjectName("ConsoleDock")
            self.console_widget = QTextEdit("Console disabled (AI_IDE_DISABLE_CONSOLE=1)")
            self.console_dock.setWidget(self.console_widget)
            self._strip_dock_decoration(self.console_dock)
            self.right_split.addWidget(self.console_dock)

        if not disable_tabs:
            self._add_initial_tab_dock()     # oben
        else:
            tabs_placeholder = QTextEdit("Tabs disabled (AI_IDE_DISABLE_TABS=1)")
            self.right_split.addWidget(tabs_placeholder)

        self.right_split.setStretchFactor(0, 3)
        self.right_split.setStretchFactor(1, 1)

        # ----------- linker horizontaler Splitter ------------------------

        self.main_split = QSplitter(Qt.Horizontal, self)
        self.main_split.addWidget(self.files_dock)       # links
        self.main_split.addWidget(self.right_split)      # rechts
        self.main_split.setSizes([250, 1000])

        self.setCentralWidget(self.main_split)

    # ----------------------------------------------------------------------
    
    def _create_console_dock(self):
        """
        Creates and configures the console dock widget for the application.

        This method initializes a QDockWidget labeled "Console", sets its object name,
        creates a QTextEdit widget for displaying console output, and adds it to the dock.
        It also removes the dock's default decorations and adds the dock to the right split area
        of the main window.

        Side Effects:
            - Modifies self.console_dock and self.console_widget attributes.
            - Updates the right_split layout by adding the console dock widget.
        """
        self.console_dock = QDockWidget("Console", self)
        self.console_dock.setObjectName("ConsoleDock")
        self.console_widget = QTextEdit("Console / Output")
        self.console_dock.setWidget(self.console_widget)
        self._strip_dock_decoration(self.console_dock)
        self.right_split.addWidget(self.console_dock)

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
            _icon("reload_.svg"), 
            "", self, 
            triggered = self.
            _toggle_accent
            )
        
        self.act_close_tab.setToolTip("change lite color")

        # ---------- NEU: Chat-Toggle --------------- # <– 10.07.2025 ---------

        self.act_toggle_chat = QAction(
            _icon("chat.svg"),     # passendes Symbol im Ordner symbols/
            "Chat", self, 
            checkable = True, 
            checked = True
            )

        self.act_toggle_chat.setToolTip("AI-Chat anzeigen/ausblenden")

        # ---------- Sichtbarkeit verknüpfen --------- # <– 10.07.2025 --------
        self.act_toggle_chat.toggled.connect(self.chat_dock.setVisible)

        # ---------- Right-Dock Toggle (for right side-toolbar) --------------
        # Uses panel-style icons instead of the chat glyph.
        self.act_toggle_right_dock = QAction(
            _icon("open_in_new_dock.svg"),
            "Right Dock",
            self,
            checkable=True,
            checked=True,
        )
        self.act_toggle_right_dock.setToolTip("Right-Dock anzeigen/ausblenden")
        self.act_toggle_right_dock.toggled.connect(self.chat_dock.setVisible)

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
             _icon("left_panel_open_.svg"),                # Symbols/explorer.svg
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
            checkable=True, checked=True
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
            self.act_new_tab,
            self.act_close_tab,
            self.act_save_tab,
            self.act_open,
            self.act_toggle_accent,
            self.act_toggle_chat,
            self.act_clone_tabdock,
            self.act_toggle_console,
            self.act_save_tab,
            self.act_save_tab_as
            ]
            )

        # ---------------- seitliche Toolbars ------------------------------- 

        self.tb_left  = QToolBar(self, orientation=Qt.Vertical)
        self.tb_right = QToolBar(self, orientation=Qt.Vertical)
        self.tb_left.setObjectName("ToolbarLeft")
        self.tb_right.setObjectName("ToolbarRight")

        # auch hier die größere Icongröße übernehmen

        for bar in (self.tb_left, self.tb_right):
            bar.setIconSize(self.tb_top.iconSize())
            self.addToolBar(Qt.LeftToolBarArea if bar is self.tb_left
                            else Qt.RightToolBarArea, bar)

        # Left toolbar: Explorer toggle (JsonTree / project explorer dock)
        if hasattr(self, "act_toggle_explorer"):
            self.tb_left.addSeparator()
            self.tb_left.addAction(self.act_toggle_explorer)

        # Right toolbar: Right-Dock open/close
        if hasattr(self, "act_toggle_right_dock"):
            self.tb_right.addSeparator()
            self.tb_right.addAction(self.act_toggle_right_dock)

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
             self.act_toggle_explorer,
             self.act_toggle_tabdock,
             self.act_toggle_console,
             self.menu_visible_action,
             self.act_grey
            ]
        
        def _addActions(act: QAction, last: bool = False) -> None:
            for act in action_list:
                view.addAction(act)
                if not last:
                    view.addSeparator()
        
        _addActions(action_list) 
        
        # -------------- TOOLS ------------------------------------------------
        
        tools = mbar.addMenu("Tools")
        tools.addAction(self.act_clone_tabdock)
   
    # ================================================= status =============
    
    def _create_status(self):
        st = QStatusBar(self)
        st.showMessage("Ready")
        # permanenter Encoding-Indikator
        self._st_enc = QLabel("UTF-8")
        st.addPermanentWidget(self._st_enc)
        self.setStatusBar(st)

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

        if hasattr(self, "act_toggle_right_dock"):
            self.chat_dock.visibilityChanged.connect(self.act_toggle_right_dock.setChecked)
            self.chat_dock.visibilityChanged.connect(self._update_right_dock_icon)
            # Initialize icon state
            self._update_right_dock_icon(self.chat_dock.isVisible())

    def _update_right_dock_icon(self, visible: bool) -> None:
        """Update the right-toolbar icon depending on dock visibility."""
        if not hasattr(self, "act_toggle_right_dock"):
            return
        icon_name = (
            "right_panel_close_24dp_666666_FILL0_wght400_GRAD0_opsz24.svg"
            if visible
            else "open_in_new_dock.svg"
        )
        self.act_toggle_right_dock.setIcon(_icon(icon_name))

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

        # insert above console (console is guaranteed to exist now)

        self.right_split.insertWidget(
            max(0, self.right_split.indexOf(self.console_dock)), dock)

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
        self._sync_explorer_scheme()

    @Slot(bool)
    def _toggle_grey(self, on: bool):
        self._base = SCHEME_GREY if on else SCHEME_DARK
        _apply_style(self, _build_scheme(self._accent, self._base))
        self._sync_explorer_scheme()

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
        self._sync_explorer_scheme()
        
        self.chat_dock.setVisible(s.value("showChat", True,  bool))

        
        self.files_dock.setVisible(s.value("showExplorer", True,  bool))
        self.console_dock.setVisible(s.value("showConsole",  True,  bool))
        tab_on = s.value("showTabDock", True, bool)
        for d in self._tab_docks:
            d.setVisible(tab_on)

        # Tabs rekonstruieren (optional)

        opened = s.value("openTabs", [])
        if opened:
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
        s.setValue("showConsole",  self.console_dock.isVisible())
        s.setValue("showChat", self.chat_dock.isVisible())   
        s.setValue("showTabDock",  all(d.isVisible() for d in self._tab_docks))

        tabs: EditorTabs = self._tab_docks[0].widget()
        s.setValue("openTabs", [tabs.tabText(i) for i in range(tabs.count())])

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
                from .chat_completion import ChatCom  # type: ignore
            except Exception:
                from chat_completion import ChatCom  # type: ignore

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
        sys.exit(app.exec())

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
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

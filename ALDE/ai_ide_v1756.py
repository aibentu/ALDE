from __future__ import annotations    ## ai_ide_v1756.py

#  Author: project maintainer
#  Contact: see README

# – start of instructs –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––– –
""" ERROR: ChatHistory hat kein Objekt-Attribut _project_vector
    Problem: Das Attribut _project_vector wurde nicht initialisiert."""
# – end of instrcus ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––– –

import os
import os
import sys
import base64
import binascii
import uuid
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PARENT = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Workaround für GNOME GLib-GIO-ERROR mit antialiasing
# Verhindert Crash durch fehlende GNOME-Settings-Keys
os.environ.setdefault('GDK_BACKEND', 'x11')
os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

# Unterdrücke GLib Warnings (optional, falls sie stören)
import warnings
warnings.filterwarnings('ignore', category=Warning)
from PIL import Image
from typing import Final, List, Optional
from io import BytesIO
import mimetypes

# ---------------------------------------------------------------------------
#  external file viewer — provides widgets & helper used for the „open file“
#  feature below.  Keeping this import clustered here avoids a hard runtime
#  dependency for users of ai_ide_v1.7.5.py that never invoke “open file”.
# ---------------------------------------------------------------------------

try:
    from file_viewer import (  
        classify as _fv_classify,
        ImageWidget as _FVImageWidget,
        PdfWidget as _FVPdfWidget,
        MarkdownWidget as _FVMarkdownWidget,
        TextWidget as _FVTextWidget,
    )
except Exception:    # pragma: no cover – soft-fail, detailed handling below
    _fv_classify = None  # type: ignore
    _FVImageWidget = _FVPdfWidget = _FVMarkdownWidget = _FVTextWidget = None  # type: ignore

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
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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
    from alde.chat_completion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore  # noqa: E402
except Exception:
    if str(_PARENT) not in sys.path:
        sys.path.insert(0, str(_PARENT))
    from alde.chat_completion import ChatCom, ImageDescription, ImageCreate, ChatHistory  # type: ignore  # noqa: E402
# --------------------------------------------------------------------------
from alde.litehigh import QSHighlighter

from alde.jstree_widget  import JsonTreeWidgetWithToolbar

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
    border-right: 2px solid {col10};
    border-top: 1px {col7};
    border-radius: 6px;
    padding: 8px;
    font: 16px
    }}

QTabBar::tab:hover {{ 
    border-right: 2px solid {col1};
    font: 16px
    }}    

QTabBar::tab:pressed {{ 
    background: {col1};
    border-right: 2px solid {col10};  
    padding: 8px;
    font: 16px
    }}

QTabBar::tab:selected {{ 
    background: {col10};    
    border-right: 2px solid {col1};
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
    template = _STYLE + _MENU_STYLE + _SEP_QSS + _TT_QSS           #  ← NEU
    fmt      = string.Formatter()

    pieces: list[str] = []
    for txt, key, spec, conv in fmt.parse(template):
        pieces.append(txt)
        if key is None:
            continue
        pieces.append(str(scheme.get(key, "{"+key+"}")))

    qss = "".join(pieces)
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

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802  (Qt-Signatur)
        if metric in self._METRICS:
            return 0
        return super().pixelMetric(metric, option, widget)


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # --- supply our customised tab-bar before doing anything else -------
        self.setTabBar(FixedLeftTabBar())             # <── ① custom bar
        self.tabBar().setUsesScrollButtons(False)
        self.tabBar().setStyle(
        NoTabScrollerStyle(self.tabBar().style())) # hide arrow buttons
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
                                     "Tab-Dock schließen",
                                     slot=self._close_dock)

        for b in (self._btn_add, self._btn_close, self._btn_dock):
            lay.addWidget(b)

        self.setCornerWidget(corner, Qt.TopRightCorner)


       # ---- stylesheet to keep the 30 px gap between last tab & corner ----
        self.setStyleSheet(
          f"QTabBar::tab:last {{ margin-right:{self._PADDING_AFTER_LAST_TAB}px; }}")

        # ---- example start-tabs (can be removed at any time) ---------------
        
        self.addTab(QTextEdit("# notes.py", tabChangesFocus=True),"")

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
        self.setCurrentIndex(index)

    @Slot()
    def _close_tab(self) -> None:
        """
        Schliesst den aktuell aktiven Tab dieser EditorTabs-Instanz.

        – Existiert kein Tab, passiert nichts  
        – Nach dem Entfernen wird automatisch der linke Nachbar aktiviert
        """
        idx = self.currentIndex()
        if idx < 0:                                  # nichts zu schliessen
            return
        self.removeTab(idx)

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
            Path(path).write_text(widget.toPlainText(), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))
            return
        # Statusbar-Nachricht über MainWindow
        main_window = self.window()
        if hasattr(main_window, 'statusBar'):
            main_window.statusBar().showMessage(f"{path} gespeichert", 3000)

    @Slot()
    def _close_all_tabs(self) -> None:
        """Schließt alle Tabs in diesem TabWidget."""
        while self.count() > 0:
            self.removeTab(0)
    
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
        self._model:   str = "o3-2025-04-16"                 # <<< zentrales Modell
        self._dropped_files: List[str] = []
        self.scheme = _build_scheme(accent, base)                # Farbschema mergen
        self._build_ui()
        self._wire()
        
        # Hover-Events aktivieren
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        # ScrollBar stylen (Pfeile ausblenden)
        css = """
            QScrollBar:vertical {
                background: {col9};  /* unsichtbar bis Hover */
            width: 4px;
        }
       /* QScrollBar::add-line, QScrollBar::sub-line { height:0px; }  /* Pfeile */
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
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not found")
                       
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
            objectName="aiInput"
        )
        self.prompt_edit.setAttribute(Qt.WA_StyledBackground, True)
        self.prompt_edit.setMinimumHeight(90)

        # 3) Splitter  ▌ ChatHistory ▌ Prompt ▌
        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(self.chat_view)
        splitter.addWidget(self.prompt_edit)
        splitter.setSizes([400, 140])

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

        self._append("AI", reply)

    # ---------------------------------------------------------------------------
    #  CHAT – Bild analysieren
    # ---------------------------------------------------------------------------
    @Slot()
    def _send_img(self) -> None:
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
                _model=self._model,
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

    # ---------------------------------------------------------------------------
    #  CHAT – Bild generieren
    # ---------------------------------------------------------------------------
    @Slot()
    def _create_img(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Info", "Bitte Prompt eingeben.")
            return  

        self._append("You", prompt)
        self.prompt_edit.clear()    

        try:
            raw = ImageCreate(
                _model="dall-e-3",
                _input_text=prompt
            ).get_img()
            self._insert_image(raw)
        except Exception as exc:
            self._append("AI", f"[ERROR] {exc}")

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
        super().__init__(parent=None)
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
        line_h = max(20, line_h)          # Mindesthöhe
        lines  = max(7, self.blockCount())
        self.setFixedHeight(lines * line_h + self._PADDING)

# -----------------------------------------------------------------
class MsgWidget(QWidget):
    """
    Eine Chat-Nachricht bestehend aus ‹who›-Header und beliebigen
    Markdown-/Code-Segmenten.  
    Alle Segmente expandieren vollständig → keine internen Scrollbars.
    """

    def __init__(self, who: str,
                 segments: list[tuple[str, str]],
                 parent: QWidget | None = None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        base_style = "border-radius: 8px; border-width: 1px; border-style: solid;"
        if who == "AI":
            bg_color, border_color = "#1f1f1f", "#3a5fff"
        else:
            bg_color, border_color = "#dfefff", "#a0bfff"
        self.setStyleSheet(f"background-color: {bg_color}; border-color: {border_color}; {base_style}")

        # Header
        from PySide6.QtWidgets import QLabel
        lay.addWidget(QLabel(f"<b>{who}:</b>", self), 0, Qt.AlignLeft)

        # Segmente rendern
        for kind, block in segments:
            block = block.strip()
            if not block:
                continue

            if kind == "code":
                lay.addWidget(CodeViewer(block, self))
            else:
                br = QTextBrowser(self)
                br.setFrameShape(QFrame.NoFrame)
                br.setOpenExternalLinks(True)
                br.setMarkdown(block)

                # Scrollbars im Browser selbst unterbinden
                br.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                #br.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

                # Automatische Höhe
                br.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._fit_browser(br)
                lay.addWidget(br)

        # kleiner Abstand nach unten
        lay.addItem(QSpacerItem(0, 8, QSizePolicy.Minimum,
                                QSizePolicy.Fixed))

    # ----------------------------------------------------------------
    def _fit_browser(self, br: QTextBrowser) -> None:
        """
        Passt die Höhe des QTextBrowser exakt an den Dokument-Inhalt an.
        """
        doc_h   = br.document().size().height()
        padding = 12     # analog CodeViewer
        #br.setFixedHeight(int(doc_h) + padding)


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

        min_h =  (#Zeilen  ×  Zeilenhöhe)  +  5 px

    Enthält das Dokument (Bilder, Tabellen …) mehr Inhalt als der
    Zeilenzähler vermuten lässt, wird automatisch der größere Wert
    verwendet, so dass nichts abgeschnitten wird.
    """
    doc        = br.document()
    rows       = max(7, doc.blockCount())          # mindestens 7 Zeilen
    font_h     = QFontMetrics(br.font()).height()
    min_h      = rows * font_h + 10                # geforderte Formel

    # Falls Qt eine höhere reale Dokument­größe meldet (z. B. Bilder):
    min_h      = max(min_h, int(doc.size().height()) + 2)

    br.setMinimumHeight(min_h)

# -- bestehende Klasse zur Laufzeit patchen -------------------------------
import types, inspect, sys

# MsgWidget befindet sich bereits im globalen Namespace des Hauptskripts
MsgWidget = next(                       # type: ignore  # noqa: N806
    obj for obj in globals().values()
    if inspect.isclass(obj) and obj.__name__ == "MsgWidget"
)

# Methode ersetzen
MsgWidget._fit_browser = types.MethodType(_autofit_browser, MsgWidget)
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
   Nachrichten **vollständig** angezeigt (keine abgeschnittenen Zeilen mehr).

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
    from alde.chat_completion import ChatHistory
except Exception:
    if str(_PARENT) not in sys.path:
        sys.path.insert(0, str(_PARENT))
    from alde.chat_completion import ChatHistory
from alde.litehigh import QSHighlighter
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

        self.setWindowTitle("AI Editor – Synergetic")
        self.resize(1280, 800)
        #self.showFullScreen
        # ---- create primary widgets/layout --------------------------------
        self._create_side_widgets()
        self._create_central_splitters()
        self._create_actions()
        self._create_toolbars()
        self._create_menu()
        self._create_status()
        self._wire_vis()
        # -----------------------------------------------------------------
   
        _apply_style(self, _build_scheme(self._accent, self._base))

        self._load_ui_state()

        # -----------------------------------------------------------------
        # <- changes 31.07.2025

        # 1) create persistence helper
        self._chat = ChatHistory()
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
        
        # Use new multi-root tree widget with toolbar
        self.explorer = JsonTreeWidgetWithToolbar()
        self.explorer.tree.setEditTriggers(
            QTreeWidget.DoubleClicked | QTreeWidget.EditKeyPressed
        )
        
        self.files_dock.setWidget(self.explorer)
        self._strip_dock_decoration(self.files_dock)
        
        # Add example workspace structure
        self._initialize_explorer_workspace()
              
        # ----------- set highlighting for QTextEdit Widget (self) ---------
        # ---------- Chat-Dock  --------------------------------------------

        self.chat_dock = ChatDock(self._accent, self._base, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
    
    def _initialize_explorer_workspace(self):
        """Initialize example workspace structure in the explorer."""
        import os
        
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

        self._create_console_dock()      # unten
        self._add_initial_tab_dock()     # oben

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

        self.act_toggle_explorer.toggled.connect(self.files_dock
                                                 .setVisible
                                                 )
       
        self.act_toggle_tabdock.toggled.connect(self._toggle_tab_docks)
        
        self.act_toggle_console.toggled.connect(self.console_dock
                                                .setVisible
                                                )
        
        self.act_clone_tabdock.triggered.connect(self._clone_tab_dock)

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

        # auch hier die größere Icongröße übernehmen

        for bar in (self.tb_left, self.tb_right):
            bar.setIconSize(self.tb_top.iconSize())
            self.addToolBar(Qt.LeftToolBarArea if bar is self.tb_left
                            else Qt.RightToolBarArea, bar)
            
            bar.addAction(self.act_open)
            bar.addAction(self.act_about)

    # ─────────────────────────  menu bar  ────────────────────────────────────
    
    def _create_menu(self) -> None:
        # ------------------------------------------------------------------ ui
        mbar: QMenuBar = QMenuBar(self)               # own menu-bar instance
        self.setMenuBar(mbar)                         # make it the window bar
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
        self._sync_tabdock_action()

    def _toggle_tab_docks(self, visible: bool) -> None:
        for dock in list(self._tab_docks):
            dock.setVisible(visible)
        self._sync_tabdock_action()

    def _sync_tabdock_action(self) -> None:
        if not hasattr(self, "act_toggle_tabdock"):
            return
        state = bool(self._tab_docks) and all(
            d.isVisible() for d in self._tab_docks
        )
        blocked = self.act_toggle_tabdock.blockSignals(True)
        self.act_toggle_tabdock.setChecked(state)
        self.act_toggle_tabdock.blockSignals(blocked)

    def _remove_tab_dock(self, dock: QDockWidget) -> None:
        try:
            self._tab_docks.remove(dock)
        except ValueError:
            return
        self._sync_tabdock_action()

    # ------------------------------------------------ tab-dock clone ------

    def _clone_tab_dock(self, set_current: bool = True):
        dock_id = len(self._tab_docks) + 1
        dock = QDockWidget(f"Tab-Dock {dock_id}", self)
        dock.setObjectName(f"TabDock_{dock_id}")
        tabs = EditorTabs()
        dock.setWidget(tabs)

        self._strip_dock_decoration(dock)

        # insert above console (console is guaranteed to exist now)

        self.right_split.insertWidget(
            max(0, self.right_split.indexOf(self.console_dock)), dock)

        self._tab_docks.append(dock)
        dock.visibilityChanged.connect(self._sync_tabdock_action)
        dock.destroyed.connect(lambda _=None, d=dock: self._remove_tab_dock(d))

        if hasattr(self, "act_toggle_tabdock"):
            dock.setVisible(self.act_toggle_tabdock.isChecked())
        self._sync_tabdock_action()

        if set_current:
            tabs.setCurrentIndex(0)
    
    # ------------------------------------------------ Slot's -- api -------
    # ------------------------------------------------ new file tab --------
    
    @Slot()
    def _new_tab(self) -> None:
        """
        Öffnet einen neuen, noch ungespeicherten Tab im fokussierten Tab-Dock
        und setzt die benötigten run-time-Properties.

        – nutzt das aktuell aktive Tab-Dock (Fallback: erstes vorhandenes)  
        – benutzt die korrekte Variable `idx` (statt des nicht existierenden
          Namens `index`)  
        – aktiviert den neuen Tab sofort
        """
        tabs = self._get_focused_tab_dock()
        if not tabs:
            return

        idx = tabs.addTab(
            QTextEdit("# new file …"),
            f"untitled_{tabs.count() + 1}.py"
        )

        tabs.widget(idx).setProperty("file_path", "")   # wichtig für Save-Logik
        tabs.setCurrentIndex(idx)
    
        # ------------------------------------------------ close tab -----------

    @Slot()
    def _close_tab(self):
        tabs = self._get_focused_tab_dock()
        if not tabs:
            return
        i = tabs.currentIndex()
        if i >= 0:
            tabs.removeTab(i)
    
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
        Speichert den Inhalt des aktiven Tabs im aktuell fokussierten Tab-Dock.
        Existiert noch kein Dateiname, wird automatisch »Speichern unter …«
        ausgeführt.
        """
        tabs = self._get_focused_tab_dock()
        if not tabs:
            return

        idx = tabs.currentIndex()
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
        tabs = self._get_focused_tab_dock()
        if not tabs:
            return

        idx = tabs.currentIndex()
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


    # ------------------------------------------------ about --------------

    @Slot()
    def _about(self):
        QMessageBox.information(
            self, "About",
            "AI Python3 Multi-Document Editor v0.5\n"            "AI Python3 Multi-Document Editor v0.5\n"

            "Fully refactored layout – © ai.bentu\nPowered by Qt / PySide6"
        )

    # ------------------------------------------------ view ---------------

    @Slot()
    def _toggle_accent(self):
        self._accent = SCHEME_GREEN if self._accent is SCHEME_BLUE else SCHEME_BLUE
        _apply_style(self, _build_scheme(self._accent, self._base))

    @Slot(bool)
    def _toggle_grey(self, on: bool):
        self._base = SCHEME_GREY if on else SCHEME_DARK
        _apply_style(self, _build_scheme(self._accent, self._base))

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
        if g and st:
            self.restoreGeometry(g)
            self.restoreState(st)

        # eigene Felder ---------------------------------------------------

        self._accent = SCHEME_GREEN if s.value("accent") == "green" else SCHEME_BLUE
        self._base   = SCHEME_GREY  if s.value("base")   == "grey"  else SCHEME_DARK
        _apply_style(self, _build_scheme(self._accent, self._base))
        
        self.chat_dock.setVisible(s.value("showChat", True,  bool))

        
        self.files_dock.setVisible(s.value("showExplorer", True,  bool))
        self.console_dock.setVisible(s.value("showConsole",  True,  bool))
        tab_on = s.value("showTabDock", True, bool)
        for d in self._tab_docks:
            d.setVisible(tab_on)

        # Tabs rekonstruieren (optional)

        opened = s.value("openTabs", [])
        if opened and self._tab_docks:
            tabs: EditorTabs = self._tab_docks[0].widget()
            tabs.clear()
            for name in opened:
                tabs.addTab(QTextEdit(f"# {name}\n"), name)
            if tabs.count():
                tabs.setCurrentIndex(0)

        self._sync_tabdock_action()

    # ---------------------------------------------------------------- save
    
    def _save_ui_state(self):         
        s = self._settings()
        s.clear()                      # sauberer Neu-Write
        s.setValue("schema",   self._SCHEMA)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("state",    self.saveState())

        s.setValue("accent", "green" if self._accent is SCHEME_GREEN else "blue")
        s.setValue("base",   "grey"  if self._base   is SCHEME_GREY  else "dark")
        s.setValue("showExplorer", self.files_dock.isVisible())
        s.setValue("showConsole",  self.console_dock.isVisible())
        s.setValue("showChat", self.chat_dock.isVisible())   
        s.setValue("showTabDock",  bool(self._tab_docks) and all(d.isVisible() for d in self._tab_docks))

        if self._tab_docks:
            tabs: EditorTabs = self._tab_docks[0].widget()
            s.setValue("openTabs", [tabs.tabText(i) for i in range(tabs.count())])
        else:
            s.setValue("openTabs", [])

    # -- <- changes 27.07.2025 ------------------------------------- closeEvent

    def closeEvent(self, ev):        # >>>
        # 1) save chat history to disk
        self._chat._flush()

        # 2) save the (unrelated) UI state
        self._save_ui_state()


        super().closeEvent(ev)
    
# ═════════════════════════════  main()  ════════════════════════════════════

def main() -> None:
    app = QApplication(sys.argv)
    win = MainAIEditor()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":

    
    main()


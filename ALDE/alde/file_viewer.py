"""
die Klasse **class TextWidget** so anpassen das ich eine variable, 
ein cache der bereits die projekt historie geladen hat,uebergeben kann und 
dann wie das pfad objekt verarbeitet wird. 
"""

from __future__ import annotations        # MUSS direkt nach Docstring stehen
import sys
import pathlib
from typing import Optional, Union, Sequence
import keyword


from PySide6.QtCore import Qt, QRegularExpression, Slot
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from regex import F
from litehigh import QSHighlighter
# ---- optionale PDF-Unterstützung ------------------------------------------
try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    PDF_AVAILABLE = True
except ModuleNotFoundError:
    PDF_AVAILABLE = False
# ---------------------------------------------------------------------------

# ----------------------------- Hilfsfunktionen -----------------------------
IMAGE_EXT    = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
TEXT_EXT     = {".txt", ".log"}
MARKDOWN_EXT = {".md", ".markdown"}
CODE_EXT     = {
    ".py", ".c", ".cpp", ".h", ".hpp", ".java", ".js", ".ts", ".json",
    ".yml", ".yaml", ".html", ".css", ".sh", ".bat", ".ps1", ".jar"
}


def classify(path: pathlib.Path) -> str:
    """
    Liefert einen generischen Dateityp zurück:
    'image' | 'pdf' | 'markdown' | 'code' | 'text' | 'unknown'
    """
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXT:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in MARKDOWN_EXT:
        return "markdown"
    if suffix in CODE_EXT:
        return "code"
    if suffix in TEXT_EXT:
        return "text"
    return "unknown"


# --------------------------------------------------------------------------- #
#                                 Highlighter                                 #
# --------------------------------------------------------------------------- #
#
class DarkHighLighter(QSyntaxHighlighter):
    # Block-Zustände für mehrzeilige Strings
    _NO_STATE     = 0
    _IN_TRIPLE_DQ = 1    # """ … """--break-system-packages
    _IN_TRIPLE_SQ = 2    # ''' … ''' 

    # VS-Code-„Dark+“-Farben
    _C_KEYWORD      = "#569CD6"   # blau
    _C_BUILTIN      = "#4FC1FF"   # hell-blau
    _C_CLASS        = "#4EC9B0"   # türkis
    _C_FUNCTION     = "#DCDCAA"   # gelb
    _C_NUMBER       = "#B5CEA8"   # grün-grau
    _C_STRING       = "#CE9178"   # ziegelrot
    _C_COMMENT      = "#6A9955"   # grün
    _C_DECORATOR    = "#C586C0"   # rosa
    _C_OPERATOR     = "#D4D4D4"   # Standard
    _C_BRACE        = "#D4D4D4"
    _C_SELF         = "#9CDCFE"   # NEW – bläuliches Cyan für self / cls

    # --------------------------------------------------------------------- #
    def __init__(self, parent):
        super().__init__(parent)

        # -------- QTextCharFormat-Objekte ---------------------------------
        self.fmt_keyword   = self._make_format(self._C_KEYWORD,   bold=True)
        self.fmt_builtin   = self._make_format(self._C_BUILTIN)
        self.fmt_class     = self._make_format(self._C_CLASS,     bold=True)
        self.fmt_function  = self._make_format(self._C_FUNCTION,  bold=True)
        self.fmt_number    = self._make_format(self._C_NUMBER)
        self.fmt_string    = self._make_format(self._C_STRING)
        self.fmt_docstring = self._make_format(self._C_STRING,    italic=True)
        self.fmt_comment   = self._make_format(self._C_COMMENT,   italic=True)
        self.fmt_decorator = self._make_format(self._C_DECORATOR)
        self.fmt_operator  = self._make_format(self._C_OPERATOR)
        self.fmt_brace     = self._make_format(self._C_BRACE)
        self.fmt_self      = self._make_format(self._C_SELF, bold=True)  # NEW

        # -------- Schlüsselwörter / Built-ins ----------------------------
        kw_pattern = r"\b(" + "|".join(keyword.kwlist) + r")\b"

        builtin_names = (
            "abs|all|any|ascii|bin|bool|bytearray|bytes|chr|classmethod|"
            "compile|complex|dict|dir|divmod|enumerate|eval|exec|filter|float|"
            "format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|"
            "int|isinstance|issubclass|iter|len|list|locals|map|max|memoryview|"
            "min|next|object|oct|open|ord|pow|print|property|range|repr|reversed|"
            "round|set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|"
            "vars|zip"
        )
        builtin_pattern = r"\b(" + builtin_names + r")\b"

        # -------- RegExp-Regeln ------------------------------------------
        # (RegExp, Format, Capture-Group)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat, int]] = [
            (QRegularExpression(kw_pattern),               self.fmt_keyword, 0),
            (QRegularExpression(builtin_pattern),          self.fmt_builtin, 0),
            (QRegularExpression(r"\b(?:self|cls)\b"),      # NEW
                                                         self.fmt_self, 0),

            # Funktions- und Klassen-Namen
            (QRegularExpression(r"\bdef\s+([A-Za-z_]\w*)"),   self.fmt_function, 1),
            (QRegularExpression(r"\bclass\s+([A-Za-z_]\w*)"), self.fmt_class,    1),

            # Modulnamen in 'import x' / 'from x import …'
            (QRegularExpression(r"\b(?:from|import)\s+([A-Za-z_][\w\.]*)"),
                                                         self.fmt_builtin, 1),

            # Dekoratoren
            (QRegularExpression(r"^\s*@[\w\.]+",
                                QRegularExpression.MultilineOption),
                                                         self.fmt_decorator, 0),

            # Zahlen-Literals
            (QRegularExpression(r"\b0[bB][01_]+"),              self.fmt_number, 0),
            (QRegularExpression(r"\b0[oO][0-7_]+"),             self.fmt_number, 0),
            (QRegularExpression(r"\b0[xX][0-9a-fA-F_]+"),       self.fmt_number, 0),
            (QRegularExpression(r"\b\d+(\.\d+)?([eE][+-]?\d+)?j?"),
                                                         self.fmt_number, 0),

            # „Kurze“ Strings
            (QRegularExpression(r"([rubfRUBF]*'[^'\\]*(\\.[^'\\]*)*')"),
                                                         self.fmt_string, 0),
            (QRegularExpression(r'([rubfRUBF]*"[^"\\]*(\\.[^"\\]*)*")'),
                                                         self.fmt_string, 0),

            # Kommentare
            (QRegularExpression(r"#.*"),                        self.fmt_comment, 0),

            # Operatoren und Klammern
            (QRegularExpression(r"[+\-*/%=<>!&|^~]+"),          self.fmt_operator, 0),
            (QRegularExpression(r"[()\[\]{}]"),                 self.fmt_brace,   0),
        ]

        # Triple-Quotes
        self.rx_triple_dq = QRegularExpression(r'"""')
        self.rx_triple_sq = QRegularExpression(r"'''")

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _make_format(color: str, *, bold=False, italic=False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _apply(self, text: str, rx: QRegularExpression,
               fmt: QTextCharFormat, group: int):
        it = rx.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(group),
                           m.capturedLength(group), fmt)

    # --------------------------------------------------------------------- #
    # Haupt-Callback
    # --------------------------------------------------------------------- #
    def highlightBlock(self, text: str):                       # noqa: C901
        prev_state = self.previousBlockState()

        # 1) Mehrzeilige Strings fortsetzen
        if prev_state in (self._IN_TRIPLE_DQ, self._IN_TRIPLE_SQ):
            end_rx = self.rx_triple_dq if prev_state == self._IN_TRIPLE_DQ else self.rx_triple_sq
            m_end = end_rx.match(text)
            if m_end.hasMatch():
                end = m_end.capturedEnd()
                self.setFormat(0, end, self.fmt_docstring)
                self.setCurrentBlockState(self._NO_STATE)
                text_rest = text[end:]
                offset = end
            else:
                self.setFormat(0, len(text), self.fmt_docstring)
                self.setCurrentBlockState(prev_state)
                return
        else:
            text_rest = text
            offset = 0
            self.setCurrentBlockState(self._NO_STATE)

        # 2) Neuer mehrzeiliger String?
        for rx, state in ((self.rx_triple_dq, self._IN_TRIPLE_DQ),
                          (self.rx_triple_sq, self._IN_TRIPLE_SQ)):
            m = rx.match(text_rest)
            if m.hasMatch():
                start = offset + m.capturedStart()
                self.setFormat(start, len(text) - start, self.fmt_docstring)
                self.setCurrentBlockState(state)
                text_rest = text_rest[:m.capturedStart()]
                break

        # 3) Alle einfachen Regeln anwenden
     
# ---------------------------- Ansichts-Widgets -----------------------------
class PdfWidget(QWidget):
    def __init__(self, path: pathlib.Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        if not PDF_AVAILABLE:
            raise RuntimeError("Qt wurde ohne PDF-Unterstützung gebaut")
        self.doc = QPdfDocument(self)
        status = self.doc.load(str(path))
        if status != QPdfDocument.Status.Ready:
            raise IOError(f"PDF konnte nicht geladen werden: {status}")
        self.viewer = QPdfView(self)
        self.viewer.setDocument(self.doc)

        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.viewer)


class ImageWidget(QLabel):
    def __init__(self, path: pathlib.Path, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(path))
        if pix.isNull():
            # keep an empty label — caller will handle error
            self._orig_pixmap = None
        else:
            self._orig_pixmap = pix
        self.setScaledContents(False)
        # Allow the widget to expand inside layouts/tabs
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Initial paint
        if getattr(self, "_orig_pixmap", None) is not None:
            self.setPixmap(self._orig_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def resizeEvent(self, ev):                 # noqa: N802
        try:
            super().resizeEvent(ev)
            if getattr(self, "_orig_pixmap", None) is None:
                return
            # Scale original pixmap to current widget size, preserve aspect ratio
            scaled = self._orig_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled)
        except Exception as exc:
            # Avoid bubbling Python exceptions into Qt's C++ event loop
            try:
                print("ImageWidget.resizeEvent error:", exc)
            except Exception:
                pass
            return


class ChatImageWidget(QLabel):
    """Compact image preview for chat bubbles.

    Scales the image to the available widget width (optionally capped), keeps
    aspect ratio, and adjusts its own height so the surrounding layout doesn't
    allocate excessive empty space.
    """

    def __init__(
        self,
        path: pathlib.Path,
        parent: Optional[QWidget] = None,
        *,
        max_width: int = 640,
    ):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._max_width = max_width
        self._orig_pixmap = QPixmap(str(path))
        if self._orig_pixmap.isNull():
            raise IOError("Unable to load image")

        # In chat we want: full available width, but a computed fixed height.
        self.setScaledContents(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(1)

        self._rescale_to_fit()

    def resizeEvent(self, ev):  # noqa: N802
        try:
            super().resizeEvent(ev)
            self._rescale_to_fit()
        except Exception as exc:
            try:
                print("ChatImageWidget.resizeEvent error:", exc)
            except Exception:
                pass

    def showEvent(self, ev):  # noqa: N802
        try:
            super().showEvent(ev)
            self._rescale_to_fit()
        except Exception:
            pass

    def _rescale_to_fit(self) -> None:
        if getattr(self, "_orig_pixmap", None) is None or self._orig_pixmap.isNull():
            return

        w = max(1, self.width())
        if self._max_width:
            w = min(w, int(self._max_width))

        scaled = self._orig_pixmap.scaledToWidth(w, Qt.SmoothTransformation)
        self.setPixmap(scaled)
        # Lock height to the scaled pixmap height so the bubble wraps tightly.
        self.setFixedHeight(max(1, scaled.height()))


class ZoomImageWidget(QWidget):
    """Image viewer with simple zoom controls and panning.

    - Fit mode (default): image scales to viewport while preserving aspect ratio.
    - Manual zoom: use slider or +/- buttons (10% steps).
    """
    def __init__(self, path: pathlib.Path, parent: Optional[QWidget] = None):
        # Ensure minimal attributes exist early: resizeEvent may be called
        # by Qt before the rest of __init__ completes. Initialize safe
        # defaults so event handlers do not raise AttributeError.
        self._fit_mode = True
        self._zoom_percent = 100
        self._orig_pixmap = None
        super().__init__(parent)
        self._orig_pixmap = QPixmap(str(path))
        if self._orig_pixmap.isNull():
            raise IOError("Unable to load image")

        # Controls
        self.btn_fit = QPushButton("Fit")
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_out = QPushButton("-")
        self.btn_reset = QPushButton("100%")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(10, 400)
        self.slider.setValue(100)

        # Image label inside scroll area
        self.lbl = QLabel(alignment=Qt.AlignCenter)
        self.lbl.setBackgroundRole(self.palette().Base)
        self.lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.lbl)
        self.scroll.setWidgetResizable(True)

        top = QHBoxLayout()
        top.setContentsMargins(4, 4, 4, 4)
        top.addWidget(self.btn_fit)
        top.addWidget(self.btn_zoom_out)
        top.addWidget(self.btn_zoom_in)
        top.addWidget(self.btn_reset)
        top.addWidget(self.slider, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.scroll, 1)

        # State
        self._fit_mode = True
        self._zoom_percent = 100

        # Wire
        self.btn_fit.clicked.connect(self._set_fit)
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        self.btn_reset.clicked.connect(self._reset_zoom)
        self.slider.valueChanged.connect(self._on_slider)

        self._apply()

    def _set_fit(self) -> None:
        self._fit_mode = True
        self._apply()

    def _zoom_in(self) -> None:
        self._fit_mode = False
        v = min(400, self.slider.value() + 10)
        self.slider.setValue(v)

    def _zoom_out(self) -> None:
        self._fit_mode = False
        v = max(10, self.slider.value() - 10)
        self.slider.setValue(v)

    def _reset_zoom(self) -> None:
        self._fit_mode = False
        self.slider.setValue(100)

    def _on_slider(self, val: int) -> None:
        self._zoom_percent = val
        self._fit_mode = False
        self._apply()

    def resizeEvent(self, ev):  # noqa: N802
        try:
            super().resizeEvent(ev)
            if self._fit_mode:
                self._apply()
        except Exception as exc:
            try:
                print("ZoomImageWidget.resizeEvent error:", exc)
            except Exception:
                pass
            return

    def _apply(self) -> None:
        try:
            if self._fit_mode:
                # fit to viewport preserving aspect ratio
                try:
                    vp = self.scroll.viewport().size()
                except Exception:
                    vp = self.size()
                scaled = self._orig_pixmap.scaled(vp, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl.setPixmap(scaled)
                self.lbl.resize(scaled.size())
            else:
                factor = self._zoom_percent / 100.0
                new_w = max(1, int(self._orig_pixmap.width() * factor))
                scaled = self._orig_pixmap.scaledToWidth(new_w, Qt.SmoothTransformation)
                self.lbl.setPixmap(scaled)
                self.lbl.resize(scaled.size())
        except Exception as exc:
            try:
                print("ZoomImageWidget._apply error:", exc)
            except Exception:
                pass
            return


class MarkdownWidget(QTextEdit):
    def __init__(self, path: pathlib.Path, parent=None):
        super().__init__(parent)
        self.setReadOnly(False)   # Editing erlauben
        with path.open(encoding="utf-8", errors="replace") as fp:
            self.setMarkdown(fp.read())


class TextWidget(QPlainTextEdit):
    """
    Flexibles Plain-Text-Widget.

    * source kann …
        - pathlib.Path          → Datei wird eingelesen
        - str                   → Text ist schon vorhanden
        - bytes                 → wird dekodiert
        - Sequence[str]         → Zeilenliste, wird mit '\n'.join(..) verbunden

    * highlight = True erzwingt Syntax-Highlighting,
      ansonsten wird es automatisch aktiviert, wenn
      ein Path mit bekannter CODE_EXT-Endung übergeben wird.
    """

    def __init__(
        self,
        source: Union[pathlib.Path, str, bytes, Sequence[str]],
        parent: Optional[QWidget] = None,
        *,
        highlight: bool = True,
        encoding: str = "utf-8",
        errors: str = "replace",
    ) -> None:
        super().__init__(parent)

        # Grund­konfiguration
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(2 * self.fontMetrics().horizontalAdvance(" "))
        self.setWordWrapMode(QTextOption.NoWrap)

        # -------------------------------------------------------------- #
        # Quelle in reinen Text umwandeln
        # -------------------------------------------------------------- #
        self._path: Optional[pathlib.Path]
        if isinstance(source, pathlib.Path):
            self._path = source
            text = source.read_text(encoding=encoding, errors=errors)
        elif isinstance(source, bytes):
            self._path = None
            text = source.decode(encoding, errors=errors)
        elif isinstance(source, Sequence) and not isinstance(source, (str, bytes)):
            self._path = None
            text = "\n".join(map(str, source))
        else:                                     # str oder sonstiges
            self._path = None
            text = str(source)

        self.setPlainText(text)

        # -------------------------------------------------------------- #
        # Optional Syntax-Highlighting
        # -------------------------------------------------------------- #
        if highlight or (
            isinstance(source, pathlib.Path)
            and source.suffix.lower() in CODE_EXT
        ):
            self.highlighter = QSHighlighter(self.document())



    # ---------- Viewer-Factory -------------------------------------------
    def _create_viewer_for(self, path: pathlib.Path) -> QWidget:
        ftype = classify(path)
        if ftype == "image":
            return ImageWidget(path)
        if ftype == "pdf":
            if not PDF_AVAILABLE:
                raise RuntimeError("Qt wurde ohne PDF-Support gebaut")
            return PdfWidget(path)
        if ftype == "markdown":
            return MarkdownWidget(path)
        if ftype in ("text", "code"):
            return TextWidget(path, highlight=(ftype == "code"))
        raise RuntimeError("Unbekannter oder nicht unterstützter Dateityp")


# ----------------------------- Unit-Test -----------------------------------
    def _test_classify():
        cases = {
        "pic.jpg":   "image",
        "paper.PDF": "pdf",
        "README.md": "markdown",
        "script.py": "code",
        "run.sh":    "code",
        "notes.txt": "text",
        "data.bin":  "unknown",
        }
        for name, exp in cases.items():
            res = classify(pathlib.Path(name))
            assert res == exp, f"{name}: {res} != {exp}"


# ----------------------- Programm-Einstiegspunkt --------------------------


# Note: do NOT run module-level tests on import (they may create Qt widgets
# and therefore raise: "QWidget: Must construct a QApplication before a QWidget").
# Keep `_test_classify()` commented-out to avoid side-effects during imports.
# Uncomment locally for development/testing only:
# _test_classify()                        # schneller Selbsttest



'''Patch : class TextWidget akzeptiert jetzt wahlweise  
• eine Datei (pathlib.Path) • bereits eingelesenen Text (str / bytes)  
• eine Zeilen-Sequenz (list/tuple).  
Damit kannst du einen beliebigen „Cache“ übergeben, ohne dass erneut von
der Platte gelesen wird.
'''

# ---------- NEU/ERSATZ ----------------------------------------------------

# ...

class TextWidget(QPlainTextEdit):
    """
    Flexibles Plain-Text-Widget.

    * source kann …
        - pathlib.Path          → Datei wird eingelesen
        - str                   → Text ist schon vorhanden
        - bytes                 → wird dekodiert
        - Sequence[str]         → Zeilenliste, wird mit '\n'.join(..) verbunden

    * highlight = True erzwingt Syntax-Highlighting,
      ansonsten wird es automatisch aktiviert, wenn
      ein Path mit bekannter CODE_EXT-Endung übergeben wird.
    """

    def __init__(
        self,
        source: Union[pathlib.Path, str, bytes, Sequence[str]],
        parent: Optional[QWidget] = None,
        *,
        highlight: bool = False,
        encoding: str = "utf-8",
        errors: str = "replace",
    ) -> None:
        super().__init__(parent)

        # Grund­konfiguration
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setWordWrapMode(QTextOption.NoWrap)

        # -------------------------------------------------------------- #
        # Quelle in reinen Text umwandeln
        # -------------------------------------------------------------- #
        self._path: Optional[pathlib.Path]
        if isinstance(source, pathlib.Path):
            self._path = source
            text = source.read_text(encoding=encoding, errors=errors)
        elif isinstance(source, bytes):
            self._path = None
            text = source.decode(encoding, errors=errors)
        elif isinstance(source, Sequence) and not isinstance(source, (str, bytes)):
            self._path = None
            text = "\n".join(map(str, source))
        else:                                     # str oder sonstiges
            self._path = None
            text = str(source)

        self.setPlainText(text)

        # -------------------------------------------------------------- #
        # Optional Syntax-Highlighting
        # -------------------------------------------------------------- #
        if highlight or (
            isinstance(source, pathlib.Path)
            and source.suffix.lower() in CODE_EXT
        ):
            self.highlighter = QSHighlighter(self.document())
'''
Kurz erklärt  
• Die ursprüngliche `path`-Abhängigkeit wurde durch das generische
  Argument `source` ersetzt.  
• Abhängig vom Typ wird der Text geladen bzw. zusammengesetzt.  
• Ein echter `Path` wird weiterhin in `self._path` behalten, bei allen
  anderen Quellen ist `self._path = None`.  
• Highlighting kann manuell erzwungen oder – wie bisher – automatisch
  anhand der Dateiendung aktiviert werden.

Drop-in: Ersetzt lediglich die alte `TextWidget`-Klasse, keine weiteren
Änderungen am restlichen Code nötig.
'''
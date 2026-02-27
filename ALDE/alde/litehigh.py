
from __future__ import annotations




import builtins
import io
import keyword
import sys
import token
import tokenize
from pathlib import Path
from types import BuiltinFunctionType, BuiltinMethodType
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QSyntaxHighlighter
from PySide6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget


# --------------------------------------------------------------------------- #
#                     Hilfsklasse zum Erzeugen von Formaten                   #
# --------------------------------------------------------------------------- #
class _Fmt:
    """Factory für vorkonfigurierte ``QTextCharFormat``-Objekte."""

    @staticmethod
    def make(
        color: str,
        /,
        *,
        bold: bool = False,
        italic: bool = False,
    ) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt


# --------------------------------------------------------------------------- #
#                    @VS-Code-Modern-Dark-Highlighter                         #
# --------------------------------------------------------------------------- #
class QSHighlighter(QSyntaxHighlighter):
    """
    QSyntaxHighlighter für Python-Code im Stil des VS-Code-Themes
    »Modern Dark« – inklusive Rainbow-Brackets.
    """

    # Grund-Palette ---------------------------------------------------------
    C_KEYWORD:   Final = "#498DC4"
    C_BUILTIN:   Final = "#4FC1FF"
    C_CLASS:     Final = "#4EC9B0"
    C_FUNC_DECL: Final = "#FBF9CF"
    C_METHOD:    Final = "#FBF9CF"
    C_ATTR:      Final = "#9CDCFE"
    C_NUMBER:    Final = "#B5CEA8"
    C_STRING:    Final = "#C2917F"
    C_COMMENT:   Final = "#6A9955"
    C_DECORATOR: Final = "#7C5885"
    C_OPERATOR:  Final = "#D4D4D4"
    C_VARIABLE:  Final = "#9CDCFE"

    # Rainbow-Brackets ------------------------------------------------------
    
    BRACKETS = [
        "#FDD354",  # 0
        "#814C8E",  # 1
        "#9A5A3A",  # 2
        "#FDD354",  # 3
        "#A9DC76",  # 4
        "#78DCE8",  # 5
        "#AB9DF2",  # 6
    ]

    # Bit-Felder im Block-State  -------------------------------------------
    #  state = (depth << 1) | after_dot
    _AFTER_DOT_MASK = 0b1

    # --------------------------------------------------------------------- #
    #                                ctor                                   #
    # --------------------------------------------------------------------- #
    def __init__(self, parent):
        super().__init__(parent)

        # ---------- Formate ----------------------------------------------
        self.fmt_kw      = _Fmt.make(self.C_KEYWORD)
        self.fmt_builtin = _Fmt.make(self.C_BUILTIN)
        self.fmt_class   = _Fmt.make(self.C_CLASS)
        self.fmt_func    = _Fmt.make(self.C_FUNC_DECL)
        self.fmt_method  = _Fmt.make(self.C_METHOD)
        self.fmt_attr    = _Fmt.make(self.C_ATTR)
        self.fmt_number  = _Fmt.make(self.C_NUMBER)
        self.fmt_string  = _Fmt.make(self.C_STRING)
        self.fmt_comment = _Fmt.make(self.C_COMMENT, italic=True)
        self.fmt_oper    = _Fmt.make(self.C_OPERATOR)
        self.fmt_var     = _Fmt.make(self.C_VARIABLE)
        self.fmt_deco    = _Fmt.make(self.C_DECORATOR)
        self.fmt_self    = _Fmt.make(self.C_VARIABLE)

        self.fmt_brackets = [_Fmt.make(c) for c in self.BRACKETS]

        # ---------- Hilfs-Sets -------------------------------------------
        self._keywords  = set(keyword.kwlist)
        self._builtins  = {
            n for n, o in vars(builtins).items()
            if isinstance(o, (BuiltinFunctionType, BuiltinMethodType, type))
        }

    # --------------------------------------------------------------------- #
    #                       the work-horse: highlightBlock                  #
    # --------------------------------------------------------------------- #

    def highlightBlock(self, text: str) -> None:          # noqa: C901
        """
        Tokenisiert die aktuelle Zeile, weist Formate zu und vererbt
        Statusinformationen (Klammer-Tiefe, »nach Punkt«-Flag) an die
        Folgezeile.
        """
        # ---------------------- alten State auslesen ----------------------
        prev_state = self.previousBlockState()
        if prev_state == -1:                              # kein State gesetzt
            prev_state = 0
        depth = prev_state >> 1
        after_dot_from_prev_line = bool(prev_state & self._AFTER_DOT_MASK)

        # ---------------------- Tokenisierung ----------------------------
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text + "\n").readline))
        except tokenize.TokenError:                       # unvollständige Zeile
            self.setCurrentBlockState(prev_state)
            return

        expect: str | None = None       # Name erwartet nach 'class' / 'def'

        # -----------------------------------------------------------------
        #                     Token-Verarbeitung                          #
        # -----------------------------------------------------------------
        for i, tok in enumerate(tokens):
            ttype, tstr, (_row, col), _, _ = tok
            length = len(tstr)

            # ---------- reine Leerraum-Tokens überspringen ----------------
            if ttype == token.ERRORTOKEN and tstr.isspace():
                continue

            # ---------- Strings / Zahlen / Kommentare --------------------
            if ttype == token.STRING:
                self.setFormat(col, length, self.fmt_string)
                continue
            if ttype == token.NUMBER:
                self.setFormat(col, length, self.fmt_number)
                continue
            if ttype == tokenize.COMMENT:
                self.setFormat(col, length, self.fmt_comment)
                continue

            # ---------- Operatoren + Rainbow-Brackets --------------------
            if ttype == token.OP:
                if tstr in "([{":
                    fmt = self.fmt_brackets[depth % len(self.fmt_brackets)]
                    self.setFormat(col, length, fmt)
                    depth += 1
                elif tstr in ")]}":
                    depth = max(depth - 1, 0)
                    fmt = self.fmt_brackets[depth % len(self.fmt_brackets)]
                    self.setFormat(col, length, fmt)
                else:
                    self.setFormat(col, length, self.fmt_oper)
                continue

            # ---------- Namen (Keywords, Variablen, …) --------------------
            if ttype == token.NAME:
                # Decorator?
                if text.lstrip().startswith("@") and col == text.find("@") + 1:
                    self.setFormat(col, length, self.fmt_deco)
                    continue

                # self / cls
                if tstr in {"self", "cls"}:
                    self.setFormat(col, length, self.fmt_self)
                    continue

                # Name nach 'class' / 'def'
                if expect == "class":
                    self.setFormat(col, length, self.fmt_class)
                    expect = None
                    continue
                if expect == "def":
                    self.setFormat(col, length, self.fmt_func)
                    expect = None
                    continue

                # Heuristik: Attribut / Methoden-Aufruf?
                prev_tok = tokens[i - 1] if i else None
                next_tok = tokens[i + 1] if i + 1 < len(tokens) else None

                # 1) direkt hinter einem '.'                      
                immediate_after_dot = prev_tok is not None and prev_tok.type == token.OP and prev_tok.string == "." 

                
                # 2) erste *bedeutende* Token der Zeile,
                #    vorherige Zeile endete mit '.'  ➜  ➊ **Fix**
                continued_after_dot = prev_tok is None and after_dot_from_prev_line
                
                is_after_dot = immediate_after_dot or continued_after_dot

                is_method_call = is_after_dot and next_tok and next_tok.type == token.OP and next_tok.string
                is_constructor_call = next_tok and next_tok.type == token.OP and next_tok.string == "(" and tstr[0].isupper()

                # ------ tatsächliche Format-Wahl -------------------------
                if tstr in self._keywords:
                    self.setFormat(col, length, self.fmt_kw)
                elif is_method_call:
                    self.setFormat(col, length, self.fmt_method)
                elif is_after_dot:
                    self.setFormat(col, length, self.fmt_attr)
                elif is_constructor_call:
                    self.setFormat(col, length, self.fmt_class)
                elif tstr in self._builtins:
                    self.setFormat(col, length, self.fmt_builtin)
                else:
                    self.setFormat(col, length, self.fmt_var)

                # 'class' / 'def' merken
                if tstr == "class":
                    expect = "class"
                elif tstr == "def":
                    expect = "def"

        # -----------------------------------------------------------------
        #             letzten signifikanten Token bestimmen                #
        # -----------------------------------------------------------------
        new_after_dot = False
        for tok in reversed(tokens):
            if tok.type in (token.ENDMARKER, token.NEWLINE, token.NL):
                continue
            if tok.type == token.ERRORTOKEN and tok.string.isspace():
                continue
            new_after_dot = tok.type == token.OP and tok.string == "."
            break

        # --------------------- State an nächste Zeile ---------------------
        new_state = (depth << 1) | int(new_after_dot)
        self.setCurrentBlockState(new_state)


# --------------------------------------------------------------------------- #
#                           Simple Markdown Highlighter                       #
# --------------------------------------------------------------------------- #
import re


class MDHighlighter(QSyntaxHighlighter):
    """Minimal Markdown highlighter for headings, emphasis, code, links, lists."""

    C_HEADING:  Final = "#569CD6"
    C_BOLD:     Final = "#DCDCAA"
    C_ITALIC:   Final = "#C586C0"
    C_CODE:     Final = "#CE9178"
    C_LINK:     Final = "#4FC1FF"
    C_LIST:     Final = "#B5CEA8"
    C_QUOTE:    Final = "#6A9955"

    _re_heading = re.compile(r"^(#{1,6})\s.*")
    _re_bold = re.compile(r"\*\*[^*]+\*\*|__[^_]+__")
    _re_italic = re.compile(r"(?<!\*)\*[^*]+\*(?!\*)|(?<!_)_[^_]+_(?!_)")
    _re_code = re.compile(r"`[^`]+`")
    _re_link = re.compile(r"\[[^\]]+\]\([^\)]+\)")
    _re_list = re.compile(r"^\s*([-*+]\s+|\d+\.\s+)")
    _re_quote = re.compile(r"^>\s.*")

    def __init__(self, parent):
        super().__init__(parent)
        self.fmt_heading = _Fmt.make(self.C_HEADING, bold=True)
        self.fmt_bold = _Fmt.make(self.C_BOLD, bold=True)
        self.fmt_italic = _Fmt.make(self.C_ITALIC, italic=True)
        self.fmt_code = _Fmt.make(self.C_CODE)
        self.fmt_link = _Fmt.make(self.C_LINK)
        self.fmt_list = _Fmt.make(self.C_LIST)
        self.fmt_quote = _Fmt.make(self.C_QUOTE, italic=True)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if not text:
            return

        m = self._re_heading.match(text)
        if m:
            self.setFormat(0, len(text), self.fmt_heading)
            return

        if self._re_quote.match(text):
            self.setFormat(0, len(text), self.fmt_quote)

        lm = self._re_list.match(text)
        if lm:
            self.setFormat(lm.start(), lm.end() - lm.start(), self.fmt_list)

        for rgx, fmt in (
            (self._re_code, self.fmt_code),
            (self._re_link, self.fmt_link),
            (self._re_bold, self.fmt_bold),
            (self._re_italic, self.fmt_italic),
        ):
            for m in rgx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# --------------------------------------------------------------------------- #
#                              Simple JSON Highlighter                        #
# --------------------------------------------------------------------------- #

class JSONHighlighter(QSyntaxHighlighter):
    """Lightweight JSON highlighter: strings, numbers, booleans, null, braces."""

    C_STRING:  Final = "#CE9178"
    C_NUMBER:  Final = "#B5CEA8"
    C_BOOL:    Final = "#569CD6"
    C_NULL:    Final = "#C586C0"
    C_PUNCT:   Final = "#D4D4D4"
    C_KEY:     Final = "#9CDCFE"

    _re_string = re.compile(r'"(?:\\.|[^"\\])*"')
    _re_number = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
    _re_bool = re.compile(r"\b(?:true|false)\b")
    _re_null = re.compile(r"\bnull\b")
    _re_punct = re.compile(r"[{}\[\]:,]")

    def __init__(self, parent):
        super().__init__(parent)
        self.fmt_string = _Fmt.make(self.C_STRING)
        self.fmt_number = _Fmt.make(self.C_NUMBER)
        self.fmt_bool = _Fmt.make(self.C_BOOL)
        self.fmt_null = _Fmt.make(self.C_NULL)
        self.fmt_punct = _Fmt.make(self.C_PUNCT)
        self.fmt_key = _Fmt.make(self.C_KEY, bold=True)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if not text:
            return

        # punctuation
        for m in self._re_punct.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_punct)

        # strings (detect keys as strings immediately followed by optional spaces and colon)
        for m in self._re_string.finditer(text):
            start, end = m.span()
            after = text[end:]
            is_key = bool(re.match(r"\s*:", after))
            self.setFormat(start, end - start, self.fmt_key if is_key else self.fmt_string)

        for m in self._re_number.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)

        for m in self._re_bool.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bool)

        for m in self._re_null.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_null)


# --------------------------------------------------------------------------- #
#                              Simple TOML Highlighter                        #
# --------------------------------------------------------------------------- #

class TOMLHighlighter(QSyntaxHighlighter):
    """Minimal TOML highlighter: sections, keys, strings, numbers, booleans, dates, comments."""

    C_SECTION: Final = "#569CD6"
    C_KEY:     Final = "#9CDCFE"
    C_STRING:  Final = "#CE9178"
    C_NUMBER:  Final = "#B5CEA8"
    C_BOOL:    Final = "#569CD6"
    C_DATE:    Final = "#C586C0"
    C_COMMENT: Final = "#6A9955"

    _re_section = re.compile(r"^\s*\[(?:[^\]]+)\]\s*$")
    _re_key = re.compile(r"^\s*([A-Za-z0-9_\-\.]+)\s*=\s*")
    _re_string = re.compile("\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|\"(?:\\\\.|[^\"\\\\])*\"|'(?:\\\\.|[^'\\\\])*'")
    _re_number = re.compile(r"(?<![A-Za-z0-9_\.])-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
    _re_bool = re.compile(r"\b(?:true|false)\b")
    _re_date = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)?\b")
    _re_comment = re.compile(r"#.*$")

    def __init__(self, parent):
        super().__init__(parent)
        self.fmt_section = _Fmt.make(self.C_SECTION, bold=True)
        self.fmt_key = _Fmt.make(self.C_KEY, bold=True)
        self.fmt_string = _Fmt.make(self.C_STRING)
        self.fmt_number = _Fmt.make(self.C_NUMBER)
        self.fmt_bool = _Fmt.make(self.C_BOOL)
        self.fmt_date = _Fmt.make(self.C_DATE)
        self.fmt_comment = _Fmt.make(self.C_COMMENT, italic=True)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if not text:
            return
        # comments
        m = self._re_comment.search(text)
        if m:
            self.setFormat(m.start(), len(text) - m.start(), self.fmt_comment)
            text = text[: m.start()]

        # section
        if self._re_section.match(text):
            self.setFormat(0, len(text), self.fmt_section)
            return

        # key at line start
        km = self._re_key.match(text)
        if km:
            self.setFormat(km.start(1), km.end(1) - km.start(1), self.fmt_key)

        # strings
        for m in self._re_string.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_string)

        # numbers / bools / dates
        for m in self._re_number.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)
        for m in self._re_bool.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bool)
        for m in self._re_date.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_date)


# --------------------------------------------------------------------------- #
#                              Simple YAML Highlighter                        #
# --------------------------------------------------------------------------- #

class YAMLHighlighter(QSyntaxHighlighter):
    """Minimal YAML highlighter: keys, list markers, strings, numbers, booleans, null, anchors, tags, comments."""

    C_KEY:     Final = "#9CDCFE"
    C_STRING:  Final = "#CE9178"
    C_NUMBER:  Final = "#B5CEA8"
    C_BOOL:    Final = "#569CD6"
    C_NULL:    Final = "#C586C0"
    C_MARK:    Final = "#D4D4D4"
    C_ANCHOR:  Final = "#AB9DF2"
    C_TAG:     Final = "#78DCE8"
    C_COMMENT: Final = "#6A9955"

    _re_comment = re.compile(r"#.*$")
    _re_key = re.compile(r"^\s*([A-Za-z0-9_\-\.]+)\s*:\s")
    _re_list = re.compile(r"^\s*-\s+")
    _re_string = re.compile("\"(?:\\\\.|[^\"\\\\])*\"|'(?:\\\\.|[^'\\\\])*'")
    _re_number = re.compile(r"(?<![A-Za-z0-9_\.])-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
    _re_bool = re.compile(r"\b(?:true|false|on|off|yes|no)\b", re.IGNORECASE)
    _re_null = re.compile(r"\b(?:null|~)\b", re.IGNORECASE)
    _re_anchor = re.compile(r"[&*][A-Za-z0-9_\-]+")
    _re_tag = re.compile(r"!![A-Za-z0-9_:\-/]+")

    def __init__(self, parent):
        super().__init__(parent)
        self.fmt_key = _Fmt.make(self.C_KEY, bold=True)
        self.fmt_mark = _Fmt.make(self.C_MARK)
        self.fmt_string = _Fmt.make(self.C_STRING)
        self.fmt_number = _Fmt.make(self.C_NUMBER)
        self.fmt_bool = _Fmt.make(self.C_BOOL)
        self.fmt_null = _Fmt.make(self.C_NULL)
        self.fmt_anchor = _Fmt.make(self.C_ANCHOR)
        self.fmt_tag = _Fmt.make(self.C_TAG)
        self.fmt_comment = _Fmt.make(self.C_COMMENT, italic=True)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        if not text:
            return
        # comments
        m = self._re_comment.search(text)
        if m:
            self.setFormat(m.start(), len(text) - m.start(), self.fmt_comment)
            text = text[: m.start()]

        # list markers and mapping keys
        lm = self._re_list.match(text)
        if lm:
            self.setFormat(lm.start(), lm.end() - lm.start(), self.fmt_mark)
        km = self._re_key.match(text)
        if km:
            self.setFormat(km.start(1), km.end(1) - km.start(1), self.fmt_key)

        # anchors and tags
        for m in self._re_anchor.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_anchor)
        for m in self._re_tag.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_tag)

        # strings / numbers / booleans / nulls
        for m in self._re_string.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_string)
        for m in self._re_number.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)
        for m in self._re_bool.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bool)
        for m in self._re_null.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_null)


# --------------------------------------------------------------------------- #
#                                   Demo                                      #
# --------------------------------------------------------------------------- #
def _demo() -> None:
    """Kleines Fenster, das sich selbst anzeigt und koloriert."""
    app = QApplication(sys.argv)

    editor = QTextEdit()
    editor.setFont(QFont("Fira Code", 15))
    editor.setPlainText(Path(__file__).read_text(encoding="utf-8"))

    # Highlighter aktivieren
    QSHighlighter(editor.document())

    win = QWidget()
    win.setWindowTitle("VS-Code Modern-Dark Highlighter – Demo")
    lay = QVBoxLayout(win)
    lay.addWidget(editor)
    win.resize(900, 600)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    _demo()
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QDockWidget,
    QWidget,
)


# Local widget that provides a compact JSON tree/explorer
# JsonTreeWidget.py lives next to this file in the repository


def _str_to_native(text: str) -> Any:
    """Best-effort-Konvertierung eines Strings in Python-Primitive."""
    low = text.lower()
    if low == "null":
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    # Zahl?
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text  # bleibt String


def json_to_items(data: Any, parent_item: QTreeWidgetItem) -> None:
    """
    Rekursiv JSON-Daten in QTreeWidgetItems einfügen.

    • dict  ⇒ Kindzeilen mit Schlüssel in Spalte 0
    • list  ⇒ Kindzeilen mit Index  [n]  in Spalte 0
    • Wert  ⇒ in Spalte 1 des aktuellen Items schreiben
    """
    if isinstance(data, dict):
        for key, value in data.items():
            child = QTreeWidgetItem(parent_item, [str(key), ""])
            json_to_items(value, child)
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            child = QTreeWidgetItem(parent_item, [f"[{idx}]", ""])
            json_to_items(value, child)
    else:  # Blatt / primitive
        parent_item.setText(1, str(data))
        # Wert editierbar machen
        parent_item.setFlags(parent_item.flags() | Qt.ItemIsEditable)


def items_to_json(item: QTreeWidgetItem) -> Any:
    """
    Rekursiv QTreeWidgetItem zurück in Python-Objekt verwandeln.
    """
    if item.childCount() == 0:  # Blatt
        return _str_to_native(item.text(1))

    # Hat Kinder → dict oder list?
    is_list = all(item.child(i).text(0).startswith("[")
                  for i in range(item.childCount()))

    if is_list:
        return [items_to_json(item.child(i)) for i in range(item.childCount())]

    return {
        item.child(i).text(0): items_to_json(item.child(i))
        for i in range(item.childCount())
    }


def tree_to_json(tree: QTreeWidget) -> Any:
    """
    Wandelt den gesamten Tree (Top-Level) in JSON-kompatible Struktur um.
    """
    top_count = tree.topLevelItemCount()
    if top_count == 0:
        return None

    # Prüfen ob Liste
    is_list = all(tree.topLevelItem(i).text(0).startswith("[")
                  for i in range(top_count))

    if is_list:
        return [items_to_json(tree.topLevelItem(i)) for i in range(top_count)]

    return {
        tree.topLevelItem(i).text(0): items_to_json(tree.topLevelItem(i))
        for i in range(top_count)
    }


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self._file_path: Path | None = None
        # --- TreeWidget ----------------------------------------------------
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Key / Index", "Value"])
        self.tree.header().setStretchLastSection(True)
        # Larger, more readable font for tree items and header
        tree_font = self.tree.font()
        tree_font.setPointSize(12)  # increase base font size (was default)
        self.tree.setFont(tree_font)
        header_font = self.tree.header().font()
        header_font.setPointSize(13)
        self.tree.header().setFont(header_font)
        self.setCentralWidget(self.tree)
        
        # --- Menü ----------------------------------------------------------
        # -------------------------------------------------------------------
      
        # --- Seitliche (Explorer) Widgets -------------------------------
        # Hänge den Json-Explorer an das Hauptfenster an
        self._create_side_widgets()

        self.setWindowTitle("JSON Tree Editor")
        self.resize(900, 600)

    # ......................................... Menü / Actions .............
    def _create_actions(self) -> None:
        self.act_open = QAction("Ö&ffnen …", self)
        self.act_open.triggered.connect(self.open_json)

        self.act_save = QAction("&Speichern", self)
        self.act_save.setShortcut("Ctrl+S")
        self.act_save.triggered.connect(self.save_json)

        self.act_save_as = QAction("Speichern &unter …", self)
        self.act_save_as.triggered.connect(lambda: self.save_json(True))

        self.act_exit = QAction("Be&enden", self)
        self.act_exit.triggered.connect(self.close)
    def _create_menu(self) -> None:
        menu = self.menuBar().addMenu("&Datei")
        menu.addAction(self.act_open)
        menu.addSeparator()
        menu.addAction(self.act_save)
        menu.addAction(self.act_save_as)
        menu.addSeparator()
        menu.addAction(self.act_exit)

    # ......................................... Öffnen / Speichern .........
    def open_json(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "JSON öffnen", "", "JSON-Dateien (*.json);;Alle Dateien (*)"
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(
                self, "Fehler",
                f"Datei konnte nicht gelesen werden:\n{exc}"
            )
            return

        self._file_path = path
        self.tree.clear()
        json_to_items(data, self.tree.invisibleRootItem())
        self.tree.expandAll()
        self.setWindowTitle(f"JSON Tree Editor – {path.name}")

    def save_json(self, explicit_save_as: bool = False) -> None:
        # Pfad bestimmen
        if self._file_path is None or explicit_save_as:
            path_str, _ = QFileDialog.getSaveFileName(
                self, "JSON speichern", "", "JSON-Dateien (*.json);;Alle Dateien (*)"
            )
            if not path_str:
                return
            self._file_path = Path(path_str)

        # Struktur sammeln
        data = tree_to_json(self.tree)
        try:
            self._file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            QMessageBox.information(
                self, "Gespeichert",
                f"Datei erfolgreich geschrieben:\n{self._file_path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", f"Konnte nicht speichern:\n{exc}")

    # ------------------------------------------------------------------
    def _strip_dock_decoration(self, dock: QDockWidget) -> None:
        """
        Entfernt Titelleiste und Dock-Buttons von einem QDockWidget, so dass
        es wie ein dekorationsloser Seitenbereich wirkt.
        """
        if dock is None:
            return

        # Titelleiste ausblenden
        dock.setTitleBarWidget(QWidget())

        # Alle Dock-Features deaktivieren (kein Andocken / Schweben …)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)

    # ------------------------------------------------------------------
    def _create_side_widgets(self) -> None:
        """
        Erzeugt seitliche Widgets (Explorer / Json-Tree) und hängt sie
        als dekorationslose Docks an das Hauptfenster an.
        """
        # Json-Explorer
        try:
            self.files_tree = JsonTreeWidget()
        except Exception as e:
            # Fallback: wenn das Widget nicht importierbar ist, skip
            self.files_tree = None
            return

        self.files_dock = QDockWidget("Explorer", self)
        # Dock nur das Widget enthalten lassen
        self.files_dock.setWidget(self.files_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.files_dock)

        # Dock dekorationslos machen
        self._strip_dock_decoration(self.files_dock)

# """ ---------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

# """
# Maintainer contact: see repository README.
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QTabWidget, QTabBar, QHBoxLayout, QVBoxLayout,
    QToolButton, QProxyStyle, QStyle)

class EditorTabs(QTabWidget):
    """
    QTabWidget that
      • hides the built-in scroll buttons (handled by NoTabScrollerStyle)
      • guarantees that the *left-most* tab always remains visible
      • inserts newly created tabs directly **right of the active tab**
    """

    _PADDING_AFTER_LAST_TAB = 0           # fixed gap before the corner widget

    def __init__(self, parent: QWidget | None = None) -> None:
        # call the real Qt widget constructor – it accepts the *parent*
        super().__init__(parent)


        # --- supply our customised tab-bar before doing anything else -------
        self.setTabBar(FixedLeftTabBar())             # <── ① custom bar
        self.tabBar().setUsesScrollButtons(False)
        self.tabBar().setStyle(
        NoTabScrollerStyle(self.tabBar().style())) # hide arrow buttonsai_ide_v1756.py
        self.setMovable(True)
        self.setDocumentMode(False)
    
        self.setTabsClosable(False)                    # we close via corner btn

            # --- corner widget ( +   ×   ◀ ) ------------------------------------
        corner = QWidget(self)
        corner.setObjectName("CornerBar")                         # für Stylesheets

        # 1)  Vertikales „Rahmen-Layout“: sorgt dafür, dass der eigentliche
        #     Button-Streifen oben ‑ statt mittig – im Tab-Balken klebt.
        vbox = QVBoxLayout(corner)
        vbox.setContentsMargins(0, 0, 0, 0)                       # keine Luft verschenken
        vbox.setSpacing(0)

        # 2)  Horizontaler Button-Streifen
        hbox = QHBoxLayout()
        hbox.setContentsMargins(8, 0, 4, 0)                       # 8 px Abstand vom letzten Tab
        hbox.setSpacing(0)
        hbox.setAlignment(Qt.AlignRight | Qt.AlignTop)            # rechts + ganz oben

        self._btn_add   = ToolButton("plus.svg",      "Neuer Tab",        slot=self._new_tab)
        self._btn_close = ToolButton("close_tab.svg", "Tab schließen",    slot=self._close_tab)
        self._btn_dock  = ToolButton("left_panel_close.svg",
                                     "Tab-Dock schließen",                 slot=self._close_dock)

        for b in (self._btn_add, self._btn_close, self._btn_dock):
            hbox.addWidget(b)

        # 3)  Button-Streifen oben einhängen, darunter Leerraum (Stretch) lassen
        vbox.addLayout(hbox, 0)
        vbox.addStretch()

        self.setCornerWidget(corner, Qt.TopRightCorner)
        # ─────────────────────────── slots ──────────────────────────────────────


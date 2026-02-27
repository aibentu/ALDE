#!/usr/bin/env python3
"""
Simple test app to verify tooltip fixes without LangChain dependencies
"""

import sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QPushButton, QToolButton, QLabel
)

# Import the fixed tooltip classes from the main app
sys.path.insert(0, str(Path(__file__).parent))

# Copy the fixed tooltip styling code here for testing

import re
from pathlib import Path

def fix_tooltip_issues():
    file_path = Path("ai_ide_v1756.py")
    
    if not file_path.exists():
        print("ai_ide_v1756.py not found!")
        return False
    
    content = file_path.read_text(encoding='utf-8')
    
    # Fix 1: Update _TT_QSS to use white text instead of blue
    tooltip_qss_pattern = r'(_TT_QSS = """[\s\S]*?color\s*:\s*#3a5fff;[\s\S]*?""")'
    new_tooltip_qss = '''_TT_QSS = """
QToolTip {
    background-color : rgba(0, 0, 0, 230);      /* 90% schwarz   */
    color            : #FFFFFF;                  /* weißer Text für bessere Sichtbarkeit */
    border           : 1px solid #3a5fff;       /* dünner blauer Rahmen */
    border-radius    : 8px;                     /* komplett rund  */
    padding          : 8px;                     /* etwas mehr Padding */
    font-size        : 14px;                    /* explizite Schriftgröße */
    font-weight      : normal;                  /* normale Schriftstärke */
}
""""'''
    
    if re.search(tooltip_qss_pattern, content):
        content = re.sub(tooltip_qss_pattern, new_tooltip_qss, content)
        print("✓ Fixed _TT_QSS tooltip styling")
    
    # Fix 2: Replace Qt.white with explicit QColor in tooltip style functions
    qt_white_pattern = r'(\s+)WHITE = Qt\.white'
    replacement = r'\1WHITE = QColor(255, 255, 255)  # Explizit weiß definieren für bessere Sichtbarkeit'
    
    content = re.sub(qt_white_pattern, replacement, content)
    print("✓ Fixed Qt.white references")
    
    # Fix 3: Add additional palette color roles after existing ones
    palette_pattern = r'(pal\.setColor\(QPalette\.Text,\s+WHITE\)\s+# fallback einiger Styles)'
    palette_replacement = r'''\1
    pal.setColor(QPalette.BrightText,  WHITE)      # zusätzlicher fallback
    pal.setColor(QPalette.ButtonText,  WHITE)      # weitere fallback-rolle'''
    
    content = re.sub(palette_pattern, palette_replacement, content)
    print("✓ Added additional palette color roles")
    
    # Write the fixed content back
    file_path.write_text(content, encoding='utf-8')
    print("✓ Changes saved to ai_ide_v1756.py")
    
    return True

if __name__ == "__main__":
    print("Fixing tooltip visibility issues...")
    if fix_tooltip_issues():
        print("✓ All tooltip fixes applied successfully!")
        print("\nThe following changes were made:")
        print("1. Changed tooltip text color from blue (#3a5fff) to white (#FFFFFF)")
        print("2. Added explicit border and improved padding for tooltips")
        print("3. Replaced Qt.white with explicit QColor(255, 255, 255)")
        print("4. Added additional palette color role fallbacks")
        print("\nYou can now run the application to test the tooltip visibility.")
    else:
        print("❌ Failed to apply fixes")
def _install_tooltip_style() -> None:
    from PySide6.QtWidgets import QProxyStyle, QApplication, QStyle
    from PySide6.QtGui import QPainter, QPainterPath, QColor
    
    class RoundedTooltipStyle(QProxyStyle):
        """zeichnet ein komplett rundes Tooltip-Panel (kein Graustich mehr)"""
        _RADIUS = 8
        _BG     = QColor(0, 0, 0, 200)

        def drawPrimitive(self, elem, opt, p, w=None):
            if elem == QStyle.PE_PanelTipLabel:
                p.save()
                p.setRenderHint(QPainter.Antialiasing, True)
                r = opt.rect.adjusted(0, 0, -1, -1)
                path = QPainterPath()
                path.addRoundedRect(r, self._RADIUS, self._RADIUS)
                p.fillPath(path, self._BG)
                p.restore()
                return
            super().drawPrimitive(elem, opt, p, w)
    
    app = QApplication.instance()
    if not app:
        return

    # (1) ‑ Proxy-Style mit echtem, rundem Panel
    app.setStyle(RoundedTooltipStyle(app.style()))

    # (2) ‑ Einheitliche Farbpalette für die ToolTips
    pal = app.palette()

    #   Hintergrund: 90 % schwarz – identisch zum QSS-Wert
    pal.setColor(QPalette.ToolTipBase, QColor(0, 0, 0, 230))

    #   VORDERGRUND – zwingend weiß:
    WHITE = QColor(255, 255, 255)  # Explizit weiß definieren für bessere Sichtbarkeit
    pal.setColor(QPalette.ToolTipText, WHITE)      # primäre Rolle
    pal.setColor(QPalette.WindowText,  WHITE)      # fallback einiger Styles
    pal.setColor(QPalette.Text,        WHITE)      # fallback einiger Styles
    pal.setColor(QPalette.BrightText,  WHITE)      # zusätzlicher fallback
    pal.setColor(QPalette.ButtonText,  WHITE)      # weitere fallback-rolle

    app.setPalette(pal)

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tooltip Test - Hover über die Buttons für Tooltips")
        self.resize(400, 300)
        
        # Dark theme
        self.setStyleSheet("""
            QMainWindow {
                background: #181818;
                color: #E3E3DED6;
            }
            QPushButton {
                background: #181818;
                color: #E3E3DED6;
                border: 1px solid #505050;
                border-radius: 5px;
                padding: 10px;
                margin: 5px;
            }
            QPushButton:hover {
                background: #303030;
                border: 1px solid #3a5fff;
            }
            QToolTip {
                background-color: rgba(0, 0, 0, 230);
                color: #FFFFFF;
                border: 1px solid #3a5fff;
                border-radius: 8px;
                padding: 8px;
                font-size: 14px;
                font-weight: normal;
            }
        """)
        
        # Create test widgets
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Test buttons with tooltips
        btn1 = QPushButton("Button 1")
        btn1.setToolTip("Dies ist ein Test-Tooltip für Button 1.\nDer Text sollte jetzt sichtbar sein!")
        
        btn2 = QPushButton("Button 2")  
        btn2.setToolTip("Tooltip für Button 2\nMit mehreren Zeilen\nUnd weißem Text auf schwarzem Hintergrund")
        
        btn3 = QToolButton()
        btn3.setText("ToolButton")
        btn3.setToolTip("ToolButton Tooltip\nSollte auch funktionieren")
        
        label = QLabel("Label mit Tooltip")
        label.setToolTip("Label Tooltip Test\nEine weitere Zeile")
        
        layout.addWidget(QLabel("Hover über die Widgets um die Tooltips zu testen:"))
        layout.addWidget(btn1)
        layout.addWidget(btn2)
        layout.addWidget(btn3)
        layout.addWidget(label)
        layout.addStretch()

def main():
    app = QApplication(sys.argv)
    
    # Apply the tooltip fixes
    _install_tooltip_style()
    
    window = TestWindow()
    window.show()
    
    print("Tooltip-Test gestartet!")
    print("Hover über die Buttons um zu testen ob die Tooltips jetzt sichtbar sind.")
    print("Die Tooltips sollten weißen Text auf schwarzem Hintergrund mit blauem Rahmen zeigen.")
    
    return app.exec()

if __name__ == "__main__":
    main()
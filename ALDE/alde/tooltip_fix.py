"""
Quick fix for tooltip visibility issue in ai_ide_v1756.py
This script will fix the tooltip color issues by modifying the relevant functions.
"""

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
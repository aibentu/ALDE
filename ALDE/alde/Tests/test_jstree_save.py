#!/usr/bin/env python3
"""Test the JsonTreeWidget save/load functionality."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from jstree_widget import JsonTreeWidgetWithToolbar

def test_save_load():
    """Test saving and loading data."""
    app = QApplication(sys.argv)
    
    # Create widget
    widget = JsonTreeWidgetWithToolbar()
    
    # Add some test data
    print("[TEST] Adding test data to PROJECTS section...")
    widget.add_to_section("PROJECTS", "TestProject1", {
        "name": "Test Project 1",
        "path": "/home/user/project1",
        "files": ["main.py", "utils.py"],
        "settings": {"version": "1.0", "debug": True}
    })
    
    widget.add_to_section("PROJECTS", "TestProject2", {
        "name": "Test Project 2",
        "path": "/home/user/project2",
        "files": ["app.py"],
        "settings": {"version": "2.0", "debug": False}
    })
    
    print("[TEST] Adding test data to DATABASES section...")
    widget.add_to_section("DATABASES", "PostgreSQL-Main", {
        "type": "PostgreSQL",
        "host": "localhost",
        "port": 5432,
        "database": "maindb",
        "username": "admin"
    })
    
    # Show widget
    widget.show()
    widget.resize(500, 600)
    
    print("\n" + "="*60)
    print("[TEST] Widget is displayed with test data.")
    print("Try editing some values in the tree, then close the window.")
    print("Run this script again to verify that changes were saved.")
    print("="*60 + "\n")
    
    # Check if data file exists
    try:
        app_data_dir = Path(__file__).parent.parent / "AppData"
        data_file = app_data_dir / "tree_data.json"
        
        if data_file.exists():
            print(f"[INFO] Data file exists at: {data_file}")
            import json
            with open(data_file, 'r') as f:
                saved_data = json.load(f)
            print(f"[INFO] Current saved data has {len(saved_data)} sections:")
            for section, items in saved_data.items():
                if isinstance(items, dict):
                    print(f"  - {section}: {len(items)} items")
        else:
            print(f"[INFO] Data file will be created at: {data_file}")
    except Exception as e:
        print(f"[WARNING] Could not check data file: {e}")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    test_save_load()

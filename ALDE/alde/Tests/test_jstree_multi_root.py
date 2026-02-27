#!/usr/bin/env python3
"""
Test-Datei für den erweiterten JsonTreeWidget mit mehreren Wurzelelementen.
Demonstriert die VS Code Explorer-ähnliche Struktur mit PROJECTS und DATABASES.
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QDockWidget
from PySide6.QtCore import Qt
from jstree_widget import JsonTreeWidgetWithToolbar


def main():
    app = QApplication(sys.argv)
    
    window = QMainWindow()
    window.setWindowTitle("Multi-Root Tree Explorer (VS Code style)")
    window.resize(800, 600)
    
    # Create the enhanced tree widget with toolbar
    tree = JsonTreeWidgetWithToolbar()
    
    # Add some example projects
    project1 = {
        "path": "/home/user/my-app",
        "files": ["main.py", "config.json", "README.md"],
        "settings": {
            "python_version": "3.11",
            "venv": ".venv"
        }
    }
    tree.add_to_section("PROJECTS", "My App", project1)
    
    project2 = {
        "path": "/home/user/website",
        "files": ["index.html", "style.css", "script.js"],
        "settings": {
            "port": 8080
        }
    }
    tree.add_to_section("PROJECTS", "Website", project2)
    
    # Add example database connections
    db1 = {
        "type": "PostgreSQL",
        "host": "localhost",
        "port": 5432,
        "database": "production",
        "username": "admin"
    }
    tree.add_to_section("DATABASES", "Production DB", db1)
    
    db2 = {
        "type": "MongoDB",
        "host": "mongodb.example.com",
        "port": 27017,
        "database": "analytics",
        "username": "readonly"
    }
    tree.add_to_section("DATABASES", "Analytics DB", db2)
    
    # Add some history data
    history_sample = [
        {"role": "user", "content": "Hello", "time": "10:30:00"},
        {"role": "assistant", "content": "Hi there!", "time": "10:30:05"}
    ]
    tree.add_to_section("HISTORY", "Recent Chat", history_sample)
    
    # Create dock widget
    dock = QDockWidget("Explorer", window)
    dock.setWidget(tree)
    window.addDockWidget(Qt.LeftDockWidgetArea, dock)
    
    window.show()
    
    print("\n=== Multi-Root Tree Explorer ===")
    print("✓ PROJECTS section with 2 projects")
    print("✓ DATABASES section with 2 connections")
    print("✓ HISTORY section with sample data")
    print("\nFeatures:")
    print("• Click '+' icon to add new projects")
    print("• Click database icon to add new connections")
    print("• Each section can be expanded/collapsed independently")
    print("• Double-click items to edit values")
    print("\n")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

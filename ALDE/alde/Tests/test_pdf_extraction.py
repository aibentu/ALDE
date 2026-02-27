#!/usr/bin/env python3
"""
Test-Skript für PDF-Extraktion im VectorStoreManager
"""
import sys
from pathlib import Path
from vector_smanager import _load_pdf, VectorStoreManager, _log

def test_pdf_extraction():
    """Testet die PDF-Extraktion für alle gefundenen PDFs"""
    
    # Finde alle PDFs im Projektverzeichnis
    project_root = Path(__file__).parent
    pdf_files = list(project_root.rglob("*.pdf"))
    
    if not pdf_files:
        _log("", "Keine PDF-Dateien im Projektverzeichnis gefunden")
        return
    
    _log("", f"Gefundene PDF-Dateien: {len(pdf_files)}")
    
    for pdf_path in pdf_files:
        _log("", f"\n--- Teste: {pdf_path} ---")
        docs = _load_pdf(pdf_path)
        
        if docs:
            _log("", f"✓ Erfolgreich extrahiert: {len(docs)} Dokumente")
            for i, doc in enumerate(docs[:3]):  # Zeige erste 3 Dokumente
                preview = doc.page_content[:150].replace('\n', ' ').strip()
                _log("", f"  Dokument {i+1}: {preview}...")
        else:
            _log("", f"✗ Keine Dokumente extrahiert")

def test_vector_store_build():
    """Testet den kompletten Build-Prozess"""
    _log("", "\n=== Teste VectorStore Build ===")
    
    vsm = VectorStoreManager()
    try:
        vsm.build()
        _log("", "✓ VectorStore Build erfolgreich")
    except Exception as e:
        _log("", f"✗ VectorStore Build Fehler: {e}")

if __name__ == "__main__":
    test_pdf_extraction()
    test_vector_store_build()
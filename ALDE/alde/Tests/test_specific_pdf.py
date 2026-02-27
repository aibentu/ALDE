#!/usr/bin/env python3
"""
Testet die PDF-Extraktion speziell mit der Test-PDF
"""
import sys
from pathlib import Path
from vector_smanager import _load_pdf, _log

def test_specific_pdf():
    """Testet die PDF-Extraktion mit der erstellten Test-PDF"""
    
    # Use relative path from this file's location
    test_pdf = Path(__file__).resolve().parent.parent / "test_document.pdf"
    
    if not test_pdf.exists():
        _log("", f"Test-PDF nicht gefunden: {test_pdf}")
        return
    
    _log("", f"\n=== Teste spezifische PDF: {test_pdf} ===")
    docs = _load_pdf(test_pdf)
    
    if docs:
        _log("", f"✓ Erfolgreich extrahiert: {len(docs)} Dokumente")
        for i, doc in enumerate(docs):
            content_preview = doc.page_content[:300].replace('\n', ' ').strip()
            _log("", f"  Dokument {i+1} (Länge: {len(doc.page_content)}): {content_preview}...")
            _log("", f"  Metadaten: {doc.metadata}")
    else:
        _log("", f"✗ Keine Dokumente aus Test-PDF extrahiert")

if __name__ == "__main__":
    test_specific_pdf()
#!/usr/bin/env python3
"""
Vollständiger Test des VectorStore mit PDF-Unterstützung
"""
from vector_smanager import VectorStoreManager, _log
from pathlib import Path

def test_full_vector_store():
    """Testet den kompletten VectorStore inklusive PDF-Verarbeitung"""
    
    _log("", "=== Teste VectorStore mit PDF-Unterstützung ===")
    
    # Erstelle VectorStoreManager
    vsm = VectorStoreManager()
    
    # Build den Index
    try:
        _log("", "Starte Index-Build...")
        vsm.build()
        _log("", "✓ Index-Build erfolgreich abgeschlossen")
    except Exception as e:
        _log("", f"✗ Index-Build Fehler: {e}")
        return
    
    # Teste Queries mit PDF-relevanten Begriffen
    test_queries = [
        "Vector Store",
        "LangChain Framework", 
        "deutsche Text",
        "Python Programmiersprache",
        "PDF Extraktion"
    ]
    
    _log("", "\n=== Teste Queries ===")
    for query in test_queries:
        _log("", f"\nQuery: '{query}'")
        try:
            # Da die query() Methode nur Ausgabe macht, rufen wir direkt similarity_search auf
            if vsm.store:
                results = vsm.store.similarity_search(query, k=3)
                if results:
                    _log("", f"✓ Gefunden: {len(results)} Ergebnisse")
                    for i, doc in enumerate(results):
                        preview = doc.page_content[:100].replace('\n', ' ')
                        source = doc.metadata.get('source', 'unbekannt')
                        _log("", f"  {i+1}. {Path(source).name}: {preview}...")
                else:
                    _log("", "✗ Keine Ergebnisse gefunden")
            else:
                _log("", "✗ Kein Store verfügbar")
        except Exception as e:
            _log("", f"✗ Query Fehler: {e}")

if __name__ == "__main__":
    test_full_vector_store()
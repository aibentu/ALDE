#!/usr/bin/env python3
"""
Erstellt eine Test-PDF mit Text zum Testen der PDF-Extraktion
"""

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io

def create_test_pdf():
    """Erstellt eine einfache Test-PDF mit deutschem Text"""
    
    # PDF im Speicher erstellen
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
    # Text hinzufügen
    p.drawString(100, 750, "Test PDF für Vector Store")
    p.drawString(100, 720, "Diese PDF enthält deutschen Text zum Testen.")
    p.drawString(100, 690, "Künstliche Intelligenz und maschinelles Lernen")
    p.drawString(100, 660, "sind wichtige Technologien der Zukunft.")
    p.drawString(100, 630, "Python ist eine vielseitige Programmiersprache.")
    p.drawString(100, 600, "Vector Stores ermöglichen semantische Suche.")
    
    # Neue Seite
    p.showPage()
    p.drawString(100, 750, "Seite 2: Weitere Testinhalte")
    p.drawString(100, 720, "LangChain ist ein Framework für LLM-Anwendungen.")
    p.drawString(100, 690, "FAISS ist eine Bibliothek für effiziente Similarity Search.")
    p.drawString(100, 660, "HuggingFace bietet vortrainierte Embeddings-Modelle.")
    
    p.save()
    
    # PDF Daten in Datei schreiben
    pdf_data = buffer.getvalue()
    buffer.close()
    
    # Use relative path from this file's location
    output_path = Path(__file__).resolve().parent.parent / "test_document.pdf"
    with open(output_path, "wb") as f:
        f.write(pdf_data)
    
    print(f"Test-PDF erstellt: {output_path}")

if __name__ == "__main__":
    try:
        create_test_pdf()
    except ImportError:
        print("reportlab nicht verfügbar. Installiere mit: pip install reportlab")
        print("Erstelle alternativ eine Test-PDF mit einem anderen Tool.")
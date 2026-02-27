#!/usr/bin/env python3
"""
RAG-Enhanced Workflow Test

Tests the complete agent workflow with RAG system.
This version adds sample documents to RAG before running the workflow.
"""

import os
import sys
import json

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from .chat_completion import ChatCom
except Exception:
    from alde.chat_completion import ChatCom


# Sample documents to add to RAG
SAMPLE_COVER_LETTER_GUIDE = """
# Anschreiben Best Practices für IT-Positionen

## Struktur eines modernen Anschreibens

### Einleitung (2-3 Sätze)
- Erwähne die konkrete Position und wie du darauf aufmerksam wurdest
- Zeige erste Begeisterung für die Firma oder Rolle
- Beispiel: "Mit großem Interesse habe ich Ihre Stellenausschreibung als Senior Python Developer gelesen..."

### Hauptteil Absatz 1: Qualifikationen
- Nenne 3-4 konkrete Skills die zur Stellenbeschreibung passen
- Verwende Zahlen und messbare Erfolge
- Beispiel: "In meiner 6-jährigen Karriere als Python Developer habe ich umfangreiche Erfahrung mit FastAPI und PostgreSQL..."

### Hauptteil Absatz 2: Motivation & Fit
- Warum diese Firma?
- Was reizt dich an der Position?
- Wie passt du zur Unternehmenskultur?

### Hauptteil Absatz 3: Mehrwert
- Was bringst du mit, das andere nicht haben?
- Welche Probleme kannst du lösen?
- Konkrete Beispiele aus vergangenen Projekten

### Schluss
- Verfügbarkeit nennen
- Call-to-Action (z.B. "Ich freue mich auf ein persönliches Gespräch")
- Höflicher Abschluss

## Ton für IT-Positionen

**Modern**: 
- Direkte, klare Sprache
- Weniger Floskeln
- Persönlicher Touch
- Beispiel: "Ich brenne für sauberen Code und performante Systeme."

**Professional**:
- Formelle Anrede
- Distanzierter Ton
- Klassische Struktur

## Länge
- Deutsch: 300-400 Wörter
- Nicht länger als 1 Seite
- 3-4 Absätze optimal

## Häufige Fehler
1. Zu generisch - nicht auf Job zugeschnitten
2. Zu lang - Recruiter haben wenig Zeit
3. Nur Wiederholung des Lebenslaufs
4. Keine konkreten Beispiele
5. Rechtschreibfehler

## Keywords für Python Developer
Wichtig in Anschreiben zu erwähnen (falls zutreffend):
- Python 3.x
- FastAPI / Django / Flask
- PostgreSQL / MongoDB
- Docker / Kubernetes
- CI/CD Pipelines
- REST APIs
- Test-Driven Development
- Git / Version Control
- Agile / Scrum
"""

SAMPLE_JOB_POSTING = """
STELLENANZEIGE

Position: Senior Python Developer
Firma: TechCorp GmbH
Standort: Berlin, Deutschland
Typ: Vollzeit

Über uns:
TechCorp GmbH ist ein führendes Softwareunternehmen mit Fokus auf KI und Data Science.

Die Rolle:
Wir suchen einen erfahrenen Senior Python Developer für unser AI-Team.

Anforderungen:
- 5+ Jahre Erfahrung in Python
- Erfahrung mit FastAPI, Django oder ähnliche Frameworks
- PostgreSQL oder andere relationale Datenbanken
- Git und CI/CD Pipelines
- Englisch fließend
- Deutsch von Vorteil

Verantwortung:
- Entwicklung von Backend-Services
- Code Review und Mentoring
- Architektur-Entscheidungen treffen
- Performance-Optimierung

Was wir bieten:
- Wettbewerbsfähiges Gehalt (60-80k EUR)
- Flexible Arbeitszeiten
- Remote Work Option
- Entwicklungsmöglichkeiten
- Moderne Tech Stack

Bewerbung:
Senden Sie Ihren Lebenslauf an jobs@techcorp.de
Bewerbungsfrist: 31.03.2026
"""

SAMPLE_PROFILE = """
MAX MUSTERMANN
Straße 123, 10115 Berlin
Tel: +49 30 1234567
Email: max@mustermann.de
LinkedIn: linkedin.com/in/maxmustermann

PROFESSIONELLE ZUSAMMENFASSUNG
Senior Python Entwickler mit 6 Jahren Erfahrung in der Entwicklung von Web-APIs
und Datenverarbeitung. Spezialisiert auf FastAPI, PostgreSQL und Cloud-Deployment.

BERUFSERFAHRUNG

Senior Python Developer - DataSystems GmbH, Berlin (2022-heute)
- Entwicklung von REST APIs mit FastAPI und Python 3.10+
- PostgreSQL Datenbankdesign und Optimierung
- CI/CD Pipeline mit GitHub Actions und Docker
- Mentoring von 2 Junior Entwicklern
- Performance Optimierung: 40% Speedup in kritischen Funktionen

Python Developer - WebSolutions AG, München (2019-2022)
- Backend Development mit Django
- REST API Design und Implementierung
- Datenmigration und Datenbank-Refactoring
- Unit Testing und Code Coverage (85%+)

BILDUNG
Bachelor Informatik - Technische Universität München (2019)

SKILLS
Technisch:
- Python 3.8+
- FastAPI, Django
- PostgreSQL, MongoDB
- Docker, Kubernetes Basics
- Git, GitHub
- Linux/Ubuntu
- REST APIs

Soft Skills:
- Teamfähigkeit
- Problemlösung
- Kommunikation
- Lernbereitschaft

Sprachen:
- Deutsch (Muttersprache)
- Englisch (fließend, C1)

PROJEKTE
AI Data Pipeline - Entwicklung einer automatisierten Datenpipeline für ML-Modelle
- Tech: Python, FastAPI, PostgreSQL, Docker
- Impact: Reduzierte Datenprocessing Zeit um 50%
"""


def setup_rag_documents():
    """Add sample documents to RAG system."""
    print("\n" + "="*80)
    print("SETUP: Adding Sample Documents to RAG")
    print("="*80)
    
    try:
        from rag_core import create_rag_system
        
        print("\n[1] Creating RAG system...")
        rag = create_rag_system(store_path="AppData/VSM_1_Data")
        
        stats = rag.get_stats()
        print(f"  ✓ RAG System initialized")
        print(f"    Backend: {stats.get('active_backend', 'unknown')}")
        
        if stats.get('active_backend') == 'dummy':
            print("  ⚠️  WARNING: Using dummy embeddings (no real RAG available)")
            print("  💡 To enable RAG: export OPENAI_API_KEY='sk-...'")
            print("  💡 Or install: pip install langchain-huggingface sentence-transformers")
            return False
        
        # Add cover letter guide
        print("\n[2] Adding cover letter guide...")
        chunks = rag.add_document(
            content=SAMPLE_COVER_LETTER_GUIDE,
            source="guides/cover_letter_best_practices.md",
            title="Cover Letter Best Practices"
        )
        print(f"  ✓ Added {chunks} chunks")
        
        # Update stats
        stats = rag.get_stats()
        print(f"\n[3] RAG System Status:")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  Indexed sources: {stats['indexed_sources']}")
        
        # Test query
        print("\n[4] Testing RAG query...")
        results = rag.retrieve("How to write modern cover letter for Python developer?", k=2)
        if results:
            print(f"  ✓ Found {len(results)} relevant chunks")
            print(f"  Top result score: {results[0].relevance_score:.3f}")
        else:
            print("  ⚠️  No results found")
        
        return True
        
    except Exception as e:
        print(f"  ✗ RAG setup failed: {e}")
        return False


def run_workflow_test():
    """Run the complete workflow test."""
    print("\n" + "="*80)
    print("WORKFLOW TEST: Data Dispatcher + Cover Letter Generation")
    print("="*80)
    
    # Prepare request
    user_request = {
        "action": "generate_cover_letter",
        "job_posting": {
            "source": "text",
            "value": SAMPLE_JOB_POSTING
        },
        "applicant_profile": {
            "source": "text",
            "value": SAMPLE_PROFILE
        },
        "options": {
            "language": "de",
            "tone": "modern",
            "max_words": 350,
            "include_enclosures": True
        }
    }
    
    print("\n[STEP 1] Creating Primary Agent Request...")
    print("-" * 80)
    print(f"User Input:")
    print(f"  - Action: {user_request['action']}")
    print(f"  - Job Posting: {len(user_request['job_posting']['value'])} chars")
    print(f"  - Profile: {len(user_request['applicant_profile']['value'])} chars")
    print(f"  - Options: {user_request['options']}")
    
    print("\n[STEP 2] Initializing Chat with Primary Agent...")
    print("-" * 80)
    
    try:
        chat = ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(user_request, ensure_ascii=False, indent=2),
            _name="test_workflow"
        )
        print("  ✓ ChatCom initialized successfully")
        
        if hasattr(chat, '_last_model_response'):
            print(f"  Assistant response type: {type(chat._last_model_response).__name__}")
    except Exception as e:
        print(f"  ✗ ChatCom initialization failed: {e}")
        return False
    
    print("\n[STEP 3] Getting Agent Response...")
    print("-" * 80)
    
    try:
        response = chat.get_response()
        print("  ✓ Got response from agent")
        
        # Show partial response
        response_preview = response[:200] if len(response) > 200 else response
        print(f"Response (first 200 chars): {response_preview}")
        
        # Try to parse as JSON if it looks like JSON
        if response.strip().startswith('{'):
            try:
                parsed = json.loads(response)
                print(f"\n  ✓ Valid JSON response")
                if 'cover_letter' in parsed:
                    print(f"  ✓ Contains cover_letter field")
                    if 'full_text' in parsed.get('cover_letter', {}):
                        letter = parsed['cover_letter']['full_text']
                        print(f"  Cover letter length: {len(letter)} chars")
            except json.JSONDecodeError:
                print(f"  ℹ️  Response is not JSON (expected for error messages)")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to get response: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test runner."""
    print("\n" + "="*80)
    print("RAG-ENHANCED AGENT WORKFLOW TEST")
    print("="*80)
    print(f"Date: {os.popen('date').read().strip()}")
    print(f"Python: {sys.version.split()[0]}")
    
    # Check for OpenAI API key
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    print(f"OpenAI API Key: {'✓ Set' if has_openai else '✗ Not set'}")
    
    if not has_openai:
        print("\n⚠️  WARNING: OPENAI_API_KEY not set")
        print("   Agents will work, but RAG might not be fully functional")
        print("   To enable RAG with OpenAI: export OPENAI_API_KEY='sk-...'")
    
    # Setup RAG (optional, won't fail if it doesn't work)
    rag_ready = setup_rag_documents()
    
    # Run workflow test (should work even without RAG)
    success = run_workflow_test()
    
    # Summary
    print("\n" + "="*80)
    if success:
        print("✓ WORKFLOW TEST COMPLETED SUCCESSFULLY")
    else:
        print("✗ WORKFLOW TEST FAILED")
    print("="*80)
    
    if rag_ready:
        print("\n💡 RAG System is active and ready")
        print("   Documents indexed and queryable by agents")
    else:
        print("\n⚠️  RAG System not fully functional")
        print("   Agents work, but without RAG context enhancement")
        print("   To fix: Set OPENAI_API_KEY or install sentence-transformers")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

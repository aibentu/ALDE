#!/usr/bin/env python3
"""
Test Workflow: Data Dispatcher + Cover Letter Generation
This script demonstrates the full cover letter generation workflow.
"""

import json
import sys
from pathlib import Path

# Setup path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir.parent))

try:
    from .chat_completion import ChatCom, ChatHistory
except Exception:
    from alde.chat_completion import ChatCom, ChatHistory

# ============================================================================
# TEST DATA
# ============================================================================

SAMPLE_JOB_POSTING = {
    "title": "Full Stack Software Engineer",
    "location": {
        "city": None,
        "region": "Remote",
        "country": "EU/DE time zone",
        "onsite": False
    },
    "employment": {
        "type": "Full-time",
        "model": "Remote",
        "seniority": "Mid-Senior",
        "contract": "Permanent"
    },
    "mission": [
        "Shape your role, contribute ideas, work cross-functionally",
        "Build features with high automation and great UX",
        "Tackle challenges holistically across backend and frontend"
    ],
    "responsibilities": {
        "backend": [
            "Implement API best practices; GraphQL familiarity preferred",
            "Integrate and consume REST APIs",
            "Collaborate with UX/UI to support user-oriented ideas",
            "Use Docker; Kubernetes is a plus",
            "Ensure efficient processes and distributed systems"
        ],
        "frontend": [
            "Implement innovative, user-oriented solutions with UX/UI",
            "Work with CSS, JavaScript, TypeScript",
            "Develop apps with Vue/Nuxt and a responsive framework (e.g., Tailwind)",
            "Integrate REST and GraphQL APIs"
        ]
    },
    "requirements": {
        "experience": "5+ years software engineering, full-stack focus",
        "education": "Bachelor in STEM or equivalent bootcamp (5+ yrs experience)",
        "attributes": [
            "Holistic mindset, backend + frontend",
            "Problem-solving, attention to detail",
            "Strength in either backend or frontend, willing across stack",
            "Strong English communication"
        ],
        "backend_skills": [
            "API development & integration (GraphQL ideal)",
            "Python (required); Go is a plus",
            "Distributed systems understanding",
            "Docker; Kubernetes nice to have"
        ],
        "frontend_skills": [
            "CSS, JavaScript, TypeScript",
            "Vue or Nuxt",
            "Responsive framework (e.g., Tailwind)"
        ]
    },
    "benefits": [
        "30 days vacation",
        "€1,500 annual education budget",
        "Workation opportunities",
        "International, diverse team"
    ],
    "notes": "Fully remote, must work within German/European time zone",
    "company": {
        "about": "Hamburg-based mobile marketing agency with owned/operated apps",
        "model": "Reward users for testing/engaging with client apps",
        "markets": ["DACH", "US", "UK", "Canada"],
        "size": "~80 employees",
        "culture": "Diverse and fun team"
    }
}

SAMPLE_PROFILE = {
    "profile_id": "profile:44e8fce720b6ef2f385478d7f1123027caa7a148abc37af870c7522f0ccf6040",
    "personal_info": {
        "full_name": "Example Candidate",
        "date_of_birth": "1990-01-01",
        "citizenship": "DE",
        "address": "Example Street 1, 12345 Example City, Germany",
        "phone": "(redacted)",
        "email": "example@example.com",
        "linkedin": None,
        "portfolio": None
    },
    "professional_summary": "Angehender Fachinformatiker für Anwendungsentwicklung (IHK, laufend) mit solider Praxis in IT-Systembetrieb und Troubleshooting sowie wachsendem Schwerpunkt auf Python-Entwicklung. Ich arbeite produktnah an LLM-/RAG-Themen (Ingestion, Embeddings, FAISS-Retrieval, Tool-Calling) und verbinde dabei saubere Datenpipelines mit benutzerorientierter Umsetzung. Stärken: analytisches Vorgehen, klare Kommunikation und zuverlässige Umsetzung im Team.",
    "experience": [
        {
            "title": "Servicetechniker Repair Desk",
            "company": "Tec Repair GmbH",
            "duration": "01/2018 – 03/2024",
            "description": "Reparatur und Wartung von IT-Systemen, Datenübertragungen, Betriebssystem-Reparaturen, Schwerpunkt Apple-Produkte.",
            "achievements": [
                "Spezialist für Apple-Hardware (zertifiziert)",
                "Einarbeitung neuer Mitarbeitender"
            ]
        },
        {
            "title": "Selbstständiger Medienberater",
            "company": "Kabeldeutschland",
            "duration": "12/2014 – 02/2016",
            "description": "Beratung und Vertrieb von Medien- und Telekommunikationslösungen.",
            "achievements": []
        },
        {
            "title": "Elektriker (Schaltschrankbau/Elektromontage)",
            "company": "Persona",
            "duration": "06/2013 – 02/2016",
            "description": "Elektromontage und Schaltschrankbau.",
            "achievements": []
        }
    ],
    "education": [
        {
            "degree": "Fachinformatiker – Anwendungsentwicklung (in Ausbildung)",
            "institution": "Comcave.College, Saarbrücken",
            "start": "2024-08",
            "end": "2026-08",
            "status": "in progress"
        },
        {
            "degree": "Fachoberschule Ingenieurwesen (Elektrotechnik)",
            "institution": "Neunkirchen/Homburg",
            "start": "2010",
            "end": "2012",
            "status": "completed"
        },
        {
            "degree": "Secondary School Diploma (Mittlerer Bildungsabschluss)",
            "institution": "Maximilian-Kolbe-Schule des Bistums",
            "start": "2006",
            "end": "2010",
            "status": "completed"
        }
    ],
    "skills": {
        "technical": [
  
            "Python 3.8+",
            "PySide6,Qt5",
            "FastAPI, Django",
            "Applied AI/LLM",
            "RAG Systems",
            "PostgreSQL, MongoDB",
            "Docker, Kubernetes Basics",
            "Git, GitHub",
            "Linux/Ubuntu",
            "REST APIs"           

        ],
        "soft": [
            "Analytisches Denken",
            "Klare Kommunikation",
            "Nutzer-Empathie",
            "Agile Teamarbeit",
            "Selbstorganisation"
        ],
        "languages": [
            "German (native)",
            "English (C1)"
        ]
    },
    "certifications": [
        "Apple product certification (spezialisierte Zertifizierung)"
    ],
    "projects": [
        {
            "title": "AI-IDE / Agent-Workstation (Desktop App) mit RAG und MCP-Tools",
            "year": "2025–2026",
            "tech": [
                "Python",
                "PySide6",
                "OpenAI API",
                "LangChain",
                "FAISS",
                "LLM",
                "HuggingFace Embeddings",
                "MCP"
            ],
            "impact": "Lokale AI-IDE mit Multi Agentic Systems und RAG-Pipeline (Dokument-Ingestion → Embeddings → FAISS → Retrieval) inkl. MCP-Tool-Exposition; produktnahe UX durch GUI und persistente lokale Knowledge-Sources."
        },
        {
            "title": "Inventory-forecast micro-service",
            "year": "2025",
            "tech": ["Python", "Pandas", "Prophet"],
            "impact": "Reduzierte Stock-out Events um 15% in Testumgebung"
        },
        {
            "title": "Ticket-classification bot",
            "year": "2023",
            "impact": "30% schnellere Triage für lokalen IT-Shop"
        }
    ],
    "preferences": {
        "tone": "modern",
        "max_length": 350,
        "language": "de",
        "focus_areas": [
            "Python/OOP/Data",
            "LLM-Integration (Agentic Systems)",
            "RAG / Vector Stores (FAISS)",
            "Desktop-GUI (PySide6)",
            "APIs/REST",
            "Forecasting/ML Basics",
            "IT-Systempraxis",
            "Monitoring/Automation",
            "Agiles Arbeiten"
        ]
    },
    "additional_information": {
        "travel_willingness": None,
        "work_authorization": "Germany (citizen)",
        "marital_status": "single",
        "drivers_license": "B",
        "availability": "sofort bzw. 2 Wochen Kündigungsfrist"
    }
}

# ============================================================================
# WORKFLOW TEST
# ============================================================================

def test_workflow():
    print("\n" + "=" * 80)
    print("WORKFLOW TEST: Data Dispatcher + Cover Letter Generation")
    print("=" * 80 + "\n")
    
    print("[STEP 1] Creating Primary Agent Request...")
    print("-" * 80)
    
    # User-facing request to primary agent
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
    
    print(f"User Input:")
    print(f"  - Action: {user_request['action']}")
    print(f"  - Job Posting: {len(json.dumps(SAMPLE_JOB_POSTING))} chars")
    print(f"  - Profile: {len(json.dumps(SAMPLE_PROFILE))} chars")
    print(f"  - Options: {user_request['options']}")
    
    print("\n[STEP 2] Initializing Chat with Primary Agent...")
    print("-" * 80)
    
    try:
        # Initialize chat with primary agent
        chat = ChatCom(
            _model="gpt-4o-mini",
            _input_text=json.dumps(user_request, ensure_ascii=False, indent=2),
            _name="test_workflow"
        )
        
        print("✓ ChatCom initialized successfully")
        print(f"  Assistant response type: {type(chat.assistant_msg).__name__}")
        
    except Exception as e:
        print(f"✗ Error initializing ChatCom: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n[STEP 3] Getting Agent Response...")
    print("-" * 80)
    
    try:
        response = chat.get_response()
        
        if response:
            print("✓ Got response from agent")
            
            # Try to parse as JSON if possible
            try:
                if isinstance(response, str) and response.strip().startswith('{'):
                    result = json.loads(response)
                    print("\n✓ Response is valid JSON")
                    
                    # Show structure
                    if isinstance(result, dict):
                        top_keys = list(result.keys())[:5]
                        print(f"  Top-level keys: {top_keys}")
                        
                        # Show cover letter if present
                        if "cover_letter" in result:
                            cl = result["cover_letter"]
                            if "full_text" in cl:
                                print(f"\n  Generated cover letter preview ({len(cl['full_text'])} chars):")
                                print("  " + "=" * 70)
                                lines = cl["full_text"].split('\n')[:5]
                                for line in lines:
                                    print(f"  {line}")
                                if len(cl["full_text"].split('\n')) > 5:
                                    print(f"  ... ({len(cl['full_text'].split(chr(10))) - 5} more lines)")
                                print("  " + "=" * 70)
                        
                        # Show quality metrics if present
                        if "quality" in result:
                            q = result["quality"]
                            print(f"\n  Quality Metrics:")
                            print(f"    - Word count: {q.get('word_count', 'N/A')}")
                            print(f"    - Tone: {q.get('tone_used', 'N/A')}")
                            print(f"    - Language: {q.get('language', 'N/A')}")
                            print(f"    - Matched requirements: {len(q.get('matched_requirements', []))}")
                            print(f"    - Red flags: {len(q.get('red_flags', []))}")
                else:
                    print(f"Response (first 200 chars): {response[:200]}")
                    
            except json.JSONDecodeError:
                print(f"Response (first 300 chars):")
                print(response[:300])
        else:
            print("✗ Empty response from agent")
            return False
            
    except Exception as e:
        print(f"✗ Error getting response: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 80)
    print("✓ WORKFLOW TEST COMPLETED SUCCESSFULLY")
    print("=" * 80 + "\n")
    
    return True


if __name__ == "__main__":
    success = test_workflow()
    sys.exit(0 if success else 1)

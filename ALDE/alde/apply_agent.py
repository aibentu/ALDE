from datetime import datetime
import json
import sys
try:
    from .agents_ccompletion import ChatCom  # type: ignore
    
    import ChatCom  # type: ignore
except Exception:
    import os
    import sys

    _pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _pkg_parent not in sys.path:
        sys.path.insert(0, _pkg_parent)
    from alde.chat_completion import ChatCom  # type: ignore

try:
    from . import agents_factory  # type: ignore
except Exception:
    import alde.agents_factory as agents_factory  # type: ignore
from langchain_community.document_loaders import PyPDFLoader
try:
    from .agents_config import get_specialized_system_prompt, get_system_prompt  # type: ignore
except Exception:
    from ALDE.alde.agents_config import get_specialized_system_prompt, get_system_prompt  # type: ignore

def run_agent(job_data: dict, applicant_profile: dict) -> str:
    """
    Führt den Cover Letter Generator Agenten aus.
    Args:
        job_data (dict): Strukturierte Job Posting Daten.
        applicant_profile (dict): Strukturierte Bewerberprofil Daten.
    Returns:
        str: Generiertes Bewerbungsanschreiben im strukturierten Format.
    """
    # Erst Job Posting parsen
    parser_prompt = get_specialized_system_prompt("parser", "job_posting")
    parsed_job = ChatCom(
        _model="gpt-4.1",
        _input_text=f"{parser_prompt}\n\n{job_data}"
    ).get_response()
    
    # Dann Cover Letter generieren mit geparstem Job + Profil
    writer_prompt = get_specialized_system_prompt("writer", "cover_letter")
    prompt = f"""{writer_prompt}

**Aktuelles Datum:** {datetime.now().strftime("%d. %B %Y")} 

**Job Posting Daten:**
{parsed_job}

**Bewerber Profil:**
{json.dumps(applicant_profile, indent=2, ensure_ascii=False)}
"""
    response = ChatCom(_model="gpt-4.1", _input_text=prompt).get_response()
    return response


if __name__ == "__main__":
    # Example usage - this will fail without a valid PDF path
    # To test this code, provide your own job posting PDF path
    
    if len(sys.argv) < 2:
        print("Usage: python apply_agent.py <path_to_job_posting.pdf>")
        print("Example: python apply_agent.py /path/to/job_posting.pdf")
        sys.exit(1)
    
    job_pdf_path = sys.argv[1]
    
    # Applicant Profile laden
    applicant_profile = {"profile_prompt": get_system_prompt("_profile_parser")}
    # Job PDF laden
    job_data = PyPDFLoader(job_pdf_path).load()
    
    # Cover Letter generieren
    result = run_agent(job_data, applicant_profile)
    
    # Response ist ein JSON-String, muss erst geparsed werden
    try:
        result_dict = json.loads(result.strip())
        print(result_dict['cover_letter']['full_text'])
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # Falls kein JSON oder falsches Format, ganzen Text ausgeben
        print(result)
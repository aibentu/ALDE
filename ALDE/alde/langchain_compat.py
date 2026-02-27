#!/usr/bin/env python3
"""
LangChain compatibility wrapper to handle import errors gracefully
"""

def try_import_langchain():
    """Try to import LangChain with fallback for missing functions"""
    try:
        # Test the problematic import
        from langchain_core.utils.function_calling import convert_to_json_schema
        return True
    except ImportError as e:
        print(f"Warning: LangChain import error: {e}")
        print("This may be a version compatibility issue.")
        print("The vector store functionality may be limited.")
        return False

if __name__ == "__main__":
    result = try_import_langchain()
    if result:
        print("✓ LangChain imports working correctly")
    else:
        print("❌ LangChain import issues detected")
        print("Consider updating or downgrading LangChain packages:")
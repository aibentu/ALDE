"""
Example: OpenAI API Calls mit Exponential Backoff Retry

Zeigt verschiedene Möglichkeiten, wie man die error_recovery.py 
Retry-Logik auf OpenAI API Calls anwenden kann.
"""

import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
from openai import OpenAI


# Avoid writing chat history files during tests while still logging events.
os.environ.setdefault("AI_IDE_HISTORY_AUTOSAVE", "0")
os.environ.setdefault("AI_IDE_DISABLE_HISTORY_FLUSH", "1")

# Setup logging to see retry messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Import retry functionality
try:
    from error_recovery import retry, execute_with_retry
except ImportError:
    print("ERROR: error_recovery.py not found!")
    raise

# Import OpenAI error types
try:
    from openai import (
        RateLimitError,      # 429 - Rate limit exceeded
        APITimeoutError,     # Request timeout
        APIConnectionError,  # Network connection error
        InternalServerError, # 500+ server errors
        AuthenticationError, # 401 - Invalid API key (PERMANENT)
        BadRequestError,     # 400 - Invalid parameters (PERMANENT)
    )
except ImportError:
    # Fallback for older openai versions
    print("WARNING: Could not import specific OpenAI error types")
    RateLimitError = Exception
    APITimeoutError = TimeoutError
    APIConnectionError = ConnectionError
    InternalServerError = Exception
    AuthenticationError = Exception
    BadRequestError = ValueError


def _try_chathistory_log(event: str, *, data: dict | None = None) -> None:
    """Best-effort ChatHistory logging for tests.

    Must never break tests (missing deps, import path issues, etc.).
    """
    try:
        # Ensure repo package root is importable when running this file directly.
        pkg_root = Path(__file__).resolve().parents[2]  # .../ALDE/ALDE
        if str(pkg_root) not in sys.path:
            sys.path.insert(0, str(pkg_root))

        try:
            from alde.chat_completion import ChatHistory  # type: ignore
        except Exception:
            return

        ChatHistory().log(
            _role="tool",
            _content=event,
            _obj="model",
            _data=data or {},
            _thread_name="model",
            _name_tool="openai.chat.completions.create",
        )
    except Exception:
        return


# ============================================================================
# Example 1: Simple Chat Completion with @retry decorator
# ============================================================================

client = OpenAI()  # Uses OPENAI_API_KEY from environment

@retry(
    max_retries=4,
    transient_errors=(
        RateLimitError,
        APITimeoutError,
        APIConnectionError,
        TimeoutError,
        ConnectionError
    ),
    permanent_errors=(
        AuthenticationError,
        BadRequestError,
    ),
    name="openai_chat_simple"
)
def simple_chat(message: str, model: str = "gpt-4o-mini") -> str:
    """Simple chat completion with automatic retry.
    
    Args:
        message: User message
        model: OpenAI model name
        
    Returns:
        Assistant's response text
    """
    _try_chathistory_log(
        "openai.chat.completions.create request",
        data={"model": model, "n_messages": 1, "name": "simple_chat"},
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": message}
            ]
        )
    except Exception as exc:
        _try_chathistory_log(
            "openai.chat.completions.create error",
            data={"model": model, "name": "simple_chat", "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    _try_chathistory_log(
        "openai.chat.completions.create response",
        data={"model": model, "name": "simple_chat", "response_id": getattr(response, "id", None)},
    )
    return response.choices[0].message.content


# ============================================================================
# Example 2: Chat with conversation history
# ============================================================================

@retry(
    max_retries=3,
    transient_errors=(RateLimitError, APITimeoutError, APIConnectionError),
    name="openai_chat_conversation"
)
def chat_with_history(
    messages: List[Dict[str, str]], 
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> Dict[str, Any]:
    """Chat completion with conversation history.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        model: OpenAI model name
        temperature: Sampling temperature
        max_tokens: Max tokens in response
        
    Returns:
        Full response object as dict
    """
    _try_chathistory_log(
        "openai.chat.completions.create request",
        data={"model": model, "n_messages": len(messages), "temperature": temperature, "max_tokens": max_tokens, "name": "chat_with_history"},
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
    except Exception as exc:
        _try_chathistory_log(
            "openai.chat.completions.create error",
            data={"model": model, "name": "chat_with_history", "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    _try_chathistory_log(
        "openai.chat.completions.create response",
        data={"model": model, "name": "chat_with_history", "response_id": getattr(response, "id", None)},
    )
    
    # Return as dict for easier handling
    return {
        'content': response.choices[0].message.content,
        'role': response.choices[0].message.role,
        'finish_reason': response.choices[0].finish_reason,
        'usage': {
            'prompt_tokens': response.usage.prompt_tokens,
            'completion_tokens': response.usage.completion_tokens,
            'total_tokens': response.usage.total_tokens
        }
    }


# ============================================================================
# Example 3: Function calling with tools
# ============================================================================

@retry(
    max_retries=4,
    transient_errors=(RateLimitError, APITimeoutError, APIConnectionError),
    name="openai_function_calling"
)
def chat_with_tools(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    model: str = "gpt-4o-mini"
):
    """Chat with function/tool calling support.
    
    Args:
        messages: Conversation messages
        tools: Tool definitions for function calling
        model: OpenAI model name
        
    Returns:
        Response object
    """
    _try_chathistory_log(
        "openai.chat.completions.create request",
        data={"model": model, "n_messages": len(messages), "has_tools": bool(tools), "name": "chat_with_tools"},
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice='auto'
        )
    except Exception as exc:
        _try_chathistory_log(
            "openai.chat.completions.create error",
            data={"model": model, "name": "chat_with_tools", "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    _try_chathistory_log(
        "openai.chat.completions.create response",
        data={"model": model, "name": "chat_with_tools", "response_id": getattr(response, "id", None)},
    )
    return response


# ============================================================================
# Example 4: Using execute_with_retry directly (more control)
# ============================================================================

def advanced_chat_with_retry(
    messages: List[Dict[str, str]],
    model: str = "gpt-4o-mini",
    max_retries: int = 3,
    **kwargs
):
    """
    Chat completion using execute_with_retry directly for more control.
    
    This approach allows dynamic configuration of retry parameters.
    """
    def make_api_call():
        _try_chathistory_log(
            "openai.chat.completions.create request",
            data={"model": model, "n_messages": len(messages), "name": "advanced_chat_with_retry"},
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
        except Exception as exc:
            _try_chathistory_log(
                "openai.chat.completions.create error",
                data={"model": model, "name": "advanced_chat_with_retry", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        _try_chathistory_log(
            "openai.chat.completions.create response",
            data={"model": model, "name": "advanced_chat_with_retry", "response_id": getattr(resp, "id", None)},
        )
        return resp
    
    response = execute_with_retry(
        tool_name=f"openai_chat_{model}",
        callable_func=make_api_call,
        max_retries=max_retries,
        transient_errors=(
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            TimeoutError
        ),
        permanent_errors=(
            AuthenticationError,
            BadRequestError
        )
    )
    
    return response.choices[0].message.content


# ============================================================================
# Example 5: Class-based implementation (like ChatCompletion)
# ============================================================================

class ResilientChatClient:
    """OpenAI Chat Client with built-in retry logic."""
    
    def __init__(self, api_key: str = None, max_retries: int = 3):
        """Initialize client with retry configuration.
        
        Args:
            api_key: OpenAI API key (uses env var if None)
            max_retries: Default number of retries for API calls
        """
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self.max_retries = max_retries
    
    @retry(
        max_retries=4,
        transient_errors=(RateLimitError, APITimeoutError, APIConnectionError),
        permanent_errors=(AuthenticationError, BadRequestError),
        name="resilient_chat_create"
    )
    def create_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        **kwargs
    ):
        """Create chat completion with automatic retry.
        
        This method automatically retries on transient failures with
        exponential backoff (1s, 2s, 4s, 8s).
        """
        _try_chathistory_log(
            "openai.chat.completions.create request",
            data={"model": model, "n_messages": len(messages), "name": "ResilientChatClient.create_completion"},
        )
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
        except Exception as exc:
            _try_chathistory_log(
                "openai.chat.completions.create error",
                data={"model": model, "name": "ResilientChatClient.create_completion", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        _try_chathistory_log(
            "openai.chat.completions.create response",
            data={"model": model, "name": "ResilientChatClient.create_completion", "response_id": getattr(resp, "id", None)},
        )
        return resp
    
    def chat(self, user_message: str, system_prompt: str = None) -> str:
        """Simple chat interface.
        
        Args:
            user_message: User's message
            system_prompt: Optional system prompt
            
        Returns:
            Assistant's response
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        
        response = self.create_completion(messages)
        return response.choices[0].message.content


# ============================================================================
# Example 6: Batch processing with retry
# ============================================================================

@retry(
    max_retries=5,  # More retries for batch jobs (max 31s wait)
    transient_errors=(RateLimitError, APITimeoutError, APIConnectionError),
    name="batch_process_single"
)
def process_single_item(text: str, model: str = "gpt-4o-mini") -> str:
    """Process a single item with retry."""
    _try_chathistory_log(
        "openai.chat.completions.create request",
        data={"model": model, "n_messages": 2, "name": "process_single_item"},
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Summarize the following text in one sentence."},
                {"role": "user", "content": text}
            ]
        )
    except Exception as exc:
        _try_chathistory_log(
            "openai.chat.completions.create error",
            data={"model": model, "name": "process_single_item", "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    _try_chathistory_log(
        "openai.chat.completions.create response",
        data={"model": model, "name": "process_single_item", "response_id": getattr(response, "id", None)},
    )
    return response.choices[0].message.content


def batch_process_texts(texts: List[str]) -> List[str]:
    """Process multiple texts with automatic retry per item.
    
    Each item is retried independently if it fails.
    """
    results = []
    
    for i, text in enumerate(texts, 1):
        print(f"\nProcessing item {i}/{len(texts)}...")
        try:
            result = process_single_item(text)
            results.append(result)
            print(f"✓ Item {i} completed")
        except Exception as e:
            print(f"✗ Item {i} failed permanently: {e}")
            results.append(f"ERROR: {e}")
    
    return results


# ============================================================================
# Demo / Testing
# ============================================================================

def run_examples():
    """Run all examples to demonstrate retry behavior."""
    
    print("\n" + "="*70)
    print("OPENAI API RETRY EXAMPLES")
    print("="*70)
    
    # Example 1: Simple chat
    print("\n--- Example 1: Simple Chat ---")
    try:
        response = simple_chat("What is the capital of France?")
        print(f"Response: {response}")
    except Exception as e:
        print(f"Failed: {e}")
    
    # Example 2: Chat with history
    print("\n--- Example 2: Chat with History ---")
    try:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"},
        ]
        response = chat_with_history(messages)
        print(f"Response: {response['content']}")
        print(f"Tokens used: {response['usage']['total_tokens']}")
    except Exception as e:
        print(f"Failed: {e}")
    
    # Example 3: Class-based client
    print("\n--- Example 3: ResilientChatClient ---")
    try:
        client_instance = ResilientChatClient()
        response = client_instance.chat(
            user_message="Tell me a short joke",
            system_prompt="You are a comedian"
        )
        print(f"Response: {response}")
    except Exception as e:
        print(f"Failed: {e}")
    
    # Example 4: Batch processing
    print("\n--- Example 4: Batch Processing ---")
    try:
        texts = [
            "Python is a high-level programming language known for its simplicity.",
            "Machine learning is a subset of artificial intelligence.",
            "The quick brown fox jumps over the lazy dog."
        ]
        summaries = batch_process_texts(texts)
        for i, summary in enumerate(summaries, 1):
            print(f"{i}. {summary}")
    except Exception as e:
        print(f"Batch failed: {e}")
    
    print("\n" + "="*70)
    print("All examples completed!")
    print("="*70 + "\n")


if __name__ == "__main__":
    # Run examples if OPENAI_API_KEY is set
    import os
    if os.getenv("OPENAI_API_KEY"):
        run_examples()
    else:
        print("\n⚠️  OPENAI_API_KEY not set in environment")
        print("Set it to run the examples:")
        print('    export OPENAI_API_KEY="sk-..."')
        print("\nShowing code structure only (no actual API calls)\n")

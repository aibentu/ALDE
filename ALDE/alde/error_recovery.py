"""Module for automatic retry logic with exponential backoff.

This module implements the retry logic documented in:
├── ALDE/alde/MAS_REACT_MATHEMATICAL_PATTERNS.md
└── Section 9: Error Propagation & Recovery

Features:
- Exponential backoff: 1s, 2s, 4s, ... (2^n formula)
- Decorator-based syntax for clean code
- Distinguishes between transient and permanent errors
- Comprehensive logging for debugging
- Mathematical utilities for analysis

Quick Start:
    from error_recovery import retry
    
    @retry(max_retries=3)
    def fetch_data(url):
        import requests
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    
    data = fetch_data("https://api.example.com/data")
"""

import time
import logging
from typing import Callable, TypeVar, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)

# Type variable for generic retry decorator
T = TypeVar('T')


class TransientError(Exception):
    """Raised for transient errors that can be retried.
    
    Transient errors are temporary failures that may succeed on retry:
    - Network timeouts
    - Connection refused
    - HTTP 5xx errors (Server Error)
    - Rate limiting (HTTP 429 Too Many Requests)
    - Temporary service unavailability
    """
    pass


class PermanentError(Exception):
    """Raised for permanent errors that should not be retried.
    
    Permanent errors will fail again on retry:
    - Invalid input (ValueError)
    - Type errors (TypeError)
    - Missing attributes (AttributeError)
    - Invalid configuration
    - Authentication failures (invalid credentials)
    """
    pass


def execute_with_retry(
    tool_name: str,
    callable_func: Callable[[], Any],
    max_retries: int = 3,
    transient_errors: tuple = (TransientError, TimeoutError, ConnectionError),
    permanent_errors: tuple = (ValueError, TypeError, AttributeError)
) -> Any:
    """Execute a callable with exponential backoff retry.
    
    This is the core retry function that implements exponential backoff
    as documented in MAS_REACT_MATHEMATICAL_PATTERNS.md Section 9.
    
    ╔════════════════════════════════════════════════════════════════╗
    ║ EXPONENTIAL BACKOFF FORMULA                                    ║
    ║  Wait time for attempt n: t_n = 2^n seconds                    ║
    ║                                                                ║
    ║ Default (max_retries=3):                                       ║
    ║   Attempt 1 fails: wait 1s (2^0)                               ║
    ║   Attempt 2 fails: wait 2s (2^1)                               ║
    ║   Attempt 3 fails: wait 4s (2^2)                               ║
    ║   ─────────────────────────────                                ║
    ║   Total wait:   7s                                             ║
    ╚════════════════════════════════════════════════════════════════╝
    
    Args:
        tool_name (str): 
            Name of the tool/operation for logging
        callable_func (Callable): 
            Function to execute (takes no arguments). Should raise
            an exception on failure.
        max_retries (int): 
            Maximum number of attempts. Default: 3
        transient_errors (tuple): 
            Exception types that trigger retry. Default:
            (TransientError, TimeoutError, ConnectionError)
        permanent_errors (tuple): 
            Exception types that fail immediately. Default:
            (ValueError, TypeError, AttributeError)
    
    Returns:
        Any: Result from successful execution
    
    Raises:
        Exception: The last exception raised if all retries exhausted,
                  or immediately for permanent errors
    
    Example:
        >>> def fetch_data():
        ...     import requests
        ...     response = requests.get("https://api.example.com/data")
        ...     return response.json()
        >>> 
        >>> result = execute_with_retry(
        ...     tool_name="fetch_data",
        ...     callable_func=fetch_data,
        ...     max_retries=3
        ... )
    
    Logging Output:
        INFO:  ✓ operation_name succeeded on retry N/max_retries
        WARNING: ⚠ operation_name attempt N/M failed (ErrorType). Retrying in Ns...
        ERROR: ✗ operation_name failed with permanent error: ErrorType: message
        ERROR: ✗ operation_name failed after M attempts. Last error: ErrorType: message
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            result = callable_func()
            if attempt > 0:
                logger.info(f"✓ {tool_name} succeeded on retry {attempt + 1}/{max_retries}")
            return result
        
        except permanent_errors as e:
            # Don't retry permanent errors
            logger.error(f"✗ {tool_name} failed with permanent error: {type(e).__name__}: {e}")
            raise
        
        except transient_errors as e:
            last_exception = e
            
            if attempt == max_retries - 1:
                # Final attempt failed
                logger.error(
                    f"✗ {tool_name} failed after {max_retries} attempts. "
                    f"Last error: {type(e).__name__}: {e}"
                )
                raise
            
            # Exponential backoff: 2^n seconds
            wait_time = 2 ** attempt
            logger.warning(
                f"⚠ {tool_name} attempt {attempt + 1}/{max_retries} failed "
                f"({type(e).__name__}). Retrying in {wait_time}s..."
            )
            time.sleep(wait_time)
        
        except Exception as e:
            # Unknown error type - treat as permanent
            logger.error(f"✗ {tool_name} failed with unexpected error: {type(e).__name__}: {e}")
            raise
    
    # Should never reach here, but just in case
    raise last_exception or RuntimeError(f"{tool_name} execution failed")


def retry(
    max_retries: int = 3,
    transient_errors: tuple = (TransientError, TimeoutError, ConnectionError),
    permanent_errors: tuple = (ValueError, TypeError, AttributeError),
    name: Optional[str] = None
):
    """Decorator for automatic retry with exponential backoff.
    
    Wraps a function to automatically retry on transient failures with
    exponential backoff delays. Clean, Pythonic interface.
    
    Args:
        max_retries (int): 
            Maximum number of attempts. Default: 3
        transient_errors (tuple): 
            Exception types to retry on. Default:
            (TransientError, TimeoutError, ConnectionError)
        permanent_errors (tuple): 
            Exception types to fail immediately. Default:
            (ValueError, TypeError, AttributeError)
        name (str, optional): 
            Custom name for logging. Defaults to function name.
    
    Returns:
        Decorator function that wraps the target function
    
    Example - Simple HTTP API retry:
        >>> from error_recovery import retry
        >>> 
        >>> @retry(max_retries=3)
        ... def fetch_weather(city):
        ...     import requests
        ...     response = requests.get(
        ...         f"https://api.weather.com/weather/{city}"
        ...     )
        ...     response.raise_for_status()
        ...     return response.json()
        >>> 
        >>> weather = fetch_weather("Berlin")
    
    Example - Custom error handling:
        >>> @retry(
        ...     max_retries=5,
        ...     transient_errors=(TimeoutError, ConnectionError),
        ...     permanent_errors=(ValueError, KeyError),
        ...     name="database_query"
        ... )
        ... def query_database(sql):
        ...     # Your database query here
        ...     pass
    
    Behavior:
        - Transient errors: Retry with exponential backoff (1s, 2s, 4s, ...)
        - Permanent errors: Fail immediately without retry
        - All other exceptions: Treated as permanent (fail immediately)
        
    Logging:
        Configure Python logging to see detailed retry messages:
        
        >>> import logging
        >>> logging.basicConfig(
        ...     level=logging.INFO,
        ...     format='%(levelname)s: %(message)s'
        ... )
        
        Then your decorated functions will output:
        - WARNING: ⚠ function_name attempt 1/3 failed (TimeoutError). Retrying in 1s...
        - WARNING: ⚠ function_name attempt 2/3 failed (TimeoutError). Retrying in 2s...
        - INFO: ✓ function_name succeeded on retry 3/3
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = name or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            def call_func():
                return func(*args, **kwargs)
            
            return execute_with_retry(
                tool_name=func_name,
                callable_func=call_func,
                max_retries=max_retries,
                transient_errors=transient_errors,
                permanent_errors=permanent_errors
            )
        
        return wrapper
    
    return decorator


def calculate_backoff_time(attempt: int) -> float:
    """Calculate wait time for exponential backoff.
    
    Formula:  t_n = 2^n seconds (where n = attempt number, 0-indexed)
    
    Args:
        attempt (int): 0-indexed attempt number
    
    Returns:
        float: Wait time in seconds
    
    Example:
        >>> calculate_backoff_time(0)
        1
        >>> calculate_backoff_time(1)
        2
        >>> calculate_backoff_time(2)
        4
        >>> calculate_backoff_time(3)
        8
    
    Sequence (first 6 attempts):
        Attempt 0: 2^0 = 1s
        Attempt 1: 2^1 = 2s
        Attempt 2: 2^2 = 4s
        Attempt 3: 2^3 = 8s
        Attempt 4: 2^4 = 16s
        Attempt 5: 2^5 = 32s
    """
    return float(2 ** attempt)


def calculate_total_backoff_time(num_retries: int) -> float:
    """Calculate total wait time for all retries.
    
    Formula:  T_total = Σ(2^n) = 2^k - 1
              where k = num_retries, sum from n=0 to k-1
    
    This is useful for calculating timeouts and understanding
    how long a retry sequence will take in the worst case.
    
    Args:
        num_retries (int): Number of retries
    
    Returns:
        float: Total cumulative wait time in seconds
    
    Example:
        >>> calculate_total_backoff_time(1)
        1.0
        >>> calculate_total_backoff_time(2)
        3.0
        >>> calculate_total_backoff_time(3)
        7.0
        >>> calculate_total_backoff_time(4)
        15.0
        >>> calculate_total_backoff_time(5)
        31.0
    
    Mathematical Breakdown (num_retries=3):
        Retry 0: 2^0 = 1
        Retry 1: 2^1 = 2
        Retry 2: 2^2 = 4
        ───────────────
        Total  = 7 = 2^3 - 1 ✓
    
    Real-world Example:
        If you set max_retries=4:
        - Total wait time: 15 seconds
        - Useful for setting timeout: timeout = 15 + response_time
    """
    return float(sum(2 ** attempt for attempt in range(num_retries)))


def success_probability(failure_rate: float, num_attempts: int) -> float:
    """
    Calculate probability of success given failure rate and number of attempts.
    
    Formula: P(success within k attempts) = 1 - p^k
    where p = per-attempt failure probability
    
    Args:
        failure_rate: Probability of failure per attempt (0.0 to 1.0)
        num_attempts: Number of attempts
    
    Returns:
        Probability of success (0.0 to 1.0)
    
    Example:
        >>> success_probability(0.1, 1)  # 90% on first try
        0.9
        >>> success_probability(0.1, 3)  # 99.9% after 3 tries
        0.999
    """
    return 1.0 - (failure_rate ** num_attempts)

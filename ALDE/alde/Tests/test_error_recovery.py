"""
Exponential Backoff Usage Examples & Tests

Demonstrates how to use the error_recovery module for
automatic retry with exponential backoff.
"""

import logging
from error_recovery import (
    execute_with_retry,
    retry,
    TransientError,
    PermanentError,
    calculate_backoff_time,
    calculate_total_backoff_time,
    success_probability
)

# Setup logging to see retry messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# ============================================================================
# Example 1: Using execute_with_retry() directly
# ============================================================================

def example_1_direct_call():
    """Example using execute_with_retry() function directly."""
    print("\n" + "="*70)
    print("Example 1: Direct execute_with_retry() call")
    print("="*70)
    
    attempt_count = 0
    
    def unstable_api_call():
        """Simulates an API that fails twice then succeeds."""
        nonlocal attempt_count
        attempt_count += 1
        
        if attempt_count < 3:
            # Simulate transient network error
            raise ConnectionError(f"Network timeout on attempt {attempt_count}")
        
        return {"status": "success", "data": "API response"}
    
    try:
        result = execute_with_retry(
            tool_name="unstable_api_call",
            callable_func=unstable_api_call,
            max_retries=3,
            transient_errors=(ConnectionError, TimeoutError)
        )
        print(f"\n✓ SUCCESS: {result}")
    except Exception as e:
        print(f"\n✗ FAILED: {e}")


# ============================================================================
# Example 2: Using @retry decorator
# ============================================================================

def example_2_decorator():
    """Example using @retry decorator for cleaner code."""
    print("\n" + "="*70)
    print("Example 2: Using @retry decorator")
    print("="*70)
    
    attempt_count = 0
    
    @retry(max_retries=3, name="fetch_user_data")
    def fetch_user_data(user_id: int):
        """Simulates fetching user data with temporary failures."""
        nonlocal attempt_count
        attempt_count += 1
        
        if attempt_count == 1:
            raise TimeoutError("Connection timeout")
        
        return {"user_id": user_id, "name": "John Doe", "email": "john@example.com"}
    
    try:
        result = fetch_user_data(123)
        print(f"\n✓ SUCCESS: {result}")
    except Exception as e:
        print(f"\n✗ FAILED: {e}")


# ============================================================================
# Example 3: Permanent vs Transient Errors
# ============================================================================

def example_3_error_types():
    """Example showing difference between transient and permanent errors."""
    print("\n" + "="*70)
    print("Example 3: Permanent vs Transient Errors")
    print("="*70)
    
    # This will FAIL immediately (permanent error)
    @retry(max_retries=3, permanent_errors=(ValueError,))
    def validate_email(email: str):
        if "@" not in email:
            raise ValueError(f"Invalid email format: {email}")
        return f"Valid email: {email}"
    
    try:
        result = validate_email("invalid-email")
        print(f"\n✓ SUCCESS: {result}")
    except Exception as e:
        print(f"\n✗ FAILED (immediately, no retries): {e}")


# ============================================================================
# Example 4: Mathematical Calculations
# ============================================================================

def example_4_backoff_math():
    """Example showing backoff time calculations."""
    print("\n" + "="*70)
    print("Example 4: Exponential Backoff Time Calculations")
    print("="*70)
    
    print("\nIndividual wait times (2^n seconds):")
    for attempt in range(5):
        wait_time = calculate_backoff_time(attempt)
        print(f"  Attempt {attempt}: wait {wait_time}s")
    
    print("\nTotal cumulative wait times (2^k - 1):")
    for num_retries in range(1, 6):
        total = calculate_total_backoff_time(num_retries)
        print(f"  {num_retries} retries: total {total}s")
    
    print("\nSuccess probability (p=0.1 failure rate):")
    failure_rate = 0.1
    for attempts in range(1, 6):
        prob = success_probability(failure_rate, attempts)
        prob_pct = prob * 100
        print(f"  {attempts} attempt(s): {prob_pct:.1f}% success")


# ============================================================================
# Example 5: Real-world HTTP API retry pattern
# ============================================================================

def example_5_http_api():
    """Example showing realistic HTTP API retry usage."""
    print("\n" + "="*70)
    print("Example 5: Real-world HTTP API Pattern")
    print("="*70)
    
    attempt_count = 0
    
    @retry(
        max_retries=4,
        transient_errors=(TimeoutError, ConnectionError),
        permanent_errors=(ValueError, TypeError),
        name="fetch_weather_data"
    )
    def fetch_weather_api(city: str) -> dict:
        """Fetch weather data from API with automatic retry."""
        nonlocal attempt_count
        attempt_count += 1
        
        # Simulate various failure scenarios
        if attempt_count == 1:
            raise ConnectionError("Connection refused")
        if attempt_count == 2:
            raise TimeoutError("Request timeout")
        
        # Success on 3rd try
        return {
            "city": city,
            "temperature": 25,
            "humidity": 65,
            "condition": "Sunny"
        }
    
    try:
        result = fetch_weather_api("Berlin")
        print(f"\n✓ SUCCESS: Weather for {result['city']}: {result['condition']}, {result['temperature']}°C")
    except Exception as e:
        print(f"\n✗ FAILED: {e}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("EXPONENTIAL BACKOFF & ERROR RECOVERY MODULE - EXAMPLES")
    print("="*70)
    
    example_1_direct_call()
    example_2_decorator()
    example_3_error_types()
    example_4_backoff_math()
    example_5_http_api()
    
    print("\n" + "="*70)
    print("All examples completed!")
    print("="*70 + "\n")

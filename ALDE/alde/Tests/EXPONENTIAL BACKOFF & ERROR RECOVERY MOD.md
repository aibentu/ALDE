
======================================================================
EXPONENTIAL BACKOFF & ERROR RECOVERY MODULE - EXAMPLES
======================================================================

======================================================================
Example 1: Direct execute_with_retry() call
======================================================================
2026-02-02 19:18:41,113 - error_recovery - WARNING - ⚠ unstable_api_call attempt 1/3 failed (ConnectionError). Retrying in 1s...
2026-02-02 19:18:42,113 - error_recovery - WARNING - ⚠ unstable_api_call attempt 2/3 failed (ConnectionError). Retrying in 2s...
2026-02-02 19:18:44,113 - error_recovery - INFO - ✓ unstable_api_call succeeded on retry 3/3

✓ SUCCESS: {'status': 'success', 'data': 'API response'}

======================================================================
Example 2: Using @retry decorator
======================================================================
2026-02-02 19:18:44,113 - error_recovery - WARNING - ⚠ fetch_user_data attempt 1/3 failed (TimeoutError). Retrying in 1s...
2026-02-02 19:18:45,114 - error_recovery - INFO - ✓ fetch_user_data succeeded on retry 2/3

✓ SUCCESS: {'user_id': 123, 'name': 'John Doe', 'email': 'john@example.com'}

======================================================================
Example 3: Permanent vs Transient Errors
======================================================================
2026-02-02 19:18:45,114 - error_recovery - ERROR - ✗ validate_email failed with permanent error: ValueError: Invalid email format: invalid-email

✗ FAILED (immediately, no retries): Invalid email format: invalid-email

======================================================================
Example 4: Exponential Backoff Time Calculations
======================================================================

Individual wait times (2^n seconds):
  Attempt 0: wait 1.0s
  Attempt 1: wait 2.0s
  Attempt 2: wait 4.0s
  Attempt 3: wait 8.0s
  Attempt 4: wait 16.0s

Total cumulative wait times (2^k - 1):
  1 retries: total 1.0s
  2 retries: total 3.0s
  3 retries: total 7.0s
  4 retries: total 15.0s
  5 retries: total 31.0s

Success probability (p=0.1 failure rate):
  1 attempt(s): 90.0% success
  2 attempt(s): 99.0% success
  3 attempt(s): 99.9% success
  4 attempt(s): 100.0% success
  5 attempt(s): 100.0% success

======================================================================
Example 5: Real-world HTTP API Pattern
======================================================================
2026-02-02 19:18:45,114 - error_recovery - WARNING - ⚠ fetch_weather_data attempt 1/4 failed (ConnectionError). Retrying in 1s...
2026-02-02 19:18:46,115 - error_recovery - WARNING - ⚠ fetch_weather_data attempt 2/4 failed (TimeoutError). Retrying in 2s...
2026-02-02 19:18:48,115 - error_recovery - INFO - ✓ fetch_weather_data succeeded on retry 3/4

✓ SUCCESS: Weather for Berlin: Sunny, 25°C

======================================================================
All examples completed!
======================================================================
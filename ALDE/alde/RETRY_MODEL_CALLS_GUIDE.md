# Exponential Backoff für LLM Model Calls

## Auswirkungen der Retry-Implementierung auf Model API Calls

Die Implementierung von Exponential Backoff für LLM API Calls (OpenAI, Anthropic, etc.) hat mehrere wichtige Auswirkungen:

---

## 🎯 Vorteile

### 1. **Rate Limit Handling**
```
Ohne Retry:
❌ RateLimitError → Anwendung crashed oder gibt Fehler zurück

Mit Retry:
✓ RateLimitError → Wartet 1s → 2s → 4s → Erfolg
✓ 99.9% Erfolgschance statt sofortigem Fehler
```

### 2. **Kosten-Optimierung**
- Verhindert verlorene API Calls (jeder Call kostet Geld!)
- Weniger manuelle Re-Runs nötig
- Automatisches Recovery statt User-Intervention

### 3. **Zuverlässigkeit**
```
Transiente Fehler:
- Network Timeouts
- Rate Limits (429 Too Many Requests)
- Server Errors (500, 502, 503, 504)
- Temporary Service Unavailable

→ Alle werden automatisch behandelt!
```

### 4. **User Experience**
- Keine sichtbaren Fehler bei temporären Problemen
- Transparente Fehlerbehandlung
- Logs zeigen genau, was passiert

---

## ⚠️ Wichtige Überlegungen

### API-Spezifische Fehlertypen

**OpenAI API:**
```python
from openai import (
    RateLimitError,      # 429 - zu viele Requests
    APITimeoutError,     # Request timeout
    APIConnectionError,  # Netzwerk-Problem
    InternalServerError, # 500+ Server-Fehler
    AuthenticationError, # 401 - PERMANENT!
    BadRequestError,     # 400 - PERMANENT!
)
```

**Transient (retry):**
- `RateLimitError` - Rate Limit überschritten
- `APITimeoutError` - Timeout
- `APIConnectionError` - Netzwerkfehler
- `InternalServerError` - Server temporär down

**Permanent (nicht retry):**
- `AuthenticationError` - Ungültiger API Key
- `BadRequestError` - Ungültige Parameter
- `InvalidRequestError` - Falsches Format

---

## 💡 Implementierungs-Beispiele

### Beispiel 1: Einfache OpenAI Chat Completion mit Retry

```python
from error_recovery import retry
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError

client = OpenAI(api_key="sk-...")

@retry(
    max_retries=4,
    transient_errors=(
        RateLimitError, 
        APITimeoutError, 
        APIConnectionError,
        TimeoutError,
        ConnectionError
    ),
    name="openai_chat_completion"
)
def chat_completion(messages, model="gpt-4o", **kwargs):
    """OpenAI Chat Completion mit automatischem Retry."""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs
    )
    return response

# Verwendung (identisch wie vorher!)
result = chat_completion(
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**Auswirkung:**
```
Bei Rate Limit (429):
1. Attempt 1 fails (RateLimitError) → wait 1s
2. Attempt 2 fails (RateLimitError) → wait 2s  
3. Attempt 3 fails (RateLimitError) → wait 4s
4. Attempt 4 SUCCESS ✓

Statt sofortigem Fehler → 99.9% Success Rate!
```

---

### Beispiel 2: Integration in bestehenden ChatCompletion Code

**Vorher (chat_completion.py, Zeile 1132):**
```python
# OHNE Retry
response = self._client.chat.completions.create(
    model=model_name,
    messages=_input,
    tools=tools_arg,
    tool_choice='auto'
)
```

**Nachher - Option A (Decorator auf Methoden-Ebene):**
```python
from error_recovery import retry
from openai import RateLimitError, APITimeoutError, APIConnectionError

class ChatCom:
    @retry(
        max_retries=4,
        transient_errors=(
            RateLimitError,
            APITimeoutError, 
            APIConnectionError,
            TimeoutError
        ),
        permanent_errors=(
            AuthenticationError,  # Ungültiger API Key
            BadRequestError       # Ungültige Parameter
        ),
        name="openai_chat_call"
    )
    def _make_api_call(self, model_name, messages, tools_arg):
        """Wrapper für OpenAI Call mit Retry."""
        return self._client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools_arg,
            tool_choice='auto'
        )
    
    def chat(self, _input, model_name='gpt-4o-mini', ...):
        """Hauptmethode - ruft retry-gesicherten Call auf."""
        try:
            response = self._make_api_call(model_name, _input, tools_arg)
            # ... rest der Logik
        except Exception as exc:
            # Error handling
            pass
```

**Nachher - Option B (execute_with_retry direkt):**
```python
from error_recovery import execute_with_retry
from openai import RateLimitError, APITimeoutError, APIConnectionError

def _response(_input):
    """API Call als callable für execute_with_retry."""
    # ... existing code ...
    
    # Statt direktem Call:
    # response = self._client.chat.completions.create(...)
    
    # Mit Retry:
    def make_call():
        return self._client.chat.completions.create(
            model=model_name,
            messages=_input,
            tools=tools_arg,
            tool_choice='auto'
        )
    
    response = execute_with_retry(
        tool_name="openai_chat_api",
        callable_func=make_call,
        max_retries=4,
        transient_errors=(
            RateLimitError,
            APITimeoutError,
            APIConnectionError
        )
    )
    return response
```

---

### Beispiel 3: Streaming Responses mit Retry

```python
@retry(
    max_retries=3,
    transient_errors=(RateLimitError, APIConnectionError),
    name="openai_stream"
)
def stream_completion(messages, model="gpt-4o"):
    """Streaming Chat mit Retry."""
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True
    )
    return stream

# Verwendung
for chunk in stream_completion(messages):
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end='')
```

---

## 📊 Performance & Kosten-Analyse

### Szenario: Rate Limit während Peak-Zeit

**Ohne Retry:**
```
100 Requests → 15% schlagen fehl (Rate Limit)
✗ 15 verlorene Requests × $0.03 = $0.45 verschwendet
✗ User sieht Fehler, muss manuell wiederholen
✗ Schlechte User Experience
```

**Mit Retry (max_retries=4):**
```
100 Requests → 15% schlagen INITIAL fehl
✓ 99.9% werden nach Retry erfolgreich (siehe success_probability)
✓ Nur 0.001% finale Fehler
✓ $0.45 gespart
✓ Transparentes Handling
✓ User merkt nichts
```

**Total Wait Time bei 3 Retries:**
- Formel: 2^0 + 2^1 + 2^2 = 1 + 2 + 4 = **7 Sekunden max**
- Bei 4 Retries: **15 Sekunden max**
- Akzeptabel für bessere Reliability!

---

## 🔧 Praktische Konfiguration

### Empfohlene Settings für verschiedene Use Cases

#### 1. **Interaktive Chat-Anwendung**
```python
@retry(
    max_retries=3,  # Schnell, max 7s wait
    transient_errors=(RateLimitError, APITimeoutError),
    name="chat_ui"
)
```
**Begründung:** User wartet, aber nicht zu lange

#### 2. **Batch Processing / Background Jobs**
```python
@retry(
    max_retries=6,  # Ausdauernd, max 63s wait
    transient_errors=(RateLimitError, APITimeoutError, APIConnectionError),
    name="batch_processing"
)
```
**Begründung:** Kein User wartet, höhere Success-Rate wichtiger

#### 3. **Critical Production Calls**
```python
@retry(
    max_retries=5,  # Balance, max 31s wait
    transient_errors=(
        RateLimitError,
        APITimeoutError,
        APIConnectionError,
        InternalServerError
    ),
    permanent_errors=(
        AuthenticationError,
        BadRequestError,
        InvalidRequestError
    ),
    name="production_critical"
)
```
**Begründung:** Maximale Reliability bei vertretbarem Wait

---

## 📈 Success Probability Mathematik

**Bei 10% Transient Failure Rate:**

| Retries | Success Rate | Cumulative Wait |
|---------|--------------|-----------------|
| 1       | 90.0%        | 0s              |
| 2       | 99.0%        | 1s              |
| 3       | 99.9%        | 3s (1+2)        |
| 4       | 99.99%       | 7s (1+2+4)      |
| 5       | 99.999%      | 15s (1+2+4+8)   |

**Code zum Berechnen:**
```python
from error_recovery import success_probability, calculate_total_backoff_time

# 10% failure rate, 3 retries
prob = success_probability(0.1, 3)
wait = calculate_total_backoff_time(3)

print(f"Success: {prob*100:.2f}%")  # 99.90%
print(f"Max wait: {wait}s")          # 7s
```

---

## ⚡ Logging & Monitoring

**Mit aktiviertem Logging sieht man:**

```python
import logging
logging.basicConfig(level=logging.INFO)

# Bei API Call mit Retry:
```

**Output:**
```
WARNING: ⚠ openai_chat_completion attempt 1/4 failed (RateLimitError). Retrying in 1s...
WARNING: ⚠ openai_chat_completion attempt 2/4 failed (RateLimitError). Retrying in 2s...
INFO: ✓ openai_chat_completion succeeded on retry 3/4
```

**Vorteile:**
- Sichtbarkeit über Retry-Vorgänge
- Debugging von API-Problemen
- Monitoring von Rate Limits
- Analyse von Failure-Patterns

---

## 🚨 Wichtige Warnings

### 1. **Kosten bei vielen Retries**
```python
# VORSICHT: Bei sehr langen Requests!
@retry(max_retries=10)  # ⚠️ Bis zu 1023s (17min) wait!
def long_running_call():
    pass

# Besser: Moderate Retries
@retry(max_retries=4)  # ✓ Max 15s wait
```

### 2. **Streaming kann nicht vollständig retried werden**
Wenn Stream mittendrin abbricht, kann nur der ganze Call wiederholt werden (nicht ab Position X).

### 3. **Idempotenz sicherstellen**
Bei Retries wird die Funktion mehrfach ausgeführt:
- Keine Seiteneffekte in der retry-Funktion!
- Datenbankschreibvorgänge extern behandeln

---

## 📝 Zusammenfassung

### ✅ DO's
- Retry bei RateLimitError, Timeouts, Connection Errors
- Moderate max_retries (3-5) für interaktive Apps
- Logging aktivieren für Monitoring
- Permanent Errors (Auth, BadRequest) sofort fehlschlagen lassen

### ❌ DON'Ts  
- Nicht bei AuthenticationError retrien (sinnlos!)
- Nicht zu viele Retries (Kosten & Wartezeit)
- Nicht Seiteneffekte in retry-Funktionen
- Nicht Streaming-Calls halb retrien

---

## 🎬 Quick Start für bestehenden Code

**3 Schritte:**

1. **Import hinzufügen:**
```python
from error_recovery import retry
from openai import RateLimitError, APITimeoutError
```

2. **Decorator auf API-Call-Funktion:**
```python
@retry(
    max_retries=3,
    transient_errors=(RateLimitError, APITimeoutError),
    name="my_api_call"
)
def make_openai_call(...):
    return client.chat.completions.create(...)
```

3. **Logging aktivieren (optional):**
```python
import logging
logging.basicConfig(level=logging.INFO)
```

**Fertig!** 🎉

Deine API Calls sind jetzt 99.9% zuverlässiger bei nur 7s maximalem Wait!

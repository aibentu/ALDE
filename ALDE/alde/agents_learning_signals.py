from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, TypedDict


class PolicySnapshot(TypedDict, total=False):
    k: int
    fetch_k: int
    rerank_method: str
    metadata_filters: dict[str, Any]


class QueryEvent(TypedDict, total=False):
    event_id: str
    session_id: str
    agent: str
    tool: str
    query_text: str
    timestamp: str
    k: int
    autobuild: bool | None
    store_dir: str | None
    manifest_file: str | None
    root_dir: str | None
    policy_snapshot: PolicySnapshot


class OutcomeEvent(TypedDict, total=False):
    event_id: str
    query_event_id: str
    timestamp: str
    tool: str
    success: bool
    error: str | None
    timed_out: bool
    latency_ms: int
    result_count: int
    query_rephrase_count: int
    tool_retry_count: int
    answer_used_signal: bool | None
    explicit_feedback: int | None
    reward: float


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""

    def as_tuple(self) -> tuple[bool, str]:
        return self.ok, self.reason


_REQUIRED_QUERY_FIELDS = ("event_id", "tool", "query_text", "timestamp")
_REQUIRED_OUTCOME_FIELDS = ("event_id", "query_event_id", "tool", "timestamp", "success")


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_query_event(evt: dict[str, Any]) -> tuple[bool, str]:
    for key in _REQUIRED_QUERY_FIELDS:
        if key not in evt:
            return False, f"missing required field: {key}"

    if not _is_non_empty_str(evt.get("event_id")):
        return False, "event_id must be a non-empty string"
    if not _is_non_empty_str(evt.get("tool")):
        return False, "tool must be a non-empty string"
    if not _is_non_empty_str(evt.get("query_text")):
        return False, "query_text must be a non-empty string"
    if not _is_non_empty_str(evt.get("timestamp")):
        return False, "timestamp must be a non-empty string"

    k = evt.get("k")
    if k is not None and (not isinstance(k, int) or k < 1):
        return False, "k must be a positive integer"

    return True, ""


def validate_outcome_event(evt: dict[str, Any]) -> tuple[bool, str]:
    for key in _REQUIRED_OUTCOME_FIELDS:
        if key not in evt:
            return False, f"missing required field: {key}"

    if not _is_non_empty_str(evt.get("event_id")):
        return False, "event_id must be a non-empty string"
    if not _is_non_empty_str(evt.get("query_event_id")):
        return False, "query_event_id must be a non-empty string"
    if not _is_non_empty_str(evt.get("tool")):
        return False, "tool must be a non-empty string"
    if not _is_non_empty_str(evt.get("timestamp")):
        return False, "timestamp must be a non-empty string"
    if not isinstance(evt.get("success"), bool):
        return False, "success must be bool"

    latency_ms = evt.get("latency_ms")
    if latency_ms is not None and (not isinstance(latency_ms, int) or latency_ms < 0):
        return False, "latency_ms must be a non-negative integer"

    result_count = evt.get("result_count")
    if result_count is not None and (not isinstance(result_count, int) or result_count < 0):
        return False, "result_count must be a non-negative integer"

    return True, ""


def compute_reward(query_evt: dict[str, Any], outcome_evt: dict[str, Any]) -> float:
    """Heuristic reward for quasi-unsupervised online learning."""
    reward = 0.0

    success = bool(outcome_evt.get("success", False))
    timed_out = bool(outcome_evt.get("timed_out", False))
    err = str(outcome_evt.get("error") or "").strip().lower()

    if success:
        reward += 1.0
    if timed_out or "timed out" in err:
        reward -= 1.0
    if err:
        reward -= 1.0

    # Penalize friction in the interaction loop.
    retries = int(outcome_evt.get("tool_retry_count", 0) or 0)
    rephrases = int(outcome_evt.get("query_rephrase_count", 0) or 0)
    reward -= 0.2 * retries
    reward -= 0.2 * rephrases

    used_signal = outcome_evt.get("answer_used_signal", None)
    if used_signal is True:
        reward += 0.5
    elif used_signal is False:
        reward -= 0.5

    feedback = outcome_evt.get("explicit_feedback", None)
    if isinstance(feedback, int):
        reward += max(-1, min(1, feedback)) * 0.5

    return float(round(reward, 4))

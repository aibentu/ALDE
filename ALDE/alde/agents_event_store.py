from __future__ import annotations

from pathlib import Path
from typing import Any
import json

try:
    from .agents_runtime_events import validate_runtime_event
except ImportError as e:
    msg = str(e)
    if "attempted relative import" in msg or "no known parent package" in msg:
        from ALDE_Projekt.ALDE.alde.agents_runtime_events import validate_runtime_event  # type: ignore
    else:
        raise


class RuntimeEventStoreService:
    def load_events_path(self, base_dir: str | None = None) -> Path:
        root_path = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1] / "AppData" / "generated"
        root_path.mkdir(parents=True, exist_ok=True)
        return root_path / "runtime_events.jsonl"

    def append_object(self, event_object: dict[str, Any], base_dir: str | None = None) -> str:
        ok, reason = validate_runtime_event(event_object)
        if not ok:
            raise ValueError(reason)

        target_path = self.load_events_path(base_dir)
        with open(target_path, "a", encoding="utf-8") as event_file:
            event_file.write(json.dumps(event_object, ensure_ascii=False) + "\n")
            event_file.flush()
        return str(target_path)

    def load_objects(
        self,
        *,
        base_dir: str | None = None,
        event_type: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        target_path = self.load_events_path(base_dir)
        if not target_path.exists():
            return []

        loaded_events: list[dict[str, Any]] = []
        with open(target_path, "r", encoding="utf-8") as event_file:
            for raw_line in event_file:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event_object = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event_object, dict):
                    continue
                if event_type and str(event_object.get("event_type") or "") != str(event_type):
                    continue
                if session_id and str(event_object.get("session_id") or "") != str(session_id):
                    continue
                loaded_events.append(event_object)
                if limit is not None and len(loaded_events) >= max(0, int(limit)):
                    break
        return loaded_events

    def load_objects_by_session(self, session_id: str, *, base_dir: str | None = None) -> list[dict[str, Any]]:
        return self.load_objects(base_dir=base_dir, session_id=session_id)

    def load_objects_by_type(self, event_type: str, *, base_dir: str | None = None) -> list[dict[str, Any]]:
        return self.load_objects(base_dir=base_dir, event_type=event_type)


RUNTIME_EVENT_STORE_SERVICE = RuntimeEventStoreService()


def append_runtime_event(event_object: dict[str, Any], base_dir: str | None = None) -> str:
    return RUNTIME_EVENT_STORE_SERVICE.append_object(event_object, base_dir=base_dir)


def load_runtime_events(
    *,
    base_dir: str | None = None,
    event_type: str | None = None,
    session_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return RUNTIME_EVENT_STORE_SERVICE.load_objects(
        base_dir=base_dir,
        event_type=event_type,
        session_id=session_id,
        limit=limit,
    )
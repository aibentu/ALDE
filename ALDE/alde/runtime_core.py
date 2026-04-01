from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Callable, Generic, TypeVar


MessageObject = TypeVar("MessageObject")


class AgentRuntimeCoreService:
    def load_chat_components(self) -> tuple[Any, Any, Any]:
        from alde.agents_ccompletion import ChatCom, ImageCreate, ImageDescription  # type: ignore

        return ChatCom, ImageDescription, ImageCreate

    def load_runtime_components(self) -> tuple[Any, Any, Any]:
        from alde.agents_config import get_agent_config, normalize_agent_label  # type: ignore
        from alde.agents_factory import execute_forced_route  # type: ignore

        return get_agent_config, normalize_agent_label, execute_forced_route

    def build_runtime_fallback(self, *, target_agent: str, exc: Exception) -> str:
        return (
            "Agent runtime fallback path activated. "
            f"target={target_agent}; reason={type(exc).__name__}: {exc}"
        )

    def execute_chat_object(
        self,
        *,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        model_name: str = "",
    ) -> str:
        ChatCom, _, _ = self.load_chat_components()
        get_agent_config, normalize_agent_label, execute_forced_route = self.load_runtime_components()

        normalized_target = normalize_agent_label(target_agent)
        if normalized_target == "_xplaner_xrouter":
            model = str(model_name or (get_agent_config(normalized_target) or {}).get("model") or "gpt-4o")
            chat_kwargs: dict[str, Any] = {
                "_model": model,
                "_input_text": prompt,
            }
            if attachments:
                chat_kwargs["_url"] = list(attachments)
            return str(
                ChatCom(**chat_kwargs).get_response()
                or ""
            )

        return str(
            execute_forced_route(
                {"target_agent": normalized_target, "user_question": prompt},
                ChatCom=ChatCom,
                origin_agent_label="_xplaner_xrouter",
            )
            or ""
        )

    def run_chat_object(
        self,
        *,
        target_agent: str,
        prompt: str,
        attachments: list[str] | None = None,
        model_name: str = "",
    ) -> str:
        try:
            return self.execute_chat_object(
                target_agent=target_agent,
                prompt=prompt,
                attachments=attachments,
                model_name=model_name,
            )
        except Exception as exc:
            return self.build_runtime_fallback(target_agent=target_agent, exc=exc)


class InMemoryMessageRunnerService(Generic[MessageObject]):
    def __init__(
        self,
        *,
        worker_name: str,
        process_object_message: Callable[[MessageObject], None],
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.worker_name = worker_name
        self.process_object_message = process_object_message
        self.poll_interval_seconds = max(float(poll_interval_seconds), 0.05)
        self._queue: Queue[MessageObject] = Queue()
        self._stop = Event()
        self._thread = Thread(target=self._work_loop, daemon=True, name=self.worker_name)

    def start_object_runner(self) -> None:
        if self._thread.is_alive():
            return
        self._thread = Thread(target=self._work_loop, daemon=True, name=self.worker_name)
        self._stop.clear()
        self._thread.start()

    def stop_object_runner(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def submit_object_message(self, message: MessageObject) -> None:
        self.start_object_runner()
        self._queue.put(message)

    def load_object_health(self) -> dict[str, Any]:
        return {
            "backend": "inmemory",
            "healthy": True,
            "runner_alive": self._thread.is_alive(),
            "pending_count": self._queue.qsize(),
        }

    def _work_loop(self) -> None:
        while not self._stop.is_set():
            try:
                message = self._queue.get(timeout=self.poll_interval_seconds)
            except Empty:
                continue

            try:
                self.process_object_message(message)
            finally:
                self._queue.task_done()
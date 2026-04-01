from __future__ import annotations

import tempfile
import unittest

from alde.event_store import append_runtime_event, load_runtime_events
from alde.runtime_events import create_query_event


class TestEventStore(unittest.TestCase):
    def test_append_and_filter_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            query_event = create_query_event(
                query_text="knowledge graph",
                tool_name="memorydb",
                session_id="session-a",
            )
            append_runtime_event(query_event, base_dir=temp_dir)

            loaded_all = load_runtime_events(base_dir=temp_dir)
            loaded_query = load_runtime_events(base_dir=temp_dir, event_type="query")
            loaded_session = load_runtime_events(base_dir=temp_dir, session_id="session-a")

            self.assertEqual(len(loaded_all), 1)
            self.assertEqual(len(loaded_query), 1)
            self.assertEqual(len(loaded_session), 1)


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from alde.webapp import config


class TestWebappConfig(unittest.TestCase):
    def test_load_object_database_url_resolves_relative_sqlite_path(self) -> None:
        with patch.dict(os.environ, {"ALDE_WEB_DATABASE_URL": "sqlite:///./AppData/alde_web_test.db"}, clear=False):
            database_url = config.load_object_database_url()

        expected_path = PKG_ROOT / "AppData" / "alde_web_test.db"
        self.assertEqual(database_url, f"sqlite:///{expected_path.as_posix()}")

    def test_load_object_database_url_preserves_in_memory_database(self) -> None:
        with patch.dict(os.environ, {"ALDE_WEB_DATABASE_URL": "sqlite:///:memory:"}, clear=False):
            database_url = config.load_object_database_url()

        self.assertEqual(database_url, "sqlite:///:memory:")
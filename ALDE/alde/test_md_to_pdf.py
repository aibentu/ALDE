from __future__ import annotations

import sys
import unittest
from pathlib import Path


PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from alde.md_to_pdf import iter_markdown_blocks


class TestMdToPdfPagebreak(unittest.TestCase):
    def test_iter_markdown_blocks_emits_pagebreak_block(self) -> None:
        markdown_text = "# Application\n\nBody\n\n<!-- pagebreak -->\n\n# CV\n\nProfile"
        kinds = [block.kind for block in iter_markdown_blocks(markdown_text)]

        self.assertIn("pagebreak", kinds)
        self.assertEqual(kinds.count("pagebreak"), 1)


if __name__ == "__main__":
    unittest.main()

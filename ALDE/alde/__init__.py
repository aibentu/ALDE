"""alde package.

This repository historically supported running modules both as scripts
(e.g. `python alde/ai_ide_v1756.py`) and as an importable package.

Having this file makes imports like `import alde.agents_factory` work
reliably across entrypoints.
"""

from __future__ import annotations

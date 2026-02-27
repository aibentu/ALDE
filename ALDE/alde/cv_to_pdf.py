#!/usr/bin/env python3
"""Backwards-compatible wrapper for the older CV-specific CLI.

Use `python -m alde.md_to_pdf` for a general Markdown → PDF conversion.
"""

from __future__ import annotations

from .md_to_pdf import PdfOptions, markdown_to_pdf, main

__all__ = ["PdfOptions", "markdown_to_pdf", "main"]


if __name__ == "__main__":
    raise SystemExit(main())

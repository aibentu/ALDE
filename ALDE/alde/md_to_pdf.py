#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (  # type: ignore
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


@dataclass(frozen=True)
class PdfOptions:
    title: str | None = None
    author: str | None = None
    pagesize: tuple[float, float] = A4
    margin_left_mm: float = 18
    margin_right_mm: float = 18
    margin_top_mm: float = 16
    margin_bottom_mm: float = 16


_PAGE_SIZES: dict[str, tuple[float, float]] = {
    "A4": A4,
    "LETTER": LETTER,
}


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def md_inline_to_reportlab(text: str) -> str:
    """Convert a small, safe subset of Markdown inline syntax to ReportLab Paragraph markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Links: [text](url)
    def _link_sub(m: re.Match[str]) -> str:
        label = m.group(1)
        url = m.group(2)
        return f'<link href="{url}">{label}</link>'

    text = _LINK_RE.sub(_link_sub, text)

    # Bold and italic (small subset)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)

    return text


@dataclass
class Block:
    kind: str  # heading1, heading2, heading3, para, ul
    text: str | None = None
    items: list[str] | None = None


def iter_markdown_blocks(md: str) -> Iterable[Block]:
    """Parse a minimal subset of Markdown into blocks.

    Supported:
    - # / ## / ### headings
    - unordered lists (- / *)
    - paragraphs
    - horizontal rules (---, ***, ___) are ignored

    This is intentionally conservative (ATS-friendly) and avoids complex Markdown features.
    """

    lines = md.splitlines()
    i = 0

    def is_hr(s: str) -> bool:
        s = s.strip()
        return s in {"---", "***", "___"}

    while i < len(lines):
        line = lines[i].rstrip("\n")

        if not line.strip():
            i += 1
            continue

        if is_hr(line):
            i += 1
            continue

        if line.startswith("# "):
            yield Block("heading1", text=line[2:].strip())
            i += 1
            continue

        if line.startswith("## "):
            yield Block("heading2", text=line[3:].strip())
            i += 1
            continue

        if line.startswith("### "):
            yield Block("heading3", text=line[4:].strip())
            i += 1
            continue

        if line.lstrip().startswith(("- ", "* ")):
            items: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(("- ", "* ")):
                items.append(lines[i].lstrip()[2:].rstrip())
                i += 1
            yield Block("ul", items=items)
            continue

        # paragraph: collect until blank line or next block
        para_lines: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not is_hr(lines[i])
            and not lines[i].startswith("# ")
            and not lines[i].startswith("## ")
            and not lines[i].startswith("### ")
            and not lines[i].lstrip().startswith(("- ", "* "))
        ):
            para_lines.append(lines[i].rstrip())
            i += 1

        # Preserve explicit Markdown line breaks (two trailing spaces)
        parts: list[str] = []
        for pl in para_lines:
            if pl.endswith("  "):
                parts.append(pl[:-2])
                parts.append("<br/>")
            else:
                parts.append(pl)

        joined: list[str] = []
        for p in parts:
            joined.append(p if p == "<br/>" else p.strip())

        if "<br/>" in joined:
            segs: list[str] = []
            current: list[str] = []
            for token in joined:
                if token == "<br/>":
                    if current:
                        segs.append(" ".join(current).strip())
                        current = []
                else:
                    current.append(token)
            if current:
                segs.append(" ".join(current).strip())
            para = "<br/>".join(segs)
        else:
            para = " ".join([p for p in joined if p != "<br/>"]).strip()

        yield Block("para", text=para)


def markdown_to_pdf(md_path: Path, pdf_path: Path, *, options: PdfOptions | None = None) -> None:
    options = options or PdfOptions()

    md = md_path.read_text(encoding="utf-8")

    styles = getSampleStyleSheet()
    base = styles["BodyText"]

    style_h1 = ParagraphStyle(
        "MDH1",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceAfter=8,
    )
    style_h2 = ParagraphStyle(
        "MDH2",
        parent=styles["Heading2"],
        fontSize=12.5,
        leading=16,
        spaceBefore=10,
        spaceAfter=4,
    )
    style_h3 = ParagraphStyle(
        "MDH3",
        parent=styles["Heading3"],
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=3,
    )
    style_body = ParagraphStyle(
        "MDBody",
        parent=base,
        fontSize=10.5,
        leading=14,
        spaceAfter=4,
    )

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=options.pagesize,
        leftMargin=options.margin_left_mm * mm,
        rightMargin=options.margin_right_mm * mm,
        topMargin=options.margin_top_mm * mm,
        bottomMargin=options.margin_bottom_mm * mm,
        title=options.title or md_path.stem,
        author=options.author or "",
    )

    story = []

    for block in iter_markdown_blocks(md):
        if block.kind == "heading1" and block.text:
            story.append(Paragraph(md_inline_to_reportlab(block.text), style_h1))
            continue

        if block.kind == "heading2" and block.text:
            story.append(Paragraph(md_inline_to_reportlab(block.text), style_h2))
            continue

        if block.kind == "heading3" and block.text:
            story.append(Paragraph(md_inline_to_reportlab(block.text), style_h3))
            continue

        if block.kind == "para" and block.text:
            story.append(Paragraph(md_inline_to_reportlab(block.text), style_body))
            continue

        if block.kind == "ul" and block.items:
            items = [
                ListItem(Paragraph(md_inline_to_reportlab(it), style_body), leftIndent=0)
                for it in block.items
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    leftIndent=12,
                    bulletFontSize=9,
                    bulletOffsetY=1,
                    spaceAfter=6,
                )
            )
            continue

        story.append(Spacer(1, 4))

    doc.build(story)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Convert Markdown to a clean PDF (ReportLab).")
    parser.add_argument("md", type=Path, help="Input Markdown file")
    parser.add_argument("pdf", type=Path, help="Output PDF file")
    parser.add_argument("--title", type=str, default=None, help="Optional PDF title")
    parser.add_argument("--author", type=str, default=None, help="Optional PDF author")
    parser.add_argument(
        "--pagesize",
        type=str,
        default="A4",
        choices=sorted(_PAGE_SIZES.keys()),
        help="Page size (default: A4)",
    )
    parser.add_argument("--margin-left-mm", type=float, default=18, help="Left margin in mm")
    parser.add_argument("--margin-right-mm", type=float, default=18, help="Right margin in mm")
    parser.add_argument("--margin-top-mm", type=float, default=16, help="Top margin in mm")
    parser.add_argument("--margin-bottom-mm", type=float, default=16, help="Bottom margin in mm")
    args = parser.parse_args(argv)

    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    markdown_to_pdf(
        args.md,
        args.pdf,
        options=PdfOptions(
            title=args.title,
            author=args.author,
            pagesize=_PAGE_SIZES[args.pagesize],
            margin_left_mm=args.margin_left_mm,
            margin_right_mm=args.margin_right_mm,
            margin_top_mm=args.margin_top_mm,
            margin_bottom_mm=args.margin_bottom_mm,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

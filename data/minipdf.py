"""
minipdf — a tiny, dependency-free PDF writer.

Writes multi-page PDFs with wrapped text using the built-in Helvetica fonts.
No external packages required (important: the build sandbox has no network),
and nothing to install at runtime. Good enough for clean, readable contract
documents; not a general-purpose layout engine.

Usage:
    doc = PdfDoc()
    doc.add_heading("TITLE")
    doc.add_paragraph("Some body text ...")
    doc.add_keyvalue("Customer", "Northwind Traders")
    doc.save("out.pdf")
"""
from __future__ import annotations

import io
from typing import List, Tuple

# ---- Page geometry (US Letter, 72 pt / inch) --------------------------------
PAGE_W = 612
PAGE_H = 792
MARGIN = 60
LINE_H = 14          # default leading for body text
CONTENT_W = PAGE_W - 2 * MARGIN

# Approximate Helvetica character widths (per 1000 units) for the ASCII range
# we actually use. We only need enough accuracy to wrap text sensibly.
_HELV_AVG = 0.52     # average advance width as a fraction of font size


def _esc(text: str) -> str:
    """Escape characters that are special inside a PDF string literal."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _char_width(size: float) -> float:
    return _HELV_AVG * size


def _wrap(text: str, size: float, max_w: float) -> List[str]:
    """Greedy word-wrap using the average-width approximation."""
    if text == "":
        return [""]
    cw = _char_width(size)
    max_chars = max(1, int(max_w / cw))
    out: List[str] = []
    for raw_line in text.split("\n"):
        if raw_line == "":
            out.append("")
            continue
        words = raw_line.split(" ")
        cur = ""
        for w in words:
            cand = w if cur == "" else cur + " " + w
            if len(cand) <= max_chars:
                cur = cand
            else:
                if cur:
                    out.append(cur)
                # hard-break very long words
                while len(w) > max_chars:
                    out.append(w[:max_chars])
                    w = w[max_chars:]
                cur = w
        out.append(cur)
    return out


class _Op:
    """A single text draw instruction, resolved at render time."""
    __slots__ = ("text", "size", "bold", "gap_before")

    def __init__(self, text: str, size: float, bold: bool, gap_before: float):
        self.text = text
        self.size = size
        self.bold = bold
        self.gap_before = gap_before


class PdfDoc:
    def __init__(self):
        self._ops: List[_Op] = []

    # ---- content API --------------------------------------------------------
    def add_heading(self, text: str, size: float = 16):
        self._ops.append(_Op(text, size, True, gap_before=10))

    def add_subheading(self, text: str, size: float = 12):
        self._ops.append(_Op(text, size, True, gap_before=8))

    def add_paragraph(self, text: str, size: float = 10):
        self._ops.append(_Op(text, size, False, gap_before=6))

    def add_keyvalue(self, key: str, value: str, size: float = 10):
        self._ops.append(_Op(f"{key}: {value}", size, False, gap_before=2))

    def add_spacer(self, height: float = 8):
        self._ops.append(_Op("", 1, False, gap_before=height))

    def add_rule(self):
        # a simple ASCII separator row (keeps us within WinAnsi/latin-1 safely)
        self._ops.append(_Op("-" * 80, 8, False, gap_before=4))

    # ---- rendering ----------------------------------------------------------
    def _layout_pages(self) -> List[List[Tuple[float, float, str, float, bool]]]:
        """Return pages; each page is a list of (x, y, text, size, bold)."""
        pages: List[List[Tuple[float, float, str, float, bool]]] = []
        cur: List[Tuple[float, float, str, float, bool]] = []
        y = PAGE_H - MARGIN

        def newpage():
            nonlocal cur, y
            if cur:
                pages.append(cur)
            cur = []
            y = PAGE_H - MARGIN

        for op in self._ops:
            leading = op.size + 4 if op.size > 1 else LINE_H
            y -= op.gap_before
            for line in _wrap(op.text, op.size if op.size > 1 else 10, CONTENT_W):
                if y - leading < MARGIN:
                    newpage()
                cur.append((MARGIN, y, line, op.size, op.bold))
                y -= leading
        if cur:
            pages.append(cur)
        if not pages:
            pages = [[]]
        return pages

    def save(self, path: str):
        data = self.render()
        with open(path, "wb") as fh:
            fh.write(data)

    def render(self) -> bytes:
        pages = self._layout_pages()
        objects: List[bytes] = []

        # Object numbering:
        # 1 = Catalog, 2 = Pages, 3 = Helvetica, 4 = Helvetica-Bold,
        # then per page: content stream + page object.
        font_regular = 3
        font_bold = 4

        page_obj_ids: List[int] = []
        content_objs: List[bytes] = []
        page_objs: List[bytes] = []

        next_id = 5
        for page in pages:
            content_id = next_id
            page_id = next_id + 1
            next_id += 2
            page_obj_ids.append(page_id)

            stream = io.StringIO()
            stream.write("BT\n")
            prev_font_bold = None
            for (x, y, text, size, bold) in page:
                if text == "":
                    continue
                if bold != prev_font_bold:
                    fname = "F2" if bold else "F1"
                    stream.write(f"/{fname} {size:.1f} Tf\n")
                    prev_font_bold = bold
                else:
                    stream.write(f"/{'F2' if bold else 'F1'} {size:.1f} Tf\n")
                stream.write(f"1 0 0 1 {x:.1f} {y:.1f} Tm\n")
                stream.write(f"({_esc(text)}) Tj\n")
            stream.write("ET\n")
            body = stream.getvalue().encode("latin-1", "replace")

            content = (
                f"{content_id} 0 obj\n<< /Length {len(body)} >>\nstream\n".encode()
                + body
                + b"\nendstream\nendobj\n"
            )
            content_objs.append(content)

            page_obj = (
                f"{page_id} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                f"/Contents {content_id} 0 R >>\nendobj\n"
            ).encode()
            page_objs.append(page_obj)

        kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
        catalog = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        pages_obj = (
            f"2 0 obj\n<< /Type /Pages /Kids [{kids}] "
            f"/Count {len(page_obj_ids)} >>\nendobj\n"
        ).encode()
        helv = (
            b"3 0 obj\n<< /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >>\nendobj\n"
        )
        helv_bold = (
            b"4 0 obj\n<< /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica-Bold >>\nendobj\n"
        )

        objects = [catalog, pages_obj, helv, helv_bold]
        for c, p in zip(content_objs, page_objs):
            objects.append(c)
            objects.append(p)

        # Assemble file and build the xref table.
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (len(objects) + 1)
        # objects are already numbered 1..N in order of the list
        for idx, obj in enumerate(objects, start=1):
            offsets[idx] = out.tell()
            out.write(obj)

        xref_pos = out.tell()
        n = len(objects)
        out.write(f"xref\n0 {n + 1}\n".encode())
        out.write(b"0000000000 65535 f \n")
        for idx in range(1, n + 1):
            out.write(f"{offsets[idx]:010d} 00000 n \n".encode())
        out.write(
            f"trailer\n<< /Size {n + 1} /Root 1 0 R >>\n".encode()
        )
        out.write(f"startxref\n{xref_pos}\n%%EOF\n".encode())
        return out.getvalue()

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "data"))
from minipdf import PdfDoc  # noqa: E402

OUT = os.path.join(HERE, "box_upload")


def md_to_pdf(src: str) -> bytes:
    doc = PdfDoc()
    with open(src) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("# "):
                doc.add_heading(line[2:])
            elif line.startswith("## "):
                doc.add_spacer(4)
                doc.add_subheading(line[3:])
            elif line.startswith("- "):
                doc.add_paragraph("- " + line[2:])
            else:
                doc.add_paragraph(line)
    return doc.render()


def main() -> None:
    for sub in ("evidence", "contracts"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
        for name in sorted(os.listdir(os.path.join(HERE, sub))):
            if not name.endswith(".md"):
                continue
            pdf = md_to_pdf(os.path.join(HERE, sub, name))
            dest = os.path.join(OUT, sub, name[:-3] + ".pdf")
            with open(dest, "wb") as fh:
                fh.write(pdf)
            print(dest)


if __name__ == "__main__":
    main()

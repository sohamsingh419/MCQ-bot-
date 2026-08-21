from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    output: list[str] = []
    for paragraph in root.findall(".//w:p", NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", NS)).strip()
        if text:
            output.append(re.sub(r"\s+", " ", text))
    return output


def main() -> None:
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    lines = paragraphs(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"extracted_paragraphs={len(lines)} output={destination}")
    for line in lines:
        if line.endswith("GK — State Exam के अनुसार") or line.startswith("India GK"):
            print(line)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""双源流水线 第1步：DOCX 结构提取（含 txbxContent 文本框通道）。
用法: python extract_docx.py --config config.json
输出: <out>/docx_struct.json, <out>/docx_textboxes.json
"""
import argparse, json, re, sys, zipfile, unicodedata
from pathlib import Path

def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config, encoding="utf-8"))
    docx_path, out = cfg["docx"], Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)

    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        from docx.oxml.ns import qn
    except ImportError:
        sys.exit("需要 python-docx: pip install python-docx")

    doc = Document(docx_path)

    def iter_blocks(parent):
        for child in parent.element.body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)

    items = []
    for block in iter_blocks(doc):
        if isinstance(block, Paragraph):
            items.append({"type": "p",
                          "style": block.style.name if block.style else "",
                          "text": block.text.strip()})
        else:
            rows = [[" ".join(p.text.strip() for p in tc.paragraphs if p.text.strip())
                     for tc in tr.cells] for tr in block.rows]
            items.append({"type": "table", "rows": rows})
    json.dump(items, open(out / "docx_struct.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # txbxContent channel: text boxes are invisible to body iteration
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    boxes = []
    try:
        from lxml import etree
        root = etree.fromstring(zipfile.ZipFile(docx_path).read("word/document.xml"))
        for tb in root.iter("{%s}txbxContent" % W):
            t = norm("".join(x.text or "" for x in tb.iter("{%s}t" % W)))
            if len(t) >= 15:
                boxes.append(t)
    except Exception as e:
        print("textbox scan failed:", e)
    json.dump(boxes, open(out / "docx_textboxes.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    ntab = sum(1 for i in items if i["type"] == "table")
    print(f"blocks: {len(items)}, tables: {ntab}, textboxes>=15ch: {len(boxes)}")

if __name__ == "__main__":
    main()

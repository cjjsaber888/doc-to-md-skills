# -*- coding: utf-8 -*-
"""双源流水线 第4步：RAG 切块。
用法: python build_chunks.py --config config.json
输出: <out>/03_chunks.jsonl

字段: chunk_id doc_id level_path type page_pdf pages[] text char_count
      source_records[] confidence source pii [pii_masked]
config: doc_id, redact_pii(bool)
"""
import argparse, json, os, re
from pathlib import Path

def table_to_md(rows):
    if not rows: return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    out = ["| " + " | ".join(c.replace("\n", "<br>") for c in rows[0]) + " |",
           "|" + "---|" * ncol]
    out += ["| " + " | ".join(c.replace("\n", "<br>") for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config, encoding="utf-8"))
    out = Path(cfg["out"])
    DOC_ID = cfg.get("doc_id", "doc")
    REDACT = cfg.get("redact_pii", False) or os.environ.get("REDACT_PII") == "1"
    recs = json.load(open(out / "structured.json", encoding="utf-8"))

    chunks = []
    def new_chunk(path, typ, page, text, meta):
        chunks.append({"chunk_id": f"C{len(chunks)+1:04d}", "doc_id": DOC_ID,
                       "level_path": path, "type": typ, "page_pdf": page,
                       "text": text, "char_count": len(text), **meta})

    cur = None
    for r in recs:
        t = r["type"]
        if t == "paragraph":
            txt = r["text"]
            if cur and cur["level_path"] == r["level_path"] and cur["char_count"] + len(txt) < 900:
                cur["text"] += "\n" + txt; cur["char_count"] = len(cur["text"])
                cur["source_records"].append(r["id"])
                if r["page_pdf"] not in cur["pages"]: cur["pages"].append(r["page_pdf"])
            else:
                if cur: chunks.append(cur)
                cur = {"chunk_id": "", "doc_id": DOC_ID, "level_path": r["level_path"],
                       "type": "text", "page_pdf": r["page_pdf"], "pages": [r["page_pdf"]],
                       "text": txt, "char_count": len(txt), "source_records": [r["id"]],
                       "confidence": "high", "source": "pdf_text_layer"}
        else:
            if cur: chunks.append(cur); cur = None
            if t == "heading":
                continue
            if t == "table":
                d = json.loads(r["text"])
                cap = d.get("caption", "")
                rows_md = table_to_md(d["rows"]).split("\n")
                head2, body = rows_md[:2], rows_md[2:]
                piece, plen, parts = [], 0, []
                for ln in body:
                    if plen + len(ln) > 1200 and piece:
                        parts.append(piece); piece, plen = [], 0
                    piece.append(ln); plen += len(ln)
                if piece: parts.append(piece)
                for pi, part in enumerate(parts):
                    suffix = "" if len(parts) == 1 else f"（第{pi+1}/{len(parts)}片段）"
                    src = r.get("meta", {}).get("source", "")
                    conf = "medium" if "ocr" in src else "high"
                    new_chunk(r["level_path"], "table", r["page_pdf"],
                              f"【表】{cap}{suffix}\n" + "\n".join(head2 + part),
                              {"source_records": [r["id"]], "confidence": conf,
                               "source": src or "docx_table"})
            elif t == "attachment_text":
                meta = r.get("meta", {})
                src, conf, page = meta.get("source", "docx_ocr"), meta.get("confidence", "medium"), r["page_pdf"]
                buf = ""
                for s in re.split(r"(?<=[。；：\n])", r["text"]):
                    if len(buf) + len(s) > 800 and buf:
                        new_chunk(r["level_path"], "attachment", page, buf.strip(),
                                  {"source_records": [r["id"]], "confidence": conf, "source": src})
                        buf = ""
                    buf += s
                if buf.strip():
                    new_chunk(r["level_path"], "attachment", page, buf.strip(),
                              {"source_records": [r["id"]], "confidence": conf, "source": src})
            elif t == "textbox_leftover":
                new_chunk(r["level_path"], "needs_review", -1, r["text"],
                          {"source_records": [r["id"]], "confidence": "low", "source": "docx_textbox"})
            elif t in ("cover", "roster", "toc", "attachment_list", "front_matter"):
                new_chunk(r["level_path"], "front_matter", r["page_pdf"], r["text"],
                          {"source_records": [r["id"]], "confidence": "high", "source": "pdf_text_layer"})
            # figure_caption / table_caption / drawing handled below or skipped
    if cur: chunks.append(cur)

    # figure captions -> append to nearest same-page chunk
    for f in [r for r in recs if r["type"] == "figure_caption"]:
        target = next((c for c in chunks if c["page_pdf"] == f["page_pdf"] and c["type"] in ("text", "table")), None)
        if target is None:
            cand = [c for c in chunks if c["type"] in ("text", "table") and c["page_pdf"] >= 0]
            if cand:
                target = min(cand, key=lambda c: abs(c["page_pdf"] - f["page_pdf"]))
        if target is not None:
            target["text"] += f"\n〔图示〕{f['text']}"
            target["char_count"] = len(target["text"])
            target["source_records"].append(f["id"])

    for c in chunks:
        if c["type"] == "text":
            c["text"] = f"【{c['level_path']}】\n" + c["text"]
            c["char_count"] = len(c["text"])

    # merge tiny chunks
    merged = []
    for c in chunks:
        if merged and c["char_count"] < 150 and merged[-1]["type"] == c["type"] \
           and merged[-1]["level_path"] == c["level_path"] and merged[-1]["char_count"] + c["char_count"] < 1200:
            m = merged[-1]
            m["text"] += "\n" + c["text"]; m["char_count"] = len(m["text"])
            m["source_records"] += c["source_records"]
            for p in c.get("pages", [c["page_pdf"]]):
                if p not in m.setdefault("pages", [m["page_pdf"]]): m["pages"].append(p)
        else:
            merged.append(c)
    chunks = merged

    PII = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    for i, c in enumerate(chunks):
        c["chunk_id"] = f"C{i+1:04d}"
        if "pages" not in c:
            c["pages"] = [c["page_pdf"]] if c["page_pdf"] >= 0 else []
        c["pages"] = sorted(set(p for p in c["pages"] if p >= 0))
        c["pii"] = bool(PII.search(c["text"]))
        if REDACT and c["pii"]:
            c["text"] = re.sub(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)", r"\1****\2", c["text"])
            c["char_count"] = len(c["text"])
            c["pii_masked"] = True

    with open(out / "03_chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    from collections import Counter
    lens = [c["char_count"] for c in chunks]
    print("chunks:", len(chunks), dict(Counter(c["type"] for c in chunks)))
    print("avg:", sum(lens)//max(len(lens),1), "max:", max(lens), "min:", min(lens),
          "| pii:", sum(1 for c in chunks if c["pii"]), "redact:", REDACT)

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""双源流水线 第3步：层级结构化（双源权威规则实现）。
用法: python build_structured.py --config config.json
输出: <out>/structured.json

config 关键字段:
  body_start/body_end   PDF正文区页码(0基,含头不含尾)
  att_start             附件区起始PDF页(0基)
  docx_body             [start,end] docx_struct 正文块区间
  docx_att_start        docx_struct 附件区起始块索引
  att_extra_headings    [{"regex":"^某环保许评","label":"附件10（…）","after_att":"9"}] 无标题附件补边界
  table_fix_captions    ["表X …","表Y …"] 无题表按文档顺序补标题(先人工核对PDF)
  table_fix_pages       对应PDF页码列表
  front_matter_pages    前置页数量(封面/名录/目录),默认6
"""
import argparse, json, re, unicodedata
from pathlib import Path
import fitz

def canon(s):
    return re.sub(r"\s+", "", s)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config, encoding="utf-8"))
    out = Path(cfg["out"])
    doc = fitz.open(cfg["pdf"])
    items = json.load(open(out / "docx_struct.json", encoding="utf-8"))
    textboxes = json.load(open(out / "docx_textboxes.json", encoding="utf-8")) if (out / "docx_textboxes.json").exists() else []

    # runtime TOC (never hardcode bookmarks)
    BM = [(lvl, title, page - 1) for lvl, title, page in doc.get_toc()
          if page > 0 and not re.match(r"^(C\d{4}|图纸|模型)", title)]
    head_map = {canon(t): (l, t, p) for l, t, p in BM}

    records = []
    rid = 0
    def add(path, typ, page, text, meta=None):
        nonlocal rid
        rid += 1
        rec = {"id": f"R{rid:04d}", "level_path": path, "type": typ,
               "page_pdf": page, "page_print": page + 1, "text": text}
        if meta: rec["meta"] = meta
        records.append(rec)

    body_start = cfg.get("body_start", 0)
    body_end = cfg.get("body_end", len(doc))
    att_start = cfg.get("att_start", body_end)
    nfront = cfg.get("front_matter_pages", 6)

    # 1. front matter
    for pno in range(min(nfront, body_start if body_start > 0 else nfront)):
        t = doc[pno].get_text().strip()
        if t:
            add("前置", "front_matter", pno, t)

    # 2. main body from PDF text layer
    path_stack = {1: "", 2: "", 3: ""}
    def set_path(lvl, title):
        path_stack[lvl] = title.strip()
        for l in range(lvl + 1, 4): path_stack[l] = ""
        return " > ".join(path_stack[l] for l in (1, 2, 3) if path_stack[l])

    current_path = ""
    buf = []
    def flush(page):
        nonlocal buf
        if buf:
            txt = "".join(buf).strip(); buf = []
            if txt: add(current_path or "正文", "paragraph", page, txt)

    HEAD_RE = re.compile(r"^(第\s*\d+\s*章|前言|[123]\s*\.\s*\d+)")
    FIG_RE = re.compile(r"^图\s*\d+[-–]\d+")
    TAB_RE = re.compile(r"^表\s*\d+[-–]?\s*\d*")

    for pno in range(body_start, body_end):
        lines = [ln for ln in doc[pno].get_text().split("\n")
                 if not re.fullmatch(r"\s*\d{1,3}\s*", ln)]
        i = 0
        while i < len(lines):
            ln = lines[i].strip(); i += 1
            if not ln: continue
            hit = head_map.get(canon(ln))
            if not hit and i < len(lines):
                c2 = canon(ln + lines[i].strip())
                hit = head_map.get(c2)
                if hit: i += 1
            if hit:
                flush(pno)
                lvl, title, _ = hit
                current_path = set_path(lvl, title)
                add(current_path, "heading", pno, re.sub(r"\s+", " ", title).strip(),
                    {"heading_level": lvl})
                continue
            if FIG_RE.match(ln):
                flush(pno); add(current_path or "正文", "figure_caption", pno, ln); continue
            if TAB_RE.match(ln) and len(ln) < 45:
                flush(pno); add(current_path or "正文", "table_caption", pno, ln); continue
            buf.append(ln)
        flush(pno)

    # 3. main-body tables from DOCX (authoritative structure)
    rec_path_by_title = {canon(r["text"]): r["level_path"] for r in records if r["type"] == "heading"}
    d0, d1 = cfg.get("docx_body", [0, len(items)])
    cur_sec = ""
    docx_tables = []
    for idx in range(d0, d1):
        it = items[idx]
        if it["type"] == "p":
            key = canon(it["text"].strip())
            if key in rec_path_by_title and len(key) < 30:
                cur_sec = rec_path_by_title[key]
        else:
            cap = ""
            for j in range(idx - 1, max(idx - 6, d0), -1):
                if items[j]["type"] == "p" and TAB_RE.match(items[j]["text"].strip()):
                    cap = items[j]["text"].strip(); break
            page = None
            ck = canon(cap)
            for r in records:
                if r["type"] == "table_caption" and ck and canon(r["text"]).startswith(ck[:8]):
                    page = r["page_pdf"]; break
            docx_tables.append({"caption": cap, "rows": it["rows"], "section": cur_sec, "page": page})

    fix_caps = cfg.get("table_fix_captions", [])
    fix_pages = cfg.get("table_fix_pages", [])
    fi = 0
    for tb in docx_tables:
        if not tb["caption"] and fi < len(fix_caps):
            tb["caption"] = fix_caps[fi]
            if fi < len(fix_pages): tb["page"] = fix_pages[fi]
            fi += 1
    for tb in docx_tables:
        # keep FULL grid; merged-cell repeats are real structure (audit F-01)
        clean = [[re.sub(r"\s+", " ", c).strip() for c in row] for row in tb["rows"]]
        add(tb["section"] or "正文", "table", tb["page"] if tb["page"] is not None else -1,
            json.dumps({"caption": tb["caption"], "rows": clean}, ensure_ascii=False),
            {"n_rows": len(clean), "source": "docx"})

    # 3.5 big cross-page tables via PDF find_tables (config: bigtable_pages [start,end], bigtable_title)
    bt = cfg.get("bigtable_pages")
    if bt:
        title = cfg.get("bigtable_title", "附表")
        add(title, "heading", bt[0], title, {"heading_level": 1})
        bt_rows = []
        for pno in range(bt[0], bt[1] + 1):
            for tb in doc[pno].find_tables().tables:
                for row in tb.extract():
                    # keep FULL grid, no adjacent-dup collapse (audit F-01)
                    cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in row]
                    bt_rows.append({"page": pno, "cells": cells})
        cur_page, group = None, []
        def flush_bt():
            nonlocal group
            if group:
                add(title, "table", cur_page, json.dumps({"rows": group}, ensure_ascii=False),
                    {"n_rows": len(group), "source": "pdf_find_tables",
                     "note": "跨页大表按页分组"})
                group = []
        for r in bt_rows:
            if r["page"] != cur_page:
                flush_bt(); cur_page = r["page"]
            group.append(r["cells"])
        flush_bt()

    # 4. attachment zone: DOCX channel first, then PDF text-layer fallback
    ATT_MARK = re.compile(cfg.get("att_start_regex", r"^附\s*件\s*(\d+(?:-\d+)?)\s*$"))
    extra_heads = cfg.get("att_extra_headings", [])
    i = cfg.get("docx_att_start", 0)
    cur_att, att_buf = None, []
    def flush_att():
        nonlocal att_buf
        if cur_att and att_buf:
            txt = "\n".join(att_buf).strip()
            if txt:
                add(f"附件{cur_att}", "attachment_text", -1, txt,
                    {"source": "docx_ocr", "confidence": "medium",
                     "note": "PDF原件为扫描件，文本来自转换OCR，文号金额需人工复核"})
        att_buf = []
    while i < len(items):
        it = items[i]
        if it["type"] == "p":
            t = it["text"].strip()
            m = ATT_MARK.match(t)
            if m:
                flush_att(); cur_att = m.group(1)
                add(f"附件{cur_att}", "heading", -1, t, {"heading_level": 1})
                i += 1; continue
            for eh in extra_heads:
                if cur_att == eh.get("after_att") and re.match(eh["regex"], t):
                    flush_att(); cur_att = re.sub(r"^附件", "", eh["label"]).split("（")[0]
                    add(f"附件{cur_att}", "heading", -1, eh["label"], {"heading_level": 1})
                    break
            if t: att_buf.append(t)
        else:
            flush_att()
            add(f"附件{cur_att or '附件'}", "table", -1,
                json.dumps({"rows": [[re.sub(r"\s+", " ", c).strip() for c in r] for r in it["rows"]]},
                           ensure_ascii=False),
                {"n_rows": len(it["rows"]), "source": "docx_ocr", "confidence": "medium"})
        i += 1
    flush_att()

    # PDF fallback: pages with real text layer not covered by DOCX channel
    def norm_all(s): return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))
    att_norm = norm_all("".join(r["text"] for r in records if r["level_path"].startswith("附件")))
    supplemented = []
    for pno in range(att_start, len(doc)):
        t = doc[pno].get_text().strip()
        nt = norm_all(t)
        if len(nt) < 60: continue
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        if sum(1 for ln in lines if len(ln) >= 25) < 3:  # CAD fragment filter
            continue
        if nt[20:60] and nt[20:60] in att_norm: continue
        add("附件区", "attachment_text", pno, t,
            {"source": "pdf_text_layer", "confidence": "high",
             "note": "DOCX通道未覆盖，以PDF文字层补录"})
        supplemented.append(pno)

    # textbox leftovers (>=60ch, sentence-like, uncovered)
    body_norm = norm_all("".join(r["text"] for r in records))
    tb_lost = [t for t in textboxes if len(t) >= 60 and t not in body_norm]
    for t in tb_lost:
        add("待人工归属", "textbox_leftover", -1, t,
            {"source": "docx_textbox", "confidence": "low",
             "note": "位于DOCX文本框，归属页/附件待人工判定"})

    json.dump(records, open(out / "structured.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    from collections import Counter
    c = Counter(r["type"] for r in records)
    print("records:", len(records), dict(c))
    print("pdf-fallback pages:", supplemented, "| textbox leftovers:", len(tb_lost))

if __name__ == "__main__":
    main()

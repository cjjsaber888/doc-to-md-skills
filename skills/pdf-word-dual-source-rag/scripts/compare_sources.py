# -*- coding: utf-8 -*-
"""双源流水线 第2步：逐句校正。
用法: python compare_sources.py --config config.json
输出: <out>/diff_main.json, <out>/diff_docx_only.json
"""
import argparse, json, re, unicodedata
from pathlib import Path
import fitz

def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    for a, b in [("，", ","), ("。", "."), ("；", ";"), ("（", "("), ("）", ")"), ("：", ":")]:
        s = s.replace(a, b)
    return s

def sentences(s):
    return [p for p in re.split(r"(?<=[。；;])", s) if norm(p)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config, encoding="utf-8"))
    out = Path(cfg["out"])
    # body zone: pages between body_start and body_end (0-based), default full
    p0 = cfg.get("body_start", 0)
    p1 = cfg.get("body_end", None)

    doc = fitz.open(cfg["pdf"])
    rng = range(p0, p1 if p1 is not None else len(doc))
    pdf_units = []
    for pno in rng:
        lines = doc[pno].get_text().split("\n")
        while lines and re.fullmatch(r"\s*\d{1,3}\s*", lines[0]):
            lines = lines[1:]
        while lines and re.fullmatch(r"第\s*\d+\s*页.*", lines[-1].strip()):
            lines = lines[:-1]
        pdf_units.append((pno, "\n".join(lines)))
    pdf_text = "".join(t for _, t in pdf_units)
    pdf_norm = norm(pdf_text)

    items = json.load(open(out / "docx_struct.json", encoding="utf-8"))
    d0, d1 = cfg.get("docx_body", [0, len(items)])
    parts = []
    for it in items[d0:d1]:
        if it["type"] == "p":
            parts.append(it["text"])
        else:
            parts += ["|".join(r) for r in it["rows"]]
    docx_text = "".join(parts)
    docx_norm = norm(docx_text)

    missing, found, pos = [], 0, 0
    for s in sentences(pdf_text):
        ns = norm(s)
        if len(ns) < 6:
            continue
        idx = docx_norm.find(ns[:20], max(0, pos - 50))
        if idx == -1:
            idx = docx_norm.find(ns[:20])
        if idx == -1:
            missing.append(s.strip()[:120])
        else:
            found += 1
            pos = idx + len(ns)

    extra = [s.strip()[:120] for s in sentences(docx_text)
             if len(norm(s)) >= 10 and norm(s)[:20] not in pdf_norm]

    json.dump({"pdf_chars": len(pdf_norm), "docx_chars": len(docx_norm),
               "sent_found": found, "sent_missing": len(missing),
               "missing_samples": missing[:80]},
              open(out / "diff_main.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(extra[:80], open(out / "diff_docx_only.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"pdf {len(pdf_norm)}ch docx {len(docx_norm)}ch | checked {found+len(missing)} miss {len(missing)} | docx-only {len(extra)}")

if __name__ == "__main__":
    main()

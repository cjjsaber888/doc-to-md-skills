#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pipeline_template.py — OCR 损坏中文公文/工程 PDF → 向量库 Markdown 最小骨架。

照抄流程：
  1. 提取嵌入文本层（fitz 逐页）。
  2. 测绘章节边界（扫描「第X章」首次出现的页号，硬编 SECTIONS）。
  3. 逐页 fix() 纠错 + is_garbage() 过滤 + is_heading() 探测子标题。
  4. 估算表/概算表按阅读顺序逐行保真发射（不重排网格）。
  5. 组装：7 字段元信息头 + 公文分支结构 + 嵌入附件嵌套。

使用前：先把 SECTIONS / SKIP_TABLE_LINES / 关键数字核对 按你的文档填好。
"""
import fitz
from correction_lib import fix, is_garbage, is_heading

SRC = r"your_file.pdf"
OUT_DRAFT = r"ocr_draft.txt"

doc = fitz.open(SRC)
N = doc.page_count
per_page = [doc[i].get_text("text") for i in range(N)]

# ---------------------------------------------------------------------------
# 章节地图：(start, end, heading, kind)  kind: 'chap' 章节 / 'pre' 前置 / 'toc' 目录
# 大文档务必用扫描得到的「第X章首次出现页号」硬编，不要靠正则猜。
# ---------------------------------------------------------------------------
SECTIONS = [
    (1, 9, "# 公文全称", "chap"),
    (10, 16, "## 附件清单", "att"),
    (34, 35, "## 可行性研究报告·目录", "toc"),
    (37, 55, "## 第1章 概述", "chap"),
    # ... 按你的文档补齐 第2~N章 ...
]

# 估算表页码区间（按关键词定位）。表内单元格在提取结果里是独立行，逐行保真即可。
ESTIMATE_PAGES = range(257, 276)
SKIP_TABLE_LINES = {"S99公路", "可行性研究报告", "金额(万元)", "单位", "数量", "分项编号", "技术经济指标", "工程或费用名称"}

# 关键数字核对清单（写完跑一遍 grep，确认跨文件一致、求和闭环）
KEY_FIGURES = ["256933.05", "193773.70", "18.8千米", "100千米/小时", "公路-I级"]


def emit_estimate():
    out = ["### 工可投资估算表（单元格按原文阅读顺序逐行呈现，金额单位：万元）", ""]
    out.append("> 说明：原 PDF 表格单元格在文本层提取中为独立行，以下按阅读顺序逐行保留全部数值以保证数字零失真，未做网格重排。")
    out.append("")
    for pg in ESTIMATE_PAGES:
        for line in per_page[pg - 1].splitlines():
            t = fix(line.strip())
            if not t or is_garbage(t) or t in SKIP_TABLE_LINES:
                continue
            out.append(t)
    return out


def main():
    lines = []
    for (s, e, h, kind) in SECTIONS:
        lines.append(""); lines.append(h); lines.append("")
        if kind == "chap" and s <= min(ESTIMATE_PAGES) <= e:
            for pg in range(s, e + 1):
                if s <= pg <= max(ESTIMATE_PAGES):
                    continue
                for line in per_page[pg - 1].splitlines():
                    ls = fix(line.strip())
                    if not ls or is_garbage(ls):
                        continue
                    hh = is_heading(ls)
                    if hh:
                        lines.append(""); lines.append(hh[0] + " " + hh[1]); lines.append("")
                    else:
                        lines.append(ls)
            lines += emit_estimate()
        else:
            for pg in range(s, e + 1):
                for line in per_page[pg - 1].splitlines():
                    ls = fix(line.strip())
                    if not ls or is_garbage(ls):
                        continue
                    hh = is_heading(ls)
                    if hh:
                        lines.append(""); lines.append(hh[0] + " " + hh[1]); lines.append("")
                    else:
                        lines.append(ls)
    with open(OUT_DRAFT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("draft lines:", len(lines))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
清洗文本 → 标准 Markdown
要点: YAML 元数据置顶 / 层级路径转 # ## 标题 / 表格转管道表 / 图片占位语法 / 隐私脱敏
"""
import re, sys, os


def S(t):
    return "".join(ch for ch in t if not (0xD800 <= ord(ch) <= 0xDFFF))


ID_RE = re.compile(r'(?<![0-9])(\d{6})(19|20)(\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])(\d{3})([0-9Xx])(?![0-9])')
PHONE_PAT = re.compile(r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)')


def _id_checksum(b17):
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    c = "10X98765432"
    return c[sum(int(b17[i]) * w[i] for i in range(17)) % 11]


def mask(t):
    def _id(m):
        b = m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5) + m.group(6)
        if _id_checksum(b).upper() != m.group(7).upper():
            return m.group(0)
        return f"{m.group(1)}******{m.group(7)}"
    return PHONE_PAT.sub(r'\1****\2', ID_RE.sub(_id, t))


def main(src, dst, title):
    with open(src, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")

    meta = {}
    stats = {}
    i = 0
    while i < len(lines) and not lines[i].startswith("# 正文"):
        l = lines[i].strip()
        if l.startswith("# "):
            i += 1
            continue
        m = re.match(r'^([^：]{2,10})：(.*)$', l)
        if m:
            meta[m.group(1)] = m.group(2).strip()
        i += 1
    for k in list(meta):
        if k in ("总页数", "正文页", "图片占位", "含表页", "表格行", "空白页") \
                or k.startswith("剔除页"):
            stats[k] = meta.pop(k)
    stats.pop("剔除页脚候选", None)

    body = lines[i + 1:]

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    n_tbl = n_head = n_img = 0
    in_tbl = False
    tbl_rows = []
    out = []

    def flush_tbl():
        nonlocal tbl_rows, in_tbl, n_tbl
        if not tbl_rows:
            return
        rows = [r for r in tbl_rows if r.strip(" |")]
        # 兜底：剔除误入表格单元格的层级标记
        rows = [r for r in rows if "[层级路径]" not in r]
        # 表格行同样要脱敏（身份证多出现在人员/资质表里）
        rows = [mask(r) for r in rows]
        if len(rows) >= 2:
            out.append("| " + " | ".join(rows[0].split(" | ")) + " |")
            out.append("| " + " | ".join(["---"] * len(rows[0].split(" | "))) + " |")
            for r in rows[1:]:
                out.append("| " + " | ".join(r.split(" | ")) + " |")
            n_tbl += 1
        elif rows:
            out.append("| " + " | ".join(rows[0].split(" | ")) + " |")
        tbl_rows = []
        in_tbl = False

    for l in body:
        l = S(l).rstrip()
        if l.startswith("【结构化表格】"):
            flush_tbl()
            in_tbl = True
            tbl_rows = []
            continue
        if l.startswith("【表格结束】"):
            flush_tbl()
            continue
        if in_tbl:
            tbl_rows.append(l)
            continue

        m = re.match(r'^\[层级路径\]\s*【([^】]+)】\s*(.*)$', l)
        if m:
            flush_tbl()
            mod, rest = m.group(1), m.group(2).strip()
            parts = [p.strip() for p in rest.split(">") if p.strip()]
            if "扫描图片页" in rest:
                n_img += 1
                out.append("#" * min(len(parts) + 2, 6) + " " + " > ".join(parts))
                out.append(f"> [!NOTE] 本页为扫描图片（属【{mod}】），无文字层，"
                           f"内容需回原 PDF 读图。")
                continue
            lvl = min(len(parts) + 2, 6)
            if parts:
                out.append("#" * lvl + " " + " > ".join(parts))
                n_head += 1
            else:
                out.append("#" * lvl + f" 【{mod}】")
                n_head += 1
            if mod and mod not in rest:
                out.append(f"> 所属模块：**{mod}**")
            continue

        if l.startswith("[图片扫描件]") or "扫描图片页" in l or "图片扫描件" in l:
            n_img += 1
            out.append("> [!NOTE] " + l.replace("[层级路径]", "").strip())
            continue
        if not l.strip():
            continue
        # 勾选符规范化
        l = l.replace("☑", "【已勾选】").replace("□", "【未勾选】").replace("√", "【已勾选】")
        if l.startswith(">"):
            out.append(mask(l))
        else:
            out.append(mask(l))

    flush_tbl()

    with open(dst, "w", encoding="utf-8", errors="replace") as f:
        f.write("---\n")
        f.write(f"document_type: 投标文件\n")
        f.write(f"title: {title}\n")
        for k, v in meta.items():
            f.write(f"{k}: {v or '未识别'}\n")
        for k, v in stats.items():
            f.write(f"{k}: {v}\n")
        f.write(f"source_file: {os.path.basename(src)}\n")
        f.write(f"markdown_tables: {n_tbl}\n")
        f.write(f"markdown_image_pages: {n_img}\n")
        f.write("---\n\n")
        f.write(f"# {title}\n\n")
        f.write("> 本文件由 clean_pipeline.py + to_markdown.py 从投标 PDF 自动转换，")
        f.write("章节层级来自 PDF 文本层的章/节标题推断，隐私字段已脱敏。\n\n")
        f.write("> 标「扫描图片页」的段落为无文字层的图片（多为证照、图纸、保函原件），")
        f.write("其内容不在本文件内，需回原 PDF 读图。\n\n")
        f.write("\n".join(out))
        f.write("\n")
    print(f"[MD] {title} 标题{n_head} 表格{n_tbl} 图片占位{n_img} -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
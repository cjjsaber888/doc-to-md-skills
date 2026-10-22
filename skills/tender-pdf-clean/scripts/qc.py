# -*- coding: utf-8 -*-
"""
全量质检：MD 六项锚点 / 空文件 / 残留清洗标记 / 未脱敏身份证手机 / 块完整性
"""
import os, re, glob, sys

WS = os.environ.get("WORK_DIR", r"work")   # 输出工作目录
MD = os.path.join(WS, "md")
CK = os.path.join(WS, "chunks")

rows = []
issues = []
ID_RE = re.compile(r'(?<![0-9])(\d{6})(19|20)(\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])(\d{3})([0-9Xx])(?![0-9])')
PHONE_PAT = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
CLEAN_MARK = re.compile(r'\[层级路径\]|【结构化表格】|【表格结束】')
W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
C = "10X98765432"


def real_ids(txt):
    """只统计 GB11643 校验位通过的身份证，排除统一社会信用代码"""
    n = 0
    for m in ID_RE.finditer(txt):
        b = m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5) + m.group(6)
        if C[sum(int(b[i]) * W[i] for i in range(17)) % 11].upper() == m.group(7).upper():
            n += 1
    return n

for md in sorted(glob.glob(os.path.join(MD, "*.md"))):
    name = os.path.basename(md)
    txt = open(md, encoding="utf-8", errors="replace").read()
    ck = os.path.join(CK, name[:-3] + "_向量分块.md")
    cktxt = open(ck, encoding="utf-8", errors="replace").read() if os.path.exists(ck) else ""

    has_yaml = txt.startswith("---") and txt.count("---") >= 2
    n_head = len(re.findall(r'^#{1,6} ', txt, re.M))
    n_tbl = len(re.findall(r'^\|.*\|$', txt, re.M))
    n_img = txt.count("[!NOTE]")
    n_mark = len(CLEAN_MARK.findall(txt))
    n_id = real_ids(txt)
    n_ph = len(PHONE_PAT.findall(txt))
    n_char = len(txt)

    blocks = [b for b in cktxt.split("\n---\n") if "【章节路径：" in b]
    bad_anchor = sum(1 for b in blocks if b.count("【章节路径：") != 1)
    bad_cat = sum(1 for b in blocks if "【分类：" not in b)
    bad_kw = sum(1 for b in blocks if "关键词：" not in b)
    over = sum(1 for b in blocks if len(b) > 3300)

    rows.append((name, n_char, n_head, n_tbl, n_img, n_mark, n_id, n_ph,
                 len(blocks), bad_anchor, bad_cat, bad_kw, over))

    if n_char < 20000:
        issues.append(f"{name}: 正文偏小 {n_char} 字符")
    if n_mark:
        issues.append(f"{name}: 残留清洗标记 {n_mark} 处")
    if n_id:
        issues.append(f"{name}: 未脱敏身份证 {n_id} 处")
    if n_ph:
        issues.append(f"{name}: 未脱敏手机号 {n_ph} 处")
    if not blocks:
        issues.append(f"{name}: 无分块产物")
    if bad_anchor:
        issues.append(f"{name}: 锚点数异常 {bad_anchor} 块")
    if bad_cat:
        issues.append(f"{name}: 缺分类标签 {bad_cat} 块")
    if bad_kw:
        issues.append(f"{name}: 缺关键词 {bad_kw} 块")
    if over:
        issues.append(f"{name}: 超长块 {over} 块")

hdr = f"{'文件':40s} {'字符':>8s} {'标题':>5s} {'表行':>6s} {'图占':>5s} {'残标':>4s} {'未脱敏':>5s} {'块数':>5s}"
print(hdr)
print("-" * len(hdr))
for r in rows:
    print(f"{r[0][:38]:40s} {r[1]:8d} {r[2]:5d} {r[3]:6d} {r[4]:5d} {r[5]:4d} "
          f"{r[6]+r[7]:5d} {r[8]:5d}")

print("\n=== 问题清单 ===")
if issues:
    for i in issues:
        print("  " + i)
else:
    print("  全部通过")

with open(os.path.join(WS, "qc_report.md"), "w", encoding="utf-8") as f:
    f.write("# 投标PDF转md 全量质检报告\n\n")
    f.write("| " + " | ".join(["文件", "字符数", "标题数", "表行", "图片占位",
                              "残留标记", "未脱敏", "分块数"]) + " |\n")
    f.write("|" + "---|" * 8 + "\n")
    for r in rows:
        f.write(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]+r[7]} | {r[8]} |\n")
    f.write("\n## 问题\n\n")
    f.write("\n".join("- " + i for i in issues) if issues else "全部通过\n")
print(f"\n质检报告: {os.path.join(WS,'qc_report.md')}")
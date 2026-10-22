# -*- coding: utf-8 -*-
"""
投标 PDF 清洗分层流水线（单文件版）
输入: 源PDF   输出: 干净分层纯文本
要点: 字节级探针 / 页眉页脚三重剔除 / 章节四层路径 / 表格标记 / 附件判定 / 10字段元数据
"""
import fitz, re, sys, os, collections


def S(t):
    """剥离孤立代理字符，防止 utf-8 写出时 UnicodeEncodeError 崩盘"""
    if not t:
        return ""
    return "".join(ch for ch in t if not (0xD800 <= ord(ch) <= 0xDFFF))


CHAP_MOD = {
    "第一章": "商务文件", "第二章": "技术文件",
    "第三章": "报价文件", "第四章": "附件证明",
}
SIG_CHAP = re.compile(
    r'^(第[一二三四五六七八九十]+章)\s*[（(]?\s*(商务文件|技术文件|报价文件|附件|投标文件)')
SIG_SEC = re.compile(r'^(第[一二三四五六七八九十百]+节)\s*(\S.{0,40})')
SIG_SUB = re.compile(r'^([（(]?[一二三四五六七八九十\d]+[)）]?)\s*[、.．]?\s*(\S.{0,40})$')

TECH_WORDS = [
    "总体施工组织布置及规划", "主要工程项目的施工方案", "工期保证体系",
    "安全生产管理体系", "工程质量管理体系", "环境保护水土保持",
    "文明施工文物保护", "项目风险预测与防范", "施工方案方法与技术措施",
]
CERT_WORDS = ["营业执照", "资质证书", "安全生产许可证", "认证证书", "体系认证",
              "执业资格证书", "注册证书", "开户许可证", "身份证", "审计报告",
              "财务报表", "资信证明", "获奖", "信用评价", "业绩"]

META_PAT = {
    "项目名称":   re.compile(r'项目名称[：:]\s*([^\n\r]{4,80})'),
    "报建编号":   re.compile(r'(?:报建编号|招标编号|项目编号|工程编号)[：:]\s*([A-Za-z0-9\-]{6,40})'),
    # 原文常写成「XX公司（招标人名称）：」，括号注释在冒号前，需容忍
    "标段名称":   re.compile(r'(?:标段名称|招标标段名称)[：:]\s*([^\n\r]{4,80})'),
    "标段号":     re.compile(r'标段号[：:]\s*([A-Za-z0-9\-]{1,12})'),
    "招标人":     re.compile(r'招标人(?:名称)?(?:[^：:\n\r]{0,10})[：:]\s*([^\n\r]{4,50})'),
    "投标人":     re.compile(r'投标人(?:名称)?(?:[^：:\n\r]{0,10})[：:]\s*([^\n\r]{4,50})'),
    "法定代表人": re.compile(r'法定代表人[：:]?\s*([^\u4e00-\u9fff\n\r]{2,4})(?=[^\n\r]{0,14}(?:系|为|性别|身份证|职务|现任|签章|公章))'),
    "项目负责人": re.compile(r'(?:项目负责人|项目经理)[：:]\s*([^\n\r]{2,20})'),
    "投标日期":   re.compile(r'投标日期[：:]\s*([^\n\r]{4,30})'),
    "工期":       re.compile(r'(?:计划工期|施工工期|工期)[：:]\s*([^\n\r]{2,40})'),
    "投标保证金": re.compile(r'(?:投标保证金(?:金额|数额)?)(?:[^：:\n\r]{0,8})[：:]\s*([^\n\r]{2,40})'),
    "保函形式":   re.compile(r'(银行保函|现金保函|电子保函|担保公司保函|第三方担保)'),
}

PAGE_PAT = re.compile(r'^(第\s*\d+\s*页(\s*共\s*\d+\s*页)?|-\s*\d+\s*-|\d{1,4})$')
TOC_PAT = re.compile(r'\.{2,}\s*\d*\s*$')
# 身份证：GB11643 校验位验证。18 位纯数字但校验位不过的多为统一社会信用代码，不脱敏
ID_RE = re.compile(r'(?<![0-9])(\d{6})(19|20)(\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])(\d{3})([0-9Xx])(?![0-9])')
PHONE_PAT = re.compile(r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)')


def _id_checksum(body17):
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    c = "10X98765432"
    s = sum(int(body17[i]) * w[i] for i in range(17))
    return c[s % 11]


def mask(t):
    def _id(m):
        b = m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5) + m.group(6)
        if _id_checksum(b).upper() != m.group(7).upper():
            return m.group(0)
        return f"{m.group(1)}******{m.group(7)}"
    t = ID_RE.sub(_id, t)
    t = PHONE_PAT.sub(r'\1****\2', t)
    return t


def clean_title(s):
    return re.sub(r'\s+', ' ', TOC_PAT.sub('', s)).strip()


def main(src, dst):
    raw = open(src, 'rb').read(8)
    if not raw.startswith(b'%PDF'):
        print(f"[空壳] {os.path.basename(src)} 无 %PDF 头，不可恢复")
        return 1
    doc = fitz.open(src)
    NP = doc.page_count

    pages = []
    for pno in range(NP):
        page = doc[pno]
        h = page.rect.height
        items = []
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b.get("lines", []):
                txt = S("".join(sp.get("text", "") for sp in ln.get("spans", []))).strip()
                if not txt:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                items.append({"t": txt, "y0": y0, "y1": y1})
        txt = S(page.get_text("text"))
        tabs = []
        # find_tables 对全文逐页调用很慢（约 1.3s/60页），先用廉价信号筛出表格候选页
        if len(txt) > 150 and ("：" in txt or "|" in txt or re.search(r'[一-鿿]\s*\n', txt)):
            try:
                for tb in page.find_tables().tables:
                    rows = tb.extract()
                    if rows and len(rows) >= 2:
                        tabs.append(rows)
            except Exception:
                pass
        pages.append({"items": items, "text": txt, "img": bool(page.get_images()),
                      "h": h, "tabs": tabs, "no": pno + 1})
    doc.close()

    # 页眉页脚：坐标区 + 跨页频次
    THR = max(3, int(NP * 0.02))
    hc, fc = collections.Counter(), collections.Counter()
    for p in pages:
        for it in p["items"]:
            if it["y0"] < 0.09 * p["h"]:
                hc[it["t"]] += 1
            if it["y1"] > 0.92 * p["h"]:
                fc[it["t"]] += 1
    HEAD = {t for t, c in hc.items() if c >= THR}
    FOOT = {t for t, c in fc.items() if c >= THR}

    def is_hf(t):
        return t in HEAD or t in FOOT or bool(PAGE_PAT.match(t))

    chap = sec = sub = None
    mod = "商务文件"
    in_tech = False
    out = []
    stats = collections.Counter()

    for p in pages:
        txt = p["text"]
        if not txt.strip():
            stats["空白页"] += 1
            continue
        if len(txt) < 200 and p["img"]:
            stats["图片占位"] += 1
            label = "附件证明" if any(w in txt for w in CERT_WORDS) else "图片扫描件"
            out.append(f"[层级路径] 【{label}】 > 第{p['no']}页"
                       f"（扫描图片页，文字层不可得，内容需读原图）")
            continue

        lns = [it["t"] for it in p["items"] if not is_hf(it["t"])]
        # 只扫前6个非空行判章/节，避免目录页全文污染
        for t in lns[:6]:
            tc = clean_title(t)
            m = SIG_CHAP.match(tc)
            if m:
                chap, sec, sub = tc, None, None
                mod = CHAP_MOD.get(m.group(1), mod)
                in_tech = "技术" in tc
                break
            if SIG_SEC.match(tc):
                sec, sub = tc, None
                break

        if sum(1 for w in TECH_WORDS if w in txt) >= 2 and chap is None and mod != "技术文件":
            chap = "第二章 技术文件（第一阶段）"
            mod = "技术文件"
            in_tech = True

        body = [clean_title(x) for x in lns]
        body = [x for x in body if x]

        sub = None
        if len(body) <= 3:
            for x in body[:2]:
                if SIG_SUB.match(x) and len(x) <= 30 and not x.endswith("。"):
                    sub = x
                    break

        path = f"[层级路径] 【{mod}】"
        if chap:
            path += f" > {chap}"
        if sec:
            path += f" > {sec}"
        if sub:
            path += f" > {sub}"
        out.append(path)

        for rows in p["tabs"]:
            out.append("【结构化表格】")
            for r_ in rows:
                cells = [S(c).replace("|", "¦").replace("\n", " ").strip() for c in r_]
                # 原件表格串行会把本章层级标记塞进单元格，需剔除
                cells = [c for c in cells if not c.startswith("[层级路径]")]
                cells = [c for c in cells if c]
                if cells:
                    out.append(" | ".join(cells))
                    stats["表格行"] += 1
            out.append("【表格结束】")
            stats["含表页"] += 1

        out.extend(body)
        stats["正文页"] += 1

    alltxt = "\n".join(p["text"] for p in pages)
    meta = {}
    for k, pat in META_PAT.items():
        vals = []
        for m in pat.finditer(alltxt):
            v = re.sub(r'\s+', '', S(m.group(1)).strip())
            if v and v not in vals:
                vals.append(v)
            if len(vals) >= 3:
                break
        meta[k] = "；".join(vals) if vals else ""

    # 保证金金额常印在银行保函原件（图片页），文字层抓不到。如实标注，不臆造数字
    if meta.get("投标保证金", "").startswith("（") or not meta.get("投标保证金"):
        meta["投标保证金"] = "（金额在银行保函原件扫描页，文字层不可得，见原件）"

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", errors="replace") as f:
        f.write("# 元数据\n")
        for k in META_PAT:
            f.write(f"{k}：{meta[k]}\n")
        f.write("\n# 清洗统计\n总页数：%d\n" % NP)
        for k in ("正文页", "图片占位", "含表页", "表格行", "空白页"):
            f.write(f"{k}：{stats.get(k, 0)}\n")
        f.write(f"剔除页眉候选：{len(HEAD)}  剔除页脚候选：{len(FOOT)}\n")
        f.write("\n# 正文\n")
        for l in out:
            f.write(mask(S(l)) + "\n")
    print(f"[OK] {os.path.basename(src)} 页{NP} 正文{stats.get('正文页',0)} "
          f"图占{stats.get('图片占位',0)} 表页{stats.get('含表页',0)} "
          f"表行{stats.get('表格行',0)} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
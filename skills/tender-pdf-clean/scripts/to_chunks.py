# -*- coding: utf-8 -*-
"""
Markdown → 向量分块
要点: ##为最小单元 / 3000字上限续拆 / 路径锚点 / 分类标签 / 关键词 / ---分隔
"""
import re, sys, os

MAXLEN = 3000

CERT_STRONG = ["资质证书", "安全生产许可证", "认证证书", "体系认证",
               "执业资格证书", "注册证书"]
FIN_WORDS = ["审计", "财务", "报表", "资产负债", "利润", "附注", "会计", "验资", "现金流量"]
BIZ_DICT = ["投标", "保函", "工期", "工程量清单", "报价", "评标", "资质", "承诺",
            "项目经理", "施工组织", "质量", "安全", "文明施工", "环境保护"]
GLOBAL_WORDS = ["G99", "示例招标编号", "C99", "辅道", "示例地名"]


def S(t):
    return "".join(ch for ch in t if not (0xD800 <= ord(ch) <= 0xDFFF))


def strip_prefix(t):
    t = re.sub(r'^第[一二三四五六七八九十百]+[章节]\s*', '', t)
    return t.strip()


def classify(chap, sec, text):
    if chap and "附件" in chap:
        return "财务附件" if any(w in text for w in FIN_WORDS) else "资质证件"
    if chap and "报价" in chap:
        return "报价"
    if chap and "技术" in chap:
        return "技术"
    if chap and "商务" in chap:
        if any(w in text for w in CERT_STRONG):
            return "资质证件"
        return "商务"
    if "报价" in (sec or ""):
        return "报价"
    if "技术" in (sec or ""):
        return "技术"
    return "商务"


def chunk_lines(lines):
    """按空行聚段，单段超长按行续切；表格每段重附表头"""
    paras, cur = [], []
    for l in lines:
        if not l.strip():
            if cur:
                paras.append(cur)
                cur = []
        else:
            cur.append(l)
    if cur:
        paras.append(cur)

    res = []
    for p in paras:
        if len("\n".join(p)) <= MAXLEN:
            res.append(p)
            continue
        is_tbl = p[0].lstrip().startswith("|")
        head = [p[0], p[1]] if is_tbl and len(p) >= 2 else []
        body = p[len(head):]
        cur2 = list(head)
        for l in body:
            if len("\n".join(cur2 + [l])) > MAXLEN and cur2:
                res.append(cur2)
                cur2 = list(head) if head else []
            cur2.append(l)
        if cur2:
            res.append(cur2)
    return res


def main(src, dst):
    with open(src, encoding="utf-8", errors="replace") as f:
        raw = f.read().split("\n")

    meta = []
    i = 0
    if raw and raw[0].strip() == "---":
        i = 1
        while i < len(raw) and raw[i].strip() != "---":
            meta.append(raw[i])
            i += 1
        i += 1

    # parse_pieces: # 为章, ## 为节；## 缺章时兜底
    pieces = []
    chapter = None
    section = None
    buf = []
    j = i
    while j < len(raw):
        l = raw[j]
        if re.match(r'^#\s+\S', l):
            if chapter is not None and (section is not None or buf):
                pieces.append((chapter, section, buf))
            chapter = l[2:].strip()
            section = None
            buf = []
        elif re.match(r'^##\s+\S', l):
            if chapter is None:
                chapter = "投标文档正文"
            if section is not None or buf:
                pieces.append((chapter, section, buf))
            section = l[3:].strip()
            buf = []
        elif l.strip():
            buf.append(l)
        j += 1
    if buf or (chapter and section):
        pieces.append((chapter, section, buf))

    if not pieces:
        pieces = [("投标文档正文", "正文", [x for x in raw[i:] if x.strip()])]

    chunks = []
    for chap, sec, lines in pieces:
        base = strip_prefix(chap or "投标文档正文")
        if sec:
            path = f"{base}-{strip_prefix(sec)}"
        else:
            path = base
        for n, para in enumerate(chunk_lines(lines), 1):
            if not para:
                continue
            text = "\n".join(para)
            full = f"{chap or ''} {sec or ''} {text}"
            cat = classify(chap, sec, full)
            words = []
            for w in re.split(r'[\s、，,。/|]+', strip_prefix(sec or chap or "")):
                w = w.strip()
                if len(w) >= 2 and w not in words:
                    words.append(w)
            for w in BIZ_DICT:
                if w in full and w not in words:
                    words.append(w)
            for w in GLOBAL_WORDS:
                if w in full and w not in words:
                    words.append(w)
            anchor = path if n == 1 else f"{path}（第{n}段）"
            body = "\n".join(para).strip()
            chunks.append(
                f"【章节路径：{anchor}】\n"
                f"【分类：{cat}】\n\n{body}\n\n关键词：{'、'.join(words[:20])}\n"
            )

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", errors="replace") as f:
        f.write(f"# 向量分块 · {os.path.basename(src)}\n\n")
        f.write(f"块数：{len(chunks)}　单块上限：{MAXLEN}字\n\n")
        f.write("\n---\n\n".join(chunks))

    mx = max((len(c) for c in chunks), default=0)
    print(f"[CHUNK] {os.path.basename(src)} 块数{len(chunks)} 最大块{mx}字 -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
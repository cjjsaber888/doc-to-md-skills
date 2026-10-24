# -*- coding: utf-8 -*-
"""prune_vectors.py — 按当前 chunks.jsonl 的 ID 集合剪除向量库过期条目（模板）

背景：chunk ID 为全文哈希时，OCR 把占位符替换为真实文本会让受影响的块 ID 变化，
增量嵌入只加新向量，旧 ID 的向量成为孤儿（内容为占位符的陈旧条目）。
本脚本：保留 ID 仍在 chunks.jsonl 中的行，其余删除，重建索引并重写 meta。

适配新项目：改下面 ROOT / CHUNKS / VEC 三处路径。
用法：python prune_vectors.py
前置：faiss / numpy 装在受管 venv（onnxruntime / tokenizers / faiss-cpu / numpy 齐全）。
"""
import os, json, shutil, tempfile, time

ROOT = r"<KB_ROOT>"          # ← 改这里：项目源根
CHUNKS = os.path.join(ROOT, "知识库", "02_结构化", "chunks.jsonl")
VEC = os.path.join(ROOT, "知识库", "03_向量库")
IDX = os.path.join(VEC, "vectors.faiss")
META = os.path.join(VEC, "meta.jsonl")
STATE = os.path.join(VEC, "state.json")


def log(m):
    print("[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), m), flush=True)


def cid(r):
    """与 embed.py 的 chunk ID 口径必须一致：全文哈希（禁止只哈希正文前 300 字，
    表格块表头相同会撞车；外环西段实测 587 个 ID 撞车涉及 10111 行）。"""
    import hashlib
    h = hashlib.md5()
    h.update((r.get("file", "") + "\x00" + r.get("head", "") + "\x00"
              + r.get("text", "")).encode("utf-8", "replace"))
    return h.hexdigest()


def main():
    import faiss
    # 1. 当前合法 ID 集合
    valid = set()
    for l in open(CHUNKS, encoding="utf-8"):
        valid.add(cid(json.loads(l)))
    log("当前 chunks 合法 ID %d 个" % len(valid))

    # 2. 读旧索引 + 旧 meta（faiss C++ 读接口不吃中文路径，走 ASCII 临时副本）
    tmp_ascii = os.path.join(tempfile.gettempdir(), "wb_vectors_tmp.faiss")
    shutil.copyfile(IDX, tmp_ascii)
    ix = faiss.read_index(tmp_ascii)
    vecs = ix.reconstruct_n(0, ix.ntotal)
    old_meta = [json.loads(l) for l in open(META, encoding="utf-8")]
    log("旧索引 %d 条，旧 meta %d 行" % (ix.ntotal, len(old_meta)))
    assert ix.ntotal == len(old_meta), "索引与 meta 行数不一致，先修 embed"

    # 3. 过滤过期条目
    keep_idx, keep_meta = [], []
    for j, m in enumerate(old_meta):
        if m["id"] in valid:
            keep_idx.append(j)
            keep_meta.append(m)
    log("保留 %d 条，剪除过期 %d 条" % (len(keep_idx), len(old_meta) - len(keep_idx)))

    # 4. 重建（写也走 ASCII 临时副本）
    import numpy as np
    new_vecs = vecs[keep_idx] if keep_idx else np.zeros((0, vecs.shape[1]), np.float32)
    nix = faiss.IndexFlatIP(new_vecs.shape[1])
    nix.add(new_vecs)
    faiss.write_index(nix, tmp_ascii)
    shutil.copyfile(tmp_ascii, IDX)
    with open(META, "w", encoding="utf-8") as f:
        for k, m in enumerate(keep_meta):
            m = dict(m)
            m["i"] = k
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    json.dump({"new_done": 0, "dim": int(new_vecs.shape[1])}, open(STATE, "w"))
    log("剪枝完成：%d 条 × %d 维，meta %d 行" % (nix.ntotal, nix.d, len(keep_meta)))

    # 5. 三方对齐校验（注意：不是 ntotal == meta 行数，而是 == chunks 唯一 ID 数）
    missing = len(valid) - len(keep_idx)
    if missing:
        log("警告：仍有 %d 个合法 ID 没有对应向量（应跑 embed.py 补齐）" % missing)
    else:
        log("校验通过：向量数 = meta 行数 = chunks 唯一 ID 数 = %d" % nix.ntotal)


if __name__ == "__main__":
    main()

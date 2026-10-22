# -*- coding: utf-8 -*-
"""
MD 知识库向量化模板（bge-small-zh-v1.5 + FAISS，纯单进程 onnxruntime）。

来源：某知识库 477 文档 / 73,217 块实战验证版（2026-10-12），参数化改造。
用法:
    python vectorize_template.py <知识库目录>          # 全量
    VEC_LIMIT=5 python vectorize_template.py <知识库目录>   # 试跑前 5 篇

前置: 知识库目录须含 _meta.json（rel_path/abs_path/file_type/doc_category/...）。
产物: chunks.jsonl / vectors.faiss / vectors_manifest.json / _meta.json 回写 has_vectors。
依赖: envs/ocr venv（onnxruntime, tokenizers, faiss-cpu, numpy）。
铁律: 禁用 fastembed 的 parallel（Windows spawn 死锁）；faiss 中文路径走临时 ASCII 文件。
"""
import os, re, json, time, sys, tempfile, shutil, logging, hashlib, glob

# ---------------------------------------------------------------- 参数
KB_DIR = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else None
if not KB_DIR or not os.path.isdir(KB_DIR):
    sys.exit("usage: python vectorize_template.py <知识库目录>")

META_PATH = os.path.join(KB_DIR, "_meta.json")
CHUNKS_PATH = os.path.join(KB_DIR, "chunks.jsonl")
FAISS_PATH = os.path.join(KB_DIR, "vectors.faiss")
MANIFEST_PATH = os.path.join(KB_DIR, "vectors_manifest.json")
# faiss 不支持中文路径: 真身写临时 ASCII 路径, 结束 move 过去
_TMP_NAME = "kbvec_%s.faiss" % hashlib.md5(KB_DIR.encode("utf-8")).hexdigest()[:10]
TMP_FAISS = os.path.join(tempfile.gettempdir(), _TMP_NAME)

def resolve_model_dir():
    """模型目录解析: 环境变量 > 稳定副本 > Temp fastembed 缓存。"""
    env = os.environ.get("BGE_MODEL_DIR")
    if env and os.path.isfile(os.path.join(env, "model_optimized.onnx")):
        return env
    stable = r"C:\Users\<USER>\.workbuddy\models\bge-small-zh-v1.5"
    if os.path.isfile(os.path.join(stable, "model_optimized.onnx")):
        return stable
    pat = (r"C:\Users\<USER>\AppData\Local\Temp\fastembed_cache"
           r"\models--Qdrant--bge-small-zh-v1.5\snapshots\*")
    for d in sorted(glob.glob(pat)):
        if os.path.isfile(os.path.join(d, "model_optimized.onnx")):
            return d
    sys.exit("未找到 bge-small-zh-v1.5 模型。请设 BGE_MODEL_DIR 或先经代理下载:\n"
             "  HTTP(S)_PROXY=http://127.0.0.1:7897 python -c \"from fastembed import TextEmbedding;"
             " TextEmbedding(model_name='BAAI/bge-small-zh-v1.5')\"")

MODEL_DIR = resolve_model_dir()
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DIM = 512

CHUNK_CHARS = 256        # 单块目标字符数 (中文)
OVERLAP = 48             # 相邻块字符重叠
TRUNC_TOKENS = 288       # 模型输入截断上限 (>512 会 OOM)
CAP_NORMAL = 600         # 普通文档单篇分块上限
CAP_DUMP = 250           # 巨型表格/扫描件 dump 单篇分块上限
DUMP_TYPES = {"xlsx", "xls"}
BATCH = 64
THREADS = 10
CHECKPOINT_EVERY = 5000

LIMIT = int(os.environ.get("VEC_LIMIT", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                               "vectorize.log"), encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("vectorize")

# ---------------------------------------------------------------- frontmatter
FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

def strip_frontmatter(text):
    m = FM_RE.match(text)
    return (text[m.end():], {}) if m else (text, {})

# ---------------------------------------------------------------- chunking
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

def chunk_markdown(body, max_chunks):
    lines = body.split("\n")
    heading_stack, buf, chunks = [], [], []

    def flush(keep_overlap=True):
        nonlocal buf
        if not buf:
            return
        joined = "\n".join(buf)
        hpath = " > ".join(t for _, t in heading_stack)
        text = (hpath + "\n" + joined) if hpath else joined
        chunks.append(text)
        if keep_overlap and len(chunks) < max_chunks:
            tail = joined[-OVERLAP:] if len(joined) > OVERLAP else joined
            buf = [tail] if tail.strip() else []
        else:
            buf = []

    for ln in lines:
        hm = HEADING_RE.match(ln.strip())
        if hm:
            flush()
            lvl = len(hm.group(1)); txt = hm.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= lvl:
                heading_stack.pop()
            heading_stack.append((lvl, txt)); buf = [ln.strip()]; continue
        if not ln.strip():
            if buf:
                buf.append("")
            continue
        if buf and len("\n".join(buf)) + len(ln) + 1 > CHUNK_CHARS:
            flush()
            if len(chunks) >= max_chunks:
                break
        buf.append(ln)
    flush(keep_overlap=False)
    return chunks[:max_chunks]

# ---------------------------------------------------------------- embedder
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

class BgeEmbedder:
    """CLS pooling + L2 归一, 与 fastembed OnnxTextEmbedding 逐位一致。"""

    def __init__(self, model_dir, threads=THREADS):
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(
            os.path.join(model_dir, "model_optimized.onnx"),
            sess_options=so, providers=["CPUExecutionProvider"])
        self.input_names = [n.name for n in self.sess.get_inputs()]
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(max_length=TRUNC_TOKENS, direction="right")
        self.tok.enable_padding(direction="right", pad_id=0, pad_type_id=0,
                                pad_token="[PAD]", length=None)

    def _encode_batch(self, texts):
        enc = self.tok.encode_batch(texts)
        input_ids = np.array([e.ids for e in enc], dtype=np.int64)
        attn = np.array([e.attention_mask for e in enc], dtype=np.int64)
        onnx_in = {"input_ids": input_ids}
        if "attention_mask" in self.input_names:
            onnx_in["attention_mask"] = attn
        if "token_type_ids" in self.input_names:      # bge 需要第三路全零
            onnx_in["token_type_ids"] = np.zeros_like(input_ids)
        out = self.sess.run(None, onnx_in)[0]          # (b, seq, dim)
        pooled = out[:, 0, :].astype(np.float64)       # CLS pooling
        norm = np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        return (pooled / norm).astype(np.float32)

    def embed(self, texts):
        vecs = []
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            try:
                vecs.append(self._encode_batch(batch))
            except Exception as e:
                log.warning("batch embed failed (%s); falling back per-item", e)
                for t in batch:
                    try:
                        vecs.append(self._encode_batch([t]))
                    except Exception:
                        vecs.append(np.zeros((1, DIM), dtype=np.float32))
        return np.vstack(vecs) if vecs else np.zeros((0, DIM), dtype=np.float32)

# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    meta = json.load(open(META_PATH, encoding="utf-8"))
    for i, d in enumerate(meta):
        d["doc_idx"] = i
    if LIMIT:
        log.info("VEC_LIMIT=%d -> first %d docs only", LIMIT, LIMIT)
        meta = meta[:LIMIT]

    # 1) 全量确定性分块
    all_chunks, capped_docs, empty_docs = [], [], 0
    for d in meta:
        ap = d.get("abs_path") or os.path.join(KB_DIR, d.get("rel_path", ""))
        try:
            text = open(ap, encoding="utf-8").read()
        except Exception as e:
            log.warning("read failed %s: %s", ap, e); continue
        body, _ = strip_frontmatter(text)
        if len(body.strip()) < 10:
            empty_docs += 1; continue
        ft = (d.get("file_type") or "").lower()
        cap = CAP_DUMP if ft in DUMP_TYPES else CAP_NORMAL
        ch = chunk_markdown(body, cap)
        if len(ch) >= cap:
            capped_docs.append((d.get("rel_path", ""), len(ch), ft))
        for c in ch:
            all_chunks.append({
                "doc_idx": d["doc_idx"],
                "rel_path": d.get("rel_path", ""),
                "source_file": d.get("source_file", ""),
                "section": d.get("section", ""),
                "doc_category": d.get("doc_category", ""),
                "date": d.get("date", ""),
                "file_type": d.get("file_type", ""),
                "text": c,
                "char_len": len(c),
            })
    log.info("chunking done: total_chunks=%d capped_docs=%d empty_docs=%d (%.1fs)",
             len(all_chunks), len(capped_docs), empty_docs, time.time() - t0)

    # 2) 写 chunks.jsonl (确定性, 可重跑)
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        for cid, c in enumerate(all_chunks):
            f.write(json.dumps({"id": cid, **c}, ensure_ascii=False) + "\n")
    log.info("wrote %s (%d lines)", CHUNKS_PATH, len(all_chunks))

    import faiss
    # 3) 断点续跑: 临时索引 + 参数签名 sidecar (防参数变更/旧测试污染)
    sig = hashlib.md5(json.dumps(
        {"c": CHUNK_CHARS, "o": OVERLAP, "t": TRUNC_TOKENS,
         "cn": CAP_NORMAL, "cd": CAP_DUMP, "n": len(all_chunks)}
    ).encode()).hexdigest()
    sidecar = TMP_FAISS + ".sig"
    start = 0
    if os.path.exists(TMP_FAISS) and os.path.exists(sidecar):
        try:
            if open(sidecar).read().strip() == sig:
                idx = faiss.read_index(TMP_FAISS)
                start = idx.ntotal
                log.info("resume: existing index ntotal=%d (sig match)", start)
            else:
                log.warning("checkpoint sig mismatch; discarding stale index")
                os.remove(TMP_FAISS); idx = faiss.IndexFlatIP(DIM)
        except Exception as e:
            log.warning("read existing index failed (%s); restarting", e)
            idx = faiss.IndexFlatIP(DIM); start = 0
    else:
        if os.path.exists(TMP_FAISS):
            os.remove(TMP_FAISS)
        idx = faiss.IndexFlatIP(DIM)
    open(sidecar, "w").write(sig)

    if start >= len(all_chunks):
        log.info("already fully embedded (%d == %d); finalizing", start, len(all_chunks))
    else:
        emb = BgeEmbedder(MODEL_DIR, threads=THREADS)
        texts = [c["text"] for c in all_chunks]
        tE = time.time()
        for i in range(start, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            v = emb.embed(batch)
            idx.add(v)
            if (idx.ntotal % CHECKPOINT_EVERY) < len(v) or i + BATCH >= len(texts):
                faiss.write_index(idx, TMP_FAISS)
            if (i - start) % 5000 < BATCH:
                rate = idx.ntotal / (time.time() - tE) if (time.time() - tE) > 0 else 0
                log.info("embedded %d/%d chunks (%.1f seq/s, eta %.1f min)",
                         idx.ntotal, len(texts), rate,
                         (len(texts) - idx.ntotal) / rate / 60 if rate else 0)
        log.info("embedding done: ntotal=%d (%.1fs)", idx.ntotal, time.time() - tE)

    # 4) move 到最终中文路径
    faiss.write_index(idx, TMP_FAISS)
    shutil.move(TMP_FAISS, FAISS_PATH)
    log.info("wrote %s ntotal=%d", FAISS_PATH, idx.ntotal)

    # 5) manifest (统一口径: 全部参数落档)
    manifest = {
        "model": MODEL_NAME, "dim": DIM, "index_type": "IndexFlatIP",
        "distance": "cosine (inner product on L2-normalized vectors)",
        "chunk_count": int(idx.ntotal), "doc_count": len(meta),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kb_dir": KB_DIR,
        "model_dir": MODEL_DIR,
        "chunk_params": {"chunk_chars": CHUNK_CHARS, "overlap": OVERLAP,
                         "trunc_tokens": TRUNC_TOKENS, "cap_normal": CAP_NORMAL,
                         "cap_dump": CAP_DUMP, "threads": THREADS},
        "capped_docs": [{"rel_path": r, "chunks": c, "type": t}
                        for r, c, t in capped_docs],
    }
    json.dump(manifest, open(MANIFEST_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    log.info("wrote %s", MANIFEST_PATH)

    # 6) 回写 has_vectors
    full = json.load(open(META_PATH, encoding="utf-8"))
    for d in full:
        d["has_vectors"] = True
    json.dump(full, open(META_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    log.info("updated _meta.json has_vectors=True for all docs (total %.1fs)",
             time.time() - t0)

if __name__ == "__main__":
    main()

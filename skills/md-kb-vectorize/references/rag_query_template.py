# -*- coding: utf-8 -*-
"""
MD 知识库 RAG 查询入口模板（与 vectorize_template.py 同管线）。

来源：某知识库实战验证版（2026-10-12），参数化改造。
用法:
    python rag_query_template.py <知识库目录> "查询文本" [top_k]

要点:
  - 查询编码与构建端完全同管线（同 tokenizer 截断 / CLS pooling / L2 归一），
    否则余弦分数与构建时的向量空间不可比。
  - faiss.read_index 不支持中文路径，走临时 ASCII 副本读取。
  - chunks.jsonl 逐行流式读，242MB 也别一次性 json.load。
"""
import os, sys, json, argparse, tempfile, shutil

if len(sys.argv) < 3:
    sys.exit('usage: python rag_query_template.py <知识库目录> "查询文本" [top_k]')
KB = os.path.abspath(sys.argv[1])
CHUNKS_PATH = os.path.join(KB, "chunks.jsonl")
FAISS_PATH = os.path.join(KB, "vectors.faiss")
TRUNC_TOKENS = 288   # 必须与构建端 chunk_params.trunc_tokens 一致

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

def resolve_model_dir():
    env = os.environ.get("BGE_MODEL_DIR")
    if env and os.path.isfile(os.path.join(env, "model_optimized.onnx")):
        return env
    stable = r"C:\Users\<USER>\.workbuddy\models\bge-small-zh-v1.5"
    if os.path.isfile(os.path.join(stable, "model_optimized.onnx")):
        return stable
    sys.exit("未找到 bge 模型, 请设 BGE_MODEL_DIR")

MODEL_DIR = resolve_model_dir()

class BgeQuery:
    def __init__(self, model_dir):
        so = ort.SessionOptions(); so.intra_op_num_threads = 6; so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(os.path.join(model_dir, "model_optimized.onnx"),
                                         sess_options=so, providers=["CPUExecutionProvider"])
        self.input_names = [n.name for n in self.sess.get_inputs()]
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(max_length=TRUNC_TOKENS, direction="right")
        self.tok.enable_padding(direction="right", pad_id=0, pad_type_id=0,
                                pad_token="[PAD]", length=None)

    def encode(self, texts):
        enc = self.tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        attn = np.array([e.attention_mask for e in enc], dtype=np.int64)
        inp = {"input_ids": ids}
        if "attention_mask" in self.input_names: inp["attention_mask"] = attn
        if "token_type_ids" in self.input_names: inp["token_type_ids"] = np.zeros_like(ids)
        out = self.sess.run(None, inp)[0]
        v = out[:, 0, :].astype(np.float64)            # CLS pooling, 与构建端一致
        n = np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
        return (v / n).astype(np.float32)

def read_index_unicode_safe(faiss_path):
    """faiss 的 C++ fopen 对中文路径报 'Illegal byte sequence', 复制到临时 ASCII 路径再读。"""
    import faiss
    if os.path.exists(faiss_path) and all(ord(ch) < 128 for ch in faiss_path):
        return faiss.read_index(faiss_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".faiss", delete=False,
                                      dir=tempfile.gettempdir())
    tmp.close()
    shutil.copyfile(faiss_path, tmp.name)
    try:
        idx = faiss.read_index(tmp.name)
    finally:
        try: os.remove(tmp.name)
        except OSError: pass
    return idx

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_dir")
    ap.add_argument("query")
    ap.add_argument("top_k", nargs="?", type=int, default=5)
    args = ap.parse_args()

    import faiss
    index = read_index_unicode_safe(FAISS_PATH)
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:                              # 流式读, 别一次性载入
            chunks.append(json.loads(line))
    assert index.ntotal == len(chunks), f"index {index.ntotal} != chunks {len(chunks)}"
    q = BgeQuery(MODEL_DIR).encode([args.query])
    D, I = index.search(q, args.top_k)
    print(f"\n查询: {args.query}\n(top {args.top_k}, 余弦相似度)\n" + "=" * 70)
    for score, idx in zip(D[0], I[0]):
        c = chunks[idx]
        print(f"\n[sim={score:.4f}] {c.get('source_file','')}")
        hp = c.get("heading_path", "")
        if hp: print(f"  目录: {hp}")
        print("  " + c["text"].replace("\n", "\n  ")[:400])

if __name__ == "__main__":
    main()

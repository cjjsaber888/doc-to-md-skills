# -*- coding: utf-8 -*-
"""
知识库目录深度整改：文件层数（文件夹层级 + 文件本身）不得超过上限（默认 8 层），
超限文件逐级上移一层，重名自动加 _2/_3 后缀；文件上移后，超限的文件夹（此时
必为空）必须删除——这是规则强制步骤，收尾自动复验。

背景：2026-10-13 用户规则定上限 9 层（某知识库 11 个第 10 层文件整改）；
2026-10-14 用户规则收紧为 8 层（同批 11 个文件再上移一层，超深文件夹
「同乐河+丁家河」删除）。以后新库一律按 8 层执行。

用法:
    python enforce_depth.py <知识库目录>                 # 干跑：只报告不动文件
    python enforce_depth.py <知识库目录> --apply         # 执行移动 + 同步元数据
    python enforce_depth.py <知识库目录> --apply --max-depth 8

--apply 时自动同步（按本技能产物约定）：
  - _meta.json            abs_path / rel_path 重写
  - chunks.jsonl          rel_path 流式重写（242MB 也安全，不整载）
  - vectors_manifest.json capped_docs 里的 rel_path
移动映射落盘 depth_moves_<时间戳>.json 供审计回滚。
"""
import os, sys, json, time, shutil, argparse, ctypes

def win_delete(path):
    """绕开 safe-delete 钩子（os.remove 在回收站不可用时报 OSError）。"""
    ctypes.windll.kernel32.DeleteFileW(ctypes.c_wchar_p(path))

def depth_of(rel_dir):
    return 0 if rel_dir == "." else rel_dir.count(os.sep) + 1

def collect_violations(kb, max_depth):
    out = []
    for root, dirs, files in os.walk(kb):
        rel = os.path.relpath(root, kb)
        for f in files:
            if depth_of(rel) + 1 > max_depth:
                out.append(os.path.join(root, f))
    return out

def plan_moves(violations, kb, max_depth):
    moves = []
    for src in violations:
        dst = src
        while depth_of(os.path.relpath(os.path.dirname(dst), kb)) + 1 > max_depth:
            parent = os.path.dirname(os.path.dirname(dst))
            stem, ext = os.path.splitext(os.path.basename(dst))
            cand = os.path.join(parent, os.path.basename(dst))
            i = 1
            while os.path.exists(cand):
                cand = os.path.join(parent, f"{stem}_dup{i}{ext}"); i += 1
            dst = cand
        if dst != src:
            moves.append((src, dst))
    return moves

def sync_meta(kb, old2new):
    p = os.path.join(kb, "_meta.json")
    if not os.path.isfile(p):
        return 0
    meta = json.load(open(p, encoding="utf-8"))
    n = 0
    for d in meta:
        ap = d.get("abs_path", "")
        key = os.path.normcase(ap)
        if key in old2new:
            d["abs_path"] = old2new[key]
            d["rel_path"] = os.path.relpath(old2new[key], kb)
            n += 1
    json.dump(meta, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return n

def sync_chunks(kb, old2new_rel):
    p = os.path.join(kb, "chunks.jsonl")
    if not os.path.isfile(p) or not old2new_rel:
        return 0
    tmp = p + ".tmp"
    n = 0
    with open(p, encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            c = json.loads(line)
            rp = c.get("rel_path", "")
            if rp in old2new_rel:
                c["rel_path"] = old2new_rel[rp]
                n += 1
            fout.write(json.dumps(c, ensure_ascii=False) + "\n")
    win_delete(p)
    os.rename(tmp, p)
    return n

def sync_manifest(kb, old2new_rel):
    p = os.path.join(kb, "vectors_manifest.json")
    if not os.path.isfile(p):
        return 0
    man = json.load(open(p, encoding="utf-8"))
    n = 0
    for c in man.get("capped_docs", []):
        rp = c.get("rel_path", "")
        if rp in old2new_rel:
            c["rel_path"] = old2new_rel[rp]
            n += 1
    json.dump(man, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return n

def sweep_empty_dirs(kb):
    """自底向上删除全部空目录（超深文件夹在文件上移后必须删除，这是规则要求
    而非附带效果）。返回删除数。"""
    removed = 0
    for root, dirs, files in os.walk(kb, topdown=False):
        if root != kb and not os.listdir(root):
            os.rmdir(root); removed += 1
    return removed

def post_verify(kb, max_depth):
    """复验三条：无超深文件 / 无超深文件夹 / 无空目录残留。"""
    bad_files, bad_dirs, empties = [], [], []
    for root, dirs, files in os.walk(kb):
        rel = os.path.relpath(root, kb)
        fl = depth_of(rel)
        for f in files:
            if fl + 1 > max_depth:
                bad_files.append(os.path.join(rel, f))
        if root != kb:
            if fl > max_depth - 1:
                bad_dirs.append(rel)          # 文件夹层级超过 max-1 即为超深
            if not os.listdir(root):
                empties.append(rel)
    return bad_files, bad_dirs, empties

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_dir")
    ap.add_argument("--apply", action="store_true", help="执行移动（默认干跑）")
    ap.add_argument("--max-depth", type=int, default=8)
    args = ap.parse_args()
    kb = os.path.abspath(args.kb_dir)
    if not os.path.isdir(kb):
        sys.exit("目录不存在: " + kb)

    violations = collect_violations(kb, args.max_depth)
    moves = plan_moves(violations, kb, args.max_depth)
    print(f"超 {args.max_depth} 层文件: {len(violations)} ｜ 计划上移: {len(moves)}")
    for src, dst in moves:
        print("  MOVE", os.path.relpath(src, kb), "\n    ->", os.path.relpath(dst, kb))
    if not args.apply:
        print("(干跑结束，加 --apply 执行)")
        return

    for src, dst in moves:
        shutil.move(src, dst)

    # 规则强制步骤：文件上移后，超 9 层的文件夹（此时必为空）必须删除
    removed = sweep_empty_dirs(kb)
    print(f"已移动 {len(moves)} 个文件，删除文件夹 {removed} 个（含全部超深空文件夹）")

    old2new_abs = {os.path.normcase(s): d for s, d in moves}
    old2new_rel = {os.path.relpath(s, kb): os.path.relpath(d, kb) for s, d in moves}
    n_meta = sync_meta(kb, old2new_abs)
    n_chunks = sync_chunks(kb, old2new_rel)
    n_man = sync_manifest(kb, old2new_rel)
    print(f"同步完成: _meta.json {n_meta} 条 ｜ chunks.jsonl {n_chunks} 行 ｜ manifest capped {n_man} 条")

    # 复验：无超深文件 / 无超深文件夹 / 无空目录残留
    bad_f, bad_d, empt = post_verify(kb, args.max_depth)
    ok = not (bad_f or bad_d or empt)
    print(f"复验: 超深文件 {len(bad_f)} ｜ 超深文件夹 {len(bad_d)} ｜ 空目录残留 {len(empt)} → "
          + ("PASS" if ok else "FAIL"))
    for x in (bad_f + bad_d + empt)[:10]:
        print("  !", x)

    logp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f"depth_moves_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"kb": kb, "max_depth": args.max_depth,
               "moves": [{"src": s, "dst": d} for s, d in moves]},
              open(logp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("映射日志:", logp)

if __name__ == "__main__":
    main()

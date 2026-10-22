# -*- coding: utf-8 -*-
"""
批量驱动：9 份投标 PDF → cleaned → md → chunks
断点续跑：目标 md 已存在且非空则跳过
"""
import os, sys, glob, subprocess, time, io

PY = sys.executable
SRC = os.environ.get("SRC_DIR", r"data/input")   # 投标 PDF 所在目录
WS = os.environ.get("WORK_DIR", r"work")        # 输出工作目录
SC = os.path.join(WS, "scripts")
LOG = os.path.join(WS, "progress.log")
CL = os.path.join(WS, "cleaned")
MD = os.path.join(WS, "md")
CK = os.path.join(WS, "chunks")
for d in (CL, MD, CK):
    os.makedirs(d, exist_ok=True)

log = open(LOG, "w", encoding="utf-8", buffering=1)


def safe(name):
    for c in '<>:"/\\|?*':
        name = name.replace(c, "")
    return name


files = sorted(glob.glob(os.path.join(SRC, "*.PDF")))
log.write(f"发现 {len(files)} 份PDF\n")

ok = skip = fail = 0
for p in files:
    base = os.path.splitext(os.path.basename(p))[0]
    tag = safe(base)
    ct = os.path.join(CL, f"{tag}.txt")
    md = os.path.join(MD, f"{tag}.md")
    ck = os.path.join(CK, f"{tag}_向量分块.md")
    title = f"{base} 投标文件"

    if os.path.exists(md) and os.path.getsize(md) > 5000 and os.path.exists(ck):
        log.write(f"[SKIP] {base} 已有产物\n")
        skip += 1
        continue

    t0 = time.time()
    buf = io.StringIO()
    try:
        r1 = subprocess.run([PY, os.path.join(SC, "clean_pipeline.py"), p, ct],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r1.returncode != 0:
            raise RuntimeError("clean: " + (r1.stderr or r1.stdout)[-300:])
        buf.write((r1.stdout or "").strip() + "\n")

        r2 = subprocess.run([PY, os.path.join(SC, "to_markdown.py"), ct, md, title],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r2.returncode != 0:
            raise RuntimeError("md: " + (r2.stderr or r2.stdout)[-300:])
        buf.write((r2.stdout or "").strip() + "\n")

        r3 = subprocess.run([PY, os.path.join(SC, "to_chunks.py"), md, ck],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r3.returncode != 0:
            raise RuntimeError("chunk: " + (r3.stderr or r3.stdout)[-300:])
        buf.write((r3.stdout or "").strip() + "\n")

        ok += 1
        log.write(f"[OK] {base} {time.time()-t0:.0f}s\n{buf.getvalue()}")
    except Exception as e:
        fail += 1
        log.write(f"[FAIL] {base} {e}\n")

log.write(f"\n完成 总计={len(files)} 成功={ok} 跳过={skip} 失败={fail}\n")
log.close()
print(f"完成 总计={len(files)} 成功={ok} 跳过={skip} 失败={fail}")
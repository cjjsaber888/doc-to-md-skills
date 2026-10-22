---
name: md-kb-vectorize
description: >
  把已转成 Markdown 的知识库目录补齐两层建设：结构化层（YAML frontmatter + [[实体类型:值]]
  语义标记）与向量化层（bge-small-zh-v1.5 嵌入 + FAISS IndexFlatIP + chunks.jsonl + RAG
  查询脚本）。含目录深度红线整改（文件层数 ≤8 层，超限上移并同步全部引用，enforce_depth.py）。
  内置 2026-10-12 实测铁律：fastembed 的 parallel>0 在 Windows 多进程
  spawn 死锁，必须用纯单进程 onnxruntime（CLS pooling + L2 归一，三路输入）；faiss 的
  C++ fopen 不支持中文路径，写入与读取都要走临时 ASCII 路径副本；巨型 xlsx 平铺文本会让
  分块爆炸，须按文档类型两级截断。当用户要求「向量化 / 建索引 / RAG / embedding /
  检索入口 / 补完结构化和向量化 / 文件层数超限整改」，或知识库 md 已转好要补向量层时使用。
  OCR 损坏 PDF 的转换层走 cn-gov-eng-pdf-vectorkb；双源互校走 pdf-word-dual-source-rag。
version: 1.2.0
display_name: MD知识库两层建设与向量化
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
argument-hint: <知识库目录（含 _meta.json）或「把这个知识库向量化」类描述>
visibility: public
---

# MD 知识库两层建设：结构化 + 向量化 (RAG 索引)

适用场景：招标文件、批复公文、检测报告等已批量转成 md 的项目知识库，需要结构化元数据
与语义检索能力。源目录约定为 `知识库/`，内含若干内容 md + `_meta.json`（元数据台账）。

与其他技能的分工：
- **上游转换层**（doc/xlsx/pdf → md）：`wps-legacy-format-convert`（老格式转档）、
  `cn-gov-eng-pdf-vectorkb`（OCR 损坏公文 PDF）、`pdf-word-dual-source-rag`（双源互校）。
- **本技能**：md 已就绪后的补完——结构化 + 向量化 + 检索入口。

## 核心心智模型

1. **两层是独立交付物**：结构化层（frontmatter + 语义标记）服务于人读与元数据过滤；
   向量化层（嵌入 + 索引）服务于语义召回。先结构化后向量化，分块时要剥掉 frontmatter。
2. **一切长批作业默认会中断**：分块必须确定性（重跑结果一致），嵌入必须 checkpoint
   断点续跑，参数变更须签名校验防止旧索引污染。
3. **本机环境三大坑先规避再动手**（见「铁律」节）：fastembed 多进程死锁、faiss 中文
   路径、巨型表格分块爆炸。每一个都有实测量化数据支撑，不要试图「再试一次 fastembed」。
4. **统一口径**：向量维度、分块参数、模型路径全部写进 `vectors_manifest.json`，查询端
   与构建端必须同管线（同分词、同 pooling、同归一），否则检索结果不可信。

## 标准流程

### 第 0 步：产物诊断
确认知识库目录里有 `_meta.json`（每条含 rel_path / abs_path / file_type / doc_category /
char_count / has_vectors）。没有就先写 rebuild_meta 脚本从 frontmatter 重建。统计
`has_vectors` 分布确认向量化缺口。

**目录深度红线（≤8 层）**：文件层数 = KB 根到该文件的文件夹层级 + 文件本身，不得超过
8 层（外部知识库导入的硬限制；2026-10-13 用户定 9 层，2026-10-14 收紧为 8 层）。
先跑
`references/enforce_depth.py <KB目录>` 干跑扫描；有超限文件就加 `--apply` 整改——
超限文件逐级上移一层（重名自动 `_2` 后缀）；**文件上移后，超过 8 层的文件夹必须删除**
（此时必为空，脚本自底向上清扫），并自动同步 `_meta.json`（abs_path/rel_path）、
`chunks.jsonl`（rel_path 流式重写）、`vectors_manifest.json`（capped_docs），移动映射落
`depth_moves_*.json` 供审计。收尾自动复验三条：无超深文件 / 无超深文件夹 / 无空目录残留。
库内若有生成的索引 html，其 href（百分号编码）/title（原文反斜杠）两种引用都要补替换。

### 第 1 步：结构化层
- 每篇 md 头部写入 YAML frontmatter：`source_file / source_path / file_type / section /
  doc_category / date / char_count / converted_at / has_vectors`。
- 正文注入 `[[实体类型:值]]` 语义标记。类型集按项目裁剪，常用：文号 / 金额 / 标段 /
  规范 / 单位 / 桩号 / 比例。同一类型全篇同名。
- 正则务必带捕获组（`re.compile(r"...(捕获)...")`），`m.group(1)` 才不会 IndexError。
- 脚本要幂等可重入：已处理的文件跳过，中断重跑不重复注入。

### 第 2 步：分块（先分析后定参）
- 标题感知分块：`#`~`######` 维护标题栈，块内注入 heading_path 首行。
- **先跑一遍纯分块分析**（不嵌入），看总块数与单篇分布，再定截断参数。巨型 xlsx
  平铺文本（几十 MB）单篇能产出 9 万+ 块，会把总预算炸掉。
- 两级截断：普通文档单篇上限 600，表格/扫描 dump（按 file_type 判）单篇上限 250，
  超限截断清单记入 manifest。

### 第 3 步：嵌入（单进程 onnxruntime，禁走 fastembed parallel）
- 模型：`bge-small-zh-v1.5`（dim=512），本机稳定副本在
  `C:/Users/<USER>/.workbuddy/models/bge-small-zh-v1.5/`（model_optimized.onnx +
  tokenizer.json，已从 Temp fastembed_cache 固化）。
- 管线：tokenizers 库 encode（截断 288 token、右 padding）→ onnxruntime 推理 →
  **CLS pooling**（`out[:,0]`，bge 走 fastembed OnnxTextEmbedding 路径，非 mean
  pooling）→ L2 归一。模型输入三路：`input_ids / attention_mask / token_type_ids`
  （第三路全零，缺了会报错或结果漂移）。
- 若需与 fastembed 对齐验证：fastembed 用 `specific_model_path` 指向快照目录，
  单进程（parallel 不传）出 ground truth，cosine 应 =1.000000（浮点误差 1e-8 量级）。

### 第 4 步：索引落盘
- FAISS `IndexFlatIP`（L2 归一后内积即余弦）。
- **中文路径必须绕行**：写与读都先落 `%TEMP%` 下 ASCII 文件名，`shutil.move` /
  `shutil.copyfile` 到中文真身路径。checkpoint 也写在 ASCII 路径，配参数签名
  sidecar（md5 of 分块参数 + 总块数），签名不符即丢弃旧索引。
- 产物四件套：`chunks.jsonl`（每行含 id/doc_idx/rel_path/source_file/heading 信息/
  text/char_len）、`vectors.faiss`、`vectors_manifest.json`（模型/dim/参数/截断清单）、
  `_meta.json` 回写 `has_vectors=true`。

### 第 5 步：查询入口
`rag_query.py`：查询文本走与构建端**完全相同**的编码管线（同 tokenizer 截断、同
CLS pooling、同归一），读索引走临时副本，逐行流式读 chunks（242MB 别一次进内存），
返回 top_k 的 sim + source_file + heading_path + 片段。

### 第 6 步：验收清单
- `faiss.ntotal == chunks.jsonl 行数`（ALIGN）。
- `_meta.json` 全量 `has_vectors=true`。
- 两条不同主题的样例查询均命中预期条款（sim 通常 0.6~0.8），语义标记在片段中可见。
- manifest 的 chunk_count/doc_count/参数与实际一致。

## 本机铁律（2026-10-12 实测，477 文档 / 73,217 块）

| 事项 | 结论 |
|---|---|
| fastembed `parallel>0` | Windows 上走 multiprocessing spawn，重导入主模块死锁（0 CPU）。**一律绕开**，用纯单进程 onnxruntime |
| bge pooling | CLS（`out[:,0]`）+ L2 归一，复刻 fastembed 逐位一致（cosine=1.000000） |
| onnx 模型输入 | 三路 input_ids/attention_mask/token_type_ids，缺 token_type_ids 会出错 |
| faiss 中文路径 | C++ fopen 报 "Illegal byte sequence"，写读都走临时 ASCII 路径 |
| 嵌入吞吐 | threads=10 约 **18 seq/s**（batch=64）；threads 1→8 提升有限（4→12 seq/s），别指望线程数翻倍 |
| 分块预算 | 256 字/块、overlap 48、截断 288 token；47MB xlsx 平铺 91,668 块/篇，必须两级截断 |
| 超 512 token 块 | onnxruntime 直接 OOM（memory allocation failed），截断上限 288 兜住 |
| 模型下载 | hf-mirror.com 对 Qdrant/bge-small-zh-v1.5 仓库 308/404；走代理 7897 直连 huggingface.co 可下；下完固化到 `.workbuddy/models/`（Temp 会被清） |
| 长批 ETA | 73k 块约 67 分钟；每 5000 块 checkpoint + 进度日志（含 ETA），后台跑 |
| chunked 大 JSON | 242MB chunks.jsonl 查询端逐行流式读，别 `json.load` 整个列表 |
| 目录深度 ≤8 层 | 文件夹层级 + 文件本身不得超过 8 层（外部知识库导入硬限制；10-13 定 9 层、10-14 收紧 8 层）；超限文件上移一层，**超限文件夹随后必须删除**，并同步全部 rel_path 引用。某知识库 两轮实测：11 个第 10 层文件上移 + 11 个第 9 层文件再上移、2,848 个 chunk 引用、36 个文件夹清理 |

## 性能调优顺序（先测再调）
1. 先跑**纯分块分析**（不嵌入），看块数分布定截断参数——这一步零成本，收益最大。
2. 嵌入吞吐用 256 条定长样本 benchmark threads（1/4/8/10），选性价比点。
3. batch 64 起步；batch 256 在 512 token 长序列会 OOM。
4. 总耗时 ≈ 总 token 数 ÷ 吞吐，与切块大小无关（同文本换种切法算力不变）。

## 可复用代码
- `references/vectorize_template.py`：完整向量化构建（分块 + 嵌入 + FAISS + manifest +
  断点续跑）。用法 `python vectorize_template.py <知识库目录>`，`VEC_LIMIT=N` 只跑前 N
  篇试跑。
- `references/rag_query_template.py`：RAG 查询入口。用法
  `python rag_query_template.py <知识库目录> "查询文本" [top_k]`。
- `references/enforce_depth.py`：目录深度整改（默认 8 层）。干跑扫描加 `--apply`
  执行；自动上移超限文件、清理空目录、同步 _meta/chunks/manifest，映射落
  `depth_moves_*.json`。
- 两脚本均要求受管 venv `C:/Users/<USER>/.workbuddy/binaries/python/envs/ocr`（onnxruntime
  / tokenizers / faiss-cpu / numpy 齐全）。

## 交付红线
统一口径（manifest 记录全部参数）；查询端与构建端同管线；截断文档必须留痕可审计；
**目录深度 ≤8 层**；绝不把 frontmatter 混进向量文本；验收必须含对齐校验 + 双主题样例查询。

---
name: pdf-word-dual-source-rag
description: 对同一文档的 PDF 原件与 Word 转换版（WPS/Office 转出）执行双源校对、结构化提取与 RAG 向量化切分。当用户同时给出 PDF 与其 docx 转换版，要求"对比校正/结构化/向量化/知识库化/切块入库"时使用。内置扫描件兜底、表格列位保真、PII 标记、反向审计清单。This skill should be used when the user provides a PDF plus its Word-converted version and asks for cross-validation, structured extraction with hierarchy paths, and/or RAG-ready chunking.
agent_created: true
---

# PDF↔Word 双源结构化与向量化流水线

四段流水线：双源探查 → 逐句校正 → 层级结构化 → RAG 切块。核心原则是**逐页择优的双源权威规则**，任何单一来源无条件优先都会出错。

## 适用判定

- 输入含同一文档的 `.pdf` 与 `.docx`（转换版），输出要求为校正记录 + 结构化 MD/JSON + 向量块
- 纯 PDF 处理走 pdfkit-py；纯 docx 编辑走 docx 系技能；本技能只管"双源互校 + 向量化"这条链

## 双源权威规则（本技能的核心资产）

| 内容区 | 权威源 | 理由 |
|--------|--------|------|
| 正文文字 | PDF 文字层 | 转换可能丢字、混入图内 OCR 碎片 |
| 正文表格 | DOCX 表格对象 | PDF 文字层把表格读成线性流，行列关系丢失 |
| 大型跨页表 | PDF find_tables | 保留网格列位；**禁止折叠相邻同值单元格**（合并单元格重复是真实结构，值相同不代表列冗余） |
| 扫描件附件 | 逐页择优：PDF 文字层 ≥60 字且 ≥3 行 25 字长句 → 用 PDF（high）；否则用 DOCX OCR（medium） | DOCX 的 OCR 文本可能藏在文本框里被 body 遍历漏掉；PDF 有文字层的页不该走 OCR 通道 |
| CAD/图纸页 | 排除向量化，仅登记存在性 | 碎图元（高程点、地物名）无检索价值 |

## 工作流

### 第 0 步：确认参数并生成 config.json

向用户确认或从上下文推断：PDF 路径、DOCX 路径、输出目录、文档用途（语义检索/知识库/审计留档）。写 config.json：

```json
{
  "pdf": "F:/.../doc.pdf",
  "docx": "F:/.../doc.docx",
  "out": "G:/.../output/rag",
  "doc_id": "文档短标识",
  "body_start": 6, "body_end": 73, "att_start": 79,
  "docx_body": [81, 838], "docx_att_start": 867,
  "bigtable_pages": [73, 78], "bigtable_title": "附表：××对照表",
  "att_extra_headings": [{"regex": "^某环保许评", "label": "附件10（…）", "after_att": "9"}],
  "table_fix_captions": ["表X …"], "table_fix_pages": [47],
  "att_start_regex": "^附\\s*件\\s*\\d+(?:-\\d+)?\\s*$",
  "redact_pii": false
}
```

边界参数确定方法：用 pdfkit `extract_text` 输出或 fitz 逐页扫 `get_text()`，找到正文起止页、附件标记页、DOCX 中前言/附表/附件1 的块索引，填入 config。`bigtable_pages` 仅当文档含跨页大表（如概算对照表）时设置。

### 第 1 步：探查

1. `page_count` + `bookmarks --action get`（pdfkit CLI，或直接用 fitz `doc.get_toc()`）
2. `extract_text --format text` 全 PDF，记录 `empty_pages`（扫描页清单）
3. 运行 `scripts/extract_docx.py --config config.json` → `docx_struct.json`（body 块序 + 表格 + **txbxContent 文本框通道**）

关键探查项：DOCX `word/document.xml` 中 `<w:txbxContent>` 数量。数量大说明有正文级内容可能藏在文本框（第 3 步兜底通道会抓）。

### 第 2 步：逐句校正

运行 `scripts/compare_sources.py --config config.json` → `diff_main.json` / `diff_docx_only.json`。

方法：NFKC 归一化 + 去空白 + 标点统一后，按句切分做包含性探针，双向找缺失。输出四类差异：表格断裂（PDF 侧）、OCR 碎片混入（DOCX 侧）、数字不一致、附件覆盖缺口。

探针陷阱：单元格无分隔拼接时 `\d+\.\d{2}` 会跨值伪匹配，数值核对必须按单元格集合比对，不做整段正则。

### 第 3 步：结构化

运行 `scripts/build_structured.py --config config.json` → `structured.json`。每条记录含：`id / level_path（章>节>条）/ type / page_pdf（0基）/ page_print（1基）/ text / meta{source, confidence}`。

实现要点（均为踩坑固化，勿改）：
- 章节路径用运行时 `doc.get_toc()` 构建，禁止硬编码书签（换版静默失配）
- 跨页大表走 `bigtable_pages` 的 find_tables 通道，按页分组，保留完整网格
- 附件标题正则排除尾冒号（批复自带"附件1:"子附件会误吞）；无标题附件以文号为锚补边界（`att_extra_headings`）
- 附件区 PDF 兜底通道：逐页判 `≥60 字 + ≥3 行 ≥25 字长句 + DOCX 未覆盖` → 以 `pdf_text_layer/high` 补录；CAD 碎元页靠长句密度测试自然排除
- 文本框残留（≥60 字未覆盖）以 `textbox_leftover/low` 记录入库，切块后标 `needs_review`，交人工归属，禁止静默丢弃
- 表格保留完整网格，仅做空白归一

### 第 4 步：切块

运行 `scripts/build_chunks.py --config config.json` → `03_chunks.jsonl`。

切分粒度按查询类型设计：
- 正文段落：同节聚合，目标 400-900 字，块头注入 `【章节路径】`
- 表格：整表一个语义单元，>1200 字按行组分片且每片重复表头（工程量×单价=金额的列关联不可拆）
- 附件公文：句边界切 ~800 字
- 图题：以 `〔图示〕` 前缀并入同页最近块
- 元数据：`pages` 数组（跨页溯源）、`pii` 布尔（`(?<!\d)1[3-9]\d{9}(?!\d)` 排除代码串假阳性）、`confidence`、`source_records` 回链
- `redact_pii: true` 时手机号掩码 `139****445` 并打 `pii_masked`

### 第 5 步：交付物

1. `01_校正对照报告.md`：逐类差异 + 数字抽查表 + 遗留风险
2. `02_结构化全文.md`：YAML frontmatter + 4 张全局索引（章节/表格/图/附件）+ `[[类型:值]]` 语义标记（文号/金额/实体）
3. `03_chunks.jsonl`：向量就绪块
4. `04_向量化设计说明.md`：领域判定、粒度决策依据、字段表、落库建议

### 第 6 步：反向审计（强烈建议，每次必做）

按 `references/audit_checklist.md` 八项清单自查交付物，从 chunks 逆向回链到原件。历史案例证明：自产流水线不经审计直接交付，高危缺陷率约 2/294 记录。审计脚本模式（回链完整性、文本框穷举、列数分布收敛、PII 真伪复核）见该清单。

## 批量模式（语料库级，2026-09-03 沉淀）

当输入是**一个文件夹的 N 对 PDF+DOCX**（如批复语料库 277 对）而非单文档时，逐文档人工定边界参数不可行，改用批量适配脚本（参考实现 `<WORKSPACE>/scripts/batch_rag.py`，多进程 8 workers 约 50s/277 对）：

- 边界参数改为**逐页自动探查**：页归一化 >=60 字判"有文字层"；有文字层但 >=25 字长句 <3 行判图纸页（仅登记存在性）。双源择优规则本身不变
- 标题层级用正则启发式（第X章 / 一、/ （一）/ 1.2.3 / 附件N），批复类公文够用
- 扫描件主导文档（layer_ratio=0）整篇走 DOCX 通道标 medium，frontmatter 记 `pages_scanned` 供下游过滤
- 输出布局：`structured/<doc>.md` + `chunks/<doc>.jsonl` + `reports/diff_stats.json`，另生成 `00_总览索引.md`（语料规模表 + 逐文档清单含文号）
- 审计批量化（`audit_batch.py`）：A3 列漂移、A6 PII、A8 页码、needs_review 全库汇总；PII 命中默认只标记不脱敏，对外共享前须 redact 重跑
- 陷阱：bash heredoc/内联 python -c 中含中文路径与反引号代码块会被 shell 吞掉，写 MD 内容用 `python - <<'PYEOF'` 或先写脚本文件再执行

## 输出格式硬规（用户偏好）

- 中文报告用管道表格、分层标题；批复文号保持全角〔〕原样（OCR 半角[]混排时标注不改写）
- 每条记录必须可溯源：页码 + 来源通道 + 置信度三件套
- 无法机检的环节（扫描件 OCR 正确性）显式声明"无法验证"，禁止主观补全

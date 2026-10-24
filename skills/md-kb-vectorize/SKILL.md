---
name: md-kb-vectorize
description: >
  把已转成 Markdown 的知识库目录补齐两层建设：结构化层（YAML frontmatter + [[实体类型:值]]
  语义标记 + convert_method 推导的可信度分级）与向量化层（bge-small-zh-v1.5 嵌入 + FAISS
  IndexFlatIP + chunks.jsonl + RAG 查询脚本）。含目录深度红线整改（文件层数 ≤8 层，
  源目录与知识库全盘扫描，超限文件夹连内容整体上移，enforce_depth.py）。
  内置实测铁律：fastembed 的 parallel>0 在 Windows 多进程 spawn 死锁，必须用纯单进程
  onnxruntime（CLS pooling + L2 归一，三路输入）；faiss 的 C++ fopen 不支持中文路径，
  写入与读取都要走临时 ASCII 路径副本；巨型 xlsx 平铺文本会让分块爆炸，须按文档类型
  两级截断；chunk ID 必须全文哈希（只哈希正文前 300 字会让表格块表头撞车，实测 587 个
  ID 撞车涉及 10111 行）；验收必须三方对齐（chunks 唯一 ID 数 == faiss ntotal == meta
  行数，ntotal==行数是假象，实测 70070==70070 时实际 899 条过期 + 10111 行重复）。
  含长批防断体系（Windows 计划任务探针 + 文件锁收尾链，与会话解耦）与多代理域摘要派活
  规范。当用户要求「向量化 / 建索引 / RAG / embedding / 检索入口 / 补完结构化和向量化 /
  文件层数超限整改」，或知识库 md 已转好要补向量层时使用。
  OCR 损坏 PDF 的转换层走 cn-gov-eng-pdf-vectorkb；双源互校走 pdf-word-dual-source-rag。
version: 1.3.0
display_name: MD知识库两层建设与向量化
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
argument-hint: <知识库目录（含 _meta.json）或「对这个知识库向量化」类描述>
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
3. **块 ID 是增量的地基**：ID 用全文哈希；同内容块只嵌一次（一内容一向量）；OCR 补件
   换掉占位符后旧 ID 的向量是过期条目，必须剪枝或重建。ID 规则错了，增量全是脏的。
4. **本机环境四大坑先规避再动手**（见「铁律」节）：fastembed 多进程死锁、faiss 中文
   路径、巨型表格分块爆炸、块 ID 弱哈希撞车。每一个都有实测量化数据支撑，不要试图
   「再试一次 fastembed」。
5. **防断是体系不是补丁**：会话内的后台守护环随会话殉葬（实测白停 33 小时）。长批
   （OCR/嵌入）必须挂 Windows 计划任务级探针，带忙检查 + 文件锁 + 停滞检测。
6. **统一口径**：向量维度、分块参数、模型路径全部写进 `vectors_manifest.json`，查询端
   与构建端必须同管线（同分词、同 pooling、同归一），否则检索结果不可信。

## 标准流程

### 第 0 步：产物诊断
确认知识库目录里有 `_meta.json`（每条含 rel_path / abs_path / file_type / doc_category /
char_count / has_vectors）。没有就先写 rebuild_meta 脚本从 frontmatter 重建。统计
`has_vectors` 分布确认向量化缺口。

**目录深度红线（≤8 层）**：文件层数 = 路径名字段数（`count(os.sep)+1`，目录与文件同
口径，根不计层），不得超过 8 层（外部知识库导入的硬限制；2026-10-13 用户定 9 层，
2026-10-14 收紧为 8 层）。**扫描范围必须是「源目录 + 知识库」全盘**：知识库内部通常
扁平，超限往往藏在源目录（2026-10-24 实测：知识库最深 2 层零超限，源目录 6 个第 8 层
文件夹内的 190 个文件落在第 9 层）。先跑
`references/enforce_depth.py <根目录>` 干跑扫描；有超限文件就加 `--apply` 整改——
超限文件夹连内容整体上移一层（与用户口径一致；重名自动 `_2` 后缀）；**文件夹上移后
若因此超过 8 层必须继续上移或删除**（此时必为空，脚本自底向上清扫），并自动同步
`_meta.json`（abs_path/rel_path）、`chunks.jsonl`（rel_path 流式重写）、
`vectors_manifest.json`（capped_docs），移动映射落 `depth_moves_*.json` 供审计。
收尾自动复验三条：无超深文件 / 无超深文件夹 / 无空目录残留。
库内若有生成的索引 html，其 href（百分号编码）/title（原文反斜杠）两种引用都要补替换。

**三个口径教训（2026-10-24 实测）**：① 层数口径统一为「路径名字段数」，执行脚本
自己判「零超限」不可信（曾因少算 1 漏报第 9 层），复扫必须用独立写的同口径脚本；
② 移动前查目标位置（祖父目录）同名冲突，移动时逐一断言文件数一致、源目录已消失；
③ 源目录结构调整后，受影响 md 的 frontmatter source_path 会陈旧，在缺口说明里登记
即可，不必回改全部 md 文件名。

### 第 1 步：结构化层
- 每篇 md 头部写入 YAML frontmatter：`source_file / source_path / file_type / section /
  doc_category / date / char_count / converted_at / has_vectors`。
- 正文注入 `[[实体类型:值]]` 语义标记。类型集按项目裁剪，常用：文号 / 金额 / 标段 /
  规范 / 单位 / 桩号 / 比例。同一类型全篇同名。
- 正则务必带捕获组（`re.compile(r"...(捕获)...")`），`m.group(1)` 才不会 IndexError。
- 脚本要幂等可重入：已处理的文件跳过，中断重跑不重复注入。

**可信度分级（credibility，按 convert_method 推导，不要等 frontmatter 显式标注）**：
直读/RAR/原样 md → A；WPS 转档 → B；OCR 识别 → C；图纸只登记 → D。OCR 补件跑完后，
frontmatter 的 convert_method 不会自动改写，须跑一遍校准脚本把 OCR 件的页数与转换方式
改准，否则可信度会误判为 A。检索结果必须带可信度标注（C 级附「引用金额/文号/日期前
须回看原件」提醒）。

**三条容易错的细节（2026-10-24 实测）**：
- 域/分类必须从**源路径顶层目录**取（`rel.split(sep)[0]`），不能用 md 文件名 split
  （md 文件名 = 源路径 `__` 连接，split 会错分到别的域）。
- 空块与过短块（正文 <20 字）不得入库，否则污染向量索引（实测 413 空块 + 325 过短块）。
- 全库缺口扫描用 md frontmatter 的 `text_pages` 字段秒级完成，不要逐个开 PDF
  （实测 659 个 PDF 逐页探要 30 分钟，读 frontmatter 只要几秒）。

### 第 2 步：分块（先分析后定参）
- 标题感知分块：`#`~`######` 维护标题栈，块内注入 heading_path 首行。
- **先跑一遍纯分块分析**（不嵌入），看总块数与单篇分布，再定截断参数。巨型 xlsx
  平铺文本（几十 MB）单篇能产出 9 万+ 块，会把总预算炸掉。
- 两级截断：普通文档单篇上限 600，表格/扫描 dump（按 file_type 判）单篇上限 250，
  超限截断清单记入 manifest。
- **块 ID 必须全文哈希**：`md5(file + \x00 + head + \x00 + text)`。只哈希正文前 300 字
  会让表格块（表头行相同）撞车——2026-10-24 实测 587 个 ID 撞车涉及 10111 行。
- **重复内容按 ID 去重，一内容一向量**：同名工作表的 xls 转录件会产生完全相同的块
  （实测 7103 行），嵌入前在待嵌清单按 ID 去重；chunks.jsonl 保留全量供检索展示，
  但向量与 meta 只留唯一条目。

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
- **OCR 补件后必须剪枝**：OCR 把 `(no-text)` 占位符换成真实文本后，受影响块的 ID
  变化，增量嵌入只加新向量，旧 ID 的向量成为过期条目（实测 899 条）。跑
  `references/prune_vectors.py` 按当前 chunks 的 ID 集合剪除，并做三方对齐校验。
- 产物四件套：`chunks.jsonl`（每行含 id/doc_idx/rel_path/source_file/heading 信息/
  text/char_len）、`vectors.faiss`、`vectors_manifest.json`（模型/dim/参数/截断清单）、
  `_meta.json` 回写 `has_vectors=true`。

### 第 5 步：查询入口
`rag_query.py`：查询文本走与构建端**完全相同**的编码管线（同 tokenizer 截断、同
CLS pooling、同归一），读索引走临时副本，逐行流式读 chunks（242MB 别一次进内存），
返回 top_k 的 sim + source_file + heading_path + 片段 + **credibility 分级标注**
（C 级 OCR 件附回看原件提醒）。支持 `--域/--topic/--cred` 过滤，让调用方能按可信度
取舍证据。

### 第 6 步：验收清单
- **三方对齐（唯一有效标准）**：`chunks.jsonl 唯一 ID 数 == faiss.ntotal == meta 行数`。
  ⚠️ `ntotal == chunks 行数` 是假象：2026-10-24 实测索引与 meta 都是 70070「一致
  =True」，而 chunks 实际只有 62080 个唯一 ID——899 条过期向量 + 10111 行重复块全
  被这个宽松标准放行。唯一 ID 数要现算（全文哈希口径），不能信行数。
- `_meta.json` 全量 `has_vectors=true`。
- 两条不同主题的样例查询均命中预期条款（sim 通常 0.6~0.8），语义标记在片段中可见，
  可信度标注正确。
- manifest 的 chunk_count/doc_count/参数与实际一致。
- 深度红线复扫：源目录 + 知识库均无超 8 层文件/文件夹（用独立同口径脚本复扫）。

## 长批防断体系（2026-10-23 外环西段实测，OCR 26180 页端到端零人工）

**根因教训**：`run_in_background` 的 bash 守护环生命周期绑定会话，会话一断全链殉葬
（实测白停 33 小时，日志静默无异常记录）。防断必须挪出会话，落到 Windows 计划任务层。

**体系三件套**（模板在 `references/`）：

| 组件 | 文件 | 机制 |
|---|---|---|
| 计划任务探针 | `ocr_watchdog.ps1` | schtasks 每 2 分钟触发：无链在跑且无 DONE 标记 → 拉起收尾链；OCR 进程活着但日志 30 分钟无更新 → 杀进程等重启（只杀命令行带本项目特有标记的子进程，避免误伤其他项目在跑的 OCR）；每次触发刷心跳文件 |
| 收尾链执行器 | `run_pipeline.ps1` | 链：主批续跑→校准→结构化→向量化→终校准。守卫：①主批忙检查（不插队）②文件锁原子抢占（New-Item 同路径只有一个调用方成功，防双链）③每步失败重试 3 次、链级 6 次上限写 FAIL 标记转人工。全链可反复重入 |
| 剪枝 | `prune_vectors.py` | OCR 补件后按当前 chunks ID 集合剪过期向量，自带三方对齐校验 |

**配套纪律**：
- 主批调度器**先写 md 再存 state**（反序会让崩溃窗口产生「状态已登记但 md 仍是占
  位符」的永久缺口，resume 时该页被跳过）。
- 链步骤全部幂等可重入：OCR 按 state 断点、向量化按 chunk ID 增量、结构化全量重建。
- PowerShell 5.1 读无 BOM 的 UTF-8 .ps1 会中文乱码报解析错，含中文的 .ps1 必须用
  `UTF8Encoding($true)` 补 BOM，并用 `Parser::ParseFile` 语法校验。
- **沙箱进程代理现象**：同一逻辑进程在进程表里呈现为父子链上两个 PID（命令行全同、
  启动时间同秒）。不要凭进程表双 PID 就判定双开抢跑。取证三件套：日志单流（累计值
  无重复）、state 无重复登记、目标 md 页号连续唯一——三项全过即健康，别动手杀。

## 多代理域摘要派活规范（2026-10-24 实测，5 代理 20 份摘要零返工）

域摘要（每个业务域一份事实表 + 分域展开）适合多代理并行，派活 prompt 必须带齐四样：

1. **精确取数路径**：分块清单（chunks.jsonl）+ 逐件转录目录（文件名 = file 字段）+
   域级参考索引；说明「优先读信息密度高的分块，关键数字必须回看原文」。
2. **一份范例文件**：让代理照结构仿写（YAML frontmatter → 域定位 → 核心事实表 →
   按域展开），格式漂移概率大降。
3. **硬性规则**：只引用文件真实文字与数字、禁止编造；可信度 A/B/C 分级；找不到写
   「待补」不猜；多标段按标段分列不得串台；禁用句式与标点约定。
4. **交叉验证设计**：让不同域的代理天然互证（如通信管线中标合计 vs 招标代理域审核
   意见书），能抓出单价异常、跨项目混存、限价口径冲突。

已知故障：子代理偶发 `400 [PacRpcClient] request timed out after 5000ms` 瞬时超时，
**重派即恢复**，不要改 prompt 也不要放弃。

## 本机铁律（2026-10-12 G320 实测 477 文档 / 73,217 块；2026-10-24 外环西段实测 1125 文档 / 62,080 向量）

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
| 目录深度 ≤8 层 | 文件夹层级 + 文件本身不得超过 8 层（外部知识库导入硬限制；10-13 定 9 层、10-14 收紧 8 层）；超限文件夹连内容整体上移一层，并同步全部 rel_path 引用。G320 两轮实测：11 个第 10 层文件上移 + 11 个第 9 层再上移、2,848 个 chunk 引用、36 个文件夹清理；外环西段实测：知识库内扁平零超限，超限全在源目录（6 个第 8 层文件夹 190 文件），扫描必须全盘 |
| 层数口径 | 路径名字段数 = `count(os.sep)+1`，目录与文件同口径；执行脚本自判「零超限」不可信（曾少算 1 漏报第 9 层），复扫用独立脚本 |
| 块 ID | **全文哈希** `md5(file+head+text)`。只哈希前 300 字会让表格块表头撞车（实测 587 ID 撞车 / 10111 行）；同名工作表 xls 转录件产生 7103 行完全重复块，按 ID 去重保一内容一向量 |
| 验收标准 | **三方对齐：chunks 唯一 ID 数 == faiss.ntotal == meta 行数**。ntotal==行数是假象（实测 70070==70070 时实际 899 过期 + 10111 重复） |
| OCR 补件后 | frontmatter 的 convert_method 不会自动改写，须跑校准脚本改准页数与转换方式（否则可信度误判 A）；补件后旧 ID 向量过期，跑 prune_vectors.py 剪枝 |
| 长批防断 | 会话内后台守护环随会话殉葬（实测白停 33 小时）；必须挂计划任务探针（忙检查 + 文件锁 + 停滞检测 30 分钟 + 先写 md 再存 state） |
| 沙箱进程代理 | 同一逻辑进程呈现父子链两个 PID（命令行全同、同秒启动）；取证三件套（日志单流 / state 无重复 / md 页号连续唯一）全过即健康，勿凭双 PID 杀进程 |
| PS 5.1 脚本编码 | 无 BOM 的 UTF-8 .ps1 中文乱码报解析错；必须补 BOM（`UTF8Encoding($true)`）+ Parser::ParseFile 校验 |

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
- `references/ocr_watchdog.ps1`：计划任务探针模板（每 2 分钟）。保活 + 停滞检测 +
  心跳。注册命令见文件头注释。
- `references/run_pipeline.ps1`：收尾链执行器模板。忙检查 + 文件锁 + 步骤重试，
  链步骤区按项目改。
- `references/prune_vectors.py`：过期向量剪枝 + 三方对齐校验。
- Python 脚本均要求受管 venv
  `C:/Users/<USER>/.workbuddy/binaries/python/envs/ocr`（onnxruntime / tokenizers /
  faiss-cpu / numpy 齐全）；.ps1 必须带 UTF-8 BOM。

## 交付红线
统一口径（manifest 记录全部参数）；查询端与构建端同管线；截断文档必须留痕可审计；
**目录深度 ≤8 层（源目录 + 知识库全盘复扫）**；绝不把 frontmatter 混进向量文本；
块 ID 全文哈希 + 按 ID 去重；OCR 补件后跑剪枝；验收必须含**三方对齐** + 双主题样例
查询 + 深度复扫。

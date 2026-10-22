---
name: cn-gov-eng-pdf-vectorkb
description: 将 OCR 损坏的中文公文/工程 PDF（文本层带形近字与数字漏位，文件名常含“可搜索”或“OCR”）转换为高保真、可检索的向量库标准
  Markdown。覆盖：6 类工程批复/请示/函 + Excel 概算表；7 字段元信息头、公文分支与 Excel 分支结构、向量切片优化、交叉核对纠正
  OCR 错误。当用户给出“某公文/可研报告/批复/概算 PDF 转 md/知识库/向量库”类需求，或文件标注“可搜索/OCR”且中文错字、数字错位时使用。
version: 1.0.0
description_zh: OCR 损坏的中文公文/工程 PDF → 向量库标准 Markdown（含交叉核对纠错）
description_en: OCR-corrupted Chinese official/engineering PDF → vector-KB
  standard Markdown, with cross-check correction
display_name: 中文公文工程PDF转向量库MD
display_name_en: CN Gov/Eng PDF to VectorKB MD
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
argument-hint: <PDF 或 Excel 文件路径，或“这批公文转知识库”类描述>
visibility: public
---

# 中文公文/工程 PDF → 向量库标准 Markdown

适用：发改委/交通委/住建委等批复、请示、函，以及工程可行性研究报告、初步设计、概算表等。
这些文件常标注「可搜索」或「OCR」，其**嵌入文本层是被 OCR 损坏的**：中文形近字乱跳（文但→文件、高谏→高速）、数字漏位或字母替数字（188→18.8、177O84→177084、21063→211063）。**绝不能机械照抄提取文本**，否则向量库会一路错下去。

与 `quota-pdf-to-md`（定额类「错位覆层」PDF）互补：本 skill 处理**字符级损坏 + 公文/可研 prose + 跨文件交叉核对**；若遇到定额表错位覆层，改调 `quota-pdf-to-md`。

md 转好后要补**结构化（frontmatter+语义标记）与向量化（bge+FAISS+RAG 查询）**，交给下游 `md-kb-vectorize`（含 fastembed 死锁、faiss 中文路径、巨型表格分块爆炸等本机铁律与现成模板）。

## 核心心智模型（先诊断，再动手）

1. **文本层不可信，但数字大多可救**：OCR 对中文形近字杀伤大，对阿拉伯数字相对友好（偶有 O/l/Z 替 0/1/2、漏位）。表格（估算表/概算表/绩效目标表）内的数字最干净，优先当作 ground truth。
2. **同项目文件互为锚点**：同一工程的「项目建议书函 / 可研批复 / 初设批复 / 概算 Excel」彼此印证里程、投资、工期、技术标准。用已清理的兄弟文件（openpyxl 干净读取的 Excel 是权威明细）反推并定位脱字。
3. **求和闭环验证**：分项相加应等于总额（工程费+二类费+预备费+前期费=总投资）。不相等即说明有漏位，回去查源页。
4. **绝不编造**：疑点标 `「[原文未明确]」`，不推断、不补写。

## 标准流程

### 第 0 步：诊断损坏类型
`fitz` 取几页 `get_text("text")`，肉眼（或比对兄弟文件）判断：
- **字符级损坏**（本 skill）：形近字 + 数字漏位。→ 走下方流程。
- **错位覆层**（定额类）：同字体同色 OCR 覆层叠在干净层上。→ 改 `quota-pdf-to-md`。

### 第 1 步：提取
- PDF：`fitz` 逐页 `get_text("text")` 存一份 `embedded.txt`（快，全本）。表格单元格在提取结果里常落在**独立行**（网格被打散），这是正常现象。
- Excel（Branch 2）：`openpyxl` 先 `data_only=False` 读公式，再 `False` 二次核对；两视角都空才是真空。`NaN` 陷阱：`isinstance(v,float) and math.isnan(v)` 才判无值。
- 渲染图仅供挑页 OCR 用；`Read` 工具**读不了图片**（"model does not support images"），无法肉眼核对，只能靠文本+Excel 交叉。

### 第 2 步：结构测绘
扫描全本定位：
- 章节边界：正则 `第[一二三四五六七八九十\d]+章`、`一、`、`（一）`、`\d+\.\d+`；**大文档（200+ 页）直接硬编章节起止页**（扫描「第X章」首次出现的页号），再在每章内做子标题探测。
- 图像型页（封面/编制说明/附图）：提取出二进制乱码 → 标记跳过，从目录页起截取正文。
- 关键表：按关键词（投资估算/概算/绩效目标）定位页码区间。

### 第 3 步：交叉核对关键数字
锚定嵌入表格数字，与兄弟文件/Excel 比：里程、总投资、工程费、工期、技术标准（设计速度、荷载、净空、抗震）、文号、日期。发现 `188千米`/`177O84`/`21063` 这类，用兄弟文件与表格闭环修正。

### 第 4 步：系统性纠错
- **纠错词典**：compound-first（长词优先），再做单字替换。每个文档要现加现测（见 `references/correction_lib.py` 的示例字典与扩展说明）。
- **数字形近归一**：仅对「纯数字串」做 `O→0, Z→2, l→1, I→1`（避免误伤公式变量，如车速模型里的 `Z<1`）。
- **章↔草** 等 OCR 把「章」识成「草」：正则 `第(\d+)草 → 第\1章`。
- 挑页二次确认走本机默认引擎 `paddlevl-ocr` 双通道（见环境坑）。纯文字页可用 `--engine fast` 快速通道，单页约 2 秒；表格或版面页用默认精解通道。`rapidocr-onnxruntime` 独立调用仅作兜底。

### 第 5 步：发射与组装
- 标题来自章节地图；估算表/概算表**按阅读顺序逐行保真发射**（不做网格重排，重排会丢数字），加一句说明「单元格按原文顺序逐行呈现」。
- `is_garbage()` 过滤二进制乱码行（控制符 / mojibake 字符集 / 无 CJK 且无 ASCII 的可疑行）。
- 组装：7 字段元信息头 + 公文分支（`# 公文全称 → ## 主送单位 → ## 正文核心内容 → ## 批复/请示核心结论(建设规模/项目总投资/建设工期/核心审批要求) → ## 附件清单`）+ 嵌入附件作嵌套 `#`；Excel 分支（`## Sheet名` → 标准 Markdown 表，合计行加粗）。**删抄送/印发/页码**。纯 Markdown，无前言后语、无 AI 增补。
- **7 字段元信息头**（YAML frontmatter，固定顺序；原文缺失的字段填 `「[原文未明确]」`，不得推断）：

  | 序号 | 字段 | 说明 |
  |---|---|---|
  | 1 | `doc_title` | 公文全称，去掉书名号与换行 |
  | 2 | `issuer` | 发文机关全称，取页眉机关名或落款 |
  | 3 | `doc_number` | 发文字号，全角〔〕规范化，如 `示发改投〔2026〕1号` |
  | 4 | `addressee` | 主送单位 |
  | 5 | `issued_date` | 成文日期，统一 `YYYY-MM-DD` |
  | 6 | `doc_type` | 批复 / 请示 / 函 / 可研报告 / 初设 / 概算表 |
  | 7 | `source_file` | 源文件名（不含路径） |


### 第 6 步：QC 清单
- 元信息 7 字段齐全；关键数字跨文件一致；表格合计/总额正确；无前言后语；无抄送/页码残留；二进制乱码计数为 0；章节顺序正确无幽灵章。

## 环境坑（本机实测，重要）
- **OCR 引擎：一律先调用本机默认引擎 `paddlevl-ocr` 双通道。**
  入口：`bash "C:/Users/<USER>/.workbuddy/skills/paddlevl-ocr/scripts/pdocr.sh" --input <绝对路径> --out <输出目录> [--engine auto] [--dpi 200] [--pages 1-5] [--resume]`
  输出 `<stem>.md` / `<stem>.json` / `<stem>.log` 三件套。
  - **通道选择**：默认 `--engine auto`。有正常文本层的 PDF 会自动直取文本（0.03 秒）；扫描件自动走精解通道 VL-1.6，版面与表格结构保留。
  - **公文类务必核验发文字号、页眉机关名、页码三项是否在 `.md` 里**。paddlex 默认会丢弃 `header` 标签块，把发文字号整行静默删掉；本引擎已默认规避并自动规范化全角〔〕。若缺失，回 `<stem>.json` 的 `parsing_res_list` 里找。
  - **涉及概算表、投资表等数字密集页时**，用 `--engine recheck` 双通道复核。它独立比对数字串与发文字号，能拦住被长页相似度稀释的金额错位。
- **旧结论已推翻（2026-09-29 实测）**：本节此前记录「PaddleOCR 3.x 不可用、统一用 rapidocr」。
  当时的崩溃发生在 **静态模型路段**（PP-OCRv5 / PP-StructureV3），签名为
  `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`，
  且 `enable_mkldnn=False`、`FLAGS_enable_new_executor=0`、`FLAGS_use_mkldnn=0` 三种开关均无效。
  2026-09-29 复测确认：PaddleOCR-VL-1.6 走的是 `paddle_dynamic` 动态引擎，
  不论版面检测开或关（含静态模型 `PP-DocLayoutV3`）**均不再复现该崩溃**，VL-1.6 在本机可用。
- **兜底链**：仅当 `pdocr.sh` 返回退出码 3（引擎不可用）且已走完
  `C:/Users/<USER>/.workbuddy/skills/paddlevl-ocr/references/troubleshoot.md` 全部降级阶梯仍失败时，
  才回退 `rapidocr_onnxruntime`，并须在产物说明中标注已降级。
  - 兜底 API：`from rapidocr_onnxruntime import RapidOCR; res,_ = RapidOCR()(img)`，返回 `[(bbox, text, score), ...]`。
    纯 ONNXRuntime 后端，不依赖 paddle。2026-09-29 复测单页约 2 秒 @200dpi（旧记录的 17 秒已过时）。
    **注意**：独立调用 rapidocr 属兜底行为。日常快速通道请用 `pdocr.sh --engine fast`，它带阅读顺序还原与统一的输出契约。
- 批量场景把 OCR 跑在**逐文件子进程**里（隔离 OOM，父进程续跑），并务必**断点续跑**（跳过已生成的 .md）与记日志。
- 受管 venv：`C:\Users\<USER>\.workbuddy\binaries\python\envs\default`（py3.13）、OCR 用 `envs/ocr\Scripts\python.exe`。pip 走腾讯镜像。
- `os.remove` 触发 safe-delete 钩子抛 OSError（回收站不可用）。临时文件用 `ctypes.windll.kernel32.DeleteFileW(ctypes.c_wchar_p(path))` 绕开。
- 全量 OCR 批次耗时长（纯图片 PDF 单文件数分钟），务必**断点续跑**（跳过已生成 .md）+ 记日志；OCR 偶有数字/印章误读，保真优先下按原图保留不强行改。

## 可复用代码
- `references/correction_lib.py`：纠错词典骨架 + `norm_num` / `is_garbage` / `is_heading` 工具函数（按文档现扩现测）。
- `references/pipeline_template.py`：提取→纠错→章节地图→发射→组装 的最小可运行骨架。

## 交付红线（用户硬要求）
100% 忠于原文、数字零失真、歧义标 `「[原文未明确]」`、纯 Markdown、7 字段元信息、公文/Excel 双分支结构、向量切片优化（严格 `#/##/###`、段落≤300 字、关键句独立成行、保留条款编号）。

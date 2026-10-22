# doc-to-md-skills

**把中文工程与政府公文转成可检索、可计算、可核验的知识库。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Skills](https://img.shields.io/badge/skills-9-blue.svg)](skills)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](https://www.python.org/)

[English](README.md) | 简体中文

## 为什么有这个仓库

中文工程文档转 Markdown，难点从来不在"解析 PDF"。真正的麻烦有六层：

1. **扫描件没有文本层**。上世纪末到 2015 年前后的图纸与批复，绝大多数是扫描件，直接抽取得到空白。
2. **OCR 文本层是有毒的**。标称"可搜索 PDF"的文件，文本层往往由低质 OCR 生成，形近字与数字漏位遍布其中，比没有文本层更危险，因为下游会当真。
3. **表格是错位的**。概算表、工程量清单、定额子目在 PDF 里是散落的独立文本行，列位关系全靠坐标重建。
4. **公文有固定骨架**。批复、请示、函的结构高度稳定，但通用工具不认识"沪发改投〔2026〕60号"这类文号形态。
5. **目录深度有硬限**。外部知识库导入普遍卡在 8 层，而工程资料天然是"项目/标段/专业/图纸/cad/汇总/单项/数量表"这种七拐八绕的深树。
6. **原件与转换版会互相打脸**。同一份文件，PDF 排版版与 Word 源稿经常在数字上不一致，谁对谁错需要逐条判。

这个仓库里的九个技能，就是围绕这六层麻烦长出来的。

## 处理链路

```
原始 PDF
   │
   ├─ tender-pdf-clean ──────── 清洗、纠错、分层，输出干净分块文本
   │
   ├─ quota-pdf-to-md ───────── 定额类 OCR PDF 转结构化 MD
   ├─ cn-gov-eng-pdf-vectorkb ─ 公文/工程批复类转向量库标准 MD
   ├─ scanned-award-kb ──────── 扫描件公文批量转知识库五件套
   ├─ image-pdf-to-kb-site ──── 图文混排册转逐图图注 + 单文件站点
   │
   ├─ quota-pdf-to-calc-kb ──── 定额转"可计算"知识库（基价闭环校验）
   ├─ fee-schedule-pdf-to-calc-kb ─ 费率标准转"可计算"知识库
   │
   ├─ pdf-word-dual-source-rag ─ PDF 与 Word 双源对照、结构化、切块
   │
   └─ md-kb-vectorize ───────── 补齐结构化层与向量化层（FAISS）
```

## 技能清单

| 技能 | 作用 | 输入 | 输出 |
|---|---|---|---|
| [`tender-pdf-clean`](skills/tender-pdf-clean/SKILL.md) | 投标/招标 PDF 清洗、纠错、按商务技术报价分层 | 多份投标 PDF | 干净分块纯文本 + 元数据 |
| [`quota-pdf-to-md`](skills/quota-pdf-to-md/SKILL.md) | 定额类 OCR PDF 转结构化 MD，处理错位覆层 | 定额/预算 PDF | 分章 MD + 合并单文件 |
| [`quota-pdf-to-calc-kb`](skills/quota-pdf-to-calc-kb/SKILL.md) | 定额转可计算知识库，基价闭环校验 | 概算/预算/台班定额 PDF | 三层 MD + 机读 JSON |
| [`fee-schedule-pdf-to-calc-kb`](skills/fee-schedule-pdf-to-calc-kb/SKILL.md) | 费率标准转三层可计算知识库，含去水印与算例反算 | 费率/计价标准 PDF | 条款层 + 费率数据层 + 计算规则层 |
| [`cn-gov-eng-pdf-vectorkb`](skills/cn-gov-eng-pdf-vectorkb/SKILL.md) | 公文/工程批复转向量库标准 MD，含 OCR 交叉纠错 | 批复/请示/函 + 概算表 | 带 7 字段元信息头的 MD |
| [`scanned-award-kb`](skills/scanned-award-kb/SKILL.md) | 扫描件公文批量转知识库五件套，多联一致性校验 | 中标通知书/评标报告扫描件 | 站点 + MD + 台账 + 脚本 + 证据图 |
| [`image-pdf-to-kb-site`](skills/image-pdf-to-kb-site/SKILL.md) | 图文混排册转逐图图注与断语条目 | 图册/样张集/影像册 PDF | 双向可查知识库 + 单文件站点 |
| [`pdf-word-dual-source-rag`](skills/pdf-word-dual-source-rag/SKILL.md) | 同一文档 PDF 与 Word 双源校对、结构化、切块 | PDF + DOCX 成对 | structured MD + chunks jsonl + 差异报告 |
| [`md-kb-vectorize`](skills/md-kb-vectorize/SKILL.md) | MD 知识库补齐结构化层与向量化层 | MD 知识库目录 | YAML 头 + 语义标记 + FAISS 索引 + 查询脚本 |

## 安装

这些技能遵循开放的 Agent Skills 格式，一个文件夹就是一个技能。

**WorkBuddy**

把 `skills/` 下的目标文件夹复制到你的技能目录（通常为 `~/.workbuddy/skills/`），重启会话即可。

**Claude Code**

复制到 `~/.claude/skills/`。技能名与文件夹名一致，`SKILL.md` 会被自动发现。

**任意其他 Agent**

`SKILL.md` 是纯文本工作流说明，可直接作为 prompt 或系统指令的一部分喂给其他模型，`scripts/` 里的脚本可独立运行。

## 路径适配

仓库内所有本机绝对路径已替换为占位符，使用前需按自己的环境改一次：

| 占位符 | 含义 |
|---|---|
| `C:/Users/<USER>` | 你的 Windows 用户目录 |
| `<WORKSPACE>` | 你存放该任务的工作目录 |

Linux 与 macOS 用户请把路径改为 `~/` 或 `/Users/<USER>/` 形式。脚本里的 `SRC`、`WS` 等变量已改为读取环境变量 `SRC_DIR`、`WORK_DIR`，未设置时回落到相对路径 `data/input` 与 `work`。

## 依赖

按技能取用，多数为可选：

- `PyMuPDF`（`fitz`）：文本与表格抽取、页面渲染
- `python-docx`：Word 抽取
- `openpyxl`：Excel 概算表
- `onnxruntime` + `fastembed`：向量化
- `faiss-cpu`：向量检索
- 中文嵌入模型：`bge-small-zh-v1.5`
- OCR：脚本默认调用外部 `paddlevl-ocr` 技能，无该技能时可替换为你自己的 OCR 通道，`tender-pdf-clean` 与 `cn-gov-eng-pdf-vectorkb` 的 SKILL.md 内均写明了降级阶梯

## 使用示例

```
把这份定额 PDF 转成可计算知识库
```

```
这 9 份投标 PDF 先清洗分层，再切块
```

```
这份批复的 PDF 和 Word 版对一下，把数字不一致的地方列出来
```

```
把 md 知识库向量化，索引落到本地
```

## 设计原则

- **保真优先于美观**。宁可保留错位的表格原样，也不做猜测性重排。
- **不谎报内容**。文本层为空时如实标注 `NO_TEXT_LAYER`，不填充推测文本。
- **每条规则都带实测出处**。`SKILL.md` 里的性能数字与坑位结论来自真实批次，标注了日期与规模。
- **可核验**。产出物包含台账、差异报告或证据图，供人工复核。

## 许可

MIT，见 [LICENSE](LICENSE)。

## 说明

这些技能最初在真实的工程造价与招投标审核场景里打磨而成，文档样本已全部脱敏。技能中的项目名称、单位名称与编号均为示例占位，与真实项目无关。

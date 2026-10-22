# doc-to-md-skills

**Turn Chinese engineering documents and government official documents into searchable, computable, verifiable knowledge bases.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Skills](https://img.shields.io/badge/skills-9-blue.svg)](skills)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](https://www.python.org/)
[![Agent Skills](https://img.shields.io/badge/format-Agent%20Skills-8a2be2.svg)](https://agentskills.io)

English | [简体中文](README.zh-CN.md)

---

## Why this exists

Converting Chinese engineering documents to Markdown is not a PDF parsing problem. Six things get in the way, and each of them breaks a general-purpose converter:

1. **No text layer.** Drawings and government approvals from before roughly 2015 are almost always scans. Extraction returns blank pages.
2. **Toxic OCR text layers.** PDFs labelled "searchable" often carry a text layer produced by low-quality OCR, riddled with homoglyph substitutions and dropped digits. This is worse than having no text layer at all, because downstream tooling trusts it.
3. **Broken tables.** Budget estimate sheets, bills of quantities and quota subitem tables arrive as scattered independent text runs. Column relationships exist only in the original coordinates and must be rebuilt.
4. **Fixed official-document skeletons.** Approvals, requests and letters follow rigid structures, but generic tools do not recognise document number formats such as `沪发改投〔2026〕60号`.
5. **Directory depth limits.** External knowledge bases commonly reject trees deeper than 8 levels, while engineering archives are naturally organised as project / section / discipline / drawings / cad / summary / item / quantity-sheet.
6. **Original and converted copies disagree.** The same document as a PDF and as a Word source frequently differ on numbers, and deciding which is authoritative takes per-item judgement.

The nine skills in this repository grew out of those six obstacles during real production work on cost estimation and tender review.

## Pipeline

```
raw PDF
   |
   +- tender-pdf-clean ----------- clean, correct, layer by section
   |
   +- quota-pdf-to-md ------------ quota standards to structured MD
   +- cn-gov-eng-pdf-vectorkb ---- official docs to vector-KB MD
   +- scanned-award-kb ----------- scanned documents to KB bundle
   +- image-pdf-to-kb-site ------- image-heavy albums to annotated KB
   |
   +- quota-pdf-to-calc-kb ------- quota standards to a computable KB
   +- fee-schedule-pdf-to-calc-kb  fee schedules to a computable KB
   |
   +- pdf-word-dual-source-rag --- PDF vs Word cross-check, structure, chunk
   |
   +- md-kb-vectorize ------------ structure layer + FAISS vector layer
```

Each skill is usable alone. Chained together they form one path from a stack of scans to a queryable index.

## Skills

| Skill | What it does | Input | Output |
|---|---|---|---|
| [`tender-pdf-clean`](skills/tender-pdf-clean/SKILL.md) | Clean, correct and split tender documents by commercial / technical / pricing sections | multiple tender PDFs | clean chunked text + metadata |
| [`quota-pdf-to-md`](skills/quota-pdf-to-md/SKILL.md) | Quota standards from OCR PDFs, handling misaligned overlay text | quota / budget standard PDFs | per-chapter MD + merged single file |
| [`quota-pdf-to-calc-kb`](skills/quota-pdf-to-calc-kb/SKILL.md) | Quota standards to a computable KB with base-price closure checks | estimate / budget / machine-hour quota PDFs | three-layer MD + machine-readable JSON |
| [`fee-schedule-pdf-to-calc-kb`](skills/fee-schedule-pdf-to-calc-kb/SKILL.md) | Fee schedules to a three-layer computable KB, with watermark removal and back-calculation checks | fee / pricing standard PDFs | clause layer + rate data layer + rule layer |
| [`cn-gov-eng-pdf-vectorkb`](skills/cn-gov-eng-pdf-vectorkb/SKILL.md) | Chinese official documents to vector-KB MD with OCR cross-correction | approvals / requests / letters + estimate tables | MD with 7-field metadata header |
| [`scanned-award-kb`](skills/scanned-award-kb/SKILL.md) | Bulk scans to a five-part KB bundle with multi-copy consistency checks | award notices, evaluation reports | site + MD + ledger + scripts + evidence images |
| [`image-pdf-to-kb-site`](skills/image-pdf-to-kb-site/SKILL.md) | Image-heavy albums to per-image captions and lookup entries | album / sample / photo-book PDFs | bidirectionally searchable KB + single-file site |
| [`pdf-word-dual-source-rag`](skills/pdf-word-dual-source-rag/SKILL.md) | Cross-check PDF against Word source, structure, chunk | paired PDF + DOCX | structured MD + chunk jsonl + diff report |
| [`md-kb-vectorize`](skills/md-kb-vectorize/SKILL.md) | Add a structure layer and a vector layer to an MD knowledge base | MD knowledge base directory | YAML headers + semantic tags + FAISS index + query script |

## Install

These follow the open Agent Skills format. One folder is one skill.

**Claude Code**

```bash
git clone https://github.com/cjjsaber888/doc-to-md-skills.git
cp -r doc-to-md-skills/skills/* ~/.claude/skills/
```

**WorkBuddy**

Copy the folders under `skills/` into your skill directory, usually `~/.workbuddy/skills/`, and restart the session.

**Any other agent**

`SKILL.md` is plain-text workflow documentation. Feed it to any model as system instructions. The scripts under `scripts/` and `references/` run standalone with Python 3.9+.

## Path placeholders

Absolute paths in this repository have been replaced with placeholders. Replace them once for your own environment:

| Placeholder | Meaning |
|---|---|
| `C:/Users/<USER>` | your Windows home directory |
| `<WORKSPACE>` | your working directory for the task |

On Linux and macOS, convert to `~/` or `/Users/<USER>/`. Scripts read the `SRC_DIR` and `WORK_DIR` environment variables and fall back to the relative paths `data/input` and `work`.

## Dependencies

Pick what you need. All are optional except Python itself.

- `PyMuPDF` (`fitz`): text and table extraction, page rendering
- `python-docx`: Word extraction
- `openpyxl`: Excel estimate sheets
- `onnxruntime` + `fastembed`: embedding
- `faiss-cpu`: vector search
- `bge-small-zh-v1.5`: Chinese embedding model
- OCR: scripts call an external `paddlevl-ocr` skill by default. Any OCR channel works; the degradation ladders are documented inside `tender-pdf-clean` and `cn-gov-eng-pdf-vectorkb`.

## Examples

See [`examples/`](examples) for sanitised input fragments and their expected output, so you can judge the output shape without supplying a real document.

## Validate

```bash
python scripts/validate_skills.py
```

Checks that every skill has a well-formed `SKILL.md`, that the folder name matches the frontmatter `name`, and that no absolute machine path has leaked back in. It also runs in CI.

## Design principles

- **Fidelity over cosmetics.** Keep a misaligned table misaligned rather than guessing a re-layout.
- **Never fabricate content.** When there is no text layer, emit `NO_TEXT_LAYER` instead of plausible filler.
- **Every rule carries its evidence.** Performance numbers and pitfall notes in `SKILL.md` come from real batches, with dates and scale recorded.
- **Verifiable output.** Deliverables include ledgers, diff reports or evidence images for human review.

## Scope and honesty

This is a young project. It was extracted from production use in Chinese cost engineering and tender review, so the problems it solves are real and the solutions are battle-tested, but the codebase is not a mature library. There are no unit tests for the extraction logic because the inputs are large proprietary documents that cannot be redistributed. The skills document their failure modes explicitly rather than hiding them.

The domain is deliberately narrow. If you work with Chinese, Japanese or Korean engineering, construction or government documents, these skills address gaps that English-centric tooling does not cover.

## License

MIT. See [LICENSE](LICENSE).

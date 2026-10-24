# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-24

### Changed

- `md-kb-vectorize` 1.2.0 -> 1.3.0, backfilled from a 1,125-document / 62,080-vector production run:
  - Acceptance now requires three-way alignment: unique chunk-ID count == `faiss.ntotal` == `meta.jsonl` rows. The old `ntotal == line count` check passed on a corrupted index (equal totals, 899 stale vectors and 10,111 duplicate rows underneath)
  - Chunk IDs now hash the full text (prefix hashing collided on identical table headers); duplicates collapse to one vector; stale vectors are pruned after OCR backfill
  - New long-batch resilience section: scheduled-task watchdog plus finalisation chain, with six supporting disciplines (write the md before the state file, process-proxy forensics triple-check, UTF-8 BOM for PowerShell 5.1, and more)
  - New multi-agent domain-summary dispatch spec and credibility derivation (convert method -> A/B/C/D)
  - Depth red line widened to scan the source tree as well as the knowledge base; layer counting unified to `count(sep) + 1` with an independent rescan

### Added

- `references/ocr_watchdog.ps1`: two-minute scheduled-task probe with keep-alive, stall detection and heartbeat
- `references/run_pipeline.ps1`: finalisation chain with busy check, file-lock arbitration and per-step retry
- `references/prune_vectors.py`: stale-vector pruning with built-in three-way alignment check

## [0.1.0] - 2026-10-22

Initial public release. Nine skills extracted from production work on Chinese cost engineering and tender review, fully sanitised.

### Added

- `tender-pdf-clean`: clean, correct and layer tender PDFs by commercial, technical and pricing sections, with broken page-tree recovery and header/footer stripping
- `quota-pdf-to-md`: quota standard PDFs to structured Markdown, handling misaligned OCR overlay text
- `quota-pdf-to-calc-kb`: quota standards to a three-layer computable knowledge base with base-price closure verification
- `fee-schedule-pdf-to-calc-kb`: fee schedules to a three-layer computable knowledge base, with diagonal watermark removal and back-calculation checks
- `cn-gov-eng-pdf-vectorkb`: official documents to vector-KB Markdown with a seven-field metadata header and OCR cross-correction
- `scanned-award-kb`: bulk scanned documents to a five-part knowledge base bundle with multi-copy consistency checking
- `image-pdf-to-kb-site`: image-heavy albums to per-image captions and lookup entries, plus a single-file site
- `pdf-word-dual-source-rag`: PDF versus Word cross-checking, structural extraction and RAG chunking for paired documents
- `md-kb-vectorize`: structure layer (YAML frontmatter, semantic tags) and vector layer (FAISS plus `bge-small-zh-v1.5`) for existing Markdown knowledge bases
- `scripts/validate_skills.py` for structure and path hygiene validation
- GitHub Actions workflow running validation on Python 3.9 and 3.12
- Bilingual documentation, English and Simplified Chinese

### Notes

- All absolute paths replaced with `C:/Users/<USER>` and `<WORKSPACE>` placeholders
- All project-specific identifiers replaced with generic examples
- Two skills from the internal set are deliberately not included because they embed real approval documents and bid evaluation records

# Engineering RAG

面向工程规范、建设标准与图集 PDF 的模块化单体 RAG 项目。**Document Schema V2.4 已于 2026-10-11 正式冻结（FROZEN）**。Document Parser 已完成 PDF/OCR、MinerU 私有适配、复杂表格、公式、章节/条文结构化与可恢复的端到端编排；机器结果仍是待核验的部分解析候选。Task 2 已实现独立的 Clause-first Chunking 和 Chunk V1。检索、LLM 与外部存储后端尚未实现。

## 安装与检查

要求 Python 3.11+：

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check .
ruff format --check .
```

Task 1.1 Parser 与真实 CPU OCR：

```bash
python -m pip install -e '.[dev,parser-ocr]'
python -m pytest src/engineering_rag/modules/document_parser/tests -q
```

Task 1.2 MinerU 运行时独立安装在项目忽略的 `.local/mineru-runtime`，主环境不依赖 MinerU。固定入口依赖见 `requirements/mineru-task1-2.txt`；真实 PDF 和生成产物位于被 Git 忽略的 `data/eval/task1_2_mineru/`。执行器必须传入 PDF、案例清单、输出目录、可执行文件和模型目录，不会默认处理全部 441 页。

源代码采用一个 `src/engineering_rag` 包。`contracts` 是唯一公共 Schema/Protocol 来源；七个业务模块只提供稳定 `api.py`，未来实现放各自 `internal/`；跨模块流程由 `infrastructure/orchestrator` 组合。

## 独立模块测试

```bash
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest src/engineering_rag/modules/chunking/tests -q
python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q
python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q
python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q
python -m pytest src/engineering_rag/modules/query/tests -q
python -m pytest src/engineering_rag/modules/generation/tests -q
```

`examples/document.example.json` 是虚构的完整 V2.4 示例；`examples/document.partial.example.json` 是虚构的未完成 OCR 示例；`examples/chunk_batch.example.json` 是可由 Chunk V1 校验的虚构批次；`examples/artifact_manifest.example.json` 是仅供静态校验的虚构快照清单，不要求 URI 实际存在。`references/GB50010_2015_document.v2.4.partial.json` 是只读的 441 页目录及少量人工区域，不能当成全文 OCR；正式模型不会自动接受其 `2.4-proposal`。

字段说明见 [data-contracts.md](docs/data-contracts.md)，身份规则见 [id-policy.md](docs/id-policy.md)，快照与迁移见 [artifact-policy.md](docs/artifact-policy.md)，版本差异见 [schema-changelog.md](docs/schema-changelog.md)。[schema-freeze-checklist.md](docs/schema-freeze-checklist.md) 是唯一权威冻结验收表，[schema-v2.4-freeze-record.md](docs/schema-v2.4-freeze-record.md) 是正式冻结记录。V2.4 冻结后的破坏性变更必须升级 Schema 版本并提供显式迁移机制。

Parser Task 1.1 的行为、OCR 后端与实测结果分别见 [实现说明](docs/document-parser-task1-1.md)、[OCR 后端](docs/document-parser-ocr-backend.md) 和 [验收报告](docs/document-parser-task1-1-report.md)。Task 1.2 的实际环境、逐例状态和已知失败见 [MinerU 真实测试报告](docs/task-1.2-mineru-real-test-report.md)。

Task 1.3 的表格保真政策、三组真实 GB 50010 结果、可复现命令与 Known Issues 见 [复杂表格报告](docs/task-1.3-complex-tables.md)。

Task 1.4 的公式编号三态、分组与符号解释策略、三页真实结果及页 24 回退记录见 [公式结构化报告](docs/task-1.4-formulas.md)。

Task 1.5 的章节/条文边界、跨页内容引用、说明关联、安全退化策略及真实页结果见 [语义结构化报告](docs/task-1.5-semantic-structure.md)。真实回放命令：

```bash
python scripts/assemble_mineru_clauses.py \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --output data/eval/task1_5_semantics/runs/repair-20261012/GB-COMBINED \
  --comparison-baseline \
    data/eval/task1_5_semantics/runs/final/GB-COMBINED/document.semantic.partial.json
```

Task 1.5 四项语义来源修复、反例与真实回放结果见
[修复报告](docs/task-1.5-semantic-source-repair.md)。`runs/final/` 是只读对照基线；修复后
Document、diff、manifest 和 overlays 单独保存在 `runs/repair-20261012/`。

Task 1.6 端到端入口严格区分真实推理和保存产物回放：

```bash
python scripts/run_document_parser_e2e.py \
  --mode live_mineru \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --pages 16 \
  --run-id live-p16 \
  --output data/eval/task1_6_e2e/runs/live-p16
```

同一来源、配置、模型签名和产物哈希全部一致时，可加 `--resume` 复用成功批次。
21 页代表集的真实运行结论为 20/21 页成功；第 24 页触发 MinerU 4.0.12
`Unsupported warp settings`，因此 Task 1.6 当前为 PARTIAL。完整说明见
[端到端报告](docs/task-1.6-end-to-end-report.md)、
[质量分析](docs/task-1.6-quality-analysis.md)和
[运行与恢复手册](docs/task-1.6-operations.md)。441 页全本未获授权且未运行。


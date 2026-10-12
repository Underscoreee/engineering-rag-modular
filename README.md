# Engineering RAG

面向工程规范、建设标准与图集 PDF 的模块化单体 RAG 项目。**Document Schema V2.4 已于 2026-10-11 正式冻结（FROZEN）**。Architecture Task 1.1 已实现安全 PDF/OCR partial Document；Task 1.2 增加本地 MinerU 4.x 私有适配器；Task 1.3 增加有界 HTML 格网恢复、多级表头、保守跨页续表合并和 V2.4 表格映射。所有机器表格仍为待核验候选。页面分类、Clause、公式语义、Chunking、检索、LLM 与外部存储后端尚未实现。

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

`examples/document.example.json` 是虚构的完整 V2.4 示例；`examples/document.partial.example.json` 是虚构的未完成 OCR 示例；`examples/artifact_manifest.example.json` 是仅供静态校验的虚构快照清单，不要求 URI 实际存在。另三份 Chunk/检索/答案 JSON 仍使用既有契约。`references/GB50010_2015_document.v2.4.partial.json` 是只读的 441 页目录及少量人工区域，不能当成全文 OCR；正式模型不会自动接受其 `2.4-proposal`。

字段说明见 [data-contracts.md](docs/data-contracts.md)，身份规则见 [id-policy.md](docs/id-policy.md)，快照与迁移见 [artifact-policy.md](docs/artifact-policy.md)，版本差异见 [schema-changelog.md](docs/schema-changelog.md)。[schema-freeze-checklist.md](docs/schema-freeze-checklist.md) 是唯一权威冻结验收表，[schema-v2.4-freeze-record.md](docs/schema-v2.4-freeze-record.md) 是正式冻结记录。V2.4 冻结后的破坏性变更必须升级 Schema 版本并提供显式迁移机制。

Parser Task 1.1 的行为、OCR 后端与实测结果分别见 [实现说明](docs/document-parser-task1-1.md)、[OCR 后端](docs/document-parser-ocr-backend.md) 和 [验收报告](docs/document-parser-task1-1-report.md)。Task 1.2 的实际环境、逐例状态和已知失败见 [MinerU 真实测试报告](docs/task-1.2-mineru-real-test-report.md)。

Task 1.3 的表格保真政策、三组真实 GB 50010 结果、可复现命令与 Known Issues 见 [复杂表格报告](docs/task-1.3-complex-tables.md)。


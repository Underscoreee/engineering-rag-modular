# Engineering RAG

面向工程规范、建设标准与图集 PDF 的模块化单体 RAG 项目。**Document Schema V2.4 已于 2026-10-11 正式冻结（FROZEN）**：稳定 ID、不可变 Artifact、RawGrid、引用式 ContentUnit、强条证据和完整引用校验已经形成公共契约。Architecture Task 0.2 已完成；七个模块仍只有 Protocol 与骨架，下一阶段的 Document Parser 独立实现尚未开始，也没有实现 PDF 解析、OCR、Chunking、检索、LLM 或外部系统接入。

## 安装与检查

要求 Python 3.11+：

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check .
ruff format --check .
```

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


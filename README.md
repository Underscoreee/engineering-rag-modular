# Engineering RAG

面向工程规范、建设标准与图集 PDF 的模块化单体 RAG 项目。本仓库从零开始；当前进行 **Architecture Task 0.1**：Document Schema V2.4 已作为 Parser → Chunker 的公共契约，七个模块仍只有 Protocol 与骨架。没有实现 PDF 解析、OCR、Chunking、检索、LLM 或外部系统接入。

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

`examples/document.example.json` 是虚构的完整 V2.4 示例；`examples/document.partial.example.json` 是虚构的未完成 OCR 示例。另三份 Chunk/检索/答案 JSON 仍使用现有契约，均由测试校验。`references/GB50010_2015_document.v2.4.partial.json` 是只读的 441 页真实 PDF 页面目录及少量人工核对区域，不能当成全文 OCR 结果；正式模型不会自动接受其 `2.4-proposal` 标记。字段说明见 [data-contracts.md](docs/data-contracts.md)，真实样本统计见 [reference-v24-partial-diagnostic.md](docs/reference-v24-partial-diagnostic.md)，迁移边界见 [architecture-decisions.md](docs/architecture-decisions.md)。


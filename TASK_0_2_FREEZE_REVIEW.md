# Engineering RAG Architecture Task 0.2 — V2.4 独立冻结验收报告

**验收结论：暂不冻结（BLOCKED）。** 2026-10-11，依据用户上传的 `task0-2.zip` 原始源码（没有替用户修改原始压缩包）。

## 1. 运行环境与基础验证

- ZIP 内容：272 个条目，包含 `src/engineering_rag/contracts`、7 个模块骨架、测试、文档、完整/部分/Manifest 示例。
- 安全解压后，项目 Python `src` 包可导入。审查环境为 Python 3.13.5；与归档原报告中的 Python 3.11.17 环境不同。
- 直接运行 `python -m pytest -q`：未安装 editable package，导致 17 个 ModuleNotFoundError 收集错误。这不应作为产品缺陷计入；使用 `PYTHONPATH=src` 后正常导入。
- `PYTHONPATH=src python -m pytest -q`：**115 passed**，无 skip/失败。
- 当前审查环境**没有 Ruff**；归档 `docs/schema-freeze-checklist.md` 记录它曾在 Codex 的项目 `.venv` 中通过，但此次未独立复核。
- 另加 6 项独立负例/语义正确性测试：**6 failed**。每项都是一个当前没有防御的语义或一致性问题。测试文件见 `test_freeze_gaps.py`。
- 现有测试与新增测试合计运行时为 115 passed + 6 failed（分开执行），所以不能把先前报告的 115 passed 等同于冻结验收全面通过。

## 2. 已确认的正面成果

1. `Document.schema_version=2.4`；13 种指定页面类型 + unknown；5 种 Block；文档级 bbox 坐标约定。
2. `tables[]` 聚合逻辑表格；片段 `table_id`、来源 `source_block_ids`、列定义/展开数据、notes、可选 RawGrid；基本交叉校验已经存在。
3. `Equation` 独立 `formula_id`，三种编号状态（printed / confirmed_absent / unknown）并区分缺少 OCR；支持公式组与符号项。
4. 正文/条文说明分组，ContentUnit 引用式模型，并为 `plain_text` 增加版本和源摘要；原始副本被 strict 拒绝。
5. MandatoryEvidence 已有证据枚举、审核状态、UTC 时间与三态强条判断；相互冲突时可做诊断。
6. ArtifactManifest 与 FileStore / Migration Protocol 已定义；没有越界实现 PDF OCR、检索或 LLM 业务算法。
7. `documents.py` 和模块 `INTERFACE.md` 的 Parser、Chunker 公共签名一致。

## 3. 冻结阻塞（P1）

### P1-A：正文 Clause 可以错误引用条文说明页面

**复现：**将 `examples/document.example.json` 第一页的 `page_type` 从 `body` 改成 `explanation_body`，保持正文 `n-4.2.1` 和所有引用不变，`Document.model_validate()` **仍然通过**。

- 文件：`src/engineering_rag/contracts/documents.py`，`_check_clause()`（约 786–873 行）。仅检查 Clause 对应 Section 的 `content_group`，没有核对引用 Block 所属 Page 的 `page_type`。
- 风险：正文条文误混入说明页，破坏全文来源分区和下游 Chunking 的规范效力区分。
- 修复：根据 `normative/explanations` 验证所有相关来源页属于 `body/explanation_body`；如需合法处理附录/混排特殊情况，应有明确的经过审查的例外语义，不可默认放行。

### P1-B：标记为完整 OCR 的页面允许存在未处理 Block

**复现：**在完整示例中将正文 Block 设置 `recognition_status=not_processed`、`ocr=null`，清除由该 Block 派生的 `plain_text` 缓存后，仍可使 `processing.partial=false`、`is_complete_document_ocr=true`，且 Page 的 `content_extraction_status=complete`，`Document.model_validate()` **通过**。

- 文件：`documents.py`，`Page.check_status()`（约 277–281 行）、`Document.validate_document_references()`（约 689–705 行）。
- 风险：把尚未 OCR 的数据误当作完整，遗漏规范正文与不确定公式。
- 修复：为 Page `complete` 与其所含 Block `recognition_status` 建立一致性规则，尤其拒绝 `not_processed`/`not_transcribed`；将“已运行 OCR”与“已人工核验”区别对待，避免不必要地要求所有 Block `verified`。

### P1-C：`plain_text` 派生渲染丢掉公式的“式中”符号说明

**复现：**合成示例的 FormulaGroup 有 `{symbol:"q", description:"虚构量"}`，但 `derive_clause_plain_text()` 生成的条文文本只有 `q=F/A` 等公式，没有“虚构量”。

- 文件：`documents.py`，`derive_clause_plain_text()`（约 932–1003 行），公式分支只拼接 `equations[].text/latex`，没有渲染 `symbol_explanations.items[]`。
- 风险：Chunking 如果使用缓存，会漏掉变量定义，严重影响工程公式的完整语义与检索质量。
- 修复：将符号及文字解释纳入公式组的可读文本，保留多公式与多行公式顺序；合理处理同一组公式被多个 ContentUnit 引用时的去重，避免重复说明。同步升级 renderer 版本并重算合成示例缓存与 source digest。

## 4. 冻结前建议修复（P2）

### P2-A：Manifest 与 Document 的 parser_version 冲突未校验

**复现：**仓库现有部分示例的 `Document.processing.parser_version` 是 `"2.4"`，Manifest 的 `parser_version` 是 `"synthetic-parser-0.2"`。构造 `DocumentArtifact` 仍通过。

- 文件：`contracts/artifacts.py`（约 86–124 行）；只检查 `document_id`、schema、processing status 和部分 asset 标识。
- 建议：当 Manifest 明确声明 parser_version 时，必须与 Document.processing.parser_version 对应；同步修复 fixture，让 schema 版本和 parser 版本真正分离。若两者语义有意不同，必须重命名并详细文档化。

### P2-B：Manifest 与 Document 同一 Asset 的摘要和大小可以矛盾

**复现：**同一 `asset_id` 在 Document Block 中声明 `sha256="cccc..."、size_bytes=3`，在 Manifest 中声明 `sha256="bbbb..."、size_bytes=1024`，`DocumentArtifact` **仍然通过**。

- 文件：`contracts/artifacts.py`（约 105–124 行），比较类型/URI/media_type/version，却忽略两侧都已声明的 `sha256/size_bytes`。
- 建议：对双方同时声明的摘要与大小做一致性校验；这与读取真实 URI、核对真实 bytes 是不同的职责。不要误声称静态契约已经验证磁盘内容。

### P2-C：Section 结构路径与 `number` 可以语义不符

**复现：**章节 `number="4"`，却把 `structure_path` 改成 `["999"]`，子节路径同步改成 `["999","4.2"]`，文档仍通过。现有校验只核对与父节点的前缀。

- 文件：`documents.py`，`_check_sections()`（约 708–731 行）。
- 建议：对于有 `number` 的 Section，`structure_path` 的末项应与 `number` 一致；保留带“条文说明”等前缀路径的合理场景。

### P2-D：已验证 Document 仍可在原地变为无效（未新增红测）

**复现：**构造合法 Document 后，直接 `doc.pages[0].blocks[0].ocr.text = "changed"`；已生成的 Clause `plain_text` 不会触发跨对象重新校验，直到重新序列化并验证才发现不一致。Pydantic 的 `validate_assignment=True` 并不自动触发父模型级的全图校验。

- 建议：规范“输出/持久化前重新完整校验”，必要时使用快照复制、不可变对象或显式 seal/commit 阶段；不强制立即把所有 DTO 定义为 immutable，但不可假定嵌套修改后依然有效。

## 5. 非阻塞但应注意的界限

- 对 441 页真实规范的 `references/GB50010_2015_document.v2.4.partial.json` 是不完整人工样本，不是成功进行完整 OCR 的金标准。
- `processing.partial=false`、Page=complete 并不能从纯 Schema 自证所有语义条文都被识别；Parser 质量仍须靠真实 Golden Dataset 测试，不能因纯 DTO 校验通过就声称解析准确。
- Asset URI/sha256 静态字段一致也不能代替未来 FileStore 的文件 bytes 完整性验证。
- PyMuPDF 仅在 ADR 中作为优先方向，没有被硬编码为运行依赖，符合阶段要求。

## 6. 验收门槛与下一步

当前维持 `READY_FOR_REVIEW` 或改为 `BLOCKED_PENDING_FIXES`；**不要修改为 `FROZEN`**。

最小修复：6 项独立负例变绿、对应有效案例不回归、公式符号说明在 Clause plain_text 中可见、Manifest 资产冲突被拒绝，并在与项目一致的 Python 3.11+ 环境运行原有 115 项测试及格式/Lint。然后重新出具测试证据，交维护者复核。

适用文件：
- `test_freeze_gaps.py` — 可以复制到项目的 `tests/contracts/` 目录运行（当前故意全部失败）；
- `red_tests_output.txt` — 本次独立红测输出。

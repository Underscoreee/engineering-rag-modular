# Codex：Architecture Task 0.2 冻结前缺陷修复（仅修复契约）

请在当前 Engineering RAG 项目根目录执行。先阅读 `AGENTS.md`、`docs/schema-freeze-checklist.md`、`docs/data-contracts.md`、`docs/id-policy.md`、`docs/artifact-policy.md`、`src/engineering_rag/contracts/documents.py`、`src/engineering_rag/contracts/artifacts.py`，以及我提供的 `TASK_0_2_FREEZE_REVIEW.md` 和 `test_freeze_gaps.py`。

目标：解决独立验收发现的 **3 项 P1、3 项 P2**，保持 Document V2.4 已确认的所有产品决策与 ADR，不提前实现任何 PDF/OCR、Chunking、存储后端、检索或 LLM 算法，也不得自动宣布 Frozen。

## 必修项目

1. **Clause/PageType 语义一致性：** `clauses.normative` 的每个来源 Block 必须来自 `body` 页面；`clauses.explanations` 的来源 Block 必须来自 `explanation_body` 页面。用 `Document` 的 Page/Block 索引进行跨引用校验。若存在需要支持的合法混合页面情形，应先通过 ADR 定义，不得靠放宽所有来源校验规避。添加正文错误挂到说明页、说明错误挂到正文页的反例。
2. **OCR 完整状态一致性：** `content_extraction_status=complete` 和 `processing.is_complete_document_ocr=true` 时，不允许其页面中包含标记 `not_processed/not_transcribed` 的 Block；`unverified` 表示已识别但待审核，是否允许应在契约写清楚。新增 full/partial 对照案例，防止将未处理页或未处理 Block 当完整。
3. **公式符号说明不丢失：** `derive_clause_plain_text` 渲染 `FormulaGroup.symbol_explanations.items` 的 `symbol + description`（可渲染 latex），并确保多公式、多行公式、连续公式组和同一组部分引用时不重复/漏写。更新 `PLAIN_TEXT_RENDERER_VERSION`，重新生成合成示例的 `plain_text`、`plain_text_source_digest`，保留“无单独 unit/intro 字段”的约定。
4. **Manifest/Document parser_version 对齐：** 当 Manifest 明确保存 `parser_version` 时，它应与 Document.processing.parser_version 一致；修复合成样本中把 schema version 当 parser_version 的混淆。若业务含义确实不同，请明确新字段命名并测试。
5. **Manifest/Document Asset 校验：** 同一 asset_id 的字段在双方都声明时，sha256/size_bytes 必须相等；已有 uri、type、media_type、version 校验继续保留。不得假称这验证了实际磁盘字节。
6. **Section.structure_path：** 除父子前缀/无环外，对有 number 的 Section，保证其结构路径末级编号一致；保持条文说明前缀、附录等实际规范结构可表达。

## 建议同步完成（不必立刻引入复杂不可变 DTO）

- 记录 Pydantic 内存对象经嵌套修改后跨对象校验不会自动重跑的限制；规定 `FileStore.commit_artifact` 未来实现必须先对 Document/Manifest 重新做完整验证，再计算哈希、写入快照；通过单独测试展示 revalidation 的约束。
- 为未来 Parser Golden Dataset 保留“静态 DTO 校验 != 内容提取完整性/准确性”的说明。

## 必须执行的测试

先复制提供的 `test_freeze_gaps.py` 到 `tests/contracts/test_freeze_gaps.py`，在开始修复之前确认新增负例确实失败，再迭代直到变绿。注意测试中名为 `test_clause_plain_text_contains_formula_symbol_explanations` 的断言需要随正式渲染格式合理保持符号描述可检索。

完成修复后运行：

```bash
python -m pytest tests/contracts -q
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest src/engineering_rag/modules/chunking/tests -q
python -m pytest -q
ruff check .
ruff format --check .
```

如果没有安装 editable package，可先按项目 `README` 安装；若仅作临时验证可 `PYTHONPATH=src python -m pytest -q`，但需在报告中区分。

完成时列出实际代码变更、6 项独立测试的结果、全部已有测试结果、Lint、示例 JSON 往返与未解决问题。**只有完成独立验收后，才由维护者决定是否冻结 V2.4。**

# Engineering RAG — Task 1.5 独立代码验收报告

- 检查对象：用户上传的 `task1-5.zip`（独立解压副本）
- 日期：2026-10-12
- 检查范围：冻结 Document V2.4、Document Parser 中 Section/Clause/条文说明组装、真实 MinerU 回放、负向边界测试
- **结论：PARTIAL — 暂不批准无条件进入 Task 1.6；建议先完成四项定向修复。**

## 1. 可复现的通过结果

1. 原始仓库测试：`PYTHONPATH=src python -m pytest -q` → **261 passed, 16 skipped**；未将独立新增的四个反例计入基线。
2. 显式开启已有真实产物集成测试：`ENGINEERING_RAG_RUN_REAL_MINERU=1 PYTHONPATH=src python -m pytest tests/integration/test_task1_5_real_semantics.py -q` → **5 passed**。
3. 使用本次环境中与 manifest 声明哈希一致的 GB 50010 PDF 重新运行 `scripts/assemble_mineru_clauses.py`，完整 JSON 与 ZIP 中已保存的 `document.semantic.partial.json` **内容一致**。SHA-256 PDF：`43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。
4. 真实回放组合 8 物理页，7 Sections、14 normative Clauses、3 explanation Clauses、13 pending relations；其中第 301 页缺少前置章节，按已有工作流部分保留 pending。
5. 此环境未安装 Ruff/MinerU 模型，因此 **未独立运行 Ruff 或全新 MinerU 推理**；真实回放使用 ZIP 内已保存的 MinerU 结构化产物。上游真实执行日志随 ZIP 可见，不代表本次重复执行模型推理。

## 2. 新增独立反例：4 failed

### G1 / P1：缺少分区证据时误将条文说明正文标成正文 `body`
- 文件：`src/engineering_rag/modules/document_parser/internal/semantic/page_zone_classifier.py`
- 源码触发：`elif _has_clause_or_heading(texts): page_type = BODY` 没有正文/说明分区证据。
- 真实验证：抽出真实 PDF 物理第 301 页、移除 `known_explanation_cover_page` 上下文重新分类，得到 `body`，但该页在已证实的整文档分区中为 `explanation_body`。
- 风险：在选择性解析条文说明页面时导致分组反转；后续 Section/Clause 可能进入错误命名空间。
- 修复：使用已核验封面/目录、可信连续页或外部已验证分区建立类型；无法区分时保留 `unknown` + pending 证据，不能凭三段编号默认正文；保留真实页 16 有明确章节题头可判断为正文的能力。

### G2 / P1：`unknown` 页面候选来源没有进入待关联队列
- 文件：`src/engineering_rag/modules/document_parser/internal/semantic/assembler.py` → `_build_clauses()`。
- 源码触发：`group is None` 直接跳过 Page 中 Block，不创建 `PendingSemanticRelation`。
- 复现：未知页中存在 `前页条文的跨页续文。` 的 Body Block，页面 OCR 保存在 `pages[].blocks`，但 `semantic_pending_links.json` 没有任何对应关系。
- 风险：后续补页后缺少机器可读重试索引，来源未被关联又未被标注。
- 修复：对于未分类页面，保留候选 OCR 及明确 `page_type_ambiguous`/`unclassified_content` pending；避免误造 Clause，保留可追溯 page/block IDs。

### G3 / P1：多批次 Document 合并没有防止混入不同 PDF
- 文件：`scripts/assemble_mineru_clauses.py` → `_merge_documents()`。
- 源码触发：仅判断 `document_id` 一致，不比较真实 `source_file.sha256`/`file_id`/`page_count`/`standard` 等。
- 复现：两份相同 `document_id`、不同 SHA-256、不同页码的 Document 被允许合并且最终来源依旧声称是第一份 PDF。
- 风险：跨文档证据污染、错误规范条文归属和无法验证的来源标注。
- 修复：合并前校验统一物理源、规范版本、页数、坐标系和 block/table ID 冲突；不一致 fail closed，并提供明确诊断。不能只依靠 doc ID。

### G4 / P2：安全拆分接受不在母 Block 范围内的子 bbox
- 文件：`src/engineering_rag/modules/document_parser/internal/semantic/block_splitter.py` → `split_body_block()`。
- 源码触发：子 bbox 只通过 Pydantic 的全页边界校验，未验证每个 span bbox 被母 Block bbox 包含。
- 复现：原 Block y=20–40，却允许子文本 span y=220–240 和 y=250–270，最终 Document 校验仍然通过。
- 风险：Clause 来源定位/overlay 虚假错位；伪造了「有可信位置证据」的切分。
- 修复：检查每个子 bbox 在源 Block 内（精度容差明确）；进一步确保按阅读顺序的几何证据不互相矛盾，不具备完整信息则不拆分并记录 pending。

## 3. 交付包质量问题（非 P1）

`TASK_1_5_ACCEPTANCE_CHECKLIST.md` 和 `docs/task-1.5-semantic-structure.md` 均引用根目录 `TASK_1_5_IMPLEMENTATION_REPORT.md`，但上传 ZIP 中**不存在此文件**。应补齐，或更正为实际可访问的报告路径，不得出现报告已交付但交付包找不到的情况。

## 4. 回归门槛

- 原有 **261 passed, 16 skipped** 不倒退；显式真实回放 **5 passed** 不倒退。
- `tests/audit/test_task15_independent_gaps.py` 四项新增反例由失败变为通过；原始 PDF 第 301 页无 cover 分区时安全退化为 `unknown`。
- 真实第 16、49–50、126–127、277、282、301 页组合回放保持可重现；Document V2.4 Pydantic 与 round-trip 全部通过。
- 已保存的真实原始 MinerU 产物只读；旧版本输出不覆盖，使用新目录输出修复产物。
- 正确输出日志、`ruff check .`、`ruff format --check .`，填补或更正最终报告路径。
- 不修改冻结 `src/engineering_rag/contracts/`，不引入其他引擎，不提前改 Chunking 或 Retrieval。

## 5. 说明

以上发现为独立最小反例证实的 **代码层边界缺陷**，不等于真实 8 页回放已经发生四种错误。尤其 G1 的后果依赖于缺少正文/说明分区上下文的选页模式。Task 1.5 当前有可用的真实基础结果，建议定向修复而非重写。

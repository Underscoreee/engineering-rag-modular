# Architecture Task 1.5 实施报告

## 结论

**PARTIAL**。私有语义结构化实现、S01～S36 合成回归、关键真实页回放、合法 V2.4 JSON、来源 sidecar、pending links 和 overlays 已交付。物理页 301 缺少前置 4.1 Section 页面，按保守策略未导出其 Clause；28–29、37–38 未在本轮重复回放，其 Task 1.3 逻辑表产物仍保留。

## 前置 Gates

- Document Schema `2.4` 状态 `FROZEN`；本地 annotated tag 对象为 `82f05040699346ac37798e20375722f2991dec50`，其 `^{commit}` 解析到冻结提交 `ebd9b29b3bb475401c8e91a30303ae46a8c119aa`。
- `git diff document-schema-v2.4 -- src/engineering_rag/contracts` 为空；公共 Schema、Protocol、renderer 和验证逻辑均未修改。
- Task 1.1 旋转/CropBox、SHA-256、size_bytes 修复代码与回归测试存在。
- Task 1.4 最新 grouped 产物存在：页 50 为两个完整 FormulaGroup Block（5 式 + 2 式），条件/符号解释来源消费与跨页未完成标记均可追溯。基线为 `248 passed, 10 skipped`，Ruff lint/format 通过。

## 实现

- `internal/semantic/page_zone_classifier.py`：证据驱动的正文、说明封面、说明正文、目录和 unknown 分区。
- `internal/semantic/assembler.py`：两套 Section 树、Clause 边界/跨页、ContentUnit、说明关联、pending、安全 partial、冻结 renderer 缓存和确定性 ID。
- `internal/semantic/block_splitter.py`：只有完整、不重叠 span 与 bbox 证据时才拆分混合 Body，并返回 old→new lineage。
- `internal/semantic/models.py`：来源证据、未决关系和 lineage 私有模型。
- `scripts/assemble_mineru_clauses.py`：有界本地回放、输入哈希/协议校验、合并、双次幂等检查、JSON/overlay/manifest 输出。

MinerU Parser 路径可通过私有 `ParseConfig.options.semantic_structure=true` 在同一次
`DocumentParser.parse()` 中启用语义装配；孤立说明选页可传入已核验的
`semantic_explanation_cover_page` 区段锚点。默认关闭以维持旧调用的显式阶段边界。

公共 `DocumentParser.parse(ParseRequest) -> Document` 未改变；实现没有 Chunking、检索、LLM 或外部 API 调用。

## 真实执行

源 PDF 为 441 页，SHA-256 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。运行环境为 MinerU 4.0.12 / `docvortex.middle/2.0` / basic / local CPU。

页 49–50 缺口已实际补跑：51.2001 秒，子进程 user CPU 121.7436 秒、system CPU 12.1357 秒、峰值 RSS 2,972,692 KiB。组合回放得到 8 页、7 Section、14 正文 Clause、3 说明 Clause、13 pending。GB-C01/C02/C04/C07/C08 机器检查 PASS；GB-C10 PARTIAL（缺 4.1 父 Section）。这些是待人工核验候选，不计算 Precision/Recall/F1。

输出：

- `data/eval/task1_5_semantics/runs/final/GB-COMBINED/document.semantic.partial.json`
- `semantic_source_lineage.json`、`semantic_pending_links.json`、`semantic_summary.json`
- `raw_inputs_manifest.json`、`task_1_5_results.json`
- `overlays/page_0016|0049|0050|0126|0127|0277|0282|0301_semantic_overlay.png`

## 测试

- Document Parser 独立测试：`136 passed`。
- contracts：`114 passed`。
- Chunking、keyword/vector/hybrid retrieval、query、generation：各 `1 passed`。
- 默认完整 pytest：`262 passed, 15 skipped`（真实产物测试默认显式跳过）。
- `ENGINEERING_RAG_RUN_REAL_MINERU=1` 完整 pytest：`277 passed`。
- Task 1.5 真实集成测试：`5 passed`。
- `ruff check .`：通过。
- `ruff format --check .`：`197 files already formatted`。
- `Document.model_validate()`、JSON 往返、同输入双次装配一致性：通过。

## 已知限制

- 页 301 是说明章节中段，缺少选页范围外的 4.1 标题；其文本、公式和候选边界保留在页面视图与 pending sidecar。
- 页 50 底部 `σp0i` 说明跨页未完成，未补造缺字，6.2.1 不写 plain-text 缓存；冻结 renderer 仍可按需派生当前可见的 1,369 字候选文本。
- 机器页型、Section/Clause 和 OCR 均待人工审核；没有合法 Golden Dataset，因此不报告准确率。

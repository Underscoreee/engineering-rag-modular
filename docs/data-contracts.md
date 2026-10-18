# 公共数据契约：Document V2.4（FROZEN）

`engineering_rag.contracts` 是唯一公共模型来源。Document Schema V2.4 已于 2026-10-11 冻结。所有 DTO 使用 Pydantic v2 和 `extra='forbid'`；`Document.schema_version` 只接受 `"2.4"`。`2.4-proposal`、V2.3 和 Task 0.1 候选 JSON 不会静默迁移。示例内容均为虚构测试文本。冻结后的破坏性变更必须升级 Schema 版本并提供显式迁移机制。

## Query 2.0 与 Task 6.0.1 依赖契约

Query 独立使用 `QUERY_SCHEMA_VERSION="2.0"`：RetrievalPlan 新增必填 processing_intent
（acquisition/exploratory），保留原 QueryIntent 五类语义；QueryResult 因嵌套计划同步升为
Literal 2.0，仍只返回 plan/evidence。QueryRequest、QueryOptions、检索模型、Chunk 与
Document V2.4 未改；全局 SCHEMA_VERSION 仍为 1.0。

旧计划/结果必须显式调用 migrate_retrieval_plan_v1 / migrate_query_result_v1，并提供处理
意图，不从旧语义猜测。严格旧消费者不能直接读取新版 JSON。示例为
examples/query_result.v2.example.json；迁移和兼容细节见
[ADR-Q-001](adr-task6-query-prerequisites.md)。

公共 llm.py 定义 StructuredLLMRequest/Response、StructuredLLMConfig、LLMTokenUsage；
Response.data 是未验证传输对象，validate_output 绑定请求并用指定 Pydantic 模型严格校验，
然后仍须业务层验证依据。未知用量允许 null。catalog.py 定义可信快照目录 Lookup/Record/Match，
区分唯一、歧义、未匹配、不可用以及全局有效与当前双索引入库。LLM/目录 Protocol 均在
protocols.py，仅声明能力；没有供应商 SDK、模型调用、生产目录或 Query 业务算法。

## Chunk V1

`ChunkingService.chunk(Document, ChunkingConfig) -> ChunkBatch` 消费冻结的 Document
V2.4，输出 `schema_version="1.0"` 的 Chunk V1。`ChunkingConfig.max_tokens` 默认为
800 且可配置，`overlap_tokens` 在 V1 固定为 0，未定义的 `options` 会被当前 Clause-first
实现拒绝。

`Chunk` 分离物理 `chunk_id` 与逻辑 `logical_chunk_id`，并携带 `content`、独立的
`context_header`、派生 `embedding_text`、`token_count`、`content_type`、页范围、有序
`source_refs/source_block_ids`、嵌套 `standard`、Section/Clause 身份、正文/说明及强制性
三态、父子关系、Table/Figure/Formula 身份、实现版本与超限标志。Table、FormulaGroup 是
不可拆的原子 Chunk；超过预算时保持结构并标记 `exceeds_max_tokens=true`。超长 Clause 的
物理片段共享一个 `logical_chunk_id`，无 overlap。完整行为见
`modules/chunking/INTERFACE.md`，合法虚构示例见 `examples/chunk_batch.example.json`。

Formula/Table 的 `content` 是面向 Embedding、BM25 与 LLM 的稳定语义 JSON，而不是
Document 对象的完整转储：公式只含编号、LaTeX 和符号解释；表格只含表号、表题、语义列、
业务数据与表注。识别状态、raw grid、单元格几何、内部 ID 与来源定位继续保留在 Document
和 Chunk metadata/provenance。`embedding_text` 与 `token_count` 必须由该清洗后的
`content` 派生。

Chunk V1 的确立没有修改 Document V2.4 字段或验证语义。改变 Chunk 公共字段需要升级
Chunk Schema；仅改变确定性切分/身份结果也必须升级 `chunking_version`。

## Document 顶层与页面

`Document` 必填 `document_id`、文档级 `bbox_coordinate_system={pdf_points,top_left}`、`source_file`、`standard`、`page_count` 和 `processing`，并包含 `pages[]/sections[]/tables[]/clauses`。`document_id` 与 standard code、edition、Parser 版本及 Artifact 版本含义不同。

`Page.page_number` 从 1 开始且不超过 `page_count`；尺寸为正。PageType 恰为 13 种指定类型加 `unknown`，BlockType 恰为 `title/body/table/image/formula`。bbox 只有四坐标且不得越过页面。`not_processed + blocks=[]` 表示尚未处理，不是空白页；partial Document 可省略尚未声明的 Page，但已声明引用仍必须有效。

`processing.partial=false` 要求所有页均存在且 complete，`is_complete_document_ocr=true`。反向地，`is_complete_document_ocr=true` 也要求全部页存在且 complete；完整 OCR 后仍可因为语义结构未完成而 `partial=true`。

`content_extraction_status=complete` 的页面不得包含 `recognition_status=not_processed/not_transcribed` 的 Block、未处理表格片段或未处理公式。`unverified` 表示内容已识别但尚待人工审核，允许出现在 complete 页面；它与“尚未处理”不同。Schema 只能验证声明状态一致，不能证明 Parser 确实找全或识别准确。

## Table 与 RawGrid

Page table Block 只保存本页 bbox、reading order、局部 OCR、`table_id/fragment_index/fragment_status`。完整结构只在顶层 `LogicalTable`：

- `fragments` 从 0 连续编号，顺序与 `source_block_ids` 一致，页码和 Block 关系双向校验；
- `columns[].header_path` 支持多级表头，`role` 区分横向/纵向语义，`derived=true` 表示展开派生；
- `data[]` 的业务键必须恰好等于 column keys，额外只允许 `source_page/source_block_id`；
- `notes` 只能为 null 或唯一正顺序号的 `{number,content}` 数组；
- `raw_grid` 可为 null。非空时 row/col 从 0 开始、span 为正且不越界/重叠；complete 必须全覆盖，partial 可有缺口；未识别 cell 使用 `text=null` 和非 verified 状态。

`columns/data` 是检索友好记录，`raw_grid` 是最佳可用印刷拓扑，两者职责不同且都不在 Page Block 中复制。

## Formula 与引用式 ClauseContent

每条 Equation 都必须有快照内唯一 `formula_id`。`equation_number_status=printed` 要求编号；`confirmed_absent` 要求编号为 null 且公式已核验；`unknown` 表示尚未确认编号，不能冒充无号。未识别公式可保留 `latex/text=null`。禁止旧字段 `line_index`，SymbolExplanation 禁止 `intro/unit`。

正文与说明分别位于 `clauses.normative/explanations`，同号可以共存但 `clause_id` 不同；说明可用 `explains_clause_id` 指向正文。`Clause.source_block_ids` 是按 ContentUnit 顺序去重后的索引缓存，必须完全一致。

正文 Clause 的全部来源 Block 必须位于 `page_type=body`，说明 Clause 的全部来源 Block 必须位于 `page_type=explanation_body`。当前契约不默认放行混合页面；如未来需要，必须先通过 ADR 定义可审计的区域语义。

ContentUnit 仅引用权威内容：body/list_item 引用 body Block；table 引用顶层 table 并覆盖所有片段；formula 引用公式 Block 与其中的 `formula_ids`；image 引用 image Block 与 `asset_id`。旧 `text/table/formula_group` 副本会因 strict Schema 被拒绝。

`ClauseContent.plain_text` 可空。非空时必须带 `plain_text_renderer_version` 和 `plain_text_source_digest`；`derive_clause_plain_text()` 只读取有序引用对象，并由 Document 校验结果和摘要。Renderer v2 在最后一个被引用的同组公式之后，以 `式中：符号：说明` 输出 `symbol_explanations`；同一公式组被多个连续 ContentUnit 部分引用时只输出一次。多行 LaTeX 仍保留在 Equation 权威字段中，不新增 `unit/intro`。来源改变、renderer 升版或数据仍缺失时必须清空/重算缓存，不能人工独立编辑。

## MandatoryEvidence

正文 Clause 的 `is_mandatory` 是三态。`mandatory_evidence[]` 字段包括证据 ID、明确来源枚举、可选来源 Document/page 或 URI、引用说明、pending/verified/rejected、bool/null 结论、审阅标识与 UTC 时间。

- null 可无证据或保留 pending/冲突证据；
- true/false 至少需要一条 verified 且一致的结论；
- verified 证据必须有具体文档页或外部 URI，且有审阅人标识和 UTC 时间；
- conflicting verified 证据禁止确定结论；未知结论可由 `collect_document_diagnostics()` 报 conflict；
- 说明 Clause 不得携带强条证据。

证据仅表示经声明的审阅材料，不是系统法律保证，也不能由“应/必须”、粗体或模型输出推断。

## ArtifactManifest 与版本

`ArtifactManifest` 必填 `artifact_id/artifact_version/schema_version/created_at/source_document_id/processing_status/document_json_ref`，资源引用含 URI、media type、SHA-256 和大小；`assets=[]`、`parser_version=null` 可选。时间必须为 UTC。Manifest 声明 parser version 时须等于 `Document.processing.parser_version`；双方声明同一 Asset 的 SHA-256/大小时也必须一致。`DocumentArtifact` 做声明值的内存一致性校验；failed Artifact 不携带 Document。

静态模型不打开 URI、不验证真实字节，也不实现原子存储。嵌套 Pydantic 对象原地修改不会自动重跑父级全图校验；输出或提交前必须重新序列化并完整 `DocumentArtifact.model_validate_json(...)`。`ArtifactIntegrityErrorCode` 为未来 I/O 明确区分 resource not found、checksum mismatch、unsupported schema version 和 snapshot conflict。未来 FileStore 以 `document.json + assets/ + manifest.json` 提交不可变快照；同一键不可覆盖。显式迁移边界由 `DocumentMigrationService` 声明，当前不实现转换器。

## 删除字段与序列化

继续拒绝 `Standard.is_synthetic_example`、Page `printed_page_label/primary_page_type/region_type`、PageBlock `region_type/clause_id/section_id`、bbox 的局部坐标声明、公式 `line_index`、符号 `intro/unit`。保留 `structure_path`、`processing`、Asset 版本、`page_count` 和 `ocr.text`。

JSON 使用 `model_validate_json()` 与 `model_dump_json()` 往返。完整、部分与 Manifest 示例见 `examples/`；详细身份和 Artifact 规则见 `id-policy.md` 与 `artifact-policy.md`。

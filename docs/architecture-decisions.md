# 架构决策记录

## ADR-Q-001：Query 前置契约 — Adopted

Task 6.0.1 保留语义 QueryIntent，新增独立 ProcessingIntent；RetrievalPlan/QueryResult
局部升级为 2.0，提供必须显式给出处理意图的 V1 迁移。供应商无关 StructuredLLMClient
与可信快照 StandardMetadataCatalog 只定义 DTO/Protocol 和校验边界；Query 首版采纳
Hybrid-only、可信范围验证和异常式失败政策，业务逻辑留待 Task 6.1～6.4。
Document V2.4、Chunk 与检索契约未变。详见
[Query 前置 ADR](adr-task6-query-prerequisites.md)。

## 基线决策

- **模块化单体（Adopted）**：一个安装包与部署单元，模块以 Python Protocol + Pydantic 契约进程内协作。
- **Task 0 只建边界（Adopted）**：只交付 Schema、Protocol、骨架、文档和测试，不提供业务伪实现。
- **双视图 Document（Adopted）**：Page/Block 是物理视图，Section/Clause 是语义视图；跨引用由纯函数校验，不访问外部状态。
- **显式检索分数语义（Adopted）**：BM25、向量相似度与融合分数不默认直接相加。

## Task 0.2：Document V2.4 ADR-001～007

### ADR-001 稳定 ID 与身份作用域 — Adopted

`file_id` 是 FileStore 分配的持久身份，SHA-256 不是 ID；`document_id` 表示具体标准版次；`artifact_id + artifact_version` 表示一次不可变解析快照。Block、Section、Clause、Table、Formula 与 Evidence ID 在单个快照内唯一。正文与说明同号条文使用不同 ID。语义实体优先使用命名空间、规范编号和确定性来源锚点；Block 使用页面和稳定版面锚点。OCR 文本哈希不得充当稳定身份，跨快照引用必须带 Artifact 身份或禁止。

### ADR-002 部分解析 Artifact 与 Manifest — Adopted

一个快照由 `document.json + assets/ + manifest.json` 构成，历史版本不可就地覆盖。`ArtifactManifest` 静态校验身份、版本、UTC 时间、URI、media type、SHA-256、大小与 completed/partial/failed 状态；`DocumentArtifact` 校验 Manifest 与 Document 一致。真正打开 URI、核对字节和原子提交属于未来 FileStore。迁移只声明 `DocumentMigrationService.migrate_document(...)`，不得静默转换或猜测缺失数据。

### ADR-003 PDF 库与 Golden Dataset 边界 — Adopted

后续 Parser 第一版优先评估 PyMuPDF 读取 PDF 页面与图像；OCR、版面、表格和公式引擎通过私有适配器替换。Golden Dataset 应来自真实工程规范人工标注，记录来源、标准版次、标注规则与复核状态。本决策不把库名、模型路径或数据集字段写进公共 Document/Chunking 契约；Task 0.2 不新增运行依赖、不声称识别指标。

### ADR-004 raw_grid 与规范化表格视图共存 — Adopted

顶层 `tables[]` 是逻辑表格唯一权威来源。`raw_grid` 可空，表达原印刷拓扑、跨行/跨列、识别状态与片段来源；完整格网必须全覆盖，partial 格网允许缺口，但任何格子不得重叠或越界。`columns/data` 是检索用展开视图，`derived=true` 明示派生列，不能宣称可无损还原格网。表注使用表内顺序号，不冒充印刷编号。

### ADR-005 引用式 ContentUnit 与 plain_text 缓存 — Adopted

PageBlock 是正文/公式物理内容来源，LogicalTable 是完整表格来源，ArtifactRef 是媒体来源。ContentUnit 仅保存顺序及 Block/Table/Formula/Asset 引用，不复制正文、表格或公式对象。`plain_text` 是可空派生缓存；`plain_text_renderer_version` 和 `plain_text_source_digest` 必须同时存在，Document 校验会用纯函数重新展开并核对。来源或 renderer 改变即失效，不能手工把缓存当第二份原文。

### ADR-006 mandatory_evidence — Adopted

仅正文 Clause 使用 `mandatory_evidence`。`is_mandatory` 保持 true/false/null；确定状态至少需要一条结论一致、带位置、已核验的证据，无证据不能推断 false。verified 证据必须有审阅标识、UTC 时间以及文档页或外部 URI。冲突证据在 `is_mandatory=null` 时保留并由诊断函数报告；确定状态遇到冲突则拒绝。OCR 字词、粗体或模型判断不构成法律效力证据。

### ADR-007 延后精简 — Adopted

保留 `sections.structure_path`、`processing`、Asset 版本、`page_count`、`ocr.text` 与文档级 bbox 坐标。只删除 ContentUnit 中重复的权威正文/表格/公式副本。其他精简建议仍待后续独立 ADR，不在本任务实施。

## V2.4 状态与真实样本边界

Task 0.1 的 `2.4` 是未发布候选，当时没有发布标签或外部消费者证据，因此允许在相同目标版本定稿；其 ContentUnit 格式与 Task 0.1 候选不兼容，差异记录于 `schema-changelog.md`。`references/GB50010_2015_document.v2.4.partial.json` 保持只读：它是 `2.4-proposal`、含 441 页目录但只有少量人工区域，不会被正式模型静默接收，也不声明完整 OCR。

## V2.4 冻结决议

维护者于 2026-10-11 批准 Architecture Task 0.2 修复验收并授权正式冻结。ADR-001～ADR-007 均保持 **Adopted**，Document Schema V2.4 状态为 **FROZEN**；冻结证据与 Git 标识见 `schema-v2.4-freeze-record.md`。

冻结后不得在 `2.4` 下修改已验收的 Pydantic Schema、公共 Protocol 或数据验证语义。兼容的文档澄清与测试增强可以在不改变契约行为的前提下进行；任何破坏性字段、校验或接口变更必须升级 Schema 版本，新增 ADR，并提供显式迁移机制。ADR-003 所述 Parser 技术评估仍是后续独立任务，不因本次冻结自动开始。

## ADR-DP-001：V2.4 Figure 投射与私有元数据 — Adopted

Document Schema V2.4 没有公共 `figure_number`、`figure_caption` 或多子图字段，冻结期间不新增这些字段。Document Parser 将一个逻辑 Figure 投射为一个 `BlockType.IMAGE`：完整印刷图题保存于既有 `PageBlock.ocr.text`，图像或逻辑聚合物通过既有 `PageBlock.asset` 引用，图形 bbox 明确排除图题。结构化 `figure_number`、`figure_caption`、多图片段、图内文字和逐来源消费记录保存在 Parser 私有 sidecar。

多个子图仍只产生一个公共 Image Block。V2.4 单一 `asset` 槽位引用确定性的逻辑 Figure manifest，所有原始图片资产及其哈希继续保存在私有 sidecar；不引入公共 `subfigure` 模型。图题和已确认的图内标签被 Figure 消费后不得重复成为 Body、Formula 或 Clause 内容。未来如需公共的多资产 Figure 语义，必须升级 Schema 版本并提供显式迁移机制。

## ADR-CH-001：Clause-first Chunk V1 — Adopted

Chunking 只消费冻结的 Document V2.4 公共视图，不导入 Parser 私有实现。规范 Clause 是
普通文本的首要逻辑边界，页面不是边界；正文与条文说明严格隔离。`content_units` 是装配
权威来源，Section/Chapter 只进入 context header。Table 和 FormulaGroup 作为不可拆的
原子子 Chunk，纯图片不生成虚构描述；body/explanation_body 上未归属 Clause 的有效正文
保留为 paragraph Chunk。

Chunk V1 固定 `overlap_tokens=0`。只有超长 Clause 才依次按内容单元/自然段、句子、token
window 产生多个物理 Chunk；它们共享 `logical_chunk_id`，但拥有不同 `chunk_id`。
Table/Formula 超限不破坏结构，只设置 overflow 标志。ID 由 Document 身份、语义作用域、
来源身份、完整配置摘要和实现版本确定性派生；相同输入重复运行的顺序、身份和内容必须
一致。Chunking 无 I/O 副作用，不调用 OCR、Embedding、检索或 LLM。

## ADR-KR-001：Elasticsearch BM25 关键词检索 — Adopted

关键词检索以物理 `Chunk` 为 Elasticsearch 文档，`_id=chunk_id`，使用版本化严格 Mapping、
可配置 Analyzer 和原生 BM25 `_score`。完整文档替换遵循“先成功写新快照、后清理陈旧
Chunk”，部分 Bulk 失败不执行清理；增量写入由 `IndexRequest.replace_document=false`
显式请求。默认检索单一私有 `search_text`，元数据过滤不参与评分，同分按 `chunk_id` 稳定
排序。详细决策、契约限制和已知风险见
[Task 3 Elasticsearch ADR](adr-task3-elasticsearch-keyword-retrieval.md)。

# 架构决策记录

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

Task 0.1 的 `2.4` 是未发布候选；仓库没有提交历史或外部消费者证据。本次允许在相同目标版本定稿，但其 ContentUnit 格式与 Task 0.1 候选不兼容，差异记录于 `schema-changelog.md`。`references/GB50010_2015_document.v2.4.partial.json` 保持只读：它是 `2.4-proposal`、含 441 页目录但只有少量人工区域，不会被正式模型静默接收，也不声明完整 OCR。

## 尚待维护者确认

代码与自动化门槛通过后状态只能是 `READY_FOR_REVIEW`。维护者确认、冻结日期以及提交 SHA/标签仍需人工填写；确认前不得声明 **Document Schema V2.4 — Frozen**。

# Engineering RAG — Document V2.4 架构决策记录（Task 0.2）

> **状态：已由用户采纳的架构方向；仓库实施与 V2.4 冻结尚待 Codex 测试验收。** 本文件用于指导 Codex 修改公共模型，不能视为仓库已经通过测试。

## 边界与版本

- 体系：模块化单体；共享 Pydantic v2 DTO + Python Protocol，独立模块测试，不引入网络微服务。
- 文档契约：保留 Document 的 `pages[]`、`sections[]`、`tables[]`、`clauses.normative[]`、`clauses.explanations[]`、`processing` 和统一 `bbox_coordinate_system`。
- 保留此前已确认删除：`is_synthetic_example`、`printed_page_label`、`region_type`、PageBlock 的 `section_id`/`clause_id`、bbox 内反复声明的 `origin`/`coordinate_system`、公式 `line_index`、符号说明 `intro` 和单独 `unit`。
- PageType：13 种指定类型加 `unknown`；BlockType：`title`、`body`、`table`、`image`、`formula`。
- 此前的 `2.4-proposal` 并不是一个可当作生产版本的已冻结契约。如果仓库当前已有**发布且被外部消费者使用**的 `2.4`，出现不兼容变更时必须升级版本或提供迁移层，不允许偷换已发布版本；否则可完成后冻结为 `2.4`。

## ADR-001 稳定 ID 与身份作用域 — 已采纳

**决定**

1. `FileRef.file_id` 为文件管理模块持久化分配的身份，可附加独立的 SHA-256 用于内容一致性验证，但 SHA-256 不等于身份。
2. `document_id` 是同一标准具体版次的文档身份，由文档管理持久分配；不以标准代码唯一识别不同修订版。
3. 一次解析写出的快照使用独立的 `artifact_id`、`artifact_version`（或等价 manifest 身份）；相同 `document_id` 可以有多个解析快照。
4. `block_id`、`section_id`、`clause_id`、`table_id`、`formula_id` 在**单个文档快照**内唯一。`normative` 和 `explanation` 条文即使编号相同也必须有不同 ID。
5. Section/Clause/Table 等优先使用语义身份 + 文档内确定性消歧锚点；Block 优先使用来源页面+稳定版面锚点。无法可靠确定跨次解析位置时由持久映射分配。**不能用 OCR 文本哈希作为稳定 ID，也不能声称 Block 序号插入后仍跨解析版本稳定。**
6. `source_block_ids`、`explains_clause_id`、`table_id`、公式引用必须能在其**所属快照**里解析；跨快照引用必须含有快照/Artifact 身份或禁止使用。

**实现边界**：公共 Schema 只规定身份字段、作用域、引用校验和快照语义；具体 UUIDv5/持久映射和碰撞处理算法留到相应模块实现并测试，不进入公共 Schema 的技术限定。建议在 `docs/id-policy.md` 记录示意和跨版本非稳定边界。

## ADR-002 部分解析 Artifact 存储 — 已采纳

**决定**：一个不可覆盖的解析快照由 `document.json`（结构化内容）、`assets/`（图像/表格裁剪等资源）以及 `manifest.json`（版本、校验、状态、资源索引）构成。Manifest 至少描述：`artifact_id`、`document_id`、`artifact_version`、`schema_version`、`created_at`、`processing_status`、文档 JSON 的 URI/sha256、assets 的引用/校验和。

- 只有 Manifest 成功落盘后，快照才可视为完整提交；失败或中断不得产生冒充成功的完整状态。
- 不覆盖历史产物；新的解析结果写入新的快照标识。
- 已处理、未处理与部分处理须显式表示；`pages[].blocks=[]` **不能**直接解释为空白页。
- 文件格式与迁移机制：本阶段定义轻量 `ArtifactManifest` DTO、版本语义和迁移接口约定；**不实现磁盘存储后端、迁移执行器或文件管理服务**。
- 导入旧版 JSON 需显式调用有版本标识的迁移函数；不能静默当作新版读取或自动填造无法识别的内容。

## ADR-003 PDF 库与 Golden Dataset — 已采纳但不进入公共契约

后续 Document Parser 第一版优先评估 PyMuPDF 作为 PDF 页面与图像读取基础；OCR、版面分析、表格识别和公式识别保持可替换。以真实工程规范人工标注构建 Golden Dataset，记录文档来源、标准版次、人工审阅状态与评估规则。

**Task 0.2 不新增 PyMuPDF/OCR 运行依赖，不运行识别算法、不创建虚构 Golden Dataset，不把库名/算法名编码为 Document 的强制字段或公开 Protocol。**

## ADR-004 可选 raw_grid 与 columns/data 共存 — 已采纳

- 顶层 `tables[]` 为逻辑表格唯一权威来源；每个跨页 Table Block 是物理片段，由 `table_id`/`fragment_index` 关联。
- 表格规范化视图使用 `columns[]`（`key`、`header_path[]`、`role`、可选 `derived`）和 `data[]`（列键到数据值的记录映射）。横向和纵向表头均可展开。
- `raw_grid: RawTableGrid | None` 可选。非空时至少含 `row_count`、`column_count`、`cells[]`，单元格含 `row`、`col`、`row_span`、`col_span`、`text`、`is_header`，可选来源 `source_block_ids`。
- 格网从零开始索引，跨度为正，不能越界，重叠范围必须报错；**部分识别可以不覆盖全部格网**，但须通过提取状态说明。
- `raw_grid` 追溯原始单元格拓扑；`columns/data` 是检索友好的派生记录，不能宣称它本身能无损复原格网。
- 表格附注：`notes: null | [{"number": 1, "content": "..."}]`；不单独保存固定前缀“注：”。

## ADR-005 引用式 ContentUnit 与派生 plain_text — 已采纳

- `PageBlock` 是正文及公式等**物理内容**的权威来源；`LogicalTable` 是完整逻辑表格的权威来源；媒体放在 `AssetRef`。
- `ClauseContentUnit` 保存 `content_type`、顺序、`source_block_ids` 和适用的 `table_id` / `formula_id(s)` / `asset_id`，不再复制整份 `table`、`formula_group` 或同一来源的 `body.text`。
- `clause_content.plain_text` **保留**，仅作为由有序 ContentUnits 解析出来的**派生缓存**，并在契约文档定义生成/失效规则。Parser/Renderer 修改 Block 或 Table 后应重算缓存；不得独立人工编辑该字段作为另一个事实来源。
- 清晰区分逻辑顺序与 PDF Block 的阅读顺序；可暂保留 `content_units.order`，因为此前是否删该字段仍属历史待定问题，不顺带变更。
- 下游 Chunking 直接解析引用，不能为填充 `plain_text` 重新做 OCR 或识别跨页表格。
- 如果既有字段 `source_block_ids` 与 `content_units` 顺序重复，可保留作为索引缓存，但必须校验一致性。

## ADR-006 强制性条文证据 mandatory_evidence — 已采纳

- 适用于正文 Clause；`is_mandatory: bool | None` 必须保持三态。
- `mandatory_evidence: list[MandatoryEvidence]`（或可空字段，但文档定义一致）用于记录可靠判定证据。
- 建议字段：`evidence_id`、`source_type`（官方发布公告 / 官方修订公告 / 标准正式发布文本 / 经审查的人工核验记录等**明确枚举**）、`source_document_id`（可选）、`source_page`（可选）、`external_uri`（可选）、`reference_text`（可选）、`verification_status`（待核验/已核验/否决）、`verified_by`（可选）、`verified_at`（可选）、`conclusion`（明确 true/false/unknown）。
- 非未知状态必须有**已核验且结论一致**的可靠证据；没有证据不能推断 `false`。`is_mandatory=true` 与证据仅给 `false` 或未经核验属于非法状态；出现相互矛盾的已核验证据，必须记录冲突并禁止自动得出确定结论。
- 仅靠 `应`、`必须`、粗体或大模型猜测不能设置法定强制性。
- 外部真实规范效力受适用版本和法规变化影响，证据状态不代表助手已经做过法律核验。

## ADR-007 延期精简与字段管理 — 已采纳

- `sections[].structure_path` 保留。
- `processing` 保留，支持 parser 元数据、warnings、partial、版本/状态。
- 既有 Asset 版本信息当前保持兼容；是否进一步简化后续单独评估。
- 不借 Task 0.2 顺便删除 `page_count`、`ocr.text` 或其他字段。仅为实施 ADR-005 删除 **重复的业务正文/表格/公式内容副本**。

## 需要满足的真实文档边界案例

1. 《混凝土结构设计规范》（GB 50010—2010，2015 年版）存在跨页续表：Table Block 是页内物理片段，顶层 LogicalTable 是逻辑单元。
2. 规范中存在一个条文连续多个编号公式和符号说明；`formula_id` 必须有，原印刷 `equation_number` 可以为 null，但与 OCR 没识别出来的状态区分。
3. PDF 扫描件可没有文本层；部分解析页面 `blocks=[]` 不是空白页。
4. 正文与条文说明条款可以同编号而 ID 必须不同；说明条款可以链接正文条文。

## 冻结条件（不是当前状态）

- 完整模型与独立测试已合入仓库；合成完整/部分 JSON 能用实际 Pydantic Schema 序列化和反序列化。
- 所有 ID、Page/Block、Table/RawGrid、Formula、Clause、MandatoryEvidence、Manifest 的正反契约测试通过。
- Parser 和 Chunking 的 Protocol 与接口文档同步，无重复公共模型和非法跨模块依赖。
- 版本变更/迁移约定、文档示例、变更清单以及所有 ADR 一并提交。
- `python -m pytest -q` 与仓库既定格式/类型检查实际通过，不得把 skipped 集成测试宣称为运行通过。
- 经维护者验收后将版本标为 **Document V2.4 — Frozen**，之后仅做向后兼容修复；不兼容变更升版并写迁移说明。

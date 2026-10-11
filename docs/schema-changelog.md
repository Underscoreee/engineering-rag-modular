# Document Schema 变更记录

## Task 0.1 候选 → Task 0.2 V2.4 冻结候选

Task 0.1 尚无发布、提交标签或外部消费者证据，因此本次在目标版本 `2.4` 内完成定稿。以下变更对 Task 0.1 候选 JSON 不兼容，旧文件必须显式迁移：

### 新增

- `ArtifactManifest`、`DocumentArtifact`、Artifact processing 状态及迁移 Protocol；
- `LogicalTable.raw_grid`、`RawTableGrid/RawTableCell` 与格网识别状态；
- `ClauseContentUnit.formula_ids/list_item_label`；
- `ClauseContent.plain_text_renderer_version/plain_text_source_digest`；
- `Clause.mandatory_evidence` 及来源/核验枚举；
- ArtifactRef 的可选 `sha256/size_bytes`；
- 快照内 Evidence、FormulaGroup、Asset 与所有已有实体的完整交叉校验。

### 删除或替换

- 删除 ContentUnit 的 `text` 与 `formula_group` 权威副本；table 继续只用 `table_id`；
- formula unit 通过 `formula_ids + source_block_ids` 引用公式 Block；
- 非空 `plain_text` 从自由文本改为带 renderer 版本和来源摘要、可重算并校验的缓存。

### 保留

- Document `schema_version="2.4"`、13+unknown PageType、5 种 BlockType、统一 bbox；
- 顶层 `tables[]`、`columns/data/notes`、公式编号三态、正文/说明分组；
- `sections.structure_path`、`processing`、Asset 版本、`page_count`、`ocr.text`；
- Task 0.1 已确认删除的字段继续被 strict validation 拒绝。

## 显式迁移要求

迁移器必须解析旧 ContentUnit 引用并删除重复副本，核对其与 PageBlock/LogicalTable 是否一致；为公式建立真实 `formula_ids`；重算或清空 plain_text 缓存；只有已核验来源才可填 mandatory evidence；raw_grid 不可用时写 null。`2.4-proposal` 还需逐项核对 FileRef、状态枚举和悬空说明链接。当前仓库只定义迁移接口，未实现上述算法。

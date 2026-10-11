# Document Schema 变更记录（V2.4 FROZEN）

## V2.4 正式冻结 — 2026-10-11

维护者已批准 Architecture Task 0.2 修复验收，自动化门槛全部通过，Document Schema V2.4 从 `READY_FOR_REVIEW` 升级为 `FROZEN`。本次冻结登记不修改 Pydantic Schema、公共 Protocol 或数据验证逻辑；正式记录见 `schema-v2.4-freeze-record.md`，权威验收结果见 `schema-freeze-checklist.md`。

V2.4 冻结后，兼容性澄清和不改变契约行为的测试增强可继续进行；任何破坏性字段、校验或接口变更必须使用新的 Schema 版本、记录 ADR，并提供显式迁移机制。

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

## 冻结评审修复

- Clause 来源页增加正文 `body` / 说明 `explanation_body` 分区约束；
- complete 页面拒绝未处理 Block/表格片段/公式，明确允许已识别但待审核的 `unverified`；
- plain_text renderer 升至 v2，并渲染公式符号说明；
- Manifest 与 Document 对齐 parser version，并核对双方已声明的 Asset 摘要和大小；
- 带编号 Section 的 structure_path 末级必须与 number 一致；
- 明确嵌套原地修改后的 Artifact 在提交前必须重新完整验证。

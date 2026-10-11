# 公共数据契约：Document V2.4

`engineering_rag.contracts` 是唯一公共模型来源。Pydantic v2 使用 `extra='forbid'`；`Document.schema_version` 必填且只接受 `"2.4"`。Task 0.1 未改版的 Chunk、检索等持久化对象仍为 `1.0`。JSON 以 `model_validate_json()` / `model_dump_json()` 读写。`examples/` 中的规范文字全部为虚构演示。

## 字段与空值

| 模型 | 必填 | 可空或默认 | 语义 |
|---|---|---|---|
| `Document` | `schema_version`, `document_id`, `bbox_coordinate_system`, `source_file`, `standard`, `page_count`, `processing` | `pages=[]`, `sections=[]`, `tables=[]`, `clauses` 两组默认空 | 具体解析对象；`page_count` 是 PDF 页数，partial 时 `pages` 可少于它 |
| `StandardMetadata` | `standard_name`, `standard_code` | `edition`, `revision`, `language` 可空 | 标准代码、版次和文档 ID 各有独立含义 |
| `Page` | `page_number`, `page_type`, `width`, `height`, `content_extraction_status` | `blocks=[]`, `page_type_basis=null` | 物理页，1-based，尺寸为正数 |
| `PageBlock` | `block_id`, `block_type`, `bbox`, `reading_order` | `ocr`, `asset` 和表格/公式关联字段可空；`recognition_status=verified`, `bbox_status=detected` | 本页物理片段，未识别内容以状态和资源保留 |
| `LogicalTable` | `table_id`, `page_start`, `page_end`, `source_block_ids`, `fragments`, `extraction_status` | `columns=[]`, `data=null`, `notes=null`，编号和标题可空 | 单页或跨页的唯一逻辑表 |
| `Section` | `section_id`, `title`, `section_type`, `content_group`, `structure_path` | `number`, `parent_section_id` 可空 | 正文/说明分组内的章、节、附录 |
| `Clause` | `clause_id`, `clause_number`, `section_id`, `clause_content`, `page_start`, `page_end`, `source_block_ids` | `is_mandatory=null`, `explains_clause_id=null` | 可跨页的单个条文 |
| `ClauseContent` | 无 | `plain_text=null`, `content_units=[]`, `transcription_status=verified`, `review_warning=null` | 有序逻辑内容，保留 `plain_text` |
| `ProcessingMetadata` | `parser_id`, `parser_version`, `partial`, `is_complete_document_ocr` | `warnings=[]` | 处理范围和待核验问题 |

ID 非空。Document 构造时调用纯函数 `validate_document_references()` 校验 ID、页码、bbox、Section 环、Table fragment、Formula 和 Clause 引用。bbox 只含四个坐标，统一按文档级 `{"unit":"pdf_points","origin":"top_left"}` 解释；超出页面尺寸会被拒绝。`bbox_status=manual_approximate` 表示人工估计，不能用于精确高亮。

`PageType` 恰有 13 个指定类型及 `unknown`；`BlockType` 恰有 `title/body/table/image/formula`。V2.4 禁用 `printed_page_label`、`primary_page_type`、`region_type`、Block 的 `clause_id/section_id`、Standard 的 `is_synthetic_example`。Section 的 `structure_path` 暂保留。

## 表格：物理片段与逻辑结构

每个 `pages[].blocks[]` 的 table Block 表示本页一个片段，持有 `table_id`。完整的单页/跨页表只在顶层 `tables[]` 保存。`fragments` 从 0 连续编号，顺序和 `source_block_ids` 一致；页码、Block 类型与 `table_id` 均交叉验证。只有 partial Document 中明确为 `not_processed` 或 `not_transcribed` 的待聚合片段，才可暂时没有顶层 Table；此时不能虚构完整 `data`。

`columns[].key` 唯一；`header_path` 非空，`role` 为 `row_header/column_header/dimension/value`。`derived=true` 说明此列由合并单元格展开。`data[]` 是扁平记录，业务键必须恰好对应所有 column key，值只能是原文字符串或 `null`；额外仅允许 `source_page`（本表页范围内整数）和 `source_block_id`（本表片段 ID）两个来源键。`notes` 只能是 `null` 或非空的编号注解数组，序号正整数且表内唯一。`columns/data` 是查询用规范化视图，不能无损复原合并单元格；`raw_grid` 仍待决定。

## 公式、Clause 与来源

一个 formula Block 使用 `formula_group_id` 与 `ocr.formula_group` 保存有序 Equation 和可空的 `symbol_explanations`。每条 Equation 必须有全文唯一的 `formula_id`。编号分三态：`printed` 要求非空 `equation_number`；`confirmed_absent` 要求编号 `null` 且公式已核验；`unknown` 表示编号尚未确认，此时编号也用 `null` 占位，但绝不宣称原文无号。已核验公式需要非空 `latex`；未转录/待核验可为 `null`。多行 LaTeX 通过 JSON 字符串原样往返。不使用独立 `unit`、`intro`、`line_index`。

`clauses.normative[]` 与 `clauses.explanations[]` 分别保存正文与说明。相同条文号可复用，`clause_id` 必须全文唯一；说明的 `explains_clause_id` 只能指向已声明正文 Clause 或为 `null`。Section 的 `content_group` 与 Clause 分组一致。Clause 和 unit 的 `source_block_ids` 必须存在、处于 Clause 页码范围内；table unit 的来源须覆盖该 Table 全部片段，且只引用 `table_id`，不复制整表。`list_item` 是逻辑单元，只能来自 body Block。`is_mandatory=null` 表示未判定，不据措辞或字体推断效力。

## 部分解析、兼容与真实参考样本

`not_processed` 页的 `blocks=[]` 表示未处理，**不表示空白**；`partially_transcribed` 表示仅部分内容转录；`complete` 才表示本页已完整提取。`processing.partial=true` 允许页面清单不全、尚无语义条文，但已声明引用仍不可悬空。坐标、表格、公式可分别标记人工估计、未转录与待核验。`partial=false` 要求页清单齐全、每页 complete、`is_complete_document_ocr=true`。

V2.3、Task 0 与 V2.4 不兼容，旧 JSON 不自动升级；`2.4-proposal` 也不静默接受。真实参考样本的明确迁移清单见 [architecture-decisions.md](architecture-decisions.md)。

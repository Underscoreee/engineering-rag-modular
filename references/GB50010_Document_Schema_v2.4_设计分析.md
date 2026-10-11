# GB 50010—2010（2015 年版）真实扫描 PDF 与 Document Schema V2.4 设计分析

## 0. 结论及准确性范围

实际检查的上传 PDF 共 **441 页**，没有可提取的文本层；直接按扫描图像人工审阅了封面、目录、正文、表格/公式代表页、条文说明封面及正文、末页。`GB50010_2015_document.v2.4.partial.json` 是**真实 PDF 的页面级清单 + 有限人工核实样本**，不是 441 页已完成 OCR 的全文结构化结果。

- `pages` 记录真实的 441 个 PDF 物理页面及尺寸；对于未逐页检查的页面类型使用 `sequence_inference_from_checked_boundaries`，并非逐页模型分类结果。
- 全文扫描 PDF 的正文不能使用 `page.get_text()` 提取；无 `blocks` 的页面标记 `content_extraction_status = not_processed`，绝不表示原页面空白。
- 仅若干代表性区域由图像人工核实，包含 3 个真实跨页表格、两组真实公式、多个真实条文及条文说明案例。部分表格内容未转录，不冒充已识别。
- 代码示例中 `bbox_status = manual_approximate` 表示坐标仅是人工目视估算，不能当作可用于精确高亮的 OCR/版面检测框。
- 文本和数据均来自上传 PDF 的选定页面；任何未能确信的文字不应作为准确规范条文发布。人工转录例子不代表完整且可供工程设计直接使用的规范数字化版本。

## 1. PDF 实际结构：物理页码（从 1 开始）

| PDF 页码 | 页面类型 | 视觉证据 | 备注 |
|---|---|---|---|
| 1 | outer_cover | 标准号、书名、发布与实施日期 | 外封面 |
| 2 | inner_cover | 主编部门、批准部门、出版信息 | 内封面 |
| 3 | publication_notice | 2015 年修改内容公告 | 实际文档存在多次公告 |
| 4 | revision_notes | “修订说明” | 出现在文档前部 |
| 5 | publication_notice | 发布国家标准公告 | 与第 3 页分开 |
| 6–8 | preface | 前言与编制人员名单 | 数页连续 |
| 9–11 | toc_zh | 目次 | 中文目录 |
| 12–15 | toc_en | Contents | 英文目录 |
| 16–274 | body | 第 1–11 章和附录 A–K | “正文”类型包括附录；未来可增加章节子类型，不改 page_type |
| 275 | wording_rules | 本规范用词说明 | 原文标题确认 |
| 276 | normative_references | 引用标准名录 | 原文标题确认 |
| 277 | explanation_cover | 条文说明封面 | 新的内容大区段 |
| 278 | revision_notes | 修订说明 | 条文说明前的独立页面 |
| 279–281 | explanation_toc | 条文说明目次 | 单独于正文目录 |
| 282–441 | explanation_body | 条文说明正文，直至 PDF 末页 | 包含同号条文和无印刷编号的公式 |

请注意：**范围内非关键抽查页面的 page_type 是根据已经核对的区段边界推断**，不是自动识别得到的逐页标注。日后 OCR 完整运行后，应将每页状态升级为经识别/复核。

## 2. 为什么 V2.3 不足以表达这份真实规范

### A. 跨页表格不是两个独立 Table

- PDF 第 **28–29** 页，`表3.5.2 混凝土结构的环境类别`，下一页以“续表 3.5.2”开始，表注在续表下方。
- PDF 第 **37–38** 页，`表4.2.2-2 预应力筋强度标准值`，续页有交叉/合并单元格。
- PDF 第 **126–127** 页，`表9.1.2 现浇钢筋混凝土板的最小厚度（mm）`，前 4 行在第 126 页，余下 7 行在第 127 页。第 127 页紧接着开始 `9.1.3`。

旧设计将 `blocks` 限定在一个 `page` 下，同时又要求“一整张表格是一个 Block”。这两项对于跨页表格无法同时成立。**V2.4 建议：一个页面 Table Block 对应表格的一个物理片段；新增顶层 `tables[]` 保存一张完整逻辑表格**。每个片段通过 `table_id` 关联，表注归属于逻辑表格而不是下一条条文。单页表格仍可以只用一个 Block。

实际提取样本 `table-9.1.2` 使用：

```json
{
  "table_id": "table-9.1.2",
  "table_number": "表9.1.2",
  "title": "现浇钢筋混凝土板的最小厚度（mm）",
  "page_start": 126,
  "page_end": 127,
  "source_block_ids": ["p126_t912_p1", "p127_t912_p2"],
  "columns": [
    {"key": "slab_type", "header_path": ["板的类别"], "role": "row_header"},
    {"key": "subtype", "header_path": ["板的类别"], "role": "row_header", "derived": true},
    {"key": "min_thickness_mm", "header_path": ["最小厚度"], "role": "value"}
  ],
  "data": ["参见 JSON 文件里的 11 条真实展开记录"],
  "notes": null
}
```

上述仅为结构展示，**数据以实际 JSON 文件为准**。本示例有一条悬臂板条件在扫描图中关系符号看不清，已在结构中警告；不能把不确定数据当成审核后的标准要求。

### B. `columns/data` 仍不能无损重建复杂多级表头

真实表格中同时出现纵向跨行“板的类别”、横向多级表头及合并单元格。`columns` 与 `data` 很适合查询，但**它们是“展开后的记录视图”，不是原表格版面原样**。

建议保留当前 `columns`、`data` 作为主要的检索友好结构，新增**可选** `raw_grid`：

- `raw_grid.cells[]`: `row`, `col`, `row_span`, `col_span`, `text`, `is_header`。
- `header_path`: 多级表头的完整来源路径。
- `derived`: 表示规范化新增的辅助列，不得伪装为印刷表头。
- `data` 中数值保留原文字符串与必要的破折号/空白/未知状态，不强行把“—”或含不等号内容转浮点。
- 表格附注仍保留你确定的格式：`notes: null | [{"number": 1, "content": "..."}]`。

### C. 公式编号并非总存在（必须修正上一版约束）

- PDF 第 **24 页**，条文 `3.3.2` 含 `(3.3.2-1)` 和 `(3.3.2-2)` 两个编号公式，并附“式中”解释，后续可能跨页。
- PDF 第 **50 页**，条文 `6.2.1` 含连续公式 `(6.2.1-1)` 至 `(6.2.1-5)`，后接符号解释，又出现 `(6.2.1-6)` 和 `(6.2.1-7)` 的另一组。
- **PDF 第 301 页**，条文说明 `4.1.5` 内可见公式 `E_c = 10^5/(2.2 + 34.7/f_{cu,k})`，但旁边**没有印刷公式编号**。

因此：

```json
{
  "formula_id": "f-explanation-4.1.5-unnumbered-1",
  "equation_number": null,
  "latex": "E_c=\\frac{10^5}{2.2+\\frac{34.7}{f_{cu,k}}}"
}
```

**建议 `formula_id` 永远必填，`equation_number` 允许 `null`。** 不要为了强行符合 Schema，给无号公式生成不存在的印刷编号。

同时保留原规定：公式可多行、多式共属一个 Formula Group；`symbol_explanations.items[]` 只保留 `symbol/latex/description`，不强制单独记录单位，不记录 `intro` 或 `line_index`。若原文说明含单位，可保留在原始文字，不得凭空删除。

### D. 一个 Clause 可以包含正文、1/2/1) 小项、表格、公式和图片

PDF 第 **126–127 页**说明 `9.1.2` 的条文内容包括 numbered subitems（1、2）和一张跨页表，而下一条 `9.1.3` 从续表之后紧接开始。PDF 第 **24 页**的 `3.3.2` 同时包含文字、两个公式及符号解释。

因此 `Clause` 必须有有序 `content_units[]`，允许 `body` / `table` / `formula` / `image` / `list_item`；`source_block_ids` 允许跨页，不允许按每页强制切成独立条文。`clauses.normative` 与 `clauses.explanations` 继续分开，两个分组可有相同 `clause_number`，但 `clause_id` 不得混同。

### E. 强制性条文判定应有可验证依据

PDF 第 3、5 页公告说明修订及强制性条文；正文的某些条文使用醒目字形。**仅凭粗体或条文用了“应”不能安全判断强制性。** 保留 `is_mandatory: boolean | null`，建议可选字段 `mandatory_evidence` 来自公告条目、修订清单或人工复核记录。未确认的示例均为 `null`。

### F. 页面与语义结构的实体关系

- `pages[].blocks[]`：真实物理页面范围、OCR/视觉结构、位置和原始识别内容。
- `tables[]`：跨页汇总后的**唯一逻辑表格内容**。避免“续表”误成新的表格；在 `page.blocks` 中保存物理片段。
- `sections[]`：分别建立正文与条文说明的章/节层级。
- `clauses.normative[]`、`clauses.explanations[]`：条文内容，引用来源 Block/逻辑表格，保留原定 `clause_content.plain_text` 和 `content_units`。
- Formula Group 在当前示例中位于公式 Block，标注 `formula_group_id`；若一个 Formula Group 真正跨页，可使用同理的逻辑聚合对象，但 V2.4 先不强制新增顶层 `formula_groups`。

## 3. 版本升级建议与“保留前述决定”

**继续保留 V2.3 已确定的字段决策**：删除 `is_synthetic_example`、`printed_page_label`、`region_type`、Block 的 `clause_id/section_id`、公式 `line_index` 与符号说明 `intro`，bbox 仍统一由文档顶层定义坐标约定；`page_type` 仍支持 13 类加 `unknown`；表格主数据仍是 `columns/data`；表注仍是 `number/content`、可为 null；符号解释仍不另存 `unit`。

建议为 V2.4 引入最少的新结构：

| 字段/实体 | 必要性 | 原因 |
|---|---|---|
| `pages[].content_extraction_status` | 必要 | 区分“未处理”和“已检测为空白”的页面 |
| `pages[].page_type_basis` | 建议 | 区分视觉核对与根据文档段落范围推断的分类 |
| `tables[]` | 必要 | 逻辑表格跨页、续表数据合并、表注统一挂载 |
| `blocks[].table_id`, `fragment_index` | 必要（跨页表） | 页面表格片段聚合索引 |
| `tables[].raw_grid` | 可选 | 无损表达复杂合并单元格，可后续增加 |
| `equations[].formula_id` | 必要 | 无编号公式也必须有稳定身份 |
| `equations[].equation_number` | 可空 | PDF 的条文说明里存在无印刷编号公式 |
| `processing.partial` + 质量标志 | 必要 | 无文本层扫描 PDF 不得伪装为已完成 OCR |
| `clauses[].mandatory_evidence` | 可选 | 让强制性判断能够回溯公告证据 |
| `bbox_status` | 仅用于人工标注/质量追踪 | 本次 bbox 是估算，不代表精确 OCR 框 |

`content_units` 的完整表格/公式内容是否只引用、不重复存储，仍可留到下一次决策。本次示例采用表格 `table_id` 复用逻辑表格，以便跨页；不强制改变现有其他 ContentUnit 的字段。

## 4. 对后续 Document Parser 模块的接口要求

1. 输入扫描 PDF 的文件引用；输出有版本的 `Document`，显式描述是否完全处理。
2. 页面分类必须具备 `unknown` 回退，章节正文、条文说明正文分开。
3. 可先提取物理页面的 Text/Table/Formula/Image Block，再聚合逻辑章节与条文。
4. 表格先提取页内片段，再进行跨页续表关联；结构保留 caption、列路径、数据、注解，必要时保留 `raw_grid`。
5. 公式可多行组合，逐一赋予稳定 `formula_id`；原始编号可能为空；符号说明属于适当的公式组。
6. 条文作为独立语义单元，正文和说明条文即使编号相同也拥有不同的唯一 ID。
7. 输出含 OCR 置信度、待复核段落或显式警告（不确定值不自行纠正）。
8. 必须独立测试：表 9.1.2 跨页，9.1.2→9.1.3 条文边界，6.2.1 多编号公式，条文说明 4.1.5 无编号公式，正文/说明 1.0.1 同编号隔离。
9. 当前演示的数据不能代替生产 OCR 成果，更不能用于真实施工设计。

## 5. 附带文件

- `GB50010_2015_document.v2.4.partial.json`：441 页真实页面清单、19 页人工转录片段、3 个真实逻辑表格（仅 1 个部分经过数值转录）和 7 个代表性条文；全部未完成的内容显式标记。
- `GB50010_2015_document_validation.json`：页数、标注量和引用完整性检查结果。

**下一步最应讨论并确认的两项不兼容变更**：① 引入顶层 `tables[]` 作为跨页逻辑表格；② `equation_number` 改为可空，新增必填 `formula_id`。确认之后再交给 Codex 更新 Pydantic Schema 和接口测试。

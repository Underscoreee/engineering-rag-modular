# Task 1.3：MinerU → Document V2.4 表格映射与数据保真设计

> 本文基于项目当前可见 `src/engineering_rag/contracts/documents.py` 的 V2.4 冻结版本（例如 Task 1.1 源码），最终以 Codex 当下仓库的冻结代码为权威。不能凭本指南修改 `contracts/`。

## 1. 两层对象与原始来源

```text
MinerU raw MiddleJson / table HTML / 题注+脚注 / 页面图片（保留原样）
   ↓  page_idx → 原 PDF 物理页映射；bbox → pdf_points/top_left
PageFragmentCandidate  (Parser 私有，带 raw_path 和诊断)
   ↓ 可信的 HTML cell → local grid；caption/footnote 绑定
TableFragmentCandidate (Parser 私有，保留原始每页列结构)
   ↓ 续表证据合并（不确定则保持分开）
LogicalTableCandidate (Parser 私有，重复页表头保留 provenance)
   ↓ 构建 frozen DTO 并 `Document.model_validate`
PageBlock (per page, block_type=table) + Document.tables[] LogicalTable
```

注意：MinerU 4.x `schema="docvortex.middle"`、`schema_version="2.0"` 是第三方协议，**不是** Engineering RAG 文档版本；`structured_content` 没有 MiddleJson 的 schema identity。原始内容保留 sidecar，不将第三方字段塞入冻结 `OcrContent`。

## 2. 映射速查表

| MinerU 实际已观察证据 | 目标 V2.4 字段 | 约束与失败策略 |
|---|---|---|
| 物理 PDF 页映射 | Page.page_number、TableFragment.page_number | 原始 1-based，不能仅按裁切 PDF 的局部 page_idx+1 |
| 检测到的表格 bbox | PageBlock.bbox | points/top_left、旋转/裁剪一致；无可信坐标则暂不造 Block |
| 物理 fragment | PageBlock.table_id / fragment_index / fragment_status | TableBlock 与 LogicalTable 双向引用，index 从 0 连续 |
| 表号、表题 | LogicalTable.table_number / title | 未看到则 null；禁止 OCR 猜测 |
| 同一表来源 | LogicalTable.source_block_ids / fragments / page_start/end | 强一致，跨页仅在匹配证据充分时合并 |
| HTML tr/td/th + rowspan/colspan | LogicalTable.raw_grid.cells | 带 row、col、span、header、status、source_block_ids；原 HTML 保存在 sidecar |
| 多行横向表头 | TableColumn.header_path | 合并表头沿列路径继承一次，不重复 span 覆盖 |
| 纵向行头/尺寸维度 | TableColumn.role | 有证据用 row_header / dimension；否则避免错误语义标注 |
| 可保真展开后的数据行 | LogicalTable.data[] | 业务列只存原文 string/null；`source_page` int, `source_block_id` str |
| 有编号表注 | LogicalTable.notes | 编号必须真实存在；无编号备注仅保留 raw、记录未能结构化原因 |
| 结构识别状态 | raw_grid.extraction_status + table.extraction_status | 分别表示格网覆盖与表格核验状态；未人工核实一般 unverified |
| 匹配/变换疑点 | normalization_warning + sidecar diagnostics | 不足以保证格网、表头、表注时诚实记录，不捏造 |

## 3. 跨页模型细节

- 原始 fragment 的 `html`、单元格位置、重复的 `thead`、表注图像都在 sidecar 保留；可持久化的全局 `raw_grid` 只有**一个**，无法承载单元格级来源 bbox，所以 sidecar 不可删除。
- 全局 `raw_grid` 的 `row_count/column_count` 只有在列拓扑相容、全局不重叠行号可建立时生成；`complete` 指每个格位占满，并**非**真实值已被人工复核。
- 可将续页重复表头保留为 raw_grid 的真实打印行，同时仅生成一次 canonical `columns`；`data` 排除这些重复行，不能误将它们计入规范数值。
- 如无法合并 rowspan/colspan 全局网格，可保留 `raw_grid=null` 和原始两个局部 grid（sidecar），并在有来源保证时仍组织 `columns/data`；否则 `data=null`、`structure_only`。
- 对垂直 merged data cell，推荐扁平展开时起始行保存字符串，覆盖行 `null`；保留原始 row_span 和人工说明，避免把共享条件错误复制到子行。
- 非数字文本：`1.0`、`0.05`、`—`、`不小于`、`≤`、`MPa` 等**不进行数值强转**。
- `raw_grid` 的 `text` 对 OCR 候选默认 `recognition_status=unverified`，有可信文本缺失时 `null` + `not_transcribed`（仅在实际语义支持时）；一张格网 complete 不等于其内容 verified。
- 需明确跨页匹配候选与合并决定：evidence、blocking reason、confidence（内部分数不能冒充客观准确率）、人工覆核状态、规则版本。自动合并是保守判定，拿不准则不要合并。

## 4. 可检验的双向约束

对于跨页表 T，必须满足：

```text
T.fragments[i].fragment_index == i
T.fragments[i].block_id == T.source_block_ids[i]
Page(T.fragments[i].page_number).blocks[block_id].table_id == T.table_id
Page(...).blocks[block_id].fragment_index == i
T.page_start == T.fragments[0].page_number
T.page_end == T.fragments[-1].page_number
forall cell in T.raw_grid.cells:
    set(cell.source_block_ids) ⊆ set(T.source_block_ids)
forall record in T.data:
    record.source_page ∈ [T.page_start, T.page_end] (if present)
    record.source_block_id ∈ T.source_block_ids (if present)
```

部分未处理页不要注入假的 PageBlock；如果构造的 DTO 无法满足以上约束，返回诊断而不是修改冻结模型。

## 5. 三态/缺失规则

| 场景 | 正确表达 |
|---|---|
| 已检测 table bbox，但无 HTML / 无表格格网 | 表格片段 + `LogicalTable` `structure_only, data=null, raw_grid=null`（若所有必填来源字段可满足） |
| 能解析格网但没确认语义列 | 可填 `raw_grid`，`columns=[]`、`data=null`、table `structure_only` |
| 能可靠展开、尚未经人工核验 | table `unverified`，`columns/data` 及可选 raw_grid |
| 格网覆盖齐全但 OCR 字符待复核 | raw_grid `complete` + cell `unverified`，不意味着 verified |
| 无编号“注：” | notes=null；原始文本+位置保存在 sidecar，记录映射缺口 |
| 跨页证据不足 | 保留为 2 张独立表/人工待审，不把并列表合并 |
| 缺页源映射或 bbox 无法验证 | raw sidecar 保留，V2.4 片段转换 blocked；不得伪造引用 |

## 6. 不在 Task 1.3 中实现的工作

- Clause/Section 和强制性条文证据；
- 公式 LaTeX 的语义纠错和符号说明归并；
- Chunking、向量检索、生成回答；
- 改动 V2.4/添加 raw cell bbox 字段；
- 引擎选型、PaddleOCR 部署与性能对比。

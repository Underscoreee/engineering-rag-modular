# Architecture Task 0.1：Document Schema V2.4 定稿与接口同步

> **交给 Codex 的完整执行 Prompt。** 这是全新模块化单体 Engineering RAG 项目，不依赖也不迁移旧 Task 1～5 的代码。本任务聚焦数据契约，不实现业务算法。

## 0. 角色、输入材料、优先级

你是负责 Python 架构和数据契约的工程师。请在当前已经完成 Architecture Task 0 的仓库中完成 Task 0.1。如果 Task 0 尚未完成，先确认缺口并只补足完成本任务所必需的框架，严禁顺带实现业务算法。

**首先阅读**项目根目录 `AGENTS.md`、`pyproject.toml`、现有 `src/engineering_rag/contracts/`、`modules/document_parser/INTERFACE.md`、`modules/chunking/INTERFACE.md`、`docs/data-contracts.md`、`examples/` 和所有契约测试。运行并记录 `python -m pytest -q` 的基线。

此任务的权威材料按优先级如下：

1. 本 Prompt 中 **「已经确认的产品决策」**。
2. `AGENTS.md` 中的模块化架构、测试和代码风格规则。若有冲突，先报告冲突，给出最小修订建议，不要默默忽略。
3. 用户提供的 `document.example.v2.3.json`、`GB50010_2015_document.v2.4.partial.json` 和 `GB50010_Document_Schema_v2.4_设计分析.md`，若这些文件已放在工程中则读取；若未放入，不得假装读取过，也不要以未提供的真实资料制造“已经识别”的示例。
4. 已有 Task 0 的项目实际代码。只在此前提下修改 Schema 和接口，**不大规模重构无关模块**。

特别注意：`GB50010_2015_document.v2.4.partial.json` 是 **441 页真实 PDF 的页面目录与有限人工核对样本，不是全本 OCR 完成的 Document**。里面未处理页面的 `blocks=[]` 不是空白页面；人工估计 bbox 不能当成可靠精确坐标。

## 1. 目标、范围和交付物

**目标：** 将 Document Schema V2.4 变成跨 `document_parser → chunking` 的正式 Pydantic v2 契约；完成公开 Python Protocol、接口文档、有效示例和契约测试，做到独立验证。

本任务必须交付：

- `src/engineering_rag/contracts/` 中权威的 Document V2.4 数据模型、Enum、验证器。
- Document Parser 的 `parse(request: ParseRequest) -> Document` 公开接口契约。
- Chunking 的 `chunk(document: Document, config: ChunkingConfig) -> ChunkBatch` 公开接口契约。
- `document.example.json`：**合成、完整、符合 V2.4 的测试示例**。
- `document.partial.example.json`：**不完整解析示例**（若用户提供真实 partial，可另提供来源标记明确的只读真实性测试用例），绝不能冒充完整识别。
- 对表格、公式、条文、引用、页面类型、状态枚举、JSON 读写进行的契约测试。
- 更新 `docs/data-contracts.md`、`modules/document_parser/INTERFACE.md`、`modules/chunking/INTERFACE.md`、相关 README、架构决策记录；仅将 `AGENTS.md` 中已过时的「当前阶段 Task 0」修改为「Task 0.1」，不得放宽任何长期规则。
- 真实运行的 pytest、Ruff（如已配置）输出摘要。

**不交付：** PDF OCR、图像识别、章节推断算法、表格识别与合并算法、公式识别、Chunk 切分、检索/向量库/LLM、HTTP 服务、生产数据库、真正微服务部署。

## 2. 已经确认的设计决策：不得重新争论或隐式修改

### 2.1 顶层 Document

需要支持以下语义，字段名称尽量与现有 V2.3 示例及 V2.4 partial 一致：

```json
{
  "schema_version": "2.4",
  "document_id": "...",
  "bbox_coordinate_system": {"unit": "pdf_points", "origin": "top_left"},
  "source_file": {},
  "standard": {},
  "page_count": 0,
  "pages": [],
  "sections": [],
  "tables": [],
  "clauses": {"normative": [], "explanations": []},
  "processing": {}
}
```

- 文档级 `document_id` 标识具体文档解析对象；标准编号和版次分别存在 `standard.standard_code`、`standard.edition`，不等同于文档 ID。
- `pages` 是物理视图；`sections` 和 `clauses` 是逻辑语义视图；顶层 `tables` 是逻辑完整表格视图。
- `source_file` 继续使用 Task 0 的 `FileRef` 契约，不凭空添加新版本字段。
- PDF **物理页码从 1 开始**。`page_count` 是源 PDF 的页数，不必等于已提取页面数；若 `pages` 是完整物理页清单，应校验页号范围且不重复。
- `schema_version` 作为正式版本固定为 `"2.4"`，此前真实样本可能写为 `"2.4-proposal"`，将样本中的提案标记与正式类型的转换规则**显式记录**；不要偷偷把未知版本当 2.4。
- `standard.is_synthetic_example` **不存在**；示例的合成性放在文件说明或测试元数据中，不放进生产 Standard 模型。

### 2.2 Page：严格 13 种类型 + unknown

`page_type` 枚举值：

- `outer_cover` 外封面
- `inner_cover` 内封面
- `publication_notice` 发布公告
- `preface` 前言
- `toc_zh` 中文目次
- `toc_en` 英文目次
- `body` 正文
- `wording_rules` 用词说明
- `normative_references` 引用标准名录
- `explanation_cover` 条文说明封面
- `revision_notes` 修订说明
- `explanation_toc` 条文说明目次
- `explanation_body` 条文说明正文
- `unknown` 无法可靠分类

每个 Page：`page_number`、`page_type`、`width`、`height`、`blocks[]`，允许在必要时保留来源/状态字段。

明确禁止恢复之前已经删除的字段：`printed_page_label`、`primary_page_type`、`region_type`。

对于未处理扫描件，增加 **可核实的提取状态**（例如 `content_extraction_status`）：`not_processed` / `partially_transcribed` / `complete`；可按现有实际命名确定最终枚举，但各状态必须有清晰语义。`blocks=[]` 与提取状态联合表达，不能据此断言页面为空白。是否需要 `page_type_basis` 可作为可选的来源记录，不强制假定推断出的 page_type 是逐页视觉确认的。

### 2.3 PageBlock：五种类型及来源坐标

`block_type` **仅**：`title`、`body`、`table`、`image`、`formula`。

公共字段至少：

- `block_id`: 必填，Document 范围内唯一。
- `block_type`: 五种枚举之一。
- `bbox`: `{x_min, y_min, x_max, y_max}`，保证 `x_min < x_max`、`y_min < y_max`；使用文档级 `bbox_coordinate_system`，不要在每个 bbox 重复 `coordinate_system` / `origin`。
- `reading_order`: 非负整数或符合现有约定的可选值，用于页面内稳定排序。
- `ocr`: 内容载体，根据 `block_type` 区分必需/可选内容。
- 可选的来源状态及 `asset`/资源引用；尚未精准 OCR 时不要强求虚构内容。

**禁止恢复** Block 的 `clause_id`、`section_id`、`region_type`。Clause → Block 的关系由 Clause 的来源引用表达。

对于**跨页表格**：Page 内每个 `table` Block **仅代表本页的物理片段**，拥有 `table_id`，可选 `fragment_index`、`fragment_status`、`ocr.text`、`asset`、`bbox`；**不要在 PageBlock 内重复完整逻辑表格的 `columns/data`**。即使表格仅一页也使用 `table_id` 指向顶层表格。

对 `title` / `body` 使用 OCR 文本；`image` 保留媒体引用和必要说明；`formula` 使用一个公式组（详见后文）。

### 2.4 顶层 tables[]：跨页逻辑聚合（已确认）

**所有完整表格**由顶层 `tables[]` 保存一次完整的逻辑结构，单页表也如此。建议模型 `LogicalTable` 包含：

```json
{
  "table_id": "table-9.1.2",
  "table_number": "表9.1.2",
  "title": "...",
  "page_start": 126,
  "page_end": 127,
  "source_block_ids": ["p126_part", "p127_part"],
  "fragments": [
    {"page_number": 126, "block_id": "p126_part", "fragment_index": 0},
    {"page_number": 127, "block_id": "p127_part", "fragment_index": 1}
  ],
  "columns": [
    {"key": "category", "header_path": ["板的类别"], "role": "row_header"},
    {"key": "minimum", "header_path": ["最小厚度"], "role": "value"}
  ],
  "data": [{"category": "示例类别", "minimum": "示例数值"}],
  "notes": null
}
```

- `columns[]` + `data[]` 表示**规范化记录视图**，允许多级表头 `header_path`，横向/纵向表头均可通过 `role` 表达；为展开合并单元格而产生的列允许 `derived=true` 及解释信息。
- `data` 保留原文字符串（包括空值、比较符号、范围、单位和破折号），不要强行把所有值转成浮点数。
- `columns[].key` 必须互不重复；每条记录的业务键应与这些 key 对应。若真实样本有 `source_page` 等**来源元数据**，通过明确定义的保留键或来源模型合法表达，不得把它误当成数据列，也不要悄悄丢失。
- `notes` 只允许 `null` 或 `[{"number": 1, "content": "..."}]` 等多条注解；不单独存固定文字 `"注："`；注解顺序可保留，序号正整数且在单表范围不重复。
- `table_id` 在单 Document 唯一，同一逻辑表格所有 Page table fragments 的 `table_id` 相同。
- 表格跨页由 `source_block_ids`、`fragments`、页码范围表达；不允许把续表当第二张表；未核实或未完成聚合的片段必须有状态，不准虚构完整 `data`。
- `raw_grid`（合并单元格的无损格网表示）**尚未定稿，本任务不得强制设计或新增为必填字段**；可仅记为未来扩展点。

### 2.5 FormulaBlock 与 FormulaGroup

一个 `formula` PageBlock 可含一组连续、语义相关的公式及后续符号说明：

```json
{
  "formula_group": {
    "equations": [
      {"formula_id": "f-3.3.2-1", "equation_number": "(3.3.2-1)", "latex": "\\gamma_0 S\\le R", "text": "γ₀S≤R"},
      {"formula_id": "f-exp-4.1.5-1", "equation_number": null, "latex": "E_c=\\frac{10^5}{2.2+\\frac{34.7}{f_{cu,k}}}"}
    ],
    "symbol_explanations": {
      "items": [{"symbol": "S", "latex": "S", "description": "作用效应组合"}]
    }
  }
}
```

上面两条仅为**展示结构**，不是说不同条文/章节的两条公式实际属于同一个公式组；正式 fixtures 应使用同一条文的真实逻辑组合。

- 每个 equation **必须有稳定唯一 `formula_id`**；`equation_number: str | None`，`null` 仅表示经确认原文无印刷编号，**不得**与“图像模糊、OCR 识别不到编号”混为一谈。必要时使用 `recognition_status` 记录 `not_processed` / `unverified` / `verified` 等状态。
- `latex` 是**成功识别后**的内容要求：对于未识别或待处理公式片段，可以明确状态并让 `latex` 为 `null`；禁止为满足非空规则伪造 LaTeX。
- 一个公式可以是多行 LaTeX，一个 group 可以有多个公式，次序由数组顺序确定。
- `symbol_explanations` 允许 `null`，或 `{ "items": [{"symbol": "...", "latex": "...", "description": "..."}] }`。
- 不包含单独的 `unit`、`intro`、`line_index` 字段；若原文“式中：”或单位出现在 OCR 原始文本中，应保留原始文本。
- `formula_id` 在 Document 内唯一。公式属于 PageBlock 的物理位置；公式组跨页延续的识别与聚合算法不在本任务实现，契约需能用来源或状态标记表达不完整情况。

### 2.6 Sections 和 Clauses

`sections[]` 表达章、节等层级，每条至少：`section_id`、`number`、`title`、`section_type`、`content_group`、`parent_section_id`；原有 `structure_path` 暂时保留，不能在 Task 0.1 擅自删除。

`clauses` 保持两个命名分组：

```json
{"normative": [], "explanations": []}
```

- 正文条文与条文说明可以出现同一个 `clause_number`，但 `clause_id` 必须不同，两个分组内的 Section 也要明确 `content_group`。
- 正文 Clause 至少具有 `clause_id`、`clause_number`、`section_id`、`clause_content`、`page_start`、`page_end`、`source_block_ids`、`is_mandatory: bool | None`。
- 说明 Clause 具有 `explains_clause_id: str | None`，可引用实际正文 Clause；允许没有正文条文匹配的说明，不能伪造引用。
- `clause_content` 支持有序 `content_units[]`，类型至少 `body` / `table` / `formula` / `image`，必要时允许小项 `list_item`（小项是否新增 Block 类型？**否**；它是 Clause 内逻辑单元，可来源于 body Block）。保留已有 `plain_text` 的约定，不在本任务推动其删除。
- 每个 `content_unit` 引用实际 `source_block_ids`；对于表格类另提供 `table_id` 引用顶层 `tables[]`，**表格完整结构不得再复制到 Clause**。对于其他类型已有 `text`、`formula_group` 等冗余字段的去留尚未统一决策，本任务只做实现 V2.4 所必需的最小调整，不额外清理。
- 一个 Clause 可以横跨页面，且可能含文字、小项、表格、公式与图片。`page_start <= page_end`，`source_block_ids` 不允许悬空，范围应覆盖所有已引用来源页。
- 正文强制性 `is_mandatory` 可为 `null` 表示未知。`mandatory_evidence` 是否正式固定待定，不强制新增，绝不根据“应/必须/粗体”直接猜为 `true`。

### 2.7 Processing / Partial Data

必须支持真实扫描件尚未 OCR 完成时的**明确状态语义**：

- `processing.partial: bool`
- 建议 `processing.is_complete_document_ocr: bool` 或等价字段
- 页面 `content_extraction_status`：至少区分 `not_processed`、`partially_transcribed`、`complete`
- 块/表/公式级状态或警告用于追踪**未核实/人工估计/未转录**；不要求所有可能的状态都进入复杂枚举，先选择最小但一致的方案。
- `processing.warnings[]` 支持真实问题说明。
- 不得将未处理页面的 `blocks=[]` 等价为“内容为空”；也不得对未完整转录的表格或公式填充伪造数据。
- 坐标应区分 `manual_approximate` 与准确检测坐标；如保留 `bbox_status`，它是状态元数据，不是又一套坐标约定。

## 3. 跨引用完整性校验（Pydantic v2）

除字段类型与结构之外，编写文档级校验：

1. `page_number` 合法、互不重复，在 1 到 `page_count` 范围内，页面尺寸为正数。
2. 文档内 `block_id` 唯一；`bbox` 坐标合法且不超出对应页面（可容忍有明确理由的小范围误差，但不得放弃校验）。
3. `section_id` 唯一；`parent_section_id` 若存在必须指向其他真实 Section，不得自环或存在循环。`content_group` 与 Clause 分组一致。
4. `clause_id` 在正文和说明中全局唯一；`section_id` 存在；解释关系目标必须是正文 Clause 或 `null`。
5. `source_block_ids` 所有显式引用必须真实存在；各类 Clause 的来源页必须处于 `page_start..page_end` 范围。
6. `table_id` 全局唯一；每个顶层 Table 的 `source_block_ids` 必须引用 `block_type=table` 且 `block.table_id` 一致；`fragments` 不重复、顺序明确，页码正确；每个表格 PageBlock 的 `table_id` 必须引用现有顶层 Table，**除非其状态明确标为待聚合/未处理并由契约说明**。
7. `TableColumn.key` 唯一，`header_path` 非空，`role` 为已定义值；`data` 各行的业务列与 `columns` 对应，允许明确保留的来源元数据，不任意默许拼错字段。
8. 公式的 `formula_id` 全文唯一；成功核实/识别的公式必须有非空 `latex`；确认无原文公式编号时 `equation_number=null` 有清楚状态；OCR 失败不能被当作无号。
9. `ClauseContentUnit` 中的 `table_id` 必须引用真实 Table，且引用该 Table 的 Clause 的来源块集合应能够覆盖对应表片段；不得在多个地方保存互相冲突的完整表格副本。
10. `schema_version` 必须符合正式版本策略；未兼容的旧 JSON 应给出明确报错，而非被静默篡改。

这些校验应合理支持 `partial` 文档：**对于已声明的引用禁止悬空，但对尚未解析、没有任何已声明内容的页面不得硬性要求存在 Block/Clause**。不得把不完整样本强行补充成完整数据来通过校验。

## 4. 更新公开类型化接口（不实现算法）

在 `contracts/protocols.py`（或 Task 0 的唯一权威位置）确认：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...

class ChunkingService(Protocol):
    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch: ...
```

要求：

- Parser 生成合法的 V2.4 Document；**Parser 负责**页类型、Block、章节、条文与跨页表格的逻辑识别（今后实现）。
- Chunker **只消费**结构化 Document，通过 Clause/表格引用进行构造，不应承担 PDF OCR、条文识别或跨页表格合并。
- 若 Task 0 已有 Protocol，则修改同一份定义、导出与文档，不创建第二份同名协议。
- 未实现的具体业务方法不得返回看似成功的空 Document 或空 ChunkBatch；可只用 Protocol 声明或明确抛 `NotImplementedError` 的标记骨架。
- 不修改 keyword/vector/hybrid/query/generation 等无关公开接口，除非 V2.4 造成可证实的类型冲突；遇到冲突优先保证公共 `Document` 唯一来源。

## 5. 文件组织和文档同步

优先在当前架构的固定路径内实现，例如：

```text
src/engineering_rag/contracts/
  documents.py               # Document, Page, Block, LogicalTable, Section, Clause 等
  protocols.py               # 公共接口，引用统一 Document
src/engineering_rag/modules/document_parser/
  api.py
  INTERFACE.md
src/engineering_rag/modules/chunking/
  api.py
  INTERFACE.md
examples/
  document.example.json          # 全部结构可校验的合成 V2.4 文档
  document.partial.example.json  # 合成部分解析与状态样例
tests/contracts/
  test_document_v24.py
  test_table_contract.py
  test_formula_contract.py
  test_clause_contract.py
  test_document_partial.py
docs/
  data-contracts.md
  architecture-decisions.md
README.md
```

如果现有项目文件拆分与上面不同，以现有结构为准；不要为了对齐清单复制大量文件或产生两份权威 Schema。

文档需要明确：模型字段表（必填/可空/默认值）、示例、ID 作用域、bbox 统一约定、物理/逻辑表格关系、规范化表格的数据损失边界、公式编号三种状态（印刷有号/确认无号/尚未识别）、条文说明的关联规则、部分解析语义、接口异常约定、兼容策略、独立测试命令。

**待定议题单独记入 `docs/architecture-decisions.md`，不得私自定稿：**

- `raw_grid` 是否引入及其格网数据结构。
- 除表格以外，`content_units` 中正文、公式的副本是否删除及 `plain_text` 是否继续保存。
- `mandatory_evidence` 的结构、来源分类、判定规则。
- `structure_path`、`processing`、asset 版本信息等此前待定的精简事项。

## 6. 示例数据要求

### A. 合成完整版 `examples/document.example.json`

不使用真实工程数值作为虚构示例。例子必须展示：

- 正文与条文说明的章节及同编号 Clause；说明条文 `explains_clause_id` 指向正文条文。
- 至少两页正文加一页条文说明；13 种已确定 PageType **的枚举定义**必须覆盖，示例不必强迫出现所有页面类型，但要至少出现一个 `unknown` 的独立枚举校验测试。
- 一张完整跨页表格：两个 Page table fragments、一个顶层 LogicalTable，含多级/行表头 `columns/data`，多条 `{number, content}` 注解；另一张无注解表格验证 `notes=null`。
- 一组具有两个编号公式并含符号说明的 Formula Block；一条确认无印刷编号公式，`equation_number=null`；每条都有 `formula_id`。
- Clause 的 content_units 能够先引用 body，再引用跨页 Table，再引用 formula，保留逻辑顺序、所有 source block 引用有效。
- 可以再构造 1 个正文附图，保留 image Block + asset 引用。

### B. 部分解析 `examples/document.partial.example.json`

- 至少一个 `not_processed` 扫描页面，`blocks=[]`；至少一个 `partially_transcribed` 页面且有 Block。
- 部分公式或表格可以标记 `unverified` / `not_transcribed`；不能虚构完整识别结果。
- `processing.partial=true`，并记录 warnings。

### C. 如果提供了真实 `GB50010_2015_document.v2.4.partial.json`

它是参考**真实部分识别样本**，不能因其包含部分人工标注而假设所有 441 页已 OCR。优先提供只读校验脚本或诊断报告；如为了符合最终 Schema 需要变更字段，输出**明确的迁移清单/独立派生样本**，不要改写原始真实证据，不要自动把欠缺内容补齐，不要把模糊识别数值改写为确定值。如果真实样本包含提案字段、扩展元数据、OCR 状态等，先列出与正式模型的差异并解释如何保留信息。

## 7. 必须执行的契约测试

1. 13 个页面类型与 `unknown` 的 Enum 校验，未知类型被拒绝。
2. 删除字段不得复活：`printed_page_label`、`region_type`、Block `clause_id/section_id`、bbox 内 `origin/coordinate_system`、Standard `is_synthetic_example`。
3. `bbox` 坐标合法性以及文档级唯一坐标约定。
4. 相同 `table_id` 在两页 Block 中正确指向同一顶层 LogicalTable；`table_id` 悬空、重复、片段顺序冲突被拒绝。
5. 表格多级表头、横向/纵向表头、展开后 `columns/data`；数据列对齐；`notes=null` 和多条编号 notes。
6. 公式组含两个编号公式、一个无印刷编号公式；`formula_id` 缺失/重复拒绝；`equation_number=null` 被允许且状态明确。
7. 多行 LaTeX 公式字符串能原样 JSON 往返，不把反斜杠破坏。
8. `symbol_explanations=null` 与 items 列表；无 `unit/intro/line_index`。
9. 正文与说明使用同一条文编号但不同 ID；`explains_clause_id` 正确关联；错误关联被拒绝。
10. Clause 的跨页 `page_start/page_end`、`source_block_ids`、content_unit/table 引用完整有效。
11. `not_processed` Page + `blocks=[]` 合法，不被解释为空白；部分样例可序列化。
12. Section 父子结构无环校验；Block ID / Clause ID / Formula ID 等作用域唯一。
13. 官方合成完整版与部分版 JSON 均能 `Document.model_validate_json`，再 `model_dump_json` / `model_validate_json` 等价往返。
14. `DocumentParser` / `ChunkingService` Protocol 的签名与导出路径和 `INTERFACE.md` 保持一致，可在不使用 OCR、Elasticsearch、Milvus 或 LLM 的环境独立导入测试。
15. 最低限度的反例测试覆盖不合法边界、悬空引用、重复 ID、混淆公式编号状态、错误 Table fragment 归属。

pytest 命令：

```bash
python -m pytest tests/contracts -q
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest src/engineering_rag/modules/chunking/tests -q
python -m pytest -q
```

对于不存在的预期测试目录，依照实际项目路径调整；不得写“已通过”而不真实执行。若 Ruff 已安装/配置，运行 `ruff check .` 并报告结果。

## 8. 代码风格和模块独立性

严格遵守 `AGENTS.md`：Python 3.11+、Pydantic v2、明确类型注解、`typing.Protocol`、不在 import 时产生数据库/网络副作用、异常有语义、ID 来源稳定。适度拆分验证函数，避免一个 Document 校验器有数百行硬编码规则。跨模块不导入其他模块 `internal/`。避免“万能 dict[Any,Any]”代替核心表格/公式模型；可变键 `data` 的 value 类型与来源元数据要显式限定。

## 9. 实施顺序

1. 阅读规则和仓库、运行基线测试。
2. 列出现有 Document Schema 与本 Prompt 的差异，标记高风险变更。
3. 更新统一 Pydantic 模型与字段/交叉引用校验。
4. 更新 `DocumentParser` 与 `ChunkingService` 的唯一公开 Protocol、公共导出。
5. 编写合成完整和部分 Document 示例，所有示例必须可校验。
6. 加入正反契约测试，覆盖跨页表格、公式与 Clause 等关键情况。
7. 更新两个 `INTERFACE.md` 和数据契约文档及 ADR；如 `AGENTS.md` 仍标记当前 Task 0，则仅同步阶段标记到 Task 0.1，不修改架构原则。
8. 运行模块独立测试、契约测试、全量 pytest 和已配置 lint。
9. 输出具体修改文件、失败/跳过测试、剩余待决问题，然后**停止**。

## 10. 最终交付报告格式

请依次汇报：

1. 当前仓库确认信息及基线测试结果（未检测到的材料要标明）。
2. 修改/新增文件清单。
3. V2.4 顶层数据模型及核心关联示意。
4. 新旧契约的确定变更与非兼容点。
5. 逻辑表格/物理 Block、Clause/Table、FormulaGroup 的数据关联说明。
6. 真实/合成示例分别说明，特别标明哪些页面未 OCR。
7. Parser/Chunking 的唯一 Protocol 签名及模块独立性测试。
8. pytest / Ruff 的**实际运行结果**。
9. 待定架构议题和任何限制。
10. 明确声明：**没有实现 PDF/OCR 解析或 Chunking 算法；没有开始下一 Task**。

**验收核心：给定有效 V2.4 JSON 能稳定反序列化为 Document，且可凭同一个 JSON 确定条文、表格、公式、页面来源及不完整识别状态；Parser 与 Chunker 只通过统一数据模型和类型化接口交互。**

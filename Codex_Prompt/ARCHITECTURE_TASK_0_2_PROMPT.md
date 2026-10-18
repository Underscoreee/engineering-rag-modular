# Architecture Task 0.2：Document Schema 最终补充、7 项 ADR 落地及 V2.4 冻结

> 请将本文件全文交给 Codex 执行。本次工作发生在**全新模块化单体 Engineering RAG 项目**中，假定 Architecture Task 0 和 Task 0.1 已经建立 Schema/Protocol 骨架。没有旧 Task 1～5 代码需要兼容或迁移。

## 0. 执行总原则

你是本项目的 Python 架构工程师。首先阅读仓库根目录 `AGENTS.md`，然后检查：

- `pyproject.toml`、`README.md`；
- `src/engineering_rag/contracts/` 下全部当前 Document/Chunk/Artifact DTO 与 Protocol；
- `src/engineering_rag/modules/document_parser/api.py`、`INTERFACE.md`、独立测试；
- `src/engineering_rag/modules/chunking/api.py`、`INTERFACE.md`、独立测试；
- `src/engineering_rag/infrastructure/file_store/` 的公开边界；
- `docs/data-contracts.md`、`docs/architecture-decisions.md`、`docs/dependency-rules.md`；
- `examples/`、`tests/contracts/`、`tests/architecture/`。

同时阅读本 Prompt 随附的 `ARCHITECTURE_DECISIONS_TASK_0_2.md`，它是**已获用户采纳的 7 项 ADR 决策的任务版记录**。若仓库中命名有差异，请适应既有项目结构，不要复制出两份公共 Schema。

先运行：

```bash
python -m pytest -q
```

并记录现有测试基线。若关键文件缺失，先报告真实状态；只补齐本任务所必需的架构部分，不得假装 Task 0.1 已完成。

### 任务边界

本次只完成 **Schema、Pydantic 校验、类型化公开接口、Artifact/ID 契约与版本声明、JSON fixtures、ADR/接口文档、独立测试**。

**禁止实现：** PyMuPDF、PaddleOCR/MinerU、OCR、PDF 页面识别、跨页表格合并算法、Chunking 算法、ES/Milvus、Embedding、RRF/Rerank、Query Rewrite/HyDE、LLM、HTTP/gRPC、Docker 或任何后台任务/真实存储后端。

### 版本原则

本阶段目标是冻结 `Document schema_version = "2.4"`。

- 如果当前 2.4 仅是 Task 0.1 提案、还没有被外部模块/文件正式消费，可在本次完成变更后将正式契约固定为 `"2.4"`。
- 如果已有正式发布、被依赖的 V2.4 且本次更改属不兼容变更，**不得悄悄修改该版本语义**。应提供影响分析、版本升级/显式迁移方案并报告阻塞；不允许为了满足版本号而造成破坏性静默兼容。
- Schema 版本、标准 `edition`、Parser 版本与 Artifact 快照版本是**四种不同的标识**。
- `2.4-proposal` 不能在没有明确迁移/转换的情况下默认为正式 `2.4`。

## 1. 必须保留的 V2.4 基础契约

### Document 顶层

```text
Document
  schema_version = "2.4"
  document_id
  bbox_coordinate_system     # pdf_points + top_left，全文统一
  source_file               # FileRef
  standard                  # 标准名称 / 代码 / edition
  page_count
  pages[]                   # 物理页面
  sections[]                # 章节层级
  tables[]                  # 唯一逻辑表格集合
  clauses.normative[]       # 正文条文
  clauses.explanations[]    # 条文说明条文
  processing                # 解析状态与警告
```

- PageType 固定 13 种：`outer_cover`、`inner_cover`、`publication_notice`、`preface`、`toc_zh`、`toc_en`、`body`、`wording_rules`、`normative_references`、`explanation_cover`、`revision_notes`、`explanation_toc`、`explanation_body`；此外增加 `unknown`。
- BlockType 仅 `title`、`body`、`table`、`image`、`formula`。
- 每个 Page 的 `blocks[]` 保存页内 OCR、bbox、reading_order；跨页表格通过同一 `table_id` 关联顶层逻辑表。
- `clauses` 按正文与说明分两组；`clause_id` 区分同号条文，`explains_clause_id` 链接说明→正文。
- PDF 物理 `page_number` 从 1 开始；`bbox` 只保存四个坐标，坐标统一为 PDF Points、左上角原点。
- 结构性删除字段**不得恢复**：Standard `is_synthetic_example`、Page `printed_page_label`、PageBlock `region_type`/`clause_id`/`section_id`、bbox 级的 `coordinate_system`/`origin`、公式 `line_index`、符号说明 `intro`/`unit`。
- 强制性三态 `is_mandatory: bool | None`、部分解析 `processing.partial` / `content_extraction_status`、跨页 Clause 的来源 Block 集合继续保持。
- `equation_number` 允许 `null`，但**每条公式必须有 `formula_id`**。确认无印刷编号与 OCR 尚未识别编号必须可区分。

不要因本次任务而无关修改现有 Keyword/Vector/Hybrid/Query/Generation DTO。

## 2. ADR-001：身份语义与稳定 ID

### 2.1 固定身份层级

- `FileRef.file_id`：文件管理模块持久化分配 ID，`sha256` 可做文件内容完整性校验，不充当 file_id。
- `Document.document_id`：一个具体标准版次对应的文档身份，不直接等于 `standard_code`。多个解析快照可指向同一个 `document_id`。
- `ArtifactManifest.artifact_id`：一次结构化 Document 输出快照的身份；其 `artifact_version` 记录解析产物的修订版本。
- `PageBlock.block_id`、`Section.section_id`、`Clause.clause_id`、`LogicalTable.table_id`、`Equation.formula_id`：在一个 Document 快照内必须唯一；无 `document_id`/Artifact 限定时，不能假设跨不同文档或快照全局唯一。

### 2.2 生成规则：定义语义，不强制具体库

- 条文、章节、逻辑表格优先按明确的正文/条文说明命名空间、规范编号和必要来源锚点生成稳定 ID；存在重复编号时必须确定性消歧。
- Block 优先根据页号和稳定来源锚点生成；如果重新分块导致锚点发生变化，必须通过持久映射追踪，而不是以 OCR 文本哈希伪造跨版本稳定。
- **OCR 内容改变不应自动把逻辑条文视为新的条文实体**；反之，重新分段/版面识别导致的 Block ID 改变也不能无条件隐瞒。
- 具体 UUIDv5、数据库主键、命名空间实现及跨版本 ID 映射算法属于后续 FileStore/Parser 内部；Task 0.2 只定义规则、作用域与验证器。

### 2.3 测试

- 同一个文档快照的 Block/Section/Clause/Table/Formula ID 均不得重复。
- `normative 4.2.1` 和 `explanation 4.2.1` 允许编号相同但 ID 不得相同。
- 同一 `document_id` 不同 Artifact 快照不能错误合并来源引用。
- JSON serialize/deserialize 不改变标识；缺失目标的引用必须被报告。

## 3. ADR-002：部分解析 Artifact 与 Manifest

引入轻量、版本化的 `ArtifactManifest` 公共 DTO，至少定义：

```text
artifact_id
artifact_version
schema_version
created_at             # 带时区 UTC
source_document_id
processing_status      # completed / partial / failed（如需）
document_json_ref      # URI、SHA-256、media_type
assets[]               # URI、类型、SHA-256、大小等
parser_version         # 可选；不要和 schema_version 混为一谈
```

规范：

- 文件管理模块未来存储布局：`document.json` + `assets/` + `manifest.json`。产物**不可就地覆盖**，历史 Manifest 可追踪。
- Manifest 指向的是同一个快照内的数据和资源；静态验证校验标识、类型、URI、hash 格式、版本字段，**本阶段不打开/写入实际文件**。
- 部分成功必须被 Manifest 和 Document.processing 明确表示。`not_processed` 页的 `blocks=[]` **不表示页面为空白**。
- 版本迁移定义显式入口/Protocol 或约定：`migrate_document(source: DocumentArtifact, target_schema_version: str) -> ...`，但本阶段只约束行为和版本检查，**不实现迁移执行代码或猜测填空**。
- 缺资源、校验和不一致、版本不支持的错误类型需清晰；区分 Manifest 的静态 Schema 校验和以后真实存储的 I/O 完整性校验。

## 4. ADR-003：PDF 库与 Golden Dataset 边界

- 在 `docs/architecture-decisions.md` 记录：后续 Parser 第一版优先使用 PyMuPDF 读取 PDF 页面/图像；OCR 引擎通过私有适配器可替换。
- 以真实工程规范人工标注构建 Golden Dataset，评估页面分类、条文、表格、公式识别。记录来源、版本、人工核验状态。
- **本任务不得把 PyMuPDF、OCR 模型路径、评估集选型或硬编码 GB 50010 字段放进 Document/Chunking 的公共数据契约。**
- 不安装 OCR 模型、不运行 OCR、不伪造 Recall/OCR 准确率。

## 5. ADR-004：raw_grid（正式引入可选模型）

继续以顶层 `tables[]` 为完整逻辑表格的**唯一结构化事实来源**：

```text
LogicalTable
  table_id, table_number, title
  page_start, page_end, source_block_ids, fragments[]
  columns[]      # key/header_path/role/可选 derived
  data[]         # 展开的列键记录
  notes          # null 或 number/content 列表
  raw_grid       # 可选 RawTableGrid | None
  extraction_status / warnings (沿用现有规则)
```

`RawTableGrid` 建议字段：

```json
{
  "row_count": 3,
  "column_count": 3,
  "cells": [
    {
      "row": 0,
      "col": 0,
      "row_span": 2,
      "col_span": 1,
      "text": "构件类别",
      "is_header": true,
      "source_block_ids": ["p08_table_fragment"]
    },
    {
      "row": 0,
      "col": 1,
      "row_span": 1,
      "col_span": 2,
      "text": "设计参数",
      "is_header": true,
      "source_block_ids": ["p08_table_fragment"]
    }
  ]
}
```

校验：

- 行列号从 0 开始；`row_span/col_span >= 1`；任何单元格覆盖区域必须在 grid 内。
- 不允许两个单元格占用同一个格网位置；复杂合并表头可以合法跨多行/列。
- 部分识别的格网可以有未覆盖区域，不能强制编造所有格子，必要时给 `extraction_status` 标记。
- 单元格 `text` 对未识别情况允许 `null` + 状态；不应以空字符串假装已识别。
- `raw_grid` 是**原印刷表格拓扑的最佳可用表达**；`columns/data` 是为检索而展开的记录视图。`derived=true` 的列必须可辨，不伪装成印刷表头。
- `raw_grid=null` 合法；不可将其判定为表格不存在。
- `notes` 仅 `null` 或多条 `{number:int>=1, content:string}`；`number` 定义为该表注在当前表中的**顺序号**（允许原文只有“注：”而无印刷序号），禁止声称人为分配的序号就是原文印刷编号。
- Page 级 TableBlock 只保存本页物理片段信息、`table_id`、bbox、OCR 局部文本或图片引用；不复制完整 LogicalTable 到 Block。

测试包括：跨行表头、跨列表头、横向/纵向表头、跨页片段归属、未完成 OCR、格网冲突/越界、`notes=null`、多表注、`columns/data` 字段一致性、JSON 往返。

## 6. ADR-005：ContentUnit 引用式结构 + plain_text 缓存

`ClauseContentUnit` 保留明确的内容顺序与类型，不允许存在相互矛盾的完整副本。建议按内容类别采用**类型化可判别联合体**：

- `BodyContentUnit`：`content_type="body"`，引用 `source_block_ids`，可选逻辑小项标签；**不复制 body.text**。
- `TableContentUnit`：`content_type="table"`，引用 `table_id`（及可选来源片段）；**不复制 table.columns/data/notes/raw_grid**。
- `FormulaContentUnit`：`content_type="formula"`，引用 `source_block_ids` 和/或 `formula_ids`；**不复制完整 formula_group、equations、LaTeX**。
- `ImageContentUnit`：`content_type="image"`，引用 `source_block_ids` 或 `asset_id`。
- 小项 `list_item` 可以是正文 ContentUnit 的可选语义标志，**不能擅自扩充五种 PageBlockType**。

字段约束：

1. 每条 ContentUnit 至少包含可解析的来源引用；Table 必须有合法 `table_id`，Formula 若含 `formula_ids` 必须真实存在。
2. 需要时保留现有 `order`，但必须与数组顺序保持一致；不顺便删 `sections.structure_path`。
3. `Clause.source_block_ids` 如果保留，与全部 ContentUnit 涉及的物理 Block 之间必须一致（明确去重和排序规则）；同一表格跨页片段须能回溯到每一个表格 Block。
4. `Clause.clause_content.plain_text: str | None` **保留为派生缓存**。来源是按 `content_units` 顺序解析权威 Block/Table/Formula/Asset 后生成的可读文本；它不能成为与源内容相互独立的另一份原文。
5. 为防止陈旧缓存：定义明确的生成版本/依赖变更后失效策略（例如 `plain_text_revision` 或规范化 renderer 版本/指纹）；若现有 Schema 无法完全校验缓存与来源相同，至少编写**纯函数契约辅助方法**用于 fixture 展开和核对，不实现 OCR 或 Chunk 切分算法。真实缓存策略放入 ADR 文档。
6. 已处理和未处理内容要区分；不允许为了完整 `plain_text` 杜撰缺失文本。

测试需覆盖：正文→逻辑表格（跨页）→正文→公式，跨页来源完整；删除重复内容后，依旧可以从同一份 Document 解析出逻辑条文的引用顺序和必要内容；重复存储 `table`/`formula_group`/正文副本的非法旧字段应有清晰错误或**显式**迁移流程。

## 7. ADR-006：强制性条文证据 mandatory_evidence

为**正文 Clause** 定义结构化证据 `MandatoryEvidence`。建议最小字段：

```text
evidence_id            # 文档快照内唯一或明确作用域
source_type            # official_announcement / official_amendment / published_standard / reviewed_record
source_document_id?    # 可选；来源可能是其他权威文档
source_page?           # 可选，1-based
external_uri?          # 可选权威来源链接
reference_text?        # 可选原文摘录/编号
verification_status    # pending / verified / rejected
conclusion             # true / false / null
verified_by?           # 可选审阅者标识（避免敏感个人信息）
verified_at?           # UTC datetime
```

约束：

- `is_mandatory=null` 表示未知，允许没有证据或者有尚未完成核验的证据。
- `is_mandatory=true` 必须有至少一条**verified + conclusion=true** 的合格证据；`false` 同理必须有核验为非强制性的可靠证据，不能仅因为没有命中名单就标 `false`。
- 存在 verified 且互相矛盾的证据时，必须保留冲突并报告，不得自动选定 true/false；适当采用 `is_mandatory=null` 并记录 conflict 诊断，或者明确拒绝非法确定状态。
- 已核验证据必须能引用具体公告/文件/来源位置，不能只有一句“模型判断强条”。`source_document_id` 若为当前文档须能核对；若为外部权威来源，其生命周期由文件管理负责，本任务静态校验不能擅自连接网络。
- `reference_text` 不能反向当作判定结论，扫描 OCR 粗体、词汇“应/必须”不是法定判定依据。
- 证据是**已核验的材料引用**，不是未经审查的法律合规保证。

必须实现对应合法/非法样例：null 无证据，true 有合格证据，false 有合格证据，true 只有 pending 证据应拒绝，冲突证据应保留并禁止自动肯定。真实条文的强制性属性不得仅根据某一旧版标准文本推断其现行法律效力。

## 8. ADR-007：其他字段延后精简

以下字段继续保留并确保与当前 Schema 兼容，不得借本次任务删掉：

- `sections.structure_path`
- `processing`（含 parser/version、partial、warnings）
- 现有 `asset` 中的版本/引用信息
- `page_count`、`ocr.text`、`bbox_coordinate_system`

其中 `processing` 必须能区分未处理/部分 OCR/全部已识别，`processing.partial` 与页面状态不能产生明显冲突。其他精简建议只记录，不实施。

## 9. 横向引用与文档级完整性校验

在现有 Pydantic v2 类型验证之外，实现 **可独立运行的 Document 引用校验**（推荐 `validate_document_references(document)` 返回结构化诊断，或在 Document validator 严格模式调用），至少覆盖：

1. Page 的 `page_number` 在合法范围内、唯一；尺寸为正。`blocks=[]` + `not_processed` 是合法状态。
2. Document 内 `block_id`、`section_id`、`clause_id`、`table_id`、`formula_id` 唯一；`evidence_id` 在已声明的作用域内唯一。
3. bbox 坐标合法，在所属页面范围内；不得以人工估计/空值假冒 OCR 精确定位。
4. Section 父节点、`structure_path` 与 content_group 合法；不得有循环。
5. Clause 的 Section 和 Group 匹配，`explains_clause_id` 指向已有正文条文；来源 Block 存在，Page range 覆盖所有来源。
6. Page TableBlock 的 `table_id` 与顶层 LogicalTable 双向匹配；跨页 fragments 的 block/page/顺序/范围对应。
7. LogicalTable 的 `raw_grid`、`columns/data`、`notes` 各自合法，且不违反关系约束。
8. FormulaGroup 的每个公式 `formula_id` 唯一；`equation_number=null` 与识别状态不混淆；符号解释允许 null；不允许恢复 `intro/unit/line_index`。
9. Clause ContentUnit 所指的 `table_id`、`formula_id`、`source_block_ids`、`asset_id` 必须解析到快照内的权威内容。引用式设计中不得有冲突内容副本。
10. `mandatory_evidence` 三态一致性、合格来源、冲突诊断。
11. Schema 版本不可静默猜测；不允许把错误旧字段当作任意扩展字段吞掉。
12. 支持部分解析：只检查**已声明**的对象和引用，不要求不存在的 OCR/条文被补齐。

校验方法应保持可测试、模块化，不将数百行逻辑堆进单个 Pydantic `model_validator`。对静态校验与真实 I/O 校验的边界进行文档说明。

## 10. 更新接口与基础能力边界

Parser 和 Chunking 的公开 Protocol 保持稳定：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...


class ChunkingService(Protocol):
    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch: ...
```

同步修改：

- `modules/document_parser/INTERFACE.md`：说明未来 Parser 输出完整/部分 V2.4 Document，Page/Table/Formula/Clause/证据/Asset 关系和状态；不得暗示该模块已实现 OCR。
- `modules/chunking/INTERFACE.md`：说明 Chunker 只读取 V2.4 的引用式 ContentUnits、逻辑 Tables 和 Block/Formula/Asset 权威内容，不进行 OCR/跨页续表检测或强条判断。
- `infrastructure/file_store/INTERFACE.md`：约定不可变 Artifact 快照+Manifest 及版本迁移接口，**不实现存储 I/O**。
- `contracts/protocols.py` 与 `modules/*/api.py` 保持唯一权威方法定义，无复制的同名 Schema。
- 只有相关公共类型/字段变更影响其他模块时才做最小修订；不要改检索/生成算法。

## 11. 示例数据和契约测试（核心验收）

### 必须提交的示例

1. `examples/document.example.json`：人工构造且**完整可验证**的 V2.4 文档。至少包含：正文+说明同编号、跨页续表（2 个 Page TableBlock → 1 个 LogicalTable）、raw_grid 合并单元格、多级 header_path/行表头、2 条带序号的 notes、2 个有号公式与 1 个经确认无印刷编号的公式、symbol_explanations、来源引用式 ContentUnits、正文 Clause 的有效强条证据。示例文字、标准编号与数值均明确为虚构演示，不具有规范效力。
2. `examples/document.partial.example.json`：未处理页 `blocks=[]`、部分已录入 Block、`raw_grid=null`、未识别公式 `latex=null` + 明确状态、待核验表格/强条状态、`processing.partial=true`；不能捏造 OCR 内容。
3. `examples/artifact_manifest.example.json`：引用完整/部分 Document 快照及资源的 Manifest 示例；所有 URI 和 SHA-256 属虚构 fixture，并且标明无需实际文件可用的静态契约测试。
4. 如果仓库包含 GB50010 的真实 `...partial.json`：严格保持原文件只读；必要时编写显式转换后派生样本与差异报告；**不得声明已完整转录 441 页**。

### 必须通过的测试类别

- `test_ids.py`：各实体唯一性、范围、OCR 内容变化不直接当 ID 生成规则、同号正文与说明区别、Artifact 身份。
- `test_raw_grid.py`：合并跨行/列、越界、重叠、缺失单元格的部分状态、notes 序号。
- `test_table_references.py`：跨页表与 fragments/Block/Clause 双向一致；没有悬空 `table_id`。
- `test_formula_v24.py`：`formula_id` 唯一；编号存在/确认无号/编号未识别三种状态；公式组与符号解释；无 `line_index/intro/unit`。
- `test_content_units.py`：正文/表格/公式/图片引用式数据，删除重复副本，`plain_text` 可重新推导的缓存规则，原始来源关系。
- `test_mandatory_evidence.py`：真/假/未知三态，来源核验状态，冲突处理。
- `test_artifact_manifest.py`：schema/artifact/parser 版本区分、不可变快照标识、静态 URI/校验和校验；I/O 后端不必运行。
- `test_partial_document.py`：未处理页无 Block 合法，缺少不曾声明的 OCR 数据不视为校验失败。
- `test_document_v24.py`：完整/部分 JSON 均能 Pydantic 校验和 JSON round-trip；旧 `2.4-proposal` 不会被静默接收为正式 2.4；已删除字段依旧被拒绝。
- `tests/architecture/`：无跨模块 `internal` 导入，Parser/Chunking 独立导入，无外部模型和数据库依赖。

**不要仅以测试数量衡量完成度；必须同时包含非法/悬空引用的反例测试。**

### 验证命令

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/contracts -q
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest src/engineering_rag/modules/chunking/tests -q
python -m pytest -q
ruff check .
ruff format --check .
```

根据真实项目测试目录调整命令，报告所有实际运行结果。若 Ruff 未配置/无法使用，明确说明原因。不能把未运行的真实 PDF/OCR 集成测试称为通过。

## 12. 需要更新或新增的文档

- `docs/architecture-decisions.md`：把 ADR-001～007 从 Open Decision 更新为 Adopted，记录范围、影响、未来内部实现边界。将已采纳内容归档，其他无关待决项不要自动关闭。
- `docs/data-contracts.md`：包括全部 Document V2.4 字段、raw_grid、ContentUnit 引用、证据和 ArtifactManifest，提供必要 JSON 样例。
- `docs/id-policy.md`：ID 作用域、快照身份、跨版本稳定性边界、引用合法性。
- `docs/artifact-policy.md`：Manifest/JSON/assets、不可覆盖、版本迁移、部分状态。
- `docs/schema-changelog.md`：Task 0.1→0.2 的字段增删、潜在不兼容变更、旧数据如何显式处理。
- `docs/schema-freeze-checklist.md`：可执行的冻结验收清单，测试证据和维护人审核结论。
- `modules/document_parser/INTERFACE.md`、`modules/chunking/INTERFACE.md`、`infrastructure/file_store/INTERFACE.md`。
- `README.md`：当前 Task 状态、契约测试与版本策略。
- `AGENTS.md`：仅修改阶段性状态，若旧文件写死“当前 Task 0 禁止任何新模型”，调整为允许 Task 0.2 的契约完善，**不要改变模块化、独立测试与禁止提前做业务实现的长期原则**。

## 13. 实施步骤（按顺序执行）

1. 读取仓库、AGENTS、Task0/0.1 schema、接口与测试；运行旧测试。
2. 生成「当前字段 vs 7 ADR」差异清单；判定 V2.4 是否已发布。
3. 首先明确身份作用域、Artifact 版本边界和统一 DTO 存放位置。
4. 落实 RawTableGrid/Cell 可选结构，确保不破坏既有 `columns/data`。
5. 落实引用式 ContentUnit，表格仍从顶层 `tables` 读取，正文与公式从 Block/FormulaGroup 读取。
6. 落实 MandatoryEvidence 三态与证据结构。
7. 落实 ArtifactManifest 轻量 DTO、静态校验及文件管理公开契约。
8. 添加跨实体引用验证器，包含部分解析状态处理。
9. 更新 Parser/Chunking Protocol 与三个接口文档。
10. 制作合法的完整/部分/Manifest fixtures 及反例测试。
11. 更新所有 ADR、数据契约、版本与迁移规则文档。
12. 运行独立测试、全量 pytest、Ruff；修复失败，记录 skip/未运行原因。
13. 填写冻结清单，给出**通过 / 阻塞 / 需人审**的明确结论，不虚报。
14. 完成后停止，不开始 Document Parser OCR 实现。

## 14. V2.4 冻结判据与最终报告

冻结条件（全部满足）：

- [ ] 7 项 ADR 已记录为 Adopted，仓库代码与接口一致。
- [ ] `Document.model_validate_json()` 能加载合成完整、部分 Document，Manifest 单独校验成功。
- [ ] `raw_grid` 支持合并单元格及不完整格网；`columns/data` 保持规范化记录视图。
- [ ] 页面 TableBlock、顶层 LogicalTable、Clause 引用关系正确。
- [ ] `formula_id` 必需、`equation_number` 可空且状态清晰。
- [ ] 引用式 ContentUnit 不再复制表格/正文/公式的权威内容，`plain_text` 的派生/失效规则明确。
- [ ] `mandatory_evidence` 有证据来源与核验状态，不确定条文允许 null，不会凭 OCR 粗体/词汇判强条。
- [ ] ID 与 Artifact 版本身份明确，来源不混淆，历史快照不可覆盖的规则写入文档。
- [ ] 保留已确认 PageType、BlockType、统一 bbox、已删除字段和未决定的延后精简项。
- [ ] Parser、Chunking 可以在其他算法模块未实现时独立导入和执行契约测试。
- [ ] 全量 pytest、Ruff 真实运行且无失败；无法执行的工具/测试被如实说明。
- [ ] 不存在未处理的不兼容已发布 V2.4 的风险。
- [ ] 冻结检查表有实际命令输出和维护者确认状态。

**冻结机制**：满足上述条件后，提交一个明确的 V2.4 契约候选（`ready_to_freeze=true`），更新 `docs/schema-freeze-checklist.md` 并请维护者验收。只有验收完成才能声明 `Document Schema V2.4 — Frozen`；之后新增破坏性结构必须升级版本并提供显式迁移方案。

### 最终输出格式（中文）

1. 修改的文件与公共类型清单。
2. ADR-001～007 的实施状态和未解决的例外。
3. V2.4 主要字段与旧 0.1 Schema 的兼容性差异。
4. RawGrid、ContentUnit、MandatoryEvidence、ArtifactManifest 真实代码接口简介。
5. 完整/部分/Manifest 三个 fixtures 的实际校验结果。
6. Parser/Chunking/FileStore 接口与跨模块依赖检查。
7. 基线与最终 pytest、Ruff 实际输出和跳过原因。
8. 冻结 Checklist 逐项结果和 `ready_to_freeze` 结论。
9. 未实现的业务算法（OCR、Parser、Chunking 等），避免混淆。
10. 停止执行，等待用户验收 V2.4；不自行进入 Task 1。

**最终目标：V2.4 作为唯一权威、可校验、可追溯、支持跨页表格/复杂格网/公式/强条证据/部分解析快照的稳定文档契约；任何单个模块都可以在不访问其他模块内部实现的情况下独立开发与测试。**

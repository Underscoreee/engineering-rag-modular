# Architecture Task 1.3 — 基于 MinerU 的复杂工程规范表格结构化与跨页续表恢复

> **给 Codex 的正式执行任务书。** 本任务承接 Task 1.2 的 MinerU 单引擎部署与适配，**不是引擎选型**；公共 `Document Schema V2.4` 为 **FROZEN**。本任务不实施规范条文树/强条识别或公式语义重组。

## 0. 任务目标与边界

将**实际 MinerU 推理**得到的表格片段、原始 HTML/JSON、几何和来源关联，转换为冻结 V2.4 的：

- `pages[].blocks[]` 中的 `block_type="table"` 物理片段；
- `Document.tables[]` 中的 `LogicalTable`：单页或跨页均使用顶层逻辑表，正确关联 `table_id`、`fragments`、`source_block_ids`；
- 在有足够可信结构证据时生成 `raw_grid`（单元格 `row/col/row_span/col_span/text/is_header/source_block_ids/recognition_status`）；
- 在可保真展开时生成 `columns[]`、`data[]`，保留多级横向表头、纵向行头以及表内文字原值；
- 提取有编号表注、表号、表题，保留原始证据；无法满足冻结类型的内容留在 raw sidecar，不虚构字段；
- 实现**保守的跨页续表识别**与校验：不把同号/相邻的两个无关表误合并，不丢失续表中实际的数据行；
- 提供真实 GB 50010 页面测试产物、可人工核查的单元格/来源可视化、诊断、质量评估（仅在人工金标存在时计算准确率）。

**禁止：**修改 `contracts/` 中已冻结模型、Protocol、`DOCUMENT_SCHEMA_VERSION="2.4"`；引入 PaddleOCR 对比；把 MinerU Markdown 当作无损格网；用 LLM 猜缺失单元格、缺失表注编号、跨页表格归属或条文引用；默认对 441 页全本推理；将 PDF 或截图上传外部在线 API；直接实现 Task 1.4/1.5 的公式和条文算法。

## 1. 强制前置检查 / 决策门禁

依次阅读：

1. 项目根 `AGENTS.md`、`README.md`、`docs/schema-v2.4-freeze-record.md`（若存在）和 `docs/data-contracts.md`；
2. `src/engineering_rag/contracts/documents.py`、`contracts/protocols.py`、`contracts/common.py`、`src/engineering_rag/modules/document_parser/INTERFACE.md`；
3. Task 1.1 真实 Parser 代码和 6 项历史修复回归测试；
4. Task 1.2 MinerU 适配代码、运行配置、产物 manifest、`raw MiddleJson`、页码映射、适配测试与真实案例报告；
5. 本任务的 `TASK_1_3_TABLE_MODEL_MAPPING.md`、`TASK_1_3_TEST_CASES.json`、`TASK_1_3_ACCEPTANCE_CHECKLIST.md`。

首先运行 `python -m pytest -q`、可用的 `ruff check .` 和 `ruff format --check .`，保存基线结果；对照 `document-schema-v2.4` tag/冻结记录及 Git diff 检查契约是否变化（无法看到 Git 历史时标注 `not_verified`）。

### Gate A：确认 MinerU 真实来源，不得默许 Task 1.2 已交付

必须核对：真实模型版本、MiddleJson 协议身份（4.x 常见 `schema="docvortex.middle"`、`schema_version="2.0"`）、原始 JSON/ZIP、PDF SHA256、原始物理页码映射、实际表格 HTML/结构化内容、执行日志。当前提供的 Task 1.2 资料是**任务书与候选配置**，不能当作“已真实运行”的证据。

- **若 Task 1.2 实测产物齐全**：以运行过的 MinerU 数据字段为真值来源，继续完整 Task 1.3。
- **若缺真实原始产物**：优先按 Task 1.2 指定的 28–29、37–38、126–127 页补跑 MinerU；不自动安装另一引擎、不上传外网、不默认跑全本。若环境缺模型/PDF/GPU/网络，记录阻塞，可先做**本地纯逻辑与合成样本测试**，但最终状态仅为 `blocked / partial`，不可声称跨页表格已在真实规范上验收。
- 如果 Task 1.1 的旋转/CropBox/源文件 SHA256、size_bytes 六项历史回归问题未修复，正式 V2.4 集成须列为 blocker；可以研究 raw MinerU 表格，但不得伪称生产端到端完成。

## 2. 必须遵守冻结表格契约（以当前代码为最终权威）

在当前已审阅的 V2.4 代码中：

- `PageBlock` 的表格片段要求 `block_type=table`、真实 bbox、`table_id`，含 `fragment_index` 与 `fragment_status`；`reading_order` 页内唯一；bbox 为 PDF points、左上原点。
- `LogicalTable`：`table_id, table_number, title, page_start, page_end, source_block_ids, fragments, columns, data, notes, raw_grid, extraction_status, normalization_warning`。
- `TableFragment`：`page_number, block_id, fragment_index, label`，`fragment_index` 必须从 0 连续，顺序与 `source_block_ids` 一致，首末页与 `page_start/page_end` 一致。
- `TableColumn`：`key`, `header_path`（至少一级）, `role`（`row_header/column_header/dimension/value`）, `derived`, `description`。
- `TableRow`：业务列键严格匹配 `columns[].key`，业务单元格 **仅 `str | null`**，不可将 `0.05`、`1.0`、`—`、`≥`、单位和上下标静默转换为数值；可使用 `source_page`（**整数**）、`source_block_id`（字符串）标记来源。
- `RawTableGrid`：`row_count, column_count, cells[], extraction_status`，`extraction_status` 为 `partial/complete`；每个 `RawTableCell` 有 `row/col/row_span/col_span/text/is_header/recognition_status/source_block_ids`；无越界/重叠；完整格网的覆盖位置必须全部占满。`recognition_status=verified` **需要人工核验**，机器 OCR 默认 `unverified`。
- `LogicalTable.extraction_status` 仅 `structure_only/unverified/verified`；`structure_only` 时 `data` 必须为 **null**；`verified` 要求可靠的 `columns` 与非空 `data`，且所引用片段须已核验。机器结果无人工核验不得设置 `verified`。
- `notes` 为 `null` 或具有**真实编号**的 `[{number:int>0, content:str}, ...]`，不可设为空数组，也不能为未编号的“注：”**捏造 1 号**。未编号原文留在表格 raw sidecar 和诊断；如果有真实编号，按冻结类型写入，内容避免重复“注：”固定前缀。
- 所有 `source_block_ids`、`table_id` 和表格 ID 作用域须通过 `Document.model_validate()` 和跨引用完整性校验。

**注意：**`raw_grid.extraction_status=complete` 只表示几何格位覆盖完备，**不代表文字人工核验**；`LogicalTable.extraction_status=verified` 才是强核验状态。不要混用这些含义。

## 3. 项目内部实现范围

只修改 `document_parser` 自身模块、其内部 MinerU 适配器、测试、脚本、说明文档和必要配置。尽量复用 Task 1.2 的模型、页码映射、坐标转换及 raw artifact 管理；不重复设计公共解析接口。

推荐内部划分（按现有 repo 整合，不强制新建所有文件）：

```text
src/engineering_rag/modules/document_parser/internal/
  mineru/                    # Task 1.2 已有的协议读取、归一化、raw artifacts
  tables/
    raw_html_parser.py       # 安全读取有界的 HTML table / rowspan / colspan
    fragment_builder.py      # 页面表格片段 + 题注/表注证据
    header_normalizer.py     # 多层表头、列角色、纵向行头
    continuation_matcher.py  # 保守识别相邻页面的逻辑续表
    logical_assembler.py     # 建立 LogicalTable、raw_grid、columns/data
    diagnostics.py           # 证据、置信状态、无法转换原因
    overlay.py               # 人工复核图
scripts/evaluate_tables.py  # 实测表格评估、可复现报告
```

### 3.1 原始输入和来源的优先级

1. 实际 MinerU 4.x MiddleJson 的语义 table blocks + 与其绑定的 HTML/图片、caption、footnote、bbox 和原始页面索引（根据真实协议）；
2. Task 1.2 归一化元素及选页物理页映射、原始可视 bbox；
3. 真实扫描 PDF 的局部图像**仅用于人工复核或必要的本地补充判定**；
4. 如果只有 Markdown 管道表 / 不含 rowspan 的扁平数据，**绝不能声明已经恢复无损合并结构**。

MinerU 4.x 的 `structured_content` **不等同于** `MiddleJson`，二者分别保存；某种入口导出的 HTML、图片、题注及脚注是否存在要以实测为准。**不要硬编码 3.x `pdf_info` 或想象字段名**。记录 producer 版本与 parser 协议变更，不改变冻结 V2.4。

### 3.2 安全 HTML 结构解析 → 原始局部格网

- 仅本地读取已落盘内容，禁止 HTML 外链请求、执行 JS、加载脚本或把无关标签当单元格；限制 HTML 文件大小、最大行列数、单元格数、`rowspan/colspan` 和嵌套深度，拒绝病态输入与指数级展开。
- 解析 `thead/tbody/tfoot` 与 `tr/th/td`，保留单元格真实文字（含 `≥/≤/±/—/℃/%`、上/下标的合理纯文本表示）、所在行列、合并跨度、表头属性；文本标准化不能改变实质含义，保留原始 HTML 或 JSON 以便追溯。
- 实现 occupancy 网格，遇到 rowspan/colspan 跨过多个格位应跳到下一个空位置；检查超范围、重叠和行末不一致；不能因为 bad HTML 强行填充虚构值。确定格网不完整时 `partial`，完整且覆盖全部格位时才 `complete`。
- 一张 page table Block 可能包含**多个** `<table>` / 内嵌表格：不允许静默合并为一个；分离候选或明确 blocked 诊断，保留 raw 供复核。
- 转换为 V2.4 raw cell 时，`source_block_ids` 必须指向真实的表格片段 PageBlock；缺 bbox 则不虚构 PageBlock，相关候选保留在 sidecar 并报告无法适配。

### 3.3 多级表头与纵向行头 → `columns/data`

- 多行横向表头用每列自顶向下唯一实际表头节点生成 `header_path`，跳过在同一路径上重复的合并覆盖，不要把跨列表头扁平拼接成没有层级的字符串。
- 对第一列/多列的纵向行头设置 `TableColumn.role=row_header` 或 `dimension`，仅有真实版式依据时这样标注；不能因为第一列是中文就必然判成行头。
- 对 rowspan 数据格的规范化展开要有**明确政策**：源单元格文字出现在起始行，其覆盖的后续行在规范化值中使用 `null`，或者明确规则复制显示值；必须在文档记录处理策略、能回溯 raw_grid、不可悄悄重复填充从而改变工程表格原意。建议默认 `null`，仅在经过领域审查的明确语义下另行派生；后续任务不能丢失合并关系。
- 不要将纵向组合表误识为普通记录；无法判断列语义时可以保留 `raw_grid` 并让 `data=null`、`extraction_status=structure_only`；`columns` 不得凭空补全。
- 数据行必须按原文顺序，业务值仍保持 `str|null`；保留中文符号、单位、条件、脚注角标的可读内容及原始来源。`source_page` 与 `source_block_id` 不可错误指向其他页面或片段。

### 3.4 跨页续表：**证据组合**，不是“相邻就合并”

首先创建每页独立 fragment，之后建立同一 LogicalTable 的候选链接。证据可能包含：

- 相邻物理页顺序与连续解析范围（必须使用**原 PDF 物理页**，而非选页小 PDF 的局部索引）；
- 明确印刷标志 `续表 X.X.X`，或下一页沿用原表号/表题且语义连续；
- 表格的列数、嵌套表头及列宽/表头签名**相容**；
- 上页表格确实到页底、下页在页首续接的几何证据（只能是辅助证据）；
- 不存在更明确的另一张表格、章节标题或新表号将两者隔开；
- 续页重复打印的表头应只出现一次于规范化 `columns`，且不得当作真实 `data` 行；但在原始片段与 raw artifacts 中必须保留。

规则：**明确的表号冲突必须阻止自动合并**；列结构显著冲突不得仅凭相邻合并；只有“无冲突且有足够正面证据”才自动合并。证据不足时输出**两个独立 LogicalTable 或人工待审候选**，严禁无来源的跨页表。若末行跨页断开且没有逐格证据，不可擅自拼接或重构；保留为 partial/诊断。

对 28–29（表 3.5.2）、37–38（表 4.2.2-2）、126–127（表 9.1.2，后有新条文 9.1.3）分别对连续双页与单页分开解析后的拼接进行比较。页码与表号仅作**待核验案例提示**，准确范围必须从实测文件和原图确认。

### 3.5 逻辑格网跨页拼接的诚实性

V2.4 `raw_grid` 位于整个 LogicalTable，但原生 HTML 常是**每页独立格网**，横跨页边界可能有重复表头、不同列拓扑。必须：

- 保存在 sidecar 中逐 fragment 原始 HTML、局部格网、各 cell 可用像素/PDF bbox、重复表头和原始页来源；
- 只有确定共同列拓扑，且能够为所有 cell 构造不重叠的**全局行索引**时才生成 LogicalTable `raw_grid`；原始重复表头若被规范化剔除，也不能从 raw provenance 中消失；
- 对重复续页表头，可在逻辑 raw_grid 作为**真实打印的行**保留，`columns/data` 不再重复计入；保留来源 `source_block_ids` 和侧车的 header flags；
- 不同宽度/部分裁切/行缺失时，允许 `raw_grid=null`，或在明确范围可建局部逻辑格网时标 `partial`；**不要虚构跨页单元格或完整无损格网**；
- 保留 `raw_html` / raw MiddleJson，避免因 V2.4 `raw_grid` 没有单元格级 bbox 字段而丢失可复核证据。

### 3.6 表号、表题和表注

- 从 MinerU caption/footnote 和 PDF 原文中提取已出现的表号/标题，区分 `表 X` 和 `续表 X`，跨页统一 canonical `table_number/title`，`TableFragment.label` 可保留续表标识。
- 需要**依据位置与语义**将表题/脚注归属对应 table fragment；不能简单吸收附近所有正文，也不能把“式（4.2.1）”当表号。
- 有真实阿拉伯编号的 `注 1...注 2...` 才结构化为冻结 `TableNote(number, content)`；一条未编号“注：”只能保存在私有 raw sidecar，`notes=null` 或已核验其他编号 notes；不得人为赋号。表格注解若跨 fragment，需保留原始页来源。

### 3.7 ID、Document 组装和重入行为

- Block `block_id` 在给定源 PDF、原始页和结构锚点上稳定；`table_id` 在相同表号/归属确定时稳定，不以 OCR 文本哈希直接作身份；表号无法确认时使用持久化/确定性备用锚点及人工映射台账。
- 将 Task 1.2 已输出的对应表格 Block 更新为相同稳定 ID，而不是同时保留旧“表格片段”和新“表格片段”造成重复；保留其他正文、公式、图片、Page/Document 身份。若从未存在表格 Block，则只在有真实 bbox 时构建。
- 任何被纳入 `Document.tables[]` 的表必须与所有 fragment Block **双向完整关联**、index 顺序连续、页范围一致；不能生成孤儿表。
- 最终构建新的完整的内存快照并重新 `Document.model_validate(Document.model_dump(mode="json"))`；不依赖对嵌套对象的原地修改自动触发 Document 级校验。
- `processing.partial` 仍为 `true`，直到后续页面/章节/条文等整体解析验收完成；机器表格默认 `unverified`，未实际解析页面不能标完整。

## 4. 可执行用例与测试分层

### 4.1 必备纯测试：无需 MinerU、PDF 和联网

由 `TASK_1_3_TEST_CASES.json` 驱动或编写等价 pytest 用例，至少覆盖：

1. 简单单页 HTML → 表格 fragment + raw_grid + columns/data；
2. 两层表头 colspan（含垂直 th/rowspan）→ `header_path` 与合并覆盖；
3. rowspan 数据格 → 保留 `row_span`，扁平化时不伪复制；
4. 真实字符、工程单位、缺测符号原样保留，原始数据必须保持字符串；
5. 跨页带 `续表` 与相容列头 → 单一 `LogicalTable`、fragments [0,1]；
6. 独立两个同页/相邻表的**反例**：新表号/列头冲突/错误页码/断开的页，不误合并；
7. 续表重复表头不生成重复数据行；
8. 跨页数据单元格断行但缺证据时不臆断拼接；
9. 表注编号和未编号“注：”的不同存储行为；
10. 坏 HTML、过大跨度、占位重叠、嵌套/多个 HTML table、外链，不运行脚本或联网；
11. raw_grid complete/partial、每个 cell source_block_ids、页/表格 Block 的双向引用与 Pydantic 负例；
12. 原始 MinerU 协议变化、无 HTML、丢 bbox、JSON 只给命令摘要等输入：返回结构诊断，不制造合法假数据；
13. 重试/重入稳定 ID、处理顺序确定性、第二次解析不会无意合并不同表；
14. source_page（整数）、source_block_id（字符串）、V2.4 JSON roundtrip；
15. 未处理页面与机器 OCR 不提升 `verified`、不意外创建 sections/clauses/mandatory evidence。

测试数据中**每个确认过的预期值**必须基于人工编制的合成 HTML fixture；真实 GB 用例仅当人工核对后才当金标。

### 4.2 真实 GB 50010 测试（必须实际运行或标出 blocker）

至少：

| 案例 | 原始物理 PDF 页 | 目标 |
|---|---|---|
| `GB-T352` | 28–29 | 续表编号/重复表头/表注/原始行与规范化行完整性 |
| `GB-T4222` | 37–38 | 多层表头、合并格、跨页列对齐 |
| `GB-T912` | 126–127 | 表 9.1.2 续表、结束位置与后续第 9.1.3 条边界（只作为不能误吞正文的反例，不实现 Clause） |

对于每个组至少输出：

- MinerU **真实**输入产物与版本、原 PDF SHA256、源页映射、原始 HTML/JSON、局部/跨页格网；
- `Document V2.4` 部分 JSON、可视化 PNG/SVG（自行生成覆盖框，不添加不真实内容）、`manifest`、warning / impossible-to-map 证据；
- 单页分别处理与双页连续处理的差异；
- 人工核查：表号、行/列、表头覆盖、跨页绑定、表注归属、bbox、丢失/重复单元格；
- 能确定的质量指标与耗时；没有人工金标时只写发现数、错误案例，**禁止虚构准确率**。

尽量复用 Task 1.2 的 18 例配置及运行产物，避免无必要地重新推理 441 页或改变原始样本版本。

## 5. 可复现 CLI 与落盘规范

提供一个有 `--help` 的入口，例如：

```text
python scripts/assemble_mineru_tables.py \
  --run-manifest data/eval/task1_2_mineru/runs/<run_id>/manifest.json \
  --case-id P028029 \
  --output data/eval/task1_3_tables/<run_id>/
```

它必须：明确禁止默认全本处理、支持选例/输入指定 raw 文件、限制资源、生成失败诊断、保留原 raw 不覆盖、记录算法/配置版本与源 PDF hash；能独立运行纯逻辑构建（已有 raw → 无需重启 MinerU 模型）；用安全 HTML 解析器、限制本地文件路径并阻止网络访问；不要依赖默认 shell 执行字符串命令。

建议目录：

```text
data/eval/task1_3_tables/
  runs/<run_id>/<case_id>/
    provenance.json          # MinerU版本、PDF hash、页映射、输入产物hash
    fragments.json           # 每物理页结构与诊断
    tables.json              # 逻辑表诊断视图
    document.partial.json    # V2.4（全字段合法）
    table_sidecars/          # 原 HTML、原始单格来源与局部格网
    overlay/                 # 原图+检测/单格覆盖，可人工检查
    diagnostics.json         # 不可构造事项与匹配证据
  reports/task1_3_tables_review.md
```

避免将版权 PDF/全页图/模型权重提交到公开 Git；Git 中可存简化合成 fixtures/测试和不含扫描原文的大文件元数据摘要。必要时明确本地敏感数据清理策略。

## 6. 推荐交付文件与文档

1. Parser 内部表格后处理源码及 MinerU 适配增强（只针对实际观察到的内容）。
2. 纯逻辑合成 fixtures 和正反 pytest，真实 OCR/PDF 测试显式标记（默认 pytest 不下载模型）。
3. 能重放已保存 raw MinerU 输出的 CLI 与配置；支持部分失败且诊断清楚。
4. 真实 3 组 GB 表格的逐一报告与可视化；若前置阻塞则给实际日志、缺失文件和恢复步骤。
5. `docs/task-1.3-complex-tables.md`：保真政策、连续页/碎片匹配规则、表注规则、V2.4 适配限制、Known Issues。
6. 更新 `modules/document_parser/INTERFACE.md` 只记录**内部配置和实现已支持**的特性；公共 Protocol 不变。
7. 项目完整 `pytest`、Ruff lint/format 真实输出；无法运行要逐项记录原因。

## 7. 验收标准与停工条件

**完成 Task 1.3 的必要条件：**

- Task 1.2 的 MinerU 真正输出可追溯，至少对上述三组实际解析产物进行本地处理；
- 单页及跨页表格的 raw grid / columns / data / fragments 可以按冻结类型合法转换，或对确实不可转换的案例明确保留源数据与报告；
- 多级表头合并、数据 rowspan、重复续表表头、未编号表注、错误合并反例均有可运行测试；
- Document/LogicalTable/RawCell 所有来源引用可复核，`Document.model_validate()` 和 JSON 往返验证通过；
- 不再出现“为通过 Schema 校验而捏造格子、页码、表号或源引用”的实现；
- 真实测试有日志、图像叠加、逐例诊断，所有已知错误如实记录；
- 全量回归和 Ruff 运行或明确环境 blocker，确认冻结 `contracts/` diff 为零。

任务未满足时输出 `PARTIAL / BLOCKED` 和缺口，不能伪称验收完成。**不得自发开始 Task 1.4（公式识别与符号解释）或 Task 1.5（章节条文识别）。完成后停止，提交验收资料。**

## 8. 官方参考（实际部署版本为准）

- MinerU 4.x MiddleJson/Structured Content 与产物区别：https://opendatalab.github.io/MinerU/zh/reference/output_files/
- MinerU 官方仓库：https://github.com/opendatalab/MinerU
- 本任务的 V2.4 完整字段说明见 `TASK_1_3_TABLE_MODEL_MAPPING.md`；**不要照旧代码示例手工增删已冻结字段**。

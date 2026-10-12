# Architecture Task 1.5 — 工程规范章节、条文及条文说明结构化识别（MinerU → Document V2.4 Frozen）

> Codex 正式开发任务书。**只开发 Document Parser 的规范领域语义结构识别**，不修改已冻结的公共 Pydantic Schema / Protocol，不实现 Chunking、向量检索、LLM、规则问答。本轮不更换 MinerU；保留 Task 1.2–1.4 的真实视觉解析和表格/公式语义结果。

## 0. 最终目标

从真实 GB 规范扫描 PDF 的 MinerU 文本、页内版面、表格逻辑结构、已合并的公式语义 Block 中，恢复：

1. `Page.page_type`：正文 `body`、条文说明 `explanation_body`，其余已有类型按证据分类；
2. `Document.sections[]`：章节层级、规范编号、标题、`parent_section_id`、`structure_path`、`section_type`、`content_group`；
3. `Document.clauses.normative[]`：规范正文条文及其跨页延续；
4. `Document.clauses.explanations[]`：条文说明条文，尽可能匹配 `explains_clause_id`；
5. `Clause.clause_content.content_units[]`：有序引用 Body / list_item / table / formula / image，不复制权威结构；
6. `Clause.clause_content.plain_text`：仅在来源齐全且可以由冻结 renderer 正确生成时生成缓存和 digest；
7. 完整、可追踪的诊断与证据 sidecar（候选、弃选、未决、页/块/span/bbox、OCR 状态、旧新 ID 对照、条文匹配理由）。

**一条合格的 Clause 必须包括原文及全部归属元素，不能仅因为正则检测到了 `6.2.1` 就构造一条空条文。** 同时不能为了提高「完整率」凭常识编造规范文字、章节或关联。

## 1. 开始前强制 Gates（先检查，再实现）

### Gate A — 仓库与冻结状态

- 阅读 `AGENTS.md`、`README.md`、`docs/schema-v2.4-freeze-record.md`（若存在）、`docs/data-contracts.md`、`docs/id-policy.md`、`docs/architecture-decisions.md`、`modules/document_parser/INTERFACE.md` 及实际源码。
- **逐字核对** `src/engineering_rag/contracts/documents.py` 中 `PageType`、`Section`、`Clause`、`ClauseContentUnit`、`MandatoryEvidence`、`derive_clause_plain_text`、`validate_document_references`；字段权威以真实源码为准，而不是本 Prompt 示例。
- 记录 `schema_version="2.4"`，检查 Git freeze tag / freeze record；不得修改 `src/engineering_rag/contracts/**`，不得修改 `DocumentParser.parse(ParseRequest)->Document` 签名。若已冻结契约无法承载一个合理需求，创建待决 ADR 与 Parser 私有 sidecar，绝不悄悄扩充字段。
- 记录运行前 Git 状态、`python -m pytest -q`、`ruff check .`、`ruff format --check .` 的实际结果；工具不可用明确报告。

### Gate B — 真实上游数据

- 找到 Task 1.2 实际运行的 MinerU MiddleJson（核实版本/协议身份）、原始 PDF、来源哈希、物理页码映射。
- 检查 Task 1.3 表格 `LogicalTable`（尤其跨页续表）和 Task 1.4 **最新修复版** 完整公式语义 Block（条件、编号、公式、符号解释均在同一组、来源文本已安全消费）；检查其 ID alias / lineage / 未完结标记。
- **不能默认 Task 1.4 已完成验收**。如果修复未落地，独立测试可先写，但不能宣称与公式的真实整合通过；明确列出阻塞项。不得将上一次 overlay / 手改 JSON 当作真实解析流水线执行证明。
- 若仅有选页，明确 `partial`；对跨页归属需要前页或后页时，允许标注 `pending` 并继续其它可验证功能。

### Gate C — 先核对真实文档场景

使用《混凝土结构设计规范》（GB 50010—2010，2015 年版）的实际扫描页与真实 MinerU 输出；**PDF 页码始终是物理页 1-based，印刷页码绝不替代物理页号**。

- 第 16 页：章节 `1 总则`、`1.0.1` 等正文条文；
- 第 49–50 页：`6`、`6.2`、`6.2.1` 的开始与跨页延续；**第 50 页的 `2`、`3`、`4`、`5` 是条款内分项，不是条文 2～5**；第 50 页公式 6.2.1-1～7 与条件/符号解释已归组；
- 第 126–127 页：`9.1.2` 相关续表与之后的 `9.1.3`，防止表格吞入下一个条文；
- 第 277 页：条文说明封面，不能构造 Clause；第 282 页：条文说明的 `1 总则` 和 `1.0.1` 等说明内容；
- 第 301 页：条文说明段落与无印刷编号公式的局部场景；
- 第 28–29、37–38 页：可用于含复杂表格和续表的条文归属；
- 可加入目录、公告、用词说明、引用标准名录的反例，保证这些不被解析为正文条文。

上述是样本选取与人工观察；**不是经过人工逐行标注的 Golden Dataset，更不是已有真实 MinerU 识别分数**。

## 2. 冻结 V2.4 必须遵守的精确关系

### 2.1 页面分类（必须先于 Clause 构建）

- `Page.page_type` 的当前允许类型为 `outer_cover, inner_cover, publication_notice, preface, toc_zh, toc_en, body, wording_rules, normative_references, explanation_cover, revision_notes, explanation_toc, explanation_body, unknown`。
- 正文 Clause 所有被引用 Block 所在页的 `page_type` **必须是 `body`**；说明 Clause 所有被引用 Block 所在页**必须是 `explanation_body`**。这由冻结 Document validator 强制校验。
- 先做可解释的文档分区 / 页面状态机（封面、目录、正文、条文说明封面/目录/正文）；结合章节题头、目录切换与全书范围，不允许为通过校验而将所有 `unknown` 强制改为 `body`。
- 证据不足则维持 `unknown`，且**推迟依赖该页面类型的 Clause 构造**；候选留 sidecar，支持后续选页补全重新处理。不改变 OCR 是否完成的独立状态。

### 2.2 Section / 章节层级

冻结 Section 字段：`section_id`, `number: str|null`, `title`, `section_type (chapter|section|appendix|explanation|other)`, `content_group (normative|explanation)`, `parent_section_id`, `structure_path[]`。

- 依据标题 Block、章节编号模式和版面上下文，建立树。识别 `1 总则` / `6 承载能力极限状态计算` 等章，`6.2 正截面承载力计算` 等节；附录与说明章节据实际内容识别，不用正文同名节覆盖说明树。
- `number` 非空时 `structure_path[-1] == number`；存在 parent 时路径必须恰为 `parent.structure_path` 加 1 级；正文父章节不能跨组指向条文说明。无环，ID 稳定。
- 当前 `Section` **没有来源页或 bbox 字段**，这些及 title 的 OCR 候选、置信度存 Parser 私有 sidecar。未识别足够父级信息时，保守挂在已确认的最近合法父级；不能擅自跳层造一个不存在的章节。必要时留下未决标题候选而不导出 Section。
- 不能将 `目次` 里的章节标题直接当作正文真正章节；目录仅作为低权重旁证。

### 2.3 Clause 边界与编号

冻结 `Clause` 字段：`clause_id`, `clause_number`, `section_id`, `clause_content`, `page_start`, `page_end`, `source_block_ids[]`, `is_mandatory`, `mandatory_evidence[]`, `explains_clause_id`。

- 区分 **条文号**（`1.0.1`, `6.2.1`, `9.1.3`）与 **章/节号**（`1`, `6.2`）、**分项序号**（`1`、`2`、`（1）`）、**公式号**（`6.2.1-1`）、**表号**（`表9.1.2`）、**跨条文引用**（`按第4.1.1条`）。仅段首、字号/缩进、附近标题层级和版面证据都匹配才建立 Clause 起点；禁止全局 regex 见号即建 Clause。
- 一条 Clause 延伸到**下一个真正条文起点/章节边界之前**，可跨页，包含 Body、list_item、完整逻辑表、公式组、图片。原文顺序不变；消除引用的重复语义，不吞掉后续条文。
- 对第 49–50 页，必须识别 `6.2.1` 跨页：第 50 页出现的分项 `2～5` 和条件/公式属于同一个 Clause（在上游证据足够时）。**仅处理第 50 页**时，不得伪造上一页主条文的 `clause_number` 或把分项 2～5 建为独立 Clause；记录 continuation orphan 并待补页。
- 一个 MinerU 大段中包含**多条 Clause**时，需依据可验证的 span/line/bbox 分割并创建相应原文 PageBlock / 稳定 ID 映射；没有安全的分割几何则保留并诊断，不允许一个源 Block 被虚构地复制到多条 Clause 造成重复。页上含前一条文尾部和下一条文开头同理。
- ID 基于 document 身份、group、条文号及来源锚点等稳定规则；正文与说明同号**必须不同 clause_id**。OCR 文字修订不应导致已有条文身份无端变化。保留 old→new block lineage，重试幂等。

### 2.4 `ClauseContentUnit` 权威引用与排序

冻结 `content_type`: `body | table | formula | image | list_item`。`order` 唯一递增；`source_block_ids` 非空、去重；`Clause.source_block_ids` 必须与按 ContentUnit 次序聚合去重的 block IDs **严格一致**。

- `body` 引用真实 `block_type=body`；`list_item` 亦指向 body Block 并附实际印刷 `list_item_label`；不把分项当作 Clause。
- `table` 必须有 `table_id`，且 `unit.source_block_ids` **包含 LogicalTable 的全部碎片 source_block_ids**，不得只引首页或把两个不同表拼成一张。`LogicalTable` 表本体不复制到 Clause。
- `formula` 必须有 `formula_ids[]`，且列表中的公式 ID 必须由当前 `unit.source_block_ids` 指向的公式 Block 真实提供。若 Task 1.4 已将公式 6.2.1-1～5 合并为一个 FormulaGroup Block，可在一个 Formula Unit 中有序列出 5 个 `formula_ids`，**不把同一个公式组重复生成五个 Block**。
- `image` 必须有 `asset_id`，且来源 Block 有对应资产。未提取或没有 asset 的图片不得伪造引用。
- 多页混排时按可视阅读顺序排列 Units，但 table Unit 须覆盖所有跨页 fragments（即使碎片被别的正文分开）；该逻辑需设计清楚冲突处理和排序旁证。
- 如果公式组被多个 Clause 共享、表格跨 Clause、归属冲突，先留下未决归属，**不能复制原始结构或把同一 FormulaGroup 强塞到两个无证据的 Clause**。
- 当前冻结 validator 以 `unit.content_type == BlockType.value` 检查大多数类型。Section 标题 Block 不强行塞入 body Unit；章节标题按 Section 表达。若本项目存在特殊排版不吻合字段，留 sidecar 不改契约。

### 2.5 `plain_text`、条件和公式释义不能遗漏/重复

- `plain_text` 为**派生缓存**，不可作为 OCR 的唯一权威内容。只通过冻结 `derive_clause_plain_text(document, clause)` 计算，不手写字符串/自定义另一套 renderer。
- 只有 ContentUnits 来源齐全且该 renderer 返回有效 `(text, digest)`，才填 `plain_text`、`plain_text_renderer_version=PLAIN_TEXT_RENDERER_VERSION`、`plain_text_source_digest=digest`。否则三字段保持 `null`，标注 review warning / sidecar；不得为了通过 validator 删除尚未归属的真实内容。
- 对 Task 1.4 公式语义 Block，条件、LaTeX、编号、组级 `symbol_explanations` 只出现在语义视图一次。若 `Equation.text` 覆盖 LaTeX，按冻结 renderer 的实际优先级严格核验其内容包含完整公式、条件和编号；`\tag{}` 与编号字段不能在输出中重复。
- 示例测试必须证明全文朗读/检索视图在 Clause 6.2.1 中 **两个条件、不少于 7 条公式、共享符号说明无重复**；前置 Task 1.4 若仍不满足，应明确 BLOCKED，不要擅自修改公共 renderer。

### 2.6 条文说明与正文相互关联

- `clauses.normative` 与 `clauses.explanations` 是**独立对象及独立页区间**，即使印刷条文号相同。说明 Clause 的 `section_id` 属于 explanation Section。
- 解释文本只在有可信的同号与文档版次/上下文对应时把 `explains_clause_id` 指向 Document 中实际存在的正文 Clause；**禁止将第 282 页的说明 Block 当成第 16 页的正文来源**。
- 对**部分选页**：只有说明条文、没有正文 Clause 的时候，`explains_clause_id=null`，待关联关系写私有 `pending_explanation_links`，不得构造悬空 ID 或凭空添加缺页 Clause。晚些时候补齐正文，应可稳定补关联且不重复建 Clause。
- 如正文同号不止一个候选、版次不确定、OCR 标号模糊，保持未决并提供候选与冲突证据，不能自行断言。

### 2.7 强制性条文：绝不因措辞或字重判定

- 默认正文 `is_mandatory=null`, `mandatory_evidence=[]`；条文说明 `is_mandatory=null`, `mandatory_evidence=[]`。
- **“应/必须/严禁”、加粗字体、黑体条文号、文字颜色、OCR confidence 皆不是 `is_mandatory=true` 的充分依据**。
- 仅在已核验公告、正式修订、已核验外部记录等依据明确、版本适用、来源可追溯时建立结构化 `MandatoryEvidence`；`verification_status=verified` 还需要 UTC 时间、核验人和有效来源。资料缺失不能伪造 verified，见冻结 validator。
- Task 1.5 可以识别官方公告中的候选强条名单及条文号，写入**待核验 sidecar**；没有完整核验闭环的，不写入肯定性的 `is_mandatory`。

## 3. 内部架构及实现顺序

充分复用 Task 1.2–1.4 内部模块。推荐新增/复用私有文件（非公共契约，允许按现有项目命名调整）：

```text
src/engineering_rag/modules/document_parser/internal/
  semantic/
    page_zone_classifier.py     # 规范正文 vs 条文说明 vs 非正文
    section_candidates.py       # 标题候选、章/节/附录及来源
    hierarchy_builder.py        # 独立的正文/说明章节树
    clause_boundary.py          # 起止边界与跨页延续
    content_unit_builder.py     # Body/List/Table/Formula/Image 有序引用
    explanation_linker.py       # 同号正文-说明关联与 pending
    mandatory_candidates.py     # 只产 pending 证据，不自行定强条
    v24_assembler.py            # Document 合并、引用校验、text 缓存
    diagnostics.py              # 不确定性、来源、ID lineage、未决关系
scripts/assemble_mineru_clauses.py # 重放真实 raw MinerU + 已解析表格/公式
```

实现顺序：

1. **先读原始**：真实 MinerU 产物、PDF 物理页、已处理的 tables/formulas、alias 和 source-consumption sidecar。锁定页面数据版本，避免重跑覆盖历史。
2. **页面分区**：得到 page_type 候选及其证据，区分正文/说明/目录/封面，仍未知则留未知。
3. **章/节候选**：利用号、标题字号缩进、目录旁证、相邻页连续性，建两套独立树。
4. **条文切分**：扫描 Body Block / 文本 spans / 印刷条文号，从上条尾到下条开始，不将分项/公式号当条文；缺跨页时留 orphan。
5. **混合 Block 安全分割**：依据原始行/span/bbox 生成来源 Block 与 old→new ID 映射；保留 OCR 原文和未消费 fragment；冻结 Schema 仍完全有效。
6. **内容引用**：表、公式组、图片不复制语义内容；按顺序建 ContentUnits 并校验是否存在跨条文冲突或不完整 table fragments。
7. **解释关联**：已存在正文匹配则写 ID；否则只写 pending sidecar。
8. **强条证据**：候选落 sidecar，Document 中默认三态未知。
9. **派生 plain_text**：仅完整可渲染来源才填 3 个缓存字段；再次 `Document.model_validate(Document.model_dump(mode="json"))` 并 JSON 往返；出现引用错误必须中止或生成安全 partial + 诊断，**不通过跳过 validator 隐瞒错误**。
10. **导出回放**：保存新 Document、source lineage、page overlay、审查报告、质量统计；同一输入两次结果一致。

### 重要：真实来源和可解释的暂缓策略

- 内部至少记录：`source_pdf_sha256`, `physical_page`, `source_block_id`, `span_range`, `source_bbox`, `candidate_kind`, `candidate_label`, `page_type_evidence`, `group`, `confidence_or_review`, `link_decision`, `decision_reason`, `source_consumption`, `old_new_id_map`, `pending_links`, `unresolved_reason`。
- 不允许覆盖原始 MinerU JSON、不允许在 Document 插入新增私有字段、不允许发送扫描版规范到外部 API。
- 未解析的 OCR 来源仍须在部分 Document 的 `pages[].blocks` 或保留在可重放 sidecar 中，明确状态；不能为了“干净的 JSON”静默丢失。
- 除非来源明确，禁止把不同版本或不同标准的同号条文关联；不强迫片段变成 Clause。

## 4. 真实集成测试（Gate D）

运行 `TASK_1_5_TEST_CASES.json` 指定的真实页组，**保留全页原始内容和页面上下文**。逐个案例保存：`raw_inputs_manifest.json`, `document.semantic.partial.json`, `page_XXXX_semantic_overlay.png`, `semantic_source_lineage.json`, `semantic_pending_links.json`, `task_1_5_results.json`。建议保证每个 JSON 含版本/来源标识、执行配置、物理页、实际判定与人工核验状态。

必须重点验证：

- 16 页多条文；49–50 页同一条文跨页且含公式条件与解释；126–127 页表/下条边界；277 不构造 Clause、282 只构造 explanation Clause 且缺正文则 pending；301 非编号公式不被误识为条文号。
- 真实 MinerU 识别失败或不完整时，只报告 PARTIAL，不能用合成数据伪称真实成功。
- 页 50 单页输入不应导出臆造 Clause 6.2.1；选页加入 49 页后如可证实条文起点则可以构造。
- 附件的真实图像/文件只能证明候选版面，不能替代人工逐条标注；若需要报告 Precision/Recall/F1，先创建有审阅者、页范围、标注版本和 provenance 的人工金标。

## 5. 合成正反测试（至少覆盖配置中全部测试）

必测：章节树父子、路径、正文/说明分支、章节名/目录干扰、条文号与分项号/表号/公式号区分、跨页条文、同一页面 2 Clause、混合 Block 分割、跨页表 fragments 完整引用、公式组 source 一次性使用、解释 links pending、强制性三态、条件和释义不重复、chunk/source-like 读取无损、partial 文档合法、分页变更和重试 ID 稳定、bbox 及 source lineage、缓存 version/digest 一致、全量 pytest/Ruff 回归。

异常/歧义案例要验证**安全退化**：不得发明内容，不得产生 validator 错误的 Document，不得丢掉真实 OCR 证据；诊断中必须明确阻塞条件。

## 6. 测试命令与严格交付

根据项目实际结构，运行并记录真实结果：

```bash
python -m pip install -e '.[dev]'   # 仅在项目依赖配置适用时，尽量复用已有环境
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest tests/contracts -q
python -m pytest -q
ruff check .
ruff format --check .
```

新增测试必须与已有测试隔离运行，不要求每次都加载 MinerU 模型；快速测试支持 fixture replay，真实 smoke test 单独显式触发。不得删减、跳过现有测试来凑通过。缺少 GPU / 模型 / 真实结果 / Ruff 时标明未验证，不得声称 PASS。

至少交付：

- 实际代码及模块级使用说明、接口文档更新；
- 真实 MinerU 选页运行和回放命令；
- `document.semantic.partial.json`（至少一组真实有效样本）、`semantic_source_lineage.json`、`semantic_pending_links.json`、两套章节树和正文/说明 Clause 汇总；
- `page_0049_semantic_overlay.png`、`page_0050_semantic_overlay.png`、`page_0126_semantic_overlay.png`、`page_0127_semantic_overlay.png`、`page_0282_semantic_overlay.png`（如该页有实测；其他页按测试配置）；
- `TASK_1_5_IMPLEMENTATION_REPORT.md`：设计、改动文件、测试数量与结果、真实页案例对照、缺陷与 OCR 噪声、未决关系、性能、Frozen 契约证明、Task 1.4 前置验证结果。

最终给出 `PASS`（所有强制项包括真实解析通过） / `PARTIAL`（核心逻辑通过但真实或上游不足） / `BLOCKED`（核心无法合法构建）及客观证据。只在真实测试支持时宣布通过。

**Task 1.5 完成后立即停止。不得自行开始 Task 1.6、Chunking 或 RAG。**

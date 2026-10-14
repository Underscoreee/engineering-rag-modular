# Codex 修复任务：Document Parser 人工核查反馈专项修复（GB 50010，PDF 物理页 1–48）

## 0. 背景、输入和总约束

目前 Document Parser 已实现 `PDF → MinerU → 表格 / 公式语义重建 → Sections / Clauses → Document Schema V2.4`。用户人工核查了完整解析后的前 48 个物理页并修改了 JSON，提供：

- **原始解析输出**：`document.v2.4.partial.json`
- **人工修正版对照**：`document.v2.4.partial-人工已核查1-48页.json`
- **原图 Overlay**：`page-0024.png`、`page-0025.png`、`page-0026.png`
- 以及项目已有的原始扫描版 GB 50010 PDF 和 MinerU MiddleJson/sidecar（在仓库中搜索真实路径）。

**要求修复解析流水线，不是人工修改最终 JSON，更不得硬编码 PDF 页号来替换结果。** 先阅读 `AGENTS.md`、冻结 `contracts/documents.py`、现有公式/table/semantic/assembler 相关模块、`derive_clause_plain_text`、source lineage 与 Artifact 政策。修改仅限 Parser 私有实现、必要脚本、测试、诊断及模块文档。

**Document Schema V2.4 = Frozen。禁止修改公共 `contracts/**`、Protocol、现有 ID 与来源规则。** 不重构 Chunking / Retrieval，不重跑 441 页 MinerU，不更换解析引擎。改动前保存真实输入快照，记录 git 状态、模型版本、原 PDF SHA256 和输入文件哈希。

注意：两份 JSON 都包含 441 页；只有 **前 48 页**按用户说明进行了人工核查，不可声称其余 393 页有金标。独立核对发现：人工修正版从 `pages[].blocks` 中删除的 **14 个 Block ID 仍全部被 `clauses[].source_block_ids` 引用**，属于实际悬空引用（例如 Clause `3.3.2` 所引用的旧 `S` 说明 Body、Clause `3.4.3` 的表注 3 和 4）。`clauses` 与 `sections` 未做同步更新；因此手工文件只用于**字段级核查线索与人工纠正候选**，不是整体可直接替换的有效最终 Document，也不是正式有复核人的 Golden Dataset。所有删除需经当前源码引用图检查。

## 1. 现有真实 JSON 对比中确认的事实（用于 RED fixture）

1. 物理页 17、18、19、20：人工对照共将 **23 个** `title` Block 改为 `body`（17 页 6 个、18 页 10 个、19 页 5 个、20 页 2 个），例如 `2.1.1 混凝土结构 ...`、`2.1.15 ...`、`2.2.1 材料性能`、`2.2.3 几何参数`。`2.1.x`、`2.2.x` 是 **条文/术语编号**，不是章/节标题；真正章节标题如 `2.1 术语` 应保留。
2. 物理页 24 的公式 `3.3.2-1`、`3.3.2-2` 同一个 FormulaGroup；原解析中 `S——承载能力极限状态下作用组合的效应设计值……` 在独立 Body 里，没被归入 SymbolExplanations；人工版已将 `S` 补到组级 `symbol_explanations.items` 并去掉重复 Body。
3. 物理页 24 最后一个符号解释 `f_c、f_s` 的 `description` 截断于 `应根据本规范第`；第 25 页首行 `4.1.4条及第4.2.3条的规定取值；` 是该描述续文，**不是标题/不是新 Clause**。第 25 页第二段 `a_k——几何参数的标准值 ...` 仍应归入第 24 页公式组的符号解释。其后 `注：公式(3.3.2-1)中的γ₀S……用N、M、V、T等表达。` 属于该公式组的印刷注释，不是第 25 页的新 Clause。下一条 `3.3.3` 是该跨页公式组必须停止的位置。
4. 物理页 26，逻辑表 `表3.4.3` 原有 notes 1、2，人工补充 3、4；两条独立 Body 亦被人工移除。
5. 物理页 27，逻辑表 `表3.4.5` 原来 `notes=null`，人工收集 1～7 条注解并移除重复 Body。
6. 物理页 28～29，跨页逻辑表 `表3.5.2` 原 notes 1、2，人工补充第 29 页续表后的 3～5 条并去掉重复 Body。
7. 可见页脚印刷页码（例如物理页24右下角 `9`、物理页25 `10`、物理页26 `11` 等）作为独立 Body 混入 `pages[].blocks`；用户要求不进入最终 Document。**`Page.page_number` 物理页、`Clause.page_start/page_end`、`TableFragment.page_number` 不得删除或替换**。
8. 人工文件还对物理页 41 表格注释做了补充，可作为邻近扩展回归；表格 `data` 在第 26、28～29 页也有手工改动，不得把本次表注修复误当作表格单元格全面正确。

## 2. 修复 A：标题/条文/术语边界识别

- 审查 MinerU `title`、字体/缩进、section builder 与 clause boundary 的冲突处理。新增优先级明确的领域规则：
  - `章`: `1 总则`；`节`: `2.1 术语`、`3.3 承载能力极限状态计算`（适当上下文和版面佐证）。
  - `条文`: `2.1.1`、`2.1.15`、`2.2.1`、`3.3.2`、`3.3.3` 等，必须进入 Body 语义/Clause，即使上游 MinerU 标签为 title 或该条以术语名词开头。
  - `分项`: `1 结构构件……` 或 `（1）` 等，归属已有 Clause 的 list_item，不可因数字开头被当 Chapter/Clause。
  - 公式号 `(3.3.2-1)`、表号 `表3.4.3`、条文引用 `第4.1.4条` 都不创建新的标题、条文或公式对象。
- 不允许仅对物理 17–20 页施加规则；第 16、24、25、26、49–50 页反向测试要仍能识别真正章节标题和 Clause。
- 来源 Block 的稳定 ID、bbox 和 OCR 文本应尽可能保持；对 `block_type` 修正后，必须**重新组装 Section/Clause/ContentUnit**、更新来源引用和 plain_text cache/digest；不能只改 `pages[].blocks[].block_type`，让下游持有错误标题引用。

## 3. 修复 B：公式符号解释识别（单页与跨页）

- 公式语义抽取至少处理 `[公式行/编号] + 式中 + 多个 symbol——description + 本页结尾 + 次页开头的续写段落 + 可能的“注：公式……”`。
- 原始 MinerU 大 Body 中若出现一段或多段符号解释，要依据**正文起止 / 符号边界 / 阅读顺序 / bbox**逐段消费；可识别 `S`、`R`、`R(·)`、`γ_Rd`、`f_c、f_s`、`a_k` 及 LaTeX OCR 表达，中文说明跨行/跨页连续时不得拆成多个无关实体。
- 本页 `S` 既可以作为普通变量和解释项，也会出现在公式 LaTeX 中；不得只靠 `S` 单字符字符串搜索误吞普通正文。
- 特别断点：第 24 页 `f_c、f_s` 的说明不能止于 `应根据本规范第`，要和第 25 页 `4.1.4条及第4.2.3条的规定取值；`拼接，保持真实原文空格、标点与上下标语义，不擅自改错；第 25 页 `a_k` 是独立第 7 项符号解释候选（要以实际 OCR 和原 PDF 核验）；`注：公式(3.3.2-1)…` 单独作为**组级印刷注释**，绝不可误认为表注。
- 新正文 `3.3.3` 出现时结束跨页公式合并；不吞 `3.3.4`、`3.4` 等后续段落。
- 所有已被正确、完整语义结构化的原 Body 原文不再重复出现在最终 `pages[].blocks`；对于混合 Body 只消费对应 span，不能删掉未被消费的普通正文；原始 OCR/BBox、来源块 ID、消耗范围、置信和修复理由必须保留在不可变 raw artifact + Parser 私有 sidecar。

## 4. 修复 C：跨页 FormulaGroup（保持 V2.4 不变）

**重要技术事实**：冻结的 V2.4 `FormulaGroup` 只有 `equations[]` 与 `symbol_explanations`，`Equation` 有 `latex`, `text`, `equation_number`，`PageBlock.ocr` 有 `text` 与 `formula_group`，没有顶层 `formulas[]`、`FormulaGroup.notes[]`、`FormulaGroup.fragments[]`。`PageBlock.bbox` 是**单页坐标**。不能仿照 table 给公式直接添加未冻结公共字段。

请在 Parser 私有层设计类似跨页 LogicalTable 的 `CrossPageFormulaAssembler` / `FormulaContinuationSpan`（命名可按现有项目）来做**一套逻辑组 / 多个来源 fragment**：

1. 确定首次出现页的 **canonical FormulaGroup Block**（本样本物理页24）及其稳定 `formula_group_id` 和两个稳定 `formula_id`（3.3.2-1、3.3.2-2）。
2. 从第 25 页开头识别 continuation fragment，合并第 24 页的未完符号解释 + 第 25 页的 `a_k` + “注：公式……”；Parser 私有 sidecar 记录 `group_id, ordered_fragments[{page_number, source_block_id, source_span, bbox, semantic_role}], page_start=24, page_end=25, consumed_source_ranges, note_target_formula_ids, pending_state`。只有来源充分时才能完成合并，缺第 25 页时明确 pending，不猜测。
3. 最终 Document 中公式组**只保留一个权威语义表示**：第 24 页的 FormulaGroup 承载完整 `equations` 和可表达的 `symbol_explanations`；第 25 页的已消费 Body 不应重复出现。对跨页文本贡献的精确位置，必须由 sidecar 保留，而不是把跨页 bbox 强行扩成一个不存在的跨页矩形。
4. 对 “注：公式（3.3.2-1）……” 的表示：先检查当前冻结 renderer 与对象字段能否在**不违反语义、不重复、不遗漏、保留原顺序**的情况下表达。允许使用已有 `PageBlock.ocr.text` 或可靠的 `Equation.text` 派生**完整可读文本**，但 `Equation.text` 一旦非空，冻结 `derive_clause_plain_text()` 会优先用它而不使用 LaTeX；因此它必须同时包含相关公式本体、编号及注释，绝对不能只写注释而让公式丢失。不要将印刷注释强塞进 `symbol_explanations` 伪装为一个数学符号，也不能将 `a_k` 描述当成独立公式。
5. 若现有冻结字段确实无法同时满足**跨页组注释的权威语义、阅读顺序和 `derive_clause_plain_text` 可读性**，在不改变 V2.4 的前提下，将完整注释存于有来源的 Parser 私有 sidecar，并明确告知目前 Document/renderer 表达能力的局限、给出 ADR 供下一个 Schema 版本评审。不得偷偷修改 Frozen public contract，也不能谎称完全解决了这个限制。
6. 清理独立 Body 后，重建 Clause 3.3.2 的有序 ContentUnit、`source_block_ids`, `page_start/page_end`, `plain_text`, `plain_text_renderer_version`, `plain_text_source_digest`，按冻结 validator 校验。若 Clause 中只引用第 24 页的公式 Block，其物理第 25 页补充来源仍需在 sidecar 及 Clause 页范围中真实留痕；**不能构造悬空的跨页 Formula Block ID / Formula ID**。
7. 选页 24（缺 25）与 24–25、23–26 的三种模式均需测试。不允许将缺页的未完公式误报 complete；跨批次 resume 后应可重新关联、幂等输出。

## 5. 修复 D：表注恢复与去重

围绕 `LogicalTable.notes: list[TableNote] | None` 做区域/编号/跨页后处理，而不只看 OCR 第一行是否为“注：”：

- `表3.4.3`（页26）：notes 应包含 1～4；表格第 3、4 条注释不能继续留作独立 Body；标题、表头、合并单元格、数据值不因修复而改变。
- `表3.4.5`（页27）：notes 应包含 1～7；手工版已完整记录长段多行注释，OCR 被拆成多个 Body 时要能合并；第 28 页若另有表格不能错误续接。
- `表3.5.2`（页28–29）：notes 应包含 1～5，后 3 条从第 29 页**续表后**找到并并入顶层该 LogicalTable。不能只取 28 页第一页；不能误将注释 3～5 归入第 29 页后续的 `表3.5.3`。
- 第 41 页表 4.2.6-2 的第二条注释作为非硬编码扩展样本。
- 处理 `注：1…` / `2…` 后续延伸、跨行、跨页、分号结尾、OCR 数字前后空格、非注释数字分项、表之后真实新 Clause 等正反例。
- 只有语义被 `LogicalTable.notes` **完整消费**且没有其他来源引用冲突，才在最终 `Page.blocks` 移除 Body；不完整部分、其它 Clause 文本留原位并报告。重新检查所有 TableFragment / RawGrid、`columns` / `data` / `notes` 和跨页 Clause 引用；原始来源留 sidecar。

## 6. 修复 E：印刷页码不进入最终 Document

- 对所有 `pages[]` 使用**通用页眉页脚识别器**过滤“单独印刷页码”Block，如页 24 尾部 `9`、页 25 尾部 `10`、页 26 尾部 `11`；参考几何位置（页上/下边缘）、版式奇偶页交替、相邻页连续编号和 OCR 语义，不能**只要纯数字就删除**。
- 不删除正文编号 `1/2/3` 分项、公式号 `(3.3.2-1)`、表内单元格数字、真实章节编号、目录中的结构性页码信息（除页眉/页脚孤立装饰数字）、标准编号 `GB 50010-2010`、日期或数据。
- 对单个 Body 混有正文+页码情况仅在有 span/bbox 证据时部分消费；证据不足保留并生成待审诊断。
- 最终 `Page.page_number`（PDF 物理页）照常保存，不新增/恢复已删除的 `printed_page_label` 字段。页码来源可保留在 raw 私有 sidecar 用于审计，但不能形成最终 PageBlock、Clause 或 plain_text 内容。
- 清理前验证旧 `block_id` 是否被 Section/Clause/ContentUnit 或跨页 Table/Formula 等引用；更新合法引用/缓存/阅读顺序，检查不会造成 dangling IDs。不要只在 Overlay 隐藏，**JSON 本体也必须过滤**。

## 7. 测试策略：先 RED，后 GREEN

1. 用原始 JSON + 人工修正版 **1–48 页指定改动**生成差异 fixture，记录 block_id、table_id、期望字段和来源；不能把人工版中已经删除、但未同步的 Clause 复制成最终断言。
2. 本轮严格回归：
   - 第 17–20 页上述 23 个 Block 的类型均为 Body，真正章节标题不倒退；对应 Clause 来源合法。
   - 公式 `3.3.2-1`, `3.3.2-2` 与组级 `S`、`f_c、f_s` 跨页完整说明、`a_k` 均可获得；印刷注释仅一次；第 25 页 `3.3.3` 起的正文完全保留。
   - `表3.4.3` notes 1～4；`表3.4.5` notes 1～7；`表3.5.2` notes 1～5，且第 29 页 `表3.5.3` 和 `3.5.3` Clause 未受影响。
   - 最终 1–48 页页脚孤立页码不留 PageBlock；后续抽样页及 441 页的过滤处理使用相同通用策略。对正文数字、表格数据和公式号执行误删反例。
3. 验证部分解析/选页：单页 24、跨页 24–25、跨批次 24/25、表 28–29、缺失续页、续写源文本不完整、公式注释与下一条 Clause 混杂、数字开头正文、纯数字在表格中、仅页脚印刷数字。
4. 重复运行两次输出相同 ID 与 JSON 内容；原始 MinerU raw 不变；新 Page/Block bbox 与 page bounds 合法，跨页来源仅在 sidecar 使用多页 bbox 列表。
5. 重新完整 `Document.model_validate(...)`、JSON round-trip、`validate_document_references()`、所有已涉及 Clause `derive_clause_plain_text()` 缓存 version/digest 校验；不可删除/跳过原有测试以凑 PASS。
6. 执行完整 pytest、Task 1.6 真实保存产物 Replay 集成测试、`ruff check .`、`ruff format --check .`。不要为了这些局部问题默认重新进行 441 页 live MinerU 推理；先从真实存档 raw 重放，若有可用少量页面 live 推理再单独验证，并标明运行模式。

## 8. 交付物

- 实际 Parser 私有源码最小改动与必要测试。
- 修复前后 diff：`Document.pages[].blocks`、`tables[]`、`clauses[]`、源引用变化与可能的未决项。
- `document.v2.4.repaired.json`（不要覆盖人工版、原始版）、`manual_review_repair_diff.json`、`cross_page_formula_lineage.json`、`table_note_consumption.json`、`page_number_filter_diagnostics.json`、修复后的 17–20/24–29 页 Overlay。
- 可执行的 Replay 命令、完整 pytest/Ruff 日志、V2.4 引用图校验与数据丢失/重复消费检测报告。
- 报告明示 **完全解决**、**部分解决**、**受 V2.4 表达能力限制** 的字段和具体原因；没有证据不能将未验证 OCR 标记 `verified`。

**修复后停止并等待独立验收；不得进入 Chunking，不得修改 Frozen V2.4，不得无授权执行全本 441 页 live 推理。**

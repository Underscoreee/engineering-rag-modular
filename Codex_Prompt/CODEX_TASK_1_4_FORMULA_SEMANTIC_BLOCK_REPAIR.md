# Architecture Task 1.4 补充修复：公式完整语义 Block 与来源去重

## 任务目标

基于 `\data\eval\task1_4_formulas\runs\final\GB-E621\overlays\page-0050-formulas-fixed.png` 和 `\data\eval\task1_4_formulas\runs\final\GB-E621\document.fixed.partial.json`，修复工程规范公式的语义边界。一个公式 Block 应是一段**可独立检索的完整公式组**：包含适用条件、公式表达式、印刷编号、与该组相关的“式中”符号说明；所有已被该 Block 完整消费的来源文字不得再次作为独立 PageBlock 出现在最终 Document 中。保持 Document Schema V2.4 Frozen，严禁增减/修改其公共字段及 Protocol。

## 一、从真实样本复现

GB 50010-2010（2015 年版）PDF 物理第 50 页当前共有 15 个 Block：7 个 formula、8 个 body。

- 公式 6.2.1-1 至 6.2.1-5 各占一个 formula Block，但其后六条共享的 `symbol_explanations.items` 只放在 6.2.1-5 的 Block 上。
- 公式 6.2.1-6 和 6.2.1-7 各占一个 formula Block，但其后两条共享的解释只放在 6.2.1-7 上。
- 两个“当……时”条件还分别作为独立 body Block，虽已被写入 6.2.1-1/2 的 `Equation.text`，形成两份语义内容。
- 末尾 `\sigma_{p0i}` 的解释正文被部分写入第二组 `symbol_explanations`，相同可见文字又独立保留为 body Block。
- 条件 6.2.1-1 的 OCR 原文误识为 `\ll`，原图为 `≤`，修正已进入 Equation.text，但错误的原始 condition Body 仍在 Document 中。

先用现有真实产物复现，再处理。不得用手工伪造 JSON 代替真正修复 MinerU → Document 的生成路径。

## 二、最终目标数据形态

**按共享的“式中”解释划分公式组，而不是简单要求每个编号公式都单独占一个 Block。**

- `formula_block_A`：唯一 FormulaGroup，含 Equation 6.2.1-1、-2、-3、-4、-5（共 5 项），并含其后共同的六条 `symbol_explanations.items`。把 6.2.1-1 的条件 `当 ε_c ≤ ε_0 时` 与 6.2.1-2 的条件 `当 ε_0 < ε_c ≤ ε_cu 时` 分别归于正确的 Equation；不扩散到 -3 ～ -5。
- `formula_block_B`：唯一 FormulaGroup，含 Equation 6.2.1-6、-7（共 2 项），并含其后共享的两条 `symbol_explanations.items`。末尾跨页/截断的 `\sigma_{p0i}` 解释必须明确标记未完结与待续接，不得伪造下一页文字。
- 最终 `Page.blocks[]` 中不再有单独的条件 body、完整消费的“式中”说明 body 或它们的重复副本。保留正常正文（“2 不考虑……”“3 混凝土……”“4 纵向……”“5 纵向……”）以及页码；在本次样本的所有重复来源均被安全消费时，预期为**2 个 formula Block + 5 个其它 body Block = 7 个 Block**。若因无法确认某段是否完整消费而暂时保留，则须给出逐条诊断，不得强行凑数。
- `formula_group.equations[]` 中七个 `formula_id`、`equation_number`、`equation_number_status` 及 LaTeX 不丢失；`symbol_explanations` 放在组级，而不是错误地仅归于最后一条公式。
- `bbox` 为该语义公式组**全部已归入内容**（适用条件、各条公式、印刷编号区域、符号解释）的 PDF points bbox 的并集，限制在页面范围内。不能保留仅覆盖公式行的小 bbox，却让 Block 语义包含其外大量文字。
- 保留 Parser 内部 sidecar，记录每个 Equation、条件、公式编号、每条符号解释的原始细粒度 bbox；overlay 绘制语义组边框以及各个内部组件的不同样式细框，不能因合并丢失精确定位。

注意：V2.4 不存在独立的 Equation.condition 公共字段。遵守既有 `Equation.text` 约定：对于含条件的 Equation，`text` 必须包含**适用条件 + 对应编号 + 完整公式可读表达**，不能只有条件；`latex` 保留公式本体。对渲染和 Chunking 进行测试，避免 `text` 优先导致丢掉 LaTeX 的有效公式内容。没有条件的 Equation 不得继承其他公式条件。

## 三、必须实现的处理顺序

1. **保留原始引擎结果**：MinerU MiddleJson/structured content 不可改写，原始 OCR/原始 bbox 进入持久化私有 source sidecar。
2. **页面级语义识别**：提取 FormulaCandidate、ConditionCandidate、SymbolExplanationCandidate、OrdinaryBodyCandidate，包含原始 source IDs、文段范围、页面位置和阅读顺序。
3. **条件关联**：利用“当……时”语义、方程上下位置、编号及页内相邻关系，将条件绑定到具体 formula_id。辨别 `≤` 和误识的 `\ll`：仅在有扫描图证据及显式纠错记录时修正，禁止全局盲替换。
4. **符号说明归属**：识别“式中：”开始、后续同段的符号解释列表，依据上下文绑定到连续公式组；不得只把说明归到其前一条公式，亦不得复制到组内每条公式。编号正文引用（例如“公式（6.2.1-5）”）不可误当一个新公式。
5. **FormulaGroup 语义合并**：把共享说明的连续公式构造成一个 V2.4 PageBlock，其 `ocr.formula_group.equations` 为完整有序数组，`symbol_explanations.items` 为共有说明。公式分组不得跨越独立编号条目、其他正文或不相关“式中”组。此页应为组 A（1～5）与组 B（6～7）。
6. **来源消费和去重**：只在确认 `source_segment -> semantic_component -> formula_group` 的归属且目标字段已保存信息时，移除相应 source body 的最终 PageBlock 表示；如果 source body 同时含普通正文，必须按文本片段拆分、只消费已归入的部分。对截断文本，如果其**当前可见文本**完整保存在 `symbol_explanations`，允许从最终 body 消费，但同时必须记录该条解释仍不完整，等待后续页面补全。不能用纯字符串相似度或 bbox 包含关系直接批量删除。
7. **保存 ID 映射**：七个 `formula_id` 必须稳定；对合并前 `block_id` 和 `formula_group_id` 的旧→新映射保存 alias/lineage sidecar。已有 Section/Clause/ContentUnit 引用时必须更新并重新验证或安全中止，不能产生悬空引用。新组级 block ID 按项目既有稳定 ID 策略生成，重复执行不得改变。
8. **重排阅读顺序和输出**：生成最终 V2.4 Document，再对 Document 重新完整 Pydantic 校验和 JSON 往返。`plain_text` 渲染在包含 Formula Group 的测试 Clause 中必须按准确阅读顺序输出，公式、条件、编号、解释均只被语义渲染一次。对 `\tag{}` 和 `equation_number` 双来源避免可读文本重复编号。

## 四、Parser 私有 sidecar（不得写入 Frozen V2.4 公共字段）

至少记录：`source_id`、原始 `block_id`、PDF 页码、原 OCR 文本、原 bbox、原始状态、`consumed_text_ranges`、`target_formula_group_id`、`target_formula_id`（若适用）、`semantic_role` (`condition`/`equation`/`equation_number`/`symbol_explanation`)、`component_bbox`、`confidence_or_review_status`、`corrected_from`/`corrected_to`、`correction_evidence`、跨页未完结标记、旧新 ID 对照。

原始证据和历史解析产物不得原地覆盖；诊断报告区分：完整消费、部分消费、未消费/有歧义、OCR 纠错、跨页待续接。

## 五、必须新增的测试

1. 第 50 页从原始 MinerU 产物重新解析后，最终含 7 条编号公式，且只构成 2 个 FormulaGroup Block；每组包含 5 和 2 条 Equation。
2. 组 A 的 6 条共享解释恰好一份，组 B 的 2 条共享解释恰好一份。
3. 两条“当……时”条件不再留作独立 Body；准确绑定 6.2.1-1、-2，且 6.2.1-3～5 不继承错误条件。错误 `\ll` 不进入最终检索文本，但保留在 sidecar 原 OCR 中。
4. `\sigma_{p0i}` 的已见内容只出现在组 B 的 explanation 中一次；未完结状态显式保留，不能凭空补出后续句子。
5. 保留普通 body 第 2、3、4、5 款和印刷页码“35”，不能误删除。
6. 组级 bbox 包含全部被归入的文本 bbox；各 Equation/condition/explanation 的细粒度 bbox 在 sidecar 内准确，overlay 颜色与数据一致。
7. 正反例：符号说明中混入普通正文、说明跨页、说明不完整、OCR 变量不一致、多个“式中”相邻、说明包含公式编号引用、单式独享说明、无编号公式、多行公式。
8. 在含有 Clause/ContentUnit 来源引用的合成文档中验证 group 合并后的引用完整性；没有可靠迁移方案时必须安全失败并输出诊断。
9. Formula Group 的 `derive_clause_plain_text()` 内容应同时包含条件、公式、编号、共享符号解释，各不重复；格式化并不改变原始结构化值。
10. 同一输入执行两遍，最终 JSON 和 sidecar 中的稳定 ID/映射一致；已有 Task 1.1、1.2、1.3、1.4 测试不回归。

## 六、测试和交付

- 先列出真实旧产物的问题和原始来源，再实现代码；不得仅仅手工改提交的 JSON 文件。
- 执行 `python -m pytest -q`、`ruff check .`、`ruff format --check .`；工具不可用要如实报告。
- 生成 `document.grouped.partial.json`、`formula_semantic_group_sidecar.json`、`formula_source_consumption_report.json`、`page-0050-formulas-grouped.png`、`TASK_1_4_GROUP_REPAIR_REPORT.md`。
- 报告内容包括合并前后 Block 统计、所有公式 IDs、条件关联表、共享说明列表、去重的来源范围、跨页待续接项、坐标检查、Document 校验与全部测试结果。
- 禁止修改 Document Schema V2.4 公共 Pydantic 模型、Protocol 和冻结文件；禁止提前实现 Task 1.5 条文领域识别、Chunking、检索或 LLM。
- 修复完成后停止，等待用户验收。

## 最终工程原则

**一个语义公式组只在最终 Document 中存储一次；一个来源 OCR 区域只能被一个语义组件消费；共享符号解释放在 FormulaGroup 级；源证据可多处引用，但不得作为独立、重复的检索语义 Block 再次输出。**

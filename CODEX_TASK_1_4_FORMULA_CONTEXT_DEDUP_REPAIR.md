# Codex 修复任务：Task 1.4 公式适用条件关联与符号解释去重（GB 50010 PDF 物理第 50 页）

## 0. 任务定位与禁止事项

本任务是 **Architecture Task 1.4 缺陷修复**，不是新增 Task 1.5。基于提供的真实图片 `page-0050-formulas.png` 和解析结果 `document.partial.json`，修复：

1. 公式 6.2.1-1、6.2.1-2 的分段适用条件虽已被识别为 Body，却没有关联到具体 Equation；其中第一条 OCR 将 `≤` 错写为 `\\ll`。
2. 两组公式的“式中”说明已存入 `symbol_explanations`，仍又以完整 Body Blocks 出现在 `pages[].blocks`，造成最终 Document 的重复信息。
3. 相关结构问题：公式 6.2.1-1～6.2.1-5 被打包成一个公式 Block（bbox y=99.27..215.47），中途插入的第二个条件是独立 Body（y=126.71..138.98），造成扁平化阅读顺序语义错位；需要恢复公式级的阅读顺序和条件绑定。

**必须保持 Document Schema V2.4 FROZEN**：不得修改 `src/engineering_rag/contracts/**`、Pydantic 模型、Protocol、公共 Schema 常量/验证规则。只改 Document Parser 私有后处理、sidecar/归一化导出、overlay、测试和相关说明。不得启动 Task 1.5、Chunking 或 RAG 算法开发。

先检查 `AGENTS.md`、当前 Task 1.4 源码及已冻结的 `Equation`, `FormulaGroup`, `PageBlock`, `derive_clause_plain_text`，读取 MinerU 4.0.12 原生 MiddleJson、现有 `document.partial.json` 与 overlay。**先复现，再修复。** 两个附件仅提供当前失败样本，不可臆造未上传的 raw MinerU 字段；如缺失，报告来源限制，使用真实输入可复现时重跑。

## 1. 已从用户真实样本确定的事实

| 来源 | 数据及问题 |
|---|---|
| PDF 物理页 50, block reading_order=2 | `当\\varepsilon _ { \\mathtt { c } } \\ll \\varepsilon _ { 0 }时`：确实被识别，但关系符 OCR 错，**图片可见的是 `εc ≤ ε0`** |
| formula block `block-7e43ec7515fd58c0aaa5b6277b8f1df6` | 同组包含 `6.2.1-1` 至 `6.2.1-5`，带 6 个 symbol_explanations |
| body block `block-8dd8b2fd620a5d8392b742500a7bfad1`, reading_order=4 | `当\\varepsilon _ { 0 } < \\varepsilon _ { \\mathrm { c } } \\leqslant \\varepsilon _ { \\mathrm { c u } }时`，**对应 6.2.1-2**，不是 6.2.1-3～5 的适用条件 |
| Body reading_order=5..10 | 6 个“式中”解释 Body，与第一个 FormulaGroup.symbol_explanations 重复 |
| formula block `block-30a4969a526b57a48e9ed75fe0b6135c` | 包含 `6.2.1-6`/`6.2.1-7`，已拥有 2 条 symbol_explanations |
| Body reading_order=14..15 | 第二组两条“式中”说明又作为 Body 出现，且后一行截断，需要保留未识别完整性的诊断 |

当前 `clauses.normative`、`clauses.explanations` 均为空，不能假称已经做了 Clause 关联。

## 2. 适用条件：识别、几何关联、公式语义闭环

### 2.1 内部统一候选和证据（非公共字段）

在 Parser 私有中间层引入条件识别 / 关联类型，例如 `FormulaConditionCandidate` / `FormulaApplicabilityLink`：

- `condition_id`；`raw_source_block_ids`；`source_page_number`（原 PDF 1-based）；`raw_text`；`normalized_text`；`bbox` 与坐标系；`target_formula_ids`；`match_evidence`（上下文 / 阅读顺序 / 几何 / 印刷编号 / 分支关系）；`confidence_or_review_status`；`diagnostics`。
- 候选识别应覆盖 `当…时`、`若…则`、`对于…`、`适用于…` 等工程规范句式，并**结合邻近公式和断句**，不能把所有相邻 Body 都粗暴归到下一公式；本次至少实现本页两条“当…时”的明确关系。
- 不能仅凭“最近的上一行”分配：条件可能位于一个大公式块 **内部**；先获取单条 Equation 的细粒度布局证据，按相对阅读顺序建立映射。
- `6.2.1-1`: `ε_c ≤ ε_0`。`6.2.1-2`: `ε_0 < ε_c ≤ ε_cu`。`6.2.1-3`～`6.2.1-5` 是参数/定义式，不能继承上述某个分支条件。
- 遇到两条近邻公式、多个候选条件、歧义、缺失或 OCR 关系符不可靠时，不猜测。保存原始候选及 `unresolved` 诊断；需要人工复核时不给 `verified`。

### 2.2 对 OCR 关系符的修复必须有图片证据

- 保留 MinerU 原样 `\\ll` 于 raw sidecar；检查原图区域后将**标准化后的候选**修为 `\\leq` / `≤`，注明 `ocr_math_relation_corrected_from_visual_evidence` 和原 crop/bbox；不要全局 `\\ll` → `\\leq`，因为数学中两者含义不同。
- `ε_c` / `ε_0` / `ε_cu` 的符号规范化限于有证据的无损格式统一；不可凭工程常识自动修正其它公式数值、符号和识别错误。

### 2.3 映射到现有 V2.4，保证单条公式可读

冻结 V2.4 **没有** `Equation.conditions` / `applies_when` 等字段，也没有单 Equation bbox：

1. 保留完整标准公式在 `Equation.latex`，不要将条件拼接成数学等式、也不要破坏已存在的 `equation_number`。
2. **使用既有 `Equation.text` 保存面向检索/阅读的自包含文本**，仅对证据充分的公式填充，例如：
   - `6.2.1-1`: `适用条件：当 ε_c ≤ ε_0 时。公式（6.2.1-1）：<该 Equation 原始完整 LaTeX 表达式>`
   - `6.2.1-2`: `适用条件：当 ε_0 < ε_c ≤ ε_cu 时。公式（6.2.1-2）：<该 Equation 原始完整 LaTeX 表达式>`
3. 上述 `<...>` 必须替换为**实际 Equation.latex 表达式**，不是占位文本；已有 `Equation.text` 另有可靠语义内容时，应合并而非覆盖。`Equation.text` 只是派生的完整可读文本，原始 OCR、条件原 Block 和精细绑定证据保存在 Parser 私有 sidecar。
4. **特别注意**：冻结的 `derive_clause_plain_text` 用 `equation.text or equation.latex`。因此绝对不能只向 `Equation.text` 写入条件，否则会让公式本身在 Clause plain_text 丢失。写完必须用真实公式和含符号释义的合成 Clause fixture 测试最终渲染包含条件、公式表达式和解释。
5. 仍保留条件源 Body Block 作为页面忠实 OCR 证据（其余条文识别需要它）；在未来 Clause / Chunking 使用时，通过 sidecar 的消费/上下文规则确保不重复渲染条件。**本轮不新增 Clause。**
6. 如果当前 `FormulaGroup` 粗框跨过中间 Body，尝试用 MinerU 单式 span/bbox（或可回放的局部解析证据）将组拆成能按物理顺序排序的 Formula Blocks。共享符号解释只保留一个权威归属，并用私有 `explanation_scope` 映射其适用的 formula_ids，避免拆组后重复。**没有可靠细粒度 bbox 就不能凭空拆分或编造坐标**；此时保留组并在 sidecar 记录内部交错事件及未解决的扁平化阅读顺序问题，不能宣称阅读顺序完全修好。

## 3. SymbolExplanations 去重：单一权威表示与来源保留

### 3.1 分离三个层次

- **原生识别层（不可变）**：MinerU MiddleJson、OCR lines/bbox/crops 始终原样保留。
- **Parser 私有证据层**：记录 `source_block_id -> target_formula_group_id, symbol item index, matched source span, duplicate_disposition, review_status`。具体可叫 `ConsumedSourceSpan`、`FormulaSemanticCoverage`。
- **最终 V2.4 Document**：已可靠、**完整**结构化为 `symbol_explanations` 的“式中”说明，**不得再作为独立 Body 重复保存**；其权威语义存储位置是 `FormulaGroup.symbol_explanations.items`。不能仅靠 overlay 不画它们，JSON 也必须去重。

### 3.2 何时可移除 Body；何时不得移除

- 对每个 Body/source span：用 source IDs + span 字符覆盖率 + 几何/阅读顺序 + SymbolExplanationItem 对应关系证明其内容已完整进入 `symbol_explanations`。可在原文清洗后比较，LaTeX 空格归一，但**不可以**只靠 substring、相同 `式中` 开头、或 OCR 文本高度相似就直接删块。
- 完全覆盖、无未保留尾注/单位/续行且确认不被 Clause 或其它对象引用：从 `pages[].blocks` 去掉重复 Body，记录 sidecar `consumed_body_block_ids`、原文字、bbox、来源哈希、对应 FormulaGroup / item index。将剩余 Block 的 `reading_order` 按稳定物理顺序重新赋值，原始 ID 不改。
- 部分覆盖：优先从**真实 OCR span/line 坐标**将已消费与未消费部分分开；保留未消费文字为 Body（不能凭空发明 bbox）。若无法可靠分离，保留原 Body + 标记 `dedup_unresolved`，并在面向检索的 Parser 私有去重视图只输出一次；绝不静默丢文本。
- 匹配失败 / symbol description 本身疑似 OCR 错误 / 缺失尾部 / 跨页未完成：保留源 Body，不以牺牲可靠性换取形式上的“零重复”。对这类项明确报告为什么仍存在重复风险，并建议人工复核；也不能将含糊的说明判为 `verified`。
- 如果目标 Body 已被现有 Clause.content_units 或其它冻结对象引用：不得直接删除造成 dangling references；本阶段不得擅自修改这些公共语义关系，可阻止删除并报告，或仅在可确保合法迁移且完整回归通过时处理。
- 不得为了看起来不重复而删除公式定义本身或正文条文：只有确实被语义结构化完全消费的说明性 OCR span 才可消去重复。

### 3.3 幂等性与来源追踪

- 对同一原始 MinerU 产物重跑 N 次，`formula_id`、`formula_group_id`、`block_id`、符号解释条目数、无重复状态必须稳定。
- 必须保留所有被消费的原始 OCR 和 bbox 到不可变 raw artifact 或 sidecar；生成文档仍通过冻结 V2.4 模型、跨引用校验、JSON round trip。
- Overlay 必须画出：条件（单独颜色并标目标 formula_id）、真实公式 bbox、已消费的说明 OCR 区域（即使最终不再作为 Body）、未消费的正文；图例清楚说明颜色与来源/语义层区别。
- 不能将仍然属于 OCR 原始文本、但已迁入 symbol_explanations 的部分当作“识别丢失”。

## 4. 本页重点回归测试（必须先 RED 后 GREEN）

请基于用户上传的**真实输出**固定脱敏/合法的 fixture，不修改原始文件。测试需覆盖：

1. `6.2.1-1` 的适用条件精确为 `ε_c ≤ ε_0`，不能出现 `\\ll`，原始 OCR sidecar 仍保留 `\\ll`；`6.2.1-2` 的适用条件为 `ε_0 < ε_c ≤ ε_cu`。
2. `6.2.1-1/2` 的 `Equation.text` 同时包含其正确条件、公式表达式，且 `Equation.latex` 完整不变。`6.2.1-3/4/5` 不错误继承条件。
3. 假阳性：正文讨论式（6.2.1-1）、任意两个相邻公式、缺失 OCR 条件、不确定关系符、跨栏条件，不得误绑定或自动验证。
4. 第 50 页首组 6 项和第二组 2 项符号解释不丢、不串组、不重复；当原 Body 完全匹配且无外部引用时最终 Document 不再存在那批重复 Body；原 OCR sidecar 必须可追溯。
5. 不完整说明、跨页被截断、半行说明后混有普通正文：不得删错；保留未消费内容并报告 `dedup_unresolved`。
6. 大组公式跨越插入的条件时，检查逐式的内部阅读顺序；如果没有真实逐式 bbox，不可通过编造 bbox 满足测试。若细粒度可信，则拆组后 body/公式排序正确且符号解释权威内容只出现一次。
7. 从最终结构构造**测试用** Clause content_units（不要在生产 Task1.4 构造 Clause），调用冻结的 `derive_clause_plain_text()`，确认条件、公式、符号解释齐全且均不重复；测试不可跳过第二个公式条件。
8. 相同输入多次重放幂等；既有表格/其余正文无变化；Document.model_validate / JSON roundtrip；原有公式编号状态、recognition_status 和 Document.processing.partial 不被错误提升。
9. 画出本页修复前后 overlay，并输出 Body 数量变化、保留/消费/待审清单及原因。

注意：仅存在的 17 个 Blocks 和当前 2 个 FormulaGroups 不是目标固定数量；如有可靠证据进行拆组，数量可以变化，但不得有丢失或凭空制造的内容。

## 5. 交付、命令及停止条件

- 修改 Parser 私有 `formula` 提取/分组/条件关联/去重后处理及 V2.4 构建逻辑；不得修改 frozen contracts。
- 新增含真实原始输出的回归 fixture，以及歧义/部分覆盖/重复重放等合成 fixture。
- 输出 `document.fixed.partial.json`、`formula_context_sidecar.json`、`formula_dedup_coverage.json`、`page-0050-formulas-fixed.png`、`TASK_1_4_REPAIR_REPORT.md`。文件放在当前项目规定的 artifact 路径，记录版本、hash 和来源，不覆盖 raw。
- 运行并记录 `python -m pytest -q`、`ruff check .`、`ruff format --check .`。如果依赖/实际 MinerU raw 不可用，明确报告 BLOCKED/PARTIAL，不能把 Mock 当实测。
- 在报告逐项对照上述测试，展示修复前后 `6.2.1-1/2` 条件及 symbol_explanations 的去重结果、来源证据、未解决问题。
- 只完成 Task 1.4 当前缺陷修复，完成后停止，等待验收。

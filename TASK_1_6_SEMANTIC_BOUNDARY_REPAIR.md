# Architecture Task 1.6 — 第 25 / 41 / 45 页语义边界与来源消费修复任务书

**适用项目：** Engineering RAG / Document Parser（模块化单体、Python 类型化接口）  
**修复阶段：** 端到端 Document Parser 的领域后处理专项修复  
**公共数据契约：** Document Schema V2.4 — **Frozen**  
**本轮目标：** 修正三项用户人工发现的实质性错误，建立可复用的条文 / 表注 / 公式解释 / 公式注释的边界判定和 lossless consumption 机制。不改其他模块，不默认运行 441 页实时 MinerU。

## 一、真实输入及基线审计（开始代码修改前执行）

项目工作区应提供：

1. `document.v2.4.partial.json`：此次完整上传的解析输出，**包含 50 个物理页**，`page_count=441` 表示原 PDF 总页数，不代表最终 JSON 已包含 441 页。
2. `page-0024.png`、`page-0025.png`、`page-0041.png`、`page-0045.png`：人工问题证据 Overlay；其中前两页显示公式注释在原页面上，41 页展示两式间引导文字，45 页展示表 5.2.4 后紧接条文 5.2.5。
3. `REGRESSION_EVIDENCE.json`：依据该 Document 提取的具体错误事实、ID 及期望，**仅用于定位 fixture 和验收，不允许在生产代码中以具体 ID / 页码硬编码**。
4. 原始 GB 50010-2010（2015 年版）扫描 PDF 和当次生成该 JSON 的真实 MinerU 原始数据、中间 normalized、公式/表格 sidecar、consumption ledger、run manifest、代码版本；应从仓库内核查路径，不可假定已附在本包中。
5. `AGENTS.md`、冻结 `contracts/documents.py`、表格/公式/语义装配模块及 `derive_clause_plain_text()`、`validate_document_references()` 等现有实现。

保存修改前 git 状态、输入 JSON 哈希、PDF SHA-256、模型版本、Parser 配置与已有 pytest 结果。 **原始输入 / 历史运行文件保持只读**。如果 MinerU raw 已丢失，应先报告证据缺口，在拥有原 PDF 的条件下只对相关小范围页面（24–25、40–41、44–45）发起受控实时重跑；绝不凭 Overlay 猜造 OCR 来源 span、bbox 或不存在的完整文本。

### 此次实物检查已确认

- 最终 `pages` 只有 50 页，`sections=21`、`tables=21`、`clauses.normative=116`。不要将 `page_count=441` 当作已全本处理的页数。
- 物理第 24 页 FormulaGroup 的编号为 `3.3.2-1`、`3.3.2-2`；`f_c、f_s` 与 `a_k` 的跨页解释已经进入该组，但 **“注：公式（3.3.2-1）……等表达” 在整个已上传的 pages/tables/clauses 中不存在**。
- 第 45 页表 `5.2.4` 的 `notes` 被写入第 5 条 `".2.5 当地基与结构的相互作用……"`，其开头编号 `5.2.5` 被拆成“表注序号 5”和“.2.5”。`clauses.normative` 没有 `5.2.5`，也没有独立 Body。
- 第 41 页公式 `4.2.6-1` 的符号解释说明中错误地拼接了 `预应力筋疲劳应力比值ρ_p^f应按下列公式计算：`；紧接着是编号 `4.2.6-2` 的下一 FormulaGroup，而中间应独立出现的引导 Body Block 已消失。

## 二、目标语义边界：分类优先级和结构判定

此次不是增加三条特判，而是修复现有“相邻文本 → 归属语义单元 → 消费源片段”规则：

1. **明确的新 Clause 开始标记**优先于表注、公式符号续写、正文延续。标准条文形式 `X.Y.Z`（允许排版空格与 OCR 变体）必须经数字分段、前后章节结构、行首位置、bbox 和真实分隔符共同判定；不能把 `5.2.5` 机械拆成 `5` + `.2.5`。
2. **真正表注**只有属于最近相关 LogicalTable，且满足“注：”引导、有效的注序列、表格区域与下一 Clause 边界检查时才能附着。表注可以独立换行、跨页、多行，但不得越过新 Clause/新表标题/章节标题。
3. **公式符号解释**需位于可信的“式中”上下文，含 `symbol — explanation` 的边界证据；遇到完整引导句、下一公式的引导条件、编号 Clause、章节标题，必须结束或暂挂 continuation。不能仅因两个段落几何接近就连接。
4. **公式印刷注释**例如 `注：公式（3.3.2-1）中的γ₀S ...` 要保留为 `formula_note` 语义角色，关联指定 formula/group，不是 `SymbolExplanationItem`，也不是 `TableNote`，更不是新 Clause。
5. 普通正文、公式前置引导句和条文号行均**必须有可检索的权威 Document 表示**；来源跨页时还要保留精确多页 provenance。不支持当前冻结字段的精细语义可在 **Parser 私有 sidecar** 增补，但不能因此把文字只留 sidecar 而从最终 Document 全部消失。
6. 任何含 OCR 正文的原始 source span 恰好为一种状态：`retained_in_authoritative_document` / `consumed_into_semantic_object` / `unresolved_pending` / `explicitly_filtered_decoration`。并记录去向、原因和源 hash。不得既消费为表注又写进独立正文，也不得消费后无最终去处。

## 三、修复 A — 第 25 页公式注释丢失（P1）

### 期望来源语义

第 24 页条文 `3.3.2` 包含公式 `3.3.2-1`、`3.3.2-2`，其组级符号解释跨到第 25 页。紧随其后的**原文印刷注释**位于第 25 页、在条文 `3.3.3` 之前，内容为：

> 注：公式（3.3.2-1）中的 γ₀S 为内力设计值，在本规范各章中用 N、M、V、T 等表达。

具体 OCR 字符和标点以原 PDF 与 raw evidence 核验为准；上句是人工提示，不可当做代替真实 OCR 的虚构 `source_block_id`。

### 实施要求

1. 从第 25 页 `raw middle_json` / normalized / 私有跨页公式 sidecar 与 consumption ledger 追踪此条注释的原始位置与身份：是否 OCR 从未识别、是否正确识别后被跨页 FormulaGroup 消费却未投射到 Document、还是被过度去重。报告首个丢失阶段及最小复现输入。
2. 在公式/表格/Clause 匹配之间建立明确的印刷注释路由：`注：公式（X）` 结合引用的印刷公式编号、所属 Clause、相对空间与阅读顺序，应优先走 `formula_note`；不能误入 `table.notes` / `symbol_explanations` / 下一 Clause。
3. **V2.4 结构边界**：经源码复核，`FormulaGroup` 目前只定义 `equations[]` 和 `symbol_explanations`，没有 `notes`；`Equation` 有 `latex`、`text`，`PageBlock.ocr` 有 `text` 和 `formula_group`，`Clause` 以 `content_units` 引用。不得在这些公有模型里偷偷新增 `formula_notes`、`page_spans`、`fragments` 等字段。
4. 推荐将结构化 `formula_note`、`target_formula_numbers`、`formula_group_id`、`source_page=25`、`source_block_id`、字符级 span/bbox、阅读顺序及 consume 状态保存到 **Parser 私有 `formula_semantic_sidecar`**，并同时**明确保证最终 V2.4 Document 的 Clause `3.3.2` 可检索到该注释恰好一次**。
5. 在冻结契约投射时遵循优先级：**不丢失/不重复/可追溯 > 结构化语义保真 > UI 展示**。若没有合法的组级 notes 字段，可选择保留一个归属 Clause `3.3.2` 的公式注释 Body 内容单元，并在私有 sidecar 显式连接到 `formula_group_id`，或经严格测试后使用已有 `Equation.text` 做无损文本投影；但后者必须保留原公式本体、编号和正确阅读顺序，且不得把说明错放在其他公式上。不要仅填 `PageBlock.ocr.text` 就假定 renderer 会读到它：**冻结 `derive_clause_plain_text` 对 Formula unit 主要使用 `equation.text or equation.latex`，忽略 formula Block 的 `ocr.text`**。
6. 如果无法在冻结 V2.4 中同时做到“一个 Formulagroup 内部有正式 notes 字段、Clause 正确可读、组级引用无损”，明确在 ADR 记录限制，保存兼容的权威正文投射 + formula_note 私有关系，**不得宣称公有 JSON 已具有不存在的结构字段**。
7. 确保第 24 页公式块 ID / 公式编号不重复、第 25 页的 `3.3.3` 及以后内容完全保留；重建 Clause `3.3.2` 的 content units、`page_start/page_end`（包含第 25 页有效来源）、plain_text/摘要及来源映射。

### A 的通过断言

- 从全新解析的 Document 可直接获取 “注：公式（3.3.2-1）……N、M、V、T……等表达” 的完整文本，且 Clause `3.3.2` 可检索；恰好出现一次。
- formula-note sidecar 指向 `3.3.2-1` 对应 formula_id（允许组级共有）和真实第 25 页 source span；新条文 `3.3.3` 不包含该注释。
- Formula `3.3.2-1`、`3.3.2-2` 的 LaTeX/编号与符号解释原有正确值保持，未将 note 伪装为符号解释或表注。
- 若原始 OCR 完全缺失此行，不能静默从提示补入并标 `verified`；先按事实保留失败诊断、最小页面重跑，若仍失败则按 missing-source 标为未完全修复。

## 四、修复 B — 第 45 页独立条文 5.2.5 被吞进表注（P1）

### 观察到的原错误

`tables[table_number="5.2.4"].notes` 中不应出现第 5 条；目前被错误消费为：

```json
{"number": 5, "content": ".2.5 当地基与结构的相互作用对结构的内力和变形有显著影响时，结构分析中宜考虑地基与结构相互作用的影响。"}
```

这是原 PDF 的独立条文 `5.2.5`。**当前 `clauses.normative` 中没有 `5.2.5`**。

### 实施要求

1. 找出导致 `5.2.5` 首字符被提取为表注序号 `5` 的原始文本 / 字符范围切分逻辑（一般来自 loose `number` 匹配、notes continuation、合并 OCR Body 等）。先恢复完整原文，不要直接将 `.2.5` 拼接 “5” 后掩盖消耗源数据问题。
2. 表注吞并之前先执行 Clause boundary 检测。匹配 `5.2.5` 应是完整 clause_number（允许 OCR 空白规范化），并以当前章节 `5.2`、邻接条文 `5.2.4` 与下一标题 `5.3`、行首及 bbox 为证据。查到新的独立条文后，强制停止表注收集。
3. 真正的表 5.2.4 注释保留 **1～4**，包括多行注 2～4；不得删除部分正文、表头、表格 `raw_grid`、`columns/data`、表号及已有表注结构。
4. 恢复第 45 页 `Page.blocks` 中独立 Body Block，文本为完整 `5.2.5 当地基与结构的相互作用……影响。`；建立 Clause `5.2.5`，正确挂至章节 `5.2`，位于 `5.2.4` 之后、`5.3` 标题之前；保存真实 bbox/reading_order/source lineage。若原始 OCR 不含句首 `5`，标识 OCR 错误并从可信来源做受控校正与 lineage，而不是无记录地猜测。
5. 刷新 Clause `5.2.4`、`5.2.5` 与邻近 `5.3.1` 的 `content_units`、`source_block_ids`、页范围、plain_text/cache/digest。避免表注和新条文在任何 authoritative 内容里重复出现。

### B 的通过断言

- `tables[5.2.4].notes` 仅有 1、2、3、4，不含 “当地基与结构的相互作用”。
- `pages[45].blocks` 中有规范编号 `5.2.5` 的独立 Body（非 title/表注），`clauses.normative` 中有且只有一个 Clause `5.2.5`，来源完整。
- `5.2.5` 不被并入 `5.2.4` 或 `5.3.1`；第 45 页表格本体不变。
- 负例：`注：5……`（合法表注）、`5.2.5` 出现在引用句里、公式 `5.2.5-1`、表号 `表5.2.5` 都不能被误切成新 Clause。

## 五、修复 C — 第 41 页下一公式引导正文被吞进前一公式符号解释（P1）

### 当前数据证据

`4.2.6-1` 所在 FormulaGroup 有一个符号解释：

```text
符号：σ^f_{s,min}, σ^f_{s,max}
错误 description：构件疲劳验算时，同一层钢筋的最小应力、最大应力预应力筋疲劳应力比值ρ^f_p应按下列公式计算:
```

在原图中，两个逻辑单元应当分开：

- 上一公式 **符号解释**：`构件疲劳验算时，同一层钢筋的最小应力、最大应力。`（精确标点按原 PDF）
- 下一公式 **引导 Body**：`预应力筋疲劳应力比值 ρ_p^f 应按下列公式计算：`
- 下一式：`4.2.6-2`

### 实施要求

1. 排查 FormulaGroup 构造 / `symbol_explanations` 多行合并规则：上一 SymbolDescription 的停止位置为什么越过了完整句边界并吞入下一公式引导正文。
2. 应依**符号解释起始 marker、中文句号、下一句语法功能（“……应按下列公式计算：”）、下一公式编号/几何顺序**同时判断。句号并非一概截断（合法说明可含多个完整句）；须同时具备“下一公式的引导句”及附近的下一 Formula 证据，避免在普通长描述内错误分裂。
3. 从 raw OCR 找到该引导句真正的来源 block/span。若前处理合并成一个 OCR Block，应执行**有精确 span 的安全切分**，保留原 Block ID lineage，并依据行 bbox 恢复引导正文坐标；不能在原 Block bbox 外伪造位置或生成虚拟 OCR。
4. 将 `4.2.6-1` 的对应 `SymbolExplanationItem.description` 修复成只有符号含义、没有引导句；新建/恢复独立 `body` Block，文本以 `预应力筋疲劳应力比值` 开始、以 `应按下列公式计算：` 结束，位于 `4.2.6-1` 之后和 `4.2.6-2` 之前。
5. 新 Body 归属原规范条文 Clause `4.2.6` 的正常 BODY content unit（不是符号解释、新 Clause、公式或表注）。公式 `4.2.6-2` 保持其独立公式编号、LaTeX、符号解释，下一条 `4.2.7` 不受影响。
6. 更新源 span 消费、Block lineage、公式组文字渲染、Clause plain_text/digest；新的引导句最终恰好出现一次。

### C 的通过断言

- 公式 4.2.6-1 的 `symbol_explanations` 中不再包含“预应力筋疲劳应力比值”或“应按下列公式计算”。
- `pages[41].blocks` 恢复一个 Body，含完整 `预应力筋疲劳应力比值 ρ_p^f 应按下列公式计算：`，reading_order 在两式之间。
- Clause `4.2.6` 的 content units 顺序为：相关上文 Body → 公式 4.2.6-1 → 下一公式引导 Body → 公式 4.2.6-2 → 后续内容；不丢失表 `4.2.6-2` 与表注。
- 公式 4.2.6-1、4.2.6-2 各只有一个权威表示，所属 Block/source ID 无悬空引用。

## 六、共同工程约束：先正确分类，再消费源文本

### 6.1 避免同一类错误反复出现

建议在 Parser 私有层梳理如下处理顺序（可按真实源码复用现有机制）：

```text
MinerU 原始不可变片段 + 原物理页 + bbox
    ↓
行/Block 阅读顺序 + 可追溯 OCR span
    ↓
强边界识别：Section / Clause / NewTable / NewFormula / 公式引导 Body
    ↓
语义候选：table_note / formula_note / symbol_explanation / body continuation
    ↓
结合上下文、证据强度、编号结构、空间顺序解决冲突
    ↓
原子认领 source span；冲突 / 证据不足 => unresolved_pending
    ↓
表格 / 公式语义重建 → Section / Clause 重新装配
    ↓
V2.4 验证 + source / consumption 完整性检查
```

- 不许“先按最宽泛的注释正则吞掉源 Block，再尝试从空洞的最终 Document 恢复 Clause”。
- 即使 OCR 片段已正确识别，**仍需区分 label evidence 与 consumption evidence**；语义归属错误必须能从 sidecar 追查。
- 需要一个可重复运行且结果确定的 consume ledger，最少包括：`original_source_id`、`page_number`、`char_start/end`、`bbox` 或 bbox lineage、`semantic_role`、`target_id`、`decision_rule`、`evidence`、`status`。同一源 span 不能被两个权威语义对象竞争消费；如有重复引用是非权威引用关系，应明示其含义，不得重复渲染。
- 当原始来源没有 OCR 到某个字符串时，任何“修复”必须先证明数据来源或保留诊断。不可把用户给的屏幕文字当作真实 OCR 并虚构 hash/Block ID。

### 6.2 冻结契约和缓存

- **不可变更** `src/engineering_rag/contracts/**`、Document Schema V2.4 Frozen、任何公共 Protocol 或公共 Renderer；如需改模式，提出 ADR，保持本轮兼容表示。
- 需要重建/验证 `pages[].blocks`、`clauses.normative`、`sections`、`tables[].notes`、`clause_content.content_units`、`source_block_ids`、`page_start/page_end`、`plain_text`、`plain_text_renderer_version` 和 `plain_text_source_digest`。不能只改 JSON 某字段而不维护反向引用。
- `derive_clause_plain_text()` 对公式会使用 `Equation.text or Equation.latex`，并在最后一个 formula unit 后追加对应 `symbol_explanations`。因此不要将普通公式引导正文错误塞进 `Equation.text` 或 symbol description；也不要在已消费为组级解释后保留重复 Body。
- 未验证的 OCR、bbox、公式和表格必须保持 `unverified` / `partial` / `pending`，不可因结构修复就提升到 `verified`。

## 七、测试矩阵：先 RED，再 GREEN

**优先对 24–25、40–41、44–45 做最小真实保存产物 replay**；边界处须有上下文。完整运行旧测试与 1–50 页回放的扩展检查，不在没必要时再次运行 441 页 live OCR。

| 编号 | 场景 | 正例期望 | 必备反例 |
|---|---|---|---|
| T-25-A | 3.3.2 组跨页公式印刷注释 | 注释存在且有原文、target_group、Clause 3.3.2，可检索且仅一次 | 注：表……不得归为 formula_note；缺 raw 不得伪造 |
| T-25-B | 24 单页缺续页 | 未读到的注释不得标完整，保留 pending | 3.3.3 不得成为公式续文 |
| T-45-A | 表 5.2.4 后的 5.2.5 | 表 notes 1–4，新增 Clause 5.2.5，完整原文一次 | 真正的“注：5……”仍是表注 |
| T-45-B | 编号上下文 | `5.2.5` 独立条文 | 表5.2.5、公式(5.2.5-1)、引用第5.2.5条不创建新条文 |
| T-41-A | 两公式之间引导正文 | 4.2.6-1 的符号解释结束，Body 保留、之后是 4.2.6-2 | 合法跨行多句符号解释不能被随意截断 |
| T-41-B | 原始 Block 合并 | 部分 span 无损分离、bbox 合法、lineage 完整 | 缺字符/行几何证据时 fail-safe + pending |
| T-C1 | 文本消费守恒 | 三处修复目标无丢失、无双重权威消费 | 重复消费/孤立 Block/错误 target 必须报错 |
| T-C2 | ID / 文档重建 | V2.4 Pydantic + round-trip + reference validator + renderer cache 完整 | 人工直接删 Block 的 dangling IDs 必须被检测 |
| T-C3 | 幂等与回归 | 重跑 ID/JSON 结果可比，未涉及区域不退化 | 表3.4.3、3.4.5、3.5.2 和旧公式条件回归 |
| T-C4 | 分批恢复 | 分批与一次性上下文语义等价、resume 不重复消费 | 分批 24/25、40/41、44/45 不得错挂 |

### 具体验收时必须输出的断言

1. `formula_note` 的原文在新的 final Document 的条文 `3.3.2` 中可检索，且有 Sidecar 证明来自 PDF 物理第 25 页，目标为公式 `3.3.2-1`；出现次数 **1**。
2. `table_number=5.2.4` 的 `notes` 序号严格为 `[1,2,3,4]`；存在正文 Clause `5.2.5`（而不是 `.2.5`），其来源为物理第 45 页并在表 5.2.4 后、节 5.3 前，出现次数 **1**。
3. 公式 `4.2.6-1` 的 `symbol_explanations` 不包含“预应力筋疲劳应力比值”；Clause `4.2.6` 有独立 Body 引导公式 `4.2.6-2`，出现次数 **1**。
4. 不允许 `clauses` 持有已经删除的 PageBlock ID，不允许重复 `formula_id`、table source conflict、非法 bbox、错误页范围、缺失 original ID lineage。
5. 验收数据应包含原始 raw span 截图/文本、旧 JSON 位置、新 JSON 位置及根因分类，不能单纯用最终搜索字符串命中当成成功标准。

## 八、运行和交付

先检查项目实际依赖与命令路径，再执行对应测试（路径可根据实际仓库调整）：

```bash
python -m pytest tests/audit/test_task16_semantic_boundaries.py -q -rs
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest -q -rs
ENGINEERING_RAG_RUN_REAL_MINERU=1 python -m pytest tests/integration -q -rs
ruff check .
ruff format --check .
```

最后提供：

- `TASK_1_6_SEMANTIC_BOUNDARY_REPAIR_REPORT.md`：三项 root-cause、修改源码位置、结果 `PASS/PARTIAL/BLOCKED`；不能只说“已修复”。
- 修复后的 **独立版本** `document.v2.4.semantic-boundary-repaired.json`，不能覆盖用户上传的 JSON 或历史 run。
- `semantic_consumption_diff.json`、`formula_note_lineage.json`、`table_note_clause_split.json`、`formula_leadin_split.json`、`unresolved_pending.json`（全属 Parser 私有诊断）、修复前后页 24–25、41、45 Overlay。
- 所有测试实际日志（包含 skipped 原因）、Frozen V2.4 契约 diff（预期 0）、受影响 Clause 的来源、bbox、cache/digest 和 JSON roundtrip 检查结果。
- 对无法从当前 V2.4 结构化保留的公式注释，记录兼容投射与 ADR，明确“Document 可检索”和“原生 Schema 有 notes 字段”是两回事。

**禁止修改 Frozen V2.4、禁止硬编码这 3 页的解析结果、禁止重做无关架构、禁止默认运行完整 441 页 MinerU、禁止推进 Chunking/检索。完成后停止，等待独立验收。**

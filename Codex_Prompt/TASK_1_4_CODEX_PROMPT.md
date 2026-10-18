# Architecture Task 1.4 — 基于 MinerU 的工程规范公式识别、编号与符号解释结构化

> **Codex 正式开发任务书**。沿用 Task 1.2 的 MinerU 单引擎路线和 Task 1.3 的 Parser 内部实现；**Document Schema V2.4 = FROZEN**。本阶段只开发公式领域后处理，不实现 Section/Clause/强制性判定，不修改公共 Pydantic/Protocol。

## 0. 交付目标与严格边界

将真实 MinerU 解析输出中的**行间公式（display / interline equation）**、公式所在页面和区域、LaTeX 候选、印刷编号及紧随其后的“式中”符号解释，转换为冻结 V2.4：

- `Page.blocks[]` 的 `block_type="formula"`、`formula_group_id`、`ocr.formula_group.equations[]`、`ocr.formula_group.symbol_explanations`；
- 每个 `Equation` 的稳定 `formula_id`、独立 `equation_number` 和 `equation_number_status`（`printed / confirmed_absent / unknown`）、`latex / text` 与识别状态；
- 可选公式截图资产、公式块的 PDF points `bbox`、阅读顺序和真实来源；
- **公式信息原始溯源**：保留 MinerU 原生 MiddleJson / 相关图片 / 局部公式与编号候选框 / OCR 文本 / 输出 tier / warning，不将不可装入公共 V2.4 的信息悄悄丢弃；
- 通过 `Document.model_validate()` 的部分 Document JSON、独立测试及 GB 50010 真实页可视化复核。

**非目标：**更换 MinerU/对比 PaddleOCR；从 PDF 全书构造章节树、Clause、ContentUnit；把 `"式中"` 文本归到具体规范条文；判定强制条文；将数学公式按工程物理含义重写、求解、计算或自动纠错；默认推理 441 页；将扫描件上传第三方 API。

## 1. 先确认工程现状（强制 Gate）

阅读：
1. `AGENTS.md`，`README.md`，`docs/schema-v2.4-freeze-record.md`（若存在），`docs/data-contracts.md`；
2. `src/engineering_rag/contracts/documents.py`、`contracts/common.py`、`contracts/protocols.py`，`modules/document_parser/INTERFACE.md`；
3. Task 1.1 源 PDF 的旋转/CropBox、SHA256、size_bytes 六项历史缺陷回归；
4. Task 1.2 **实际部署**的 MinerU 版本、原始 JSON、产物清单、页号映射和 CLI；
5. Task 1.3 对同一 Document 追加表格片段时的稳定 ID、排序、快照重新校验及 raw sidecar 习惯；
6. 本任务 `TASK_1_4_FORMULA_MAPPING.md`、`TASK_1_4_TEST_CASES.json`、`TASK_1_4_ACCEPTANCE_CHECKLIST.md`。

记录冻结 tag 或冻结记录、Git 基线及 `python -m pytest -q`、`ruff check .`、`ruff format --check .` 的实际基线。**禁止声称 Task 1.2/1.3 已通过，除非项目源码和实测结果确实支持。**

### Gate A — MinerU 真正可复现

- 必须确认真实输入 PDF 的 SHA256、MinerU/模型版本、执行命令、实际 tier/parse_mode、MiddleJson `schema`/`schema_version`、原始页索引到 PDF **物理页码（1 起）**的映射。
- MinerU 4.x `mineru-kit parse --format middle_json`（具体参数以已安装 `--help` 为准）与 `mineru parse --json` 的输出**不同**；前者的 `docvortex.middle` 与旧 3.x `pdf_info` 也不同。识别协议身份并按真实 JSON 适配，禁止凭字段名想象协议。
- 如果有实际原始文件：支持**从原始产物重放**，不必为每次修改重新加载模型；若缺失，尝试最小选页实际解析：**PDF 24、50、301**。对当前 OCR 档位只返回公式图片/几何而没有 LaTeX 的情况，保留 `latex=null`、实际状态和 sidecar，按能力记录原因，不伪造转写；可在项目环境内试验已有 MinerU 受支持的其它 tier/本地离线方法并记录成本，但不引入新选型。
- 若模型、文件或运行环境缺失：仍可完成纯逻辑合成测试、Parser 内部模块和 CLI，但最终验收仅 `PARTIAL / BLOCKED`；不要把 mock 当作真实 MinerU 结果。

### Gate B — Frozen 合同不得改

- 核对 `DOCUMENT_SCHEMA_VERSION="2.4"`；不得修改冻结 `src/engineering_rag/contracts/**`、公共 `DocumentParser.parse(ParseRequest) -> Document` Protocol 或其验证规则。
- 以**实际源代码**为唯一的字段权威；本文字段示意不得用于推断不存在的属性。需要更细粒度公式 bbox/置信度时放在**Parser 私有 sidecar**，不往 V2.4 增字段。
- 如 Task 1.1 历史文件一致性和旋转坐标修复未过，阻断正式端到端宣称；不阻断可重放 raw MinerU 的纯逻辑单测。

## 2. 冻结公式契约的精确要求

### 2.1 PageBlock 与公式组

- 公式 `PageBlock`: `block_id`、`block_type="formula"`、`bbox`、`reading_order`、`recognition_status`、`bbox_status`、`extraction_method`、`formula_group_id`、`ocr={"formula_group": {"equations": [...], "symbol_explanations": ...}}`。`formula_group_id` 必须存在；非公式 Block 不能带该字段或公式组。
- `FormulaGroup.equations` 至少一个元素。一个公式块可有多个方程，但不能把一整页不相干公式硬塞一个组。组边界依据相邻几何、同一引导语/解释文本、原始 MinerU 分组信息及印刷编号。必要时**单公式单组**，以保守策略为先。
- `formula_group_id`、`formula_id` 在 Document 作用域唯一、稳定且可重试：基于文档身份、**原始物理页**、几何/版面顺序/持久化锚点，不直接对 OCR LaTeX 哈希产生身份。OCR 修正不应改变已分配 ID；已知旧块 ID 尽量复用，避免 Block 重复。
- 一个 PageBlock `bbox` 代表其对应公式组可验证的可视区域；**不把印刷编号、邻近解释文本的整段 bbox 当成公式本体**；当组/几何不能确定时保留候选与诊断，禁止凭空构造坐标。每条等式独立的 bbox 和编号框只在私有 sidecar 保存（V2.4 Equation 没有 bbox 字段）。

### 2.2 公式编号三态和识别状态（重点）

- `Equation.equation_number: str | null`（保留真实印刷号，如 `3.3.2-1`、`6.2.1-4`），`equation_number_status` 只能为 `printed`、`confirmed_absent`、`unknown`。
- **从源版面确有印刷编号且可靠匹配**才填写 `printed` + 非空编号。自动识别的编号和 LaTeX 即使十分清晰，也默认 `recognition_status="unverified"`，人工验收才能升为 `verified`。
- `confirmed_absent` 只能在**确实人工核验没有印刷编号**且 `recognition_status="verified"` 时使用，这是当前冻结 validator 的约束。机器未读到编号只能使用 `unknown` + `equation_number=null`。
- `recognition_status="verified"` 强制 `latex` 非空、编号状态非 `unknown`；`not_transcribed/not_processed` 不允许凭空填写 `latex`。单个 Block 如未整体核验不能标记 `verified`。
- `latex` 保留多行公式的结构、上下标、希腊字母、关系运算符和括号；可做**无损、可追溯**的包裹剥离（如可证明的 `$$...$$`），不得擅自将 `\leq` 改写成 `<`、将字符串单位转换为计算数值、用正则按 LaTeX 换行符 `\\` 机械分裂一个方程。
- 有 LaTeX 缺失的图片公式，`latex=null`、真实识别状态、source crop/图片及 warning；**不能因 JSON 校验而编造公式**。

### 2.3 公式编号必须做正负证据区分

**可以作为编号候选的证据**：公式右侧同一水平带中的 `(6.2.1-1)`、对齐的编号框、原始 MinerU 标注的 number region、与该公式所属图片的几何关系。

**负例不应当判为公式编号**：正文引用“见式（6.2.1-1）”、普通条文 `6.2.1`、工程单位 `(N/mm²)`、括号注释、数学公式自带括号、图/表编号、另一列/邻近公式的编号、仅存在于上/下文中的引用。

具体规范：优先真实几何证据 > MinerU number-region > 单纯 regex；如果候选互相冲突，`unknown` + diagnostics，不“选一个最像的”。编号属于对应方程而非 FormulaGroup 整组；同一组多方程可有不同编号。

### 2.4 “式中”符号解释

- `FormulaGroup.symbol_explanations` 可为 `null`，或 `{"items": [{"symbol": 非空字符串, "latex": 可空, "description": 非空字符串}, ...]}`。
- 从公式之后直到下一个**可信结构边界**的“式中：”释义中识别符号与原文说明；同一段可能有 4~8 个符号，说明可能折行、含括号、单位、上下标、希腊字母、中文标点。按原文顺序保留，必要时多行拼接，但不得删减说明或将工程单位独立拆成 Schema 未定义的 `unit` 字段。
- 关联必须有阅读顺序与几何证据；跨页解释只有在连续页面有明确归属时尝试，证据不足则保留原 Body Block 和私有候选，`symbol_explanations=null`，不要吞并随后条文/新公式/新标题。
- 原有正文/说明 Block 不应被静默删除：公式后的 `式中...` 若已被识别为 Body，优先保留其实际 source block，结构化解释作为语义派生，并在 sidecar 中说明引用和去重原则。等未来 Task 1.5 构造 Clause ContentUnit 时，避免解释正文与公式组释义在 plain_text 里重复输出；本任务**不新建 Clause**。
- `latex` 格式的符号名如 `\sigma_{c}` 若可以从实际 OCR 对应，保留；不确定时只存 OCR `symbol` 并留 `latex=null`。不得根据模型常识猜说明。

### 2.5 行内公式与 LaTeX 兼容策略

- 重点是行间编号公式。一般正文内短数学表达式属于 Body 排版，保留其原文或私有 span，不得为每个 `f_c` 单独创造公式 Block。只有 MinerU 与 bbox 均可确认独立数学区域时才考虑 Formula Block。
- 不自行写复杂的 LaTeX 语法解析器，不执行 TeX 宏；只做轻量验证（空值、不平衡定界符、明显 OCR 错误提示）。不确定语义**绝不“自动修正”**；保留原样供人工核对。

## 3. Parser 内部实现任务

尽量复用 Task 1.2 MinerU adapter、V2.4 partial Document assembler、文件 manifest、PDF bbox 映射和 Task 1.3 表格后处理。推荐（不是强制）内部文件：

```text
src/engineering_rag/modules/document_parser/internal/
  formulas/
    candidates.py         # 从真实 MinerU 中间结构提取公式+编号+图片候选
    number_matcher.py     # 严格的编号识别与几何匹配
    equation_grouper.py   # 多式归组/编号对应/稳定 ID
    symbol_explanations.py# “式中”跨行说明分段与关联
    v24_builder.py        # PageBlock/Equation/FormulaGroup 和既有快照归并
    diagnostics.py        # 缺识别、冲突和证据明细
    overlay.py            # 公式及编号候选 bbox 高亮
scripts/assemble_mineru_formulas.py  # 对现有 raw MinerU 结果离线重放
```

### 3.1 原始结构优先 + 私有中间类型

从 MinerU 确切版本的 MiddleJson 读取，保留原始 `schema/version/producer`、block 类型、span/crop/LaTeX 候选、几何、页序、解析 tier。**不要**只从 Markdown `$$...$$` 提取后丢弃 bbox，也不要把 `mineru parse --json` 响应冒充 MiddleJson。

推荐内部模型（非公共 schema）具有 `source_page`, `raw_block_ref`, `raw_latex`, `raw_text`, `raw_bbox`, `bbox_space`, `equation_number_candidates`, `number_bbox`, `symbol_explanation_candidates`, `confidence/diagnostics`, `source_assets`。只在原生数据实际存在时赋值，缺失保持 `None`。

### 3.2 编号和分组必须保守、可解释

- 必须区分印刷编号候选来源：模型标签、右边 OCR 文本、视觉框、人工金标；保存带原始页和 bbox 的 evidence。
- 多条等式共享排版区域时，逐条附对应编号；无法可靠分离时写入诊断，绝不将两编号合并为一个 `equation_number`。
- 单条多行公式须保持 LaTeX 结构（`aligned`, `cases`, `frac` 等）；不要按每一 `\\` 新建 Equation。
- 同一页不同公式组不得交叉复用同一公式 Block 或 `formula_id`；重放后 ID 保持一致。

### 3.3 与 Page / Document 的协作

- 引入公式后，**保留已解析的表格、正文、图片 Block**；不重复追加原先 Task 1.2 的占位公式，也不擅自修改 Task 1.3 的 `tables`。
- 同步 `reading_order` 为 PDF 页内有效、稳定、无重复值，先复用现有排序机制，而不是公式单独用另一套编号；选页和多栏时记录排序疑点。
- Pages 的物理宽高和 bbox PDF points **top_left** 与 MinerU 原产物正确转换，裁切/旋转映射重用已有修复；全量再验 `Document.model_validate` 和 JSON 往返。
- 整体仍是部分 Document：不要为了“公式已经识别”将全本 `processing.partial` / `is_complete_document_ocr` 设为 complete，也不要将未经验证的 Formula 或 Page 标 `verified`。
- Task 1.5 以后才建 `ClauseContentUnit.formula_ids`，本轮仅保证 IDs 可稳定引用且符号解释来源可追踪。为后续 `derive_clause_plain_text` 预留测试数据，但不新增 Clause。

### 3.4 原始产物和安全性

- CLI 只接受受限本地输入；校验输入源、文件大小、页码映射、可视 bbox 范围、模型/协议身份；禁止 zip-slip 和符号链接逃逸、路径穿越、通过 HTML/TeX 执行或外链下载。
- 原始模型产物不可覆盖；生成独立 versioned run manifest，包括源 PDF SHA256、MinerU/模型版本、schema identity、公式算法版本、参数、真实运行/重放标记和诊断。
- 保存公式页的 overlay：至少区分公式主体 bbox、编号候选 bbox 与“式中”关联范围（只画出真实来源框）；符号核查表给出 `symbol`, `latex`, `description`, source page/block, extraction status。
- 默认 pytest 不联网，不要求下载 MinerU 权重、不默认读 441 页的真实 PDF；真实模型集成需显式运行或显式标记环境 blocker。

## 4. 正反测试（严格）

使用 `TASK_1_4_TEST_CASES.json` 作为用例规格，具体以冻结模型 validation 规则判定。至少覆盖：

1. 单条有印刷编号的标准公式 → 编号、LaTeX、来源/原 bbox 正确；机器输出 `unverified`。
2. 同一组多条连续公式，各有不同编号；多行 `aligned` 是**一条** Equation。
3. 可靠看到印刷编号与只在正文中引用编号的**反例**；邻近表号或单位括号不污染编号。
4. 未检测编号时保持 `unknown`；**只有人工核验**才允许 `confirmed_absent`，且 verified equation 必须有 latex。
5. 公式 LaTeX 缺失/图片-only → `latex=null` + `not_transcribed`、图片/sidecar、非完成状态，不造伪内容。
6. 符号解释：单个、多项、跨行、单位、希腊字母、上下标、说明和正文边界；无可靠归属时 `symbol_explanations=null`。
7. 公式和 Body 文字重叠、相邻多组、长表达式中的 `\\` / `cases` 等，不重复组、不误拆。
8. 中英标点及 OCR 易混字符 `σ/δ`、`ε`、`l/1`、`0/O`、`−/-` 的保存与标注，不靠公式物理含义修正。
9. bbox 旋转/裁切、像素到 PDF points、页号 off-by-one、reading_order 和源引用校验。
10. 相同源文件与 raw 重入稳定 ID、新旧公式 block 去重、其他表格/正文保存、负例悬空引用。
11. Frozen `Equation`, `FormulaGroup`, `PageBlock`, `Document` Pydantic 负例及 JSON roundtrip，嵌套对象原地变动后**整份快照重新验证**。
12. MinerU 协议错误/旧 `pdf_info`、missing metadata、无坐标、超大候选、病态 LaTeX、路径逃逸、ZIP 恶意输入，返回诊断或拒绝，不 silent success。
13. `plain_text` 符号解释逻辑的**现有**回归测试继续通过，不引入 Task 1.5 的 Clause 实现。

每组测试应明确假定数据来自**人工设计合成 fixture**还是已保存的**真实 MinerU**；不能将合成 fixtures 计入真实 OCR 成绩。

## 5. 真实 GB 50010（2015 年版）测试

**本任务默认只运行原始 PDF 物理页**（不是页脚印刷页码）：

| 案例 ID | 物理页 | 已从原扫描图观察的现象 / 验证内容 |
|---|---:|---|
| `GB-E332` | 24 | 第 3.3.2 条附近两条连续编号公式 `(3.3.2-1)` / `(3.3.2-2)`，之后多项“式中”符号解释。检查几何匹配、编号与解释归属。 |
| `GB-E621` | 50 | 第 6.2.1 条附近连续多个编号公式（可见 `(6.2.1-1)` 至 `(6.2.1-7)`）及一长段跨行“式中”说明。检查公式分组、多式、多行、编号与符号对应。 |
| `GB-EEXPL` | 301 | 条文说明正文中的 `E_c` 显示公式，视觉上无紧邻印刷公式编号。**机器仍必须 `unknown`，人工核验才可 `confirmed_absent`。** |

- 每个案例应保存真实 MinerU 输入原始 JSON 或 ZIP、命令/版本、PDF hash、source physical page map、公式候选及 bbox、候选编号、最终 V2.4 部分 Document、诊断与 overlay PNG；如果有可能，保存人工核查的公式截图/latex 对照，但**不要将整个版权 PDF/完整扫描页提交公开仓库**。
- 先测试已保存的原始 MinerU 产物重放；如果没有真实公式输出，补跑三页或记录具体阻塞。不同解析档位识别效果/图片回退应如实记录；不得把缺失 LaTeX 解释为“不存在公式”。
- 可做**真实案例人工抽样审核**：公式检测 TP/FP/FN、编号归属、符号条目完整性、逐表达式 LaTeX 质量；在尚无人工 gold 时，只报告产出数量、错误样例和未识别项，不编造总体准确率。
- 第 50 页是**多个独立公式编号的聚集页**；不能以一个 FormulaGroup 共享一个 `equation_number`。第 301 页属于说明正文，本阶段不建 explanation Clause/Section。

## 6. 可重放 CLI、文件与报表

提供一个 CLI，例如：

```bash
python scripts/assemble_mineru_formulas.py \
  --run-manifest data/eval/task1_2_mineru/runs/<run_id>/manifest.json \
  --pages 24,50,301 \
  --output data/eval/task1_4_formulas/runs/<run_id>/
```

可额外提供 `--case-id`、`--raw-middle-json`、`--strict`、`--max-pages` 等**内部命令参数**。必须支持 `--help`、确定性的离线重放、失败诊断、真正源页号、资源大小上限和不覆盖原 raw；示例路径不是仓库中已存在数据的断言。

推荐目录：

```text
data/eval/task1_4_formulas/
  runs/<run_id>/
    manifest.json
    document.partial.json
    formulas.json                 # 只读检查视图/内部公式候选
    formula_sidecars/            # 每公式 raw snippet、模型候选、图片/crop 资源引用
    overlays/p24.png
    overlays/p50.png
    overlays/p301.png
    diagnostics.json
  reports/task1_4_formulas_review.md
```

建议源码及文档：
- `internal/formulas/*.py`、已有 MinerU adapter 兼容性增强；
- `tests/.../test_formulas_*.py` 和合成 fixtures；
- `scripts/assemble_mineru_formulas.py`；
- `docs/task-1.4-formulas.md`：编号三态、拆组/合组、式中关联边界、raw 与 V2.4 映射、失真限制、待人工核验事项；
- `modules/document_parser/INTERFACE.md`：仅同步已真实实现的**私有配置/能力**，公共接口不变。

## 7. 运行与验收门槛

Codex 须实际运行并记录：

```bash
python -m pytest -q
ruff check .
ruff format --check .
```

再运行公式专属测试、离线重放和明确选页的真实 MinerU 实测（如果当前机器能运行），给出**逐项成功/失败/blocked**而不是笼统的“已测试”。验收 `Document.model_validate(document.model_dump(mode="json"))` 及 JSON roundtrip，并比较 `contracts/` 与冻结 tag 的 diff（Git tag 缺失则注明无法验证）。

**PASS**：三组 GB 页面存在真实 MinerU 可追溯解析/重放及人工可核 overlay，公式编号/分组/符号解释的重要规则通过正反测试，V2.4 引用与回归通过，冻结文件不变。

**PARTIAL**：内部公式解析可复现，部分真实案例仍缺少可转写 LaTeX/归属证据；明确列出数据缺口、结构化率和诊断，不编造通过率。

**BLOCKED**：缺 MinerU 实际产物、PDF 或运行条件，关键目标无法实测；明确命令、日志和恢复路径。

**STOP**：完成后停止，等待用户验收，不启动 Task 1.5（章节/条文识别）、Chunking、RAG 检索或其它业务任务。

## 8. 官方来源（版本以安装的真实产物为准）

- MinerU 官方结构化输出： https://github.com/opendatalab/MinerU/blob/master/docs/zh/reference/output_files.md
- MinerU GitHub： https://github.com/opendatalab/MinerU
- 当次执行的 MinerU 版本 / JSON Schema / 模型输出是适配层的**唯一实际协议事实来源**。

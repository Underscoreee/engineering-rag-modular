# Architecture Task 1 — Document Parser 独立开发总计划

**项目**：Engineering RAG，模块化单体，一个 Python 工程。  
**前置条件**：`Document Schema V2.4 — FROZEN`（由项目维护者/正式 Git 标记确认）。  
**本文件职责**：定义 Task 1 的完整技术路线、任务顺序与阶段边界；首次提交给 Codex 执行的是另外一份 `TASK_1_1_CODEX_PROMPT.md`，不是让它一轮完成所有 OCR/公式/表格/条文算法。  
**原则**：冻结契约唯一事实来源在 `engineering_rag.contracts`，Parser 只调用本模块的代码、冻结 DTO/Protocol 和注入的基础设施接口。

## 1. 目标与成功定义

最终实现：用户提供工程规范 PDF → 文件审查与页面渲染 → OCR / 文本层提取 → 版面结构 → 页面类型 → 跨页表格与公式组 → 章、节、正文 Clause、条文说明 Clause → 有来源/状态的正式 `Document(schema_version='2.4')`。允许部分解析，但必须如实声明 `partial`、页面/Block/表格/公式级提取状态。

Document Parser 不负责 Chunking、检索、向量化、LLM、跨模块编排，也不独立裁定法律强制性条文。

## 2. 开发阶段（按门禁推进）

| 阶段 | 任务 | 可交付并可独立验收的成果 | 不得冒称已实现 |
|---|---|---|---|
| **Task 1.1** | PDF IO、渲染、OCR 适配器、基本 Page/Body Block | 可直接调用 `parse()` 对真实扫描 PDF 的选定页面做 OCR，输出合法**部分** V2.4 Document；保留原 PDF 物理页号、坐标/状态/来源 | 完整条文识别、表格结构/公式 LaTeX、完整 441 页、强条识别 |
| **Task 1.2** | 页面类型、阅读顺序、五类版面 Block | 页面分类（13+unknown），版面块、表格/公式检测候选及 bbox；金标小样评测 | 不可靠块直接 `VERIFIED`，已检测表格即已解析完整 |
| **Task 1.3** | 表格解析/续表逻辑聚合 | 结构化 `columns/data/notes/raw_grid`，跨页 `table_id`，来源片段，完整性校验，表 3.5.2 / 4.2.2-2 / 9.1.2 基线 | 表格合并必然正确、任何细节自动猜测为确定值 |
| **Task 1.4** | 公式与符号说明 | LaTeX、印刷编号三态、无编号公式、多个连续编号公式/跨行公式、symbol explanations | 公式 OCR 有误却标记 `VERIFIED` |
| **Task 1.5** | 章/节/条文聚合、正文/说明、强条证据处理 | 规范目录层级、跨页 Clause、带序号条文小项、各 ContentUnit 来源、`explains_clause_id`、`plain_text` 缓存 | 凭“应/必须”、粗体自行确定强条法定性质 |
| **Task 1.6** | 441 页稳健性/Golden 评估/性能/失败恢复 | 批处理可恢复、质量报告、误差类型分析、部分文档快照，明确未完成项 | 未经人工金标的准确率、未验证全本精度 |

阶段间只能更新 Parser 模块**内部**实现或独立评估工具；V2.4 Schema、公共 Protocol 已冻结。遇到契约表达不了的真实内容，建 issue + ADR + 版本升级提案，不得直接修改合同模型。

## 3. 真实扫描 PDF 依据与样本

参考文件：`混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf`。通过本任务制定时本地 PyMuPDF 抽查，**441 页**；抽查页 `page.get_text()` 为空，几乎全为扫描页面。不要因为自动提取为空就标记真实 PDF 页面“空白”或“完整处理”。

人工审阅优先的**候选**测试页：

- 页面分类：1 外封面，2 内封面，3/5 公告，9 中文目录，12 英文目录，16 正文，275 用词说明，276 引用标准，277 说明封面，278 修订说明，279 说明目录，282 说明正文。
- 跨页表格：28–29（表 3.5.2）、37–38（表 4.2.2-2）、126–127（表 9.1.2；127 页还有下一条文 9.1.3）。
- 公式：24（条文 3.3.2 的多编号公式）、50（条文 6.2.1 的多公式组）、301（条文说明 4.1.5 中无印刷公式编号的展示公式）。
- 正文/说明：16 与 282 可作为同号条文分离的优先检视样本。

**非常重要**：`references/GB50010_2015_document.v2.4.partial.json` 是 **2.4-proposal 的人工不完整参考材料**，不是符合 `2.4` 的全本 Golden Dataset。不得通过替换 schema_version、虚构 OCR 或硬编码这些页的结论来生产解析 Document。建立人工金标时要记录原图、坐标、审核者和版本。

## 4. 技术架构（内部，可替换）

```text
DocumentParser.parse(ParseRequest)
    │
    ├── FileStore.read(FileRef)                     ← 注入、只读
    ├── PdfDocumentBackend                        ← PyMuPDF 优先
    │     ├── page metadata / text layer
    │     └── rasterize(pdf page, dpi) / geometry
    ├── PageTextRecognizer                         ← OCR 可替换
    ├── LayoutAnalyzer / PageTypeClassifier        ← Task 1.2
    ├── TableReconstructor + ContinuationMatcher   ← Task 1.3
    ├── FormulaRecognizer + SymbolParser           ← Task 1.4
    ├── StandardStructureBuilder                   ← Task 1.5
    ├── V2.4 DocumentAssembler
    │     ├── partial/recognition statuses
    │     ├── stable IDs & provenance
    │     └── frozen Document.model_validate(...)
    └── Diagnostics / Measurement
```

PyMuPDF 是首选 PDF **读取/几何/渲染**工具，不等于 OCR 引擎。OCR、版面检测、表格结构、公式解析是不同能力，分别采用适配器接口。可评估 PaddleOCR / MinerU / 专门的公式识别模型等，但不要将第三方类型、下载地址或模型权重写入冻结 DTO。选型要结合中文规范、离线可运行、GPU/CPU 资源、许可证、版本与效果；以真实 Golden Dataset 决定替换。

Task 1.1 可采用轻量真实 OCR 的首个实现（本地已安装依赖优先，模型缺失时报可操作错误），同时提供**测试专用伪 OCR**以让独立测试离线运行；不能将伪 OCR 输出作为真实文档解析成功结果。

## 5. 必须维持的正式 V2.4 契约事实

- 公开调用：`DocumentParser.parse(request: ParseRequest) -> Document`；`ParseRequest.source_file: FileRef`、`supplied_standard` 和 `config`（已有 `ParseConfig.options: dict[str, str | int | float | bool]`）。Parser 依赖 `FileStore.read`，但不能实现完整 FileStore 业务后端。
- `Document.schema_version='2.4'`；`bbox_coordinate_system={'unit':'pdf_points','origin':'top_left'}`；物理页从 1 开始；每个 Block bbox 必须是合法真实检测/来源区域，不能凭空填全页框。
- 页面类型严格 13+`unknown`；Block 类型严格 `title/body/table/image/formula`，**不能**把 `list_item` 当作新增 Block 枚举。
- `PageBlock` 已冻结：bbox 必填；不能定位的区域不应生成假 Block；状态记录真实识别情况。
- Table PageBlock 是物理片段，完整逻辑 Table **仅保存顶层 `tables[]`**，跨页 `table_id` 唯一链接；`columns/data` 对应记录视图；`raw_grid` 可选，notes 为 null 或 `{number, content}[]`。
- 公式必须有 `formula_id`，`equation_number_status=printed | confirmed_absent | unknown`；编号可空；只有**已经核对确实无号**才用 `confirmed_absent`；自动识别待定要保留 unknown。
- Clause 结构分别在 `normative/explanations`，正文 Block 必须来自 body 页面，说明 Clause 必须来自 explanation_body 页面；ContentUnit 只存来源引用，Clause `plain_text` 是由权威对象派生的可选缓存。
- `is_mandatory` 只在有一致、已审验证据时判定为 True/False；缺少正式外部核验时填 None，不能凭粗体和“应/必须”推断。
- `Document.partial` / `processing.is_complete_document_ocr` / Page extraction statuses 必须语义一致；OCR 处理了页面不等于识别了每个公式和表格；`unverified` 不等于 `verified`。
- 重新验证完整 Pydantic 图后才能持久化 Artifact，不可依赖嵌套对象赋值验证自动传播。

## 6. 评估体系：指标、分母和边界

**先人工核验 Golden，再计算指标**，不得直接把提案 JSON 当 gold 或把未处理页算作负样本。

- 页面类型：按类别的 Precision/Recall/F1、macro-F1；unknown 与不同类别混淆矩阵；以人审页分母统计。
- Layout：Block type mAP / IoU 或按类型的匹配精确率与召回率；bbox 坐标从像素到 PDF Points 的映射误差。
- OCR：中文字/字符 CER、包含符号的原文完整性、标题/正文分离和阅读顺序准确率。
- 表格：表格检测 Recall、续表关联 P/R/F1、raw-grid 单元格结构匹配率、规范化 columns/data 行列一致率、表注完整率；对关系符号和数据值分别检查。
- 公式：检测召回、印刷编号正确率、LaTeX 归一化完全匹配/人工等价通过率、符号解释 Recall、无号/未知三态分类。
- 条文：Clause 识别 P/R/F1、跨页边界、编号准确率、正文/说明分离准确率、表格/公式/图片引用覆盖率、来源可追溯率。
- 完整性：未处理/不确定对象不能误标为完成；V2.4 校验 100%（**schema 有效性不是识别准确率**）；跳过/失败页面数、误差原因和性能。

不应虚构统一生产阈值，建议先建立基线后由维护者确定每一项验收值。可将阶段验收的**行为性要求**作为硬门槛：测试全部通过、无 dangling reference、不得静默跳过、Golden 出具分母和错误样本。

## 7. 质量、安全和运行资源

- 扫描 PDF 输入是不可信数据，限定文件大小/页数/每页最大渲染像素/并发、临时文件目录和清理；没有页码或文件时明确报错，不执行远程 PDF 内嵌指令。
- OCR 模型缺失、没有 GPU、网络不可达、损坏/受密码保护 PDF 时，返回明确错误或可追踪的 partial 输出，不伪造完成。
- 支持可选 `page_selection`、`dpi`、`ocr_backend` 等内部配置，遵守已有 `ParseConfig.options` 类型（例如用逗号分隔的页号字符串，不私自改变公共类型）。
- 不要默认对 441 页启动无限内存 OCR；设计分批、日志、可恢复边界，确保 Windows/WSL 无 GPU 的开发环境可运行。
- API import 不加载大模型/打开文件；模型注入、懒加载、设备选择属于 Parser 模块内部。
- 许可证与第三方模型权重由后续选型审查记录，不把权重或完整用户 PDF 提交 Git。

## 8. 后续各阶段建议验收案例

Task 1.2：已核验封面/目录/正文/说明页产生正确 page_type，未知页面使用 unknown；Block 真实 bbox、阅读顺序可视化叠加检查。

Task 1.3：真实表 9.1.2 从第 126–127 页归一成一张逻辑表格；下一条 9.1.3 不合入表；表 3.5.2、4.2.2-2 续表关系正确，合并单元格保真；行/列错误有诊断。

Task 1.4：正文第 24 / 50 页多个不同公式带编号；第 301 页条文说明无编号，只有经人工核验后才标记 confirmed_absent；式中解释与正确公式组关联。

Task 1.5：同号正文/说明 Clause 在不同分组、独立 ID；跨页 Clause 成一个对象，条文所有表图公式引用与 source_block_ids 完整一致；未核验强条 None。

Task 1.6：至少运行指定代表页的端到端诊断与合法 partial V2.4 JSON 导出；需要时再对 441 页分批全量运行，报告真实指标和失败案例。

**执行规则：** 每次只执行当前单项子任务，阶段验收后再启用下一阶段。禁止改动 Frozen 模型与其他模块 private 目录来绕过 Parser 局限。

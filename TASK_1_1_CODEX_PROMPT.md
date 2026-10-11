# Architecture Task 1.1 — Document Parser 首个真实扫描 PDF 纵向闭环（Codex 执行 Prompt）

> **请直接按此文档执行代码改动。只完成 Task 1.1，不提前做 Task 1.2–1.6。**
>
> 前置：维护者已批准 Document Schema V2.4 Frozen；`src/engineering_rag/contracts` 的 DTO / Protocol / Validator 不可变更。若仓库尚未实际冻结，请先核对冻结记录与 Git Tag 的真实状态，存在冲突先报告；未经批准不得替用户生成假 Git tag。

## A. 开始前（必做）

1. 阅读 `AGENTS.md`、`README.md`、`docs/schema-v2.4-freeze-record.md`（若存在）、`docs/data-contracts.md`、`docs/id-policy.md`、`docs/artifact-policy.md`、`docs/architecture-decisions.md`、`src/engineering_rag/modules/document_parser/INTERFACE.md`、`src/engineering_rag/contracts/documents.py`、`common.py`、`protocols.py`、`pyproject.toml`、现有 Parser 测试。
2. 查看 `git status --short`、`git tag -l 'document-schema-v2.4'`、当前分支/提交；不得覆盖或重建现有 tag。用户批准冻结不等于本地仓库一定已打 tag。**不要为完成 Task 1.1 修改 Frozen DTO 或冻结记录。**
3. 运行现有基线：`python -m pytest -q`、`ruff check .`、`ruff format --check .`，记录准确结果，若环境缺工具需说明并按项目安装方式处理。
4. 如环境存在用户提供的真实文件 `混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf`，确认页数/样本页；如没有，**先完成合成扫描 PDF + 测试驱动的模块实现**，报告真实样本缺失并请求使用者提供路径，不得虚构真实验收。
5. 先列出实施文件和验收计划再编码。本任务只允许修改 Parser 模块、它自己的测试、脚本、相关文档、私有依赖配置；如需动公共契约，提出 ADR/issue 并停止该改动。

## B. 目标与严格范围

实现一条真实可运行的、用于中文扫描规范的最小闭环：

```text
ParseRequest(FileRef, supplied_standard, config)
  → 注入 FileStore.read(FileRef)
  → 安全地打开 PDF（PyMuPDF）
  → 收集全本页数、每页尺寸（1-based，PDF Points）
  → 只渲染 page_selection 指定页
  → 文本层可用则提取真实文字/真实位置；否则执行可替换中文 OCR
  → 生成 provisional Body PageBlocks（真实坐标、reading_order、识别状态）
  → 用已冻结 Pydantic V2.4 构建/验证部分 Document
  → 输出 JSON + 逐页诊断信息
```

这是**首个纵向闭环**，不意味着已经实现：高级页面分类、五类版面检测、跨页表格合并、公式识别、Chapter/Clause 语义构建、全本准确率或 Artifact 原子快照提交。这些留到 Task 1.2–1.6。

必须能够对一个真实扫描页实际产生 OCR 文本而不是模拟文本。离线单元测试可以使用 Fake OCR；真实集成烟测必须确实调用 OCR 引擎，且报明所用引擎/模型/是否下载过权重。**不可将固定答案硬编码到 PDF 页码或扫描图片中。**

## C. 代码组织与依赖方向

尽量在已存在的路径下增加：

```text
src/engineering_rag/modules/document_parser/
  api.py                             # 公开入口，只重导出稳定 Protocol 和生产实现入口
  INTERFACE.md                       # 兼容既有签名，明确 Task 1.1 的部分结果语义
  internal/
    parser.py                        # 可注入的 DocumentParser 实现
    pdf_backend.py                   # PyMuPDF 适配器（只负责 PDF 访问、文本层、渲染、坐标）
    ocr.py                           # 本模块私有 OCR 协议 + 结果类型
    ocr_<chosen_backend>.py          # 首个真正可执行中文 OCR 适配器
    layout_baseline.py               # 初级文本片段与阅读顺序，不宣称复杂版面识别
    document_assembler.py            # 使用冻结 DTO 装配与验证
    config.py                        # 解析并验证现有 ParseConfig.options
    ids.py                           # 单 Document 内 ID 分配/稳定锚点映射策略
    diagnostics.py                   # 具体页面错误 / 失败阶段 / 识别状态
  tests/
    test_pdf_backend.py
    test_ocr_adapter.py
    test_parser_partial.py
    test_coordinate_mapping.py
    test_failure_cases.py
scripts/
  inspect_pdf_document_parser.py    # 开发诊断 CLI，不替代正式 public parse()
docs/
  document-parser-task1-1.md
  document-parser-ocr-backend.md
```

以上是建议，不为凑目录而拆无意义小文件。实现类放 Parser 内部或由 Parser 的 `api.py` 公开工厂导出；**不得在 contracts 新建 OCR、PDF 专用公共协议**。不引入其他业务模块 `internal/`，不依赖 Chunking/ES/Milvus/LLM，不在 import 时打开 PDF/加载模型/发网络请求。

`DocumentParser.parse(request: ParseRequest) -> Document` 的签名保持**完全不变**。真实 FileStore 使用 `FileStore.read(source_file)` 注入；测试使用仅供测试的 FileStore stub。CLI 可有只读、受约束的本地文件适配器，不要假装已经实现 FileStore 的持久化/删除/事务。

## D. PDF 与 OCR 的实现要求

### D1. PyMuPDF — 第一层 PDF 能力

- 使用 PyMuPDF（`pymupdf`/`fitz` 根据实测安装版本），PDF 没有文本层时 `page.get_text()` 为空是**真实扫描件的常见情形**，不能当空白页。
- 页面坐标以**PDF Points + 左上角原点**返回；扫描 OCR 通常返回像素矩形，显式实现像素→PDF bbox 的矩阵映射，并测试 rotation/crop/不同 DPI；对越界/无面积/NaN 框拒绝或记录错误，**不随意扩大成整页**。
- 从 FileStore 的 BinaryIO 读取时可按块写入安全临时文件再用 PyMuPDF 打开，避免每次读入约 147 MB 大文件内存；临时资源必须 context-managed，异常也清理。
- 限制 DPI、单页输出像素、选择页数量、内存占用；页号以 1-based 对外，对内部 0-based 显式转换；不一次性将 441 页渲染进内存。
- 混合页支持真实可提取文本的优先策略，但不得因页面中有少量文本层就直接跳过所有扫描区域，需至少明示局限及后续混合检测策略。对多栏、图片/表格内部 OCR 暂只能输出 provisional 文本块。
- PDF 损坏、加密、空文件、不是 PDF、选择不存在页等有可定位且能测试的错误，不返回看似完成的空 Document。

### D2. 中文 OCR — 私有可替换适配器

- 定义 Parser 内部的 OCR 抽象，最小输出：`text`、像素 `bbox`、可选 confidence、来源/引擎版本；一页返回多条 OCR 文本片段（不是仅拼接成字符串）。
- 首个实际 OCR 实现优先选择 **CPU 可运行的中文 OCR 引擎**（如PaddleOCR或MinerU），先列出实测支持的版本/API/许可证/模型权重加载方式并记录选择依据；不要在不知道版本的情况下调用假设存在的第三方 API。
- 通过本地配置显式启用真实 OCR；没有模型/依赖时报告明确错误，不静默返回空结果、不把 Fake OCR 当真实运行。
- 测试中 Fake OCR 仅用于覆盖坐标/装配/失败场景；真实验收日志必须说明 OCR 真实执行且包含至少一条来自本地扫描页的非空文本与其实际 bbox。
- **识别结果仅自动产生 `recognition_status=unverified`**；只有人工复核才标记 `verified`。不能把 OCR 模型置信度直接视为人工认证。
- OCR 引擎/模型不能写进 Frozen DTO 的新字段；可记录在 Parser 的私有配置/日志、`ProcessingMetadata.parser_id/parser_version` 与外部诊断报告中。

### D3. 第一期布局输出（避免错误承诺）

- 在没有独立表格/公式/图片结构识别器的 Task 1.1，OCR 文本片段可以被**临时映射为 `block_type=body`**，但必须标记 `unverified`，记录这是 provisional 分类。
- 不得假装识别出 Section、Clause、LogicalTable、RawGrid、FormulaGroup。允许 `sections=[]`、`tables=[]`、`clauses.normative=[]`、`clauses.explanations=[]`；该 Document **必须是 partial**。
- 表格或公式片段被 OCR 当文本读取时，不能等同于结构化表格/公式成功。
- 不确定页类型用 `page_type=unknown`；只在有实际识别依据时标记指定页面类型，禁止根据「GB 50010 第 28 页就是正文」等位置表在**生产**实现中硬编码页类型。
- Reading order 在第一页至少有确定性排序，避免不同运行随机变化；对于多栏和交错布局，在诊断报告里说明启发式不足。

## E. 按 Frozen DTO 正确装配 Document

**再次核对实际源码字段，不要凭提示词重写 Pydantic 模型。** 当前已知契约：

- `ParseRequest.source_file: FileRef`，`ParseRequest.supplied_standard: StandardMetadata | None`，`ParseConfig.config_id + options`。
- `Document.schema_version='2.4'`，`bbox_coordinate_system={'unit':'pdf_points','origin':'top_left'}`。
- `Document.page_count` 是源 PDF 总页数，`pages[].page_number` 是 1-based 物理页码；建议**所有页面都列入 pages 清单**，未选择/未处理页面设 `not_processed`、`blocks=[]` 和 `page_type=unknown`；选择页产生真实 OCR/text layer Block。
- 当页面仅做文本提取、尚未理解表格/公式/条文时，页面 `content_extraction_status` 不得虚报完整的 Document 语义处理；可以标记 `partially_transcribed`，Document `processing.partial=true`、`is_complete_document_ocr=false`，直到后续阶段符合契约约束再提高状态。
- 处理后的文本 `PageBlock` 需有合法 bbox、reading_order、`ocr.text`、`recognition_status=unverified`、合理的 `bbox_status` 和 extraction_method。未提供 bbox 的 OCR 片段不可伪造定位。
- `source_file` 沿用请求中的 FileRef；如果 `supplied_standard` 缺失且不能**可靠证明**标准名称/编号，不得填演示值；返回明确可操作错误（要求调用方提供），或实现有可靠依据且会记录来源的提取策略（不能凭 PDF 文件名无条件猜测）。
- 自动生成 document_id / block_id：沿用 `docs/id-policy.md`，不能按 OCR 内容哈希充当稳定身份；保证同快照唯一与序列化往返稳定，并区分同源不同 Parser 产物版本；不能声称跨版本 Block ID 一定不变。
- `processing.parser_id/parser_version` 是真实实现标识；warnings 使用冻结 `ContractError` 模型而不是普通字符串；失败要标明页码/阶段。
- `Document.model_validate(...)` 验证通过后再 `model_dump_json()`、反序列化往返，保证同一份数据的引用与状态一致。

**错误恢复行为**：有具体页处理失败而文件仍能读取时，按显式配置决定 `raise` 或记录 warnings + 页面仍 `not_processed` 并返回 partial；不得吞掉错误后声称全页成功。

**禁止**修改 `engineering_rag.contracts.documents`、`contracts.protocols`、`contracts.common`、`contracts.artifacts`，以及其他业务模块实现；若 frozen contract 不支持客观识别状态，停止该子功能并提出 ADR，不是绕过验证器。

## F. CLI：用真实 GB 50010 PDF 验收（选页，非全本）

提供**真实可运行的**轻量 CLI，公开契约仍通过 `parse()` 使用。建议：

```bash
python scripts/inspect_pdf_document_parser.py \
  --pdf "/path/to/混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf" \
  --pages 1,16,24,28,29,50,126,127,277,282,301 \
  --dpi 200 \
  --standard-name "混凝土结构设计规范" \
  --standard-code "GB 50010-2010" \
  --edition "2015年版" \
  --out-dir ./outputs/parser_task1_1
```

CLI 中 `--pages` 对应内部选页配置（序列化为既有 ParseConfig.options 可接受的**字符串**）；CLI 所有参数名称可按实际更易用的实现调整并写入文档。`outputs/` 需在 `.gitignore`，不得将真实规范 PDF 全本、全部图片或下载权重提交 Git。

输出至少：

1. `document.partial.json` — **符合冻结 V2.4** 的真实来源部分文档（不能替换原始输入或伪造完整条文）。
2. `diagnostics.json` — 引擎/版本/选页/每页阶段状态/耗时/OCR 非空项数量/异常/不确定性，独立于 Frozen DTO。
3. 对选定页至少输出一张 `page-XXX-overlay.png` — OCR bbox 可视化，便于人工检查像素→PDF 坐标映射。
4. `summary.md` — 实际处理的页数、未处理的页数、样本 OCR 文字片段和局限；不计造假的解析准确率。

如果本地模型不可用，CLI 应立即给明确错误/安装指导（无凭据或网络时不暗中下载），日志里标记真实 OCR 未运行。这种环境下单测可通过，但**真实 OCR smoke 门禁未完成**，不得向维护者报告 Task 1.1 完全验收通过。

## G. 必须测试

- 单元：PDF 识别 / 页数 / page rect / 文字层有无；单页及指定页选择；所有无文本层页不能误判为空白。
- 坐标：缩放矩阵、不同 DPI、旋转页、CropBox / 非方形页，bbox 合法且位置与可视区域一致；同坐标映射正反向误差按测试样本合理限定。
- OCR：使用合成**扫描图像**（先文本渲染成图片，再放进 PDF，确保确实没有文本层）运行真正 OCR 引擎；Fake OCR 的失败/空返回仅测装配层。
- 状态：未处理页 `blocks=[]+not_processed`，已 OCR 的 Block `unverified`，局部失败 partial/warnings，不能谎称 `is_complete_document_ocr=true`。
- 错误：加密、损坏、空文件、非 PDF、选页越界、缺失标准元数据、FileStore read 失败、OCR backend 缺失、OCR 返回非法 bbox。
- ID：同 Document 内唯一、可追溯、OCR 文本变化不自动改变语义 Clause ID（本阶段尚无 Clause）；不同运行同一稳定身份/配置不产生随机漂移（如果使用快照身份分配需给出具体稳定规则）。
- Schema：`Document.model_validate_json` 通过，且未修改 contracts；导入 Parser 不加载第三方模型或启动外部连接。
- 回归：现有 Frozen Schema 测试 / 7 业务模块接口独立测试 / 代码边界测试均通过。
- 可选真实烟测：GB 50010 至少 1 个真正 OCR 成功的页、至少 1 个无 OCR 处理的页；**真实 PDF 不作为自动离线单测必备文件**。

验收日志要明确区分：**离线单测（Fake）**、**合成图像真实 OCR**、**GB50010 真实 PDF 实际运行**。不能把三者混报。

## H. Golden Dataset 第一轮建立：仅候选，不冒充金标

在 Parser 模块测试或 `evaluation/` 内制作 `golden_cases.v0.candidates.json`，可引用附送 `GOLDEN_DATASET_CANDIDATES.json`：

- 记录 PDF 物理页、目标结构现象（封面、表格续页、多编号公式、说明无号等）、状态 `candidate_pending_human_review`。
- **候选绝不是 golden**；只有经过人工对照扫描图确认的 text/bbox/table cells/公式编号/Clause boundary 才允许标记 `verified` 并进入准确率分母。
- Task 1.1 的目标是打通数据集审阅/评估入口和记录机制，不要求在此任务完成 Task 1.3–1.5 的全部 Gold 标注。

## I. 测试命令与正式验收

优先按项目方式安装：

```bash
python -m pip install -e '.[dev]'
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest tests/contracts tests/architecture -q
python -m pytest -q
ruff check .
ruff format --check .
```

如新增可选依赖 `.[parser]` 或 `.[parser-ocr]`，须保持基础 `.[dev]` 不强制下载安装数 GB 的 OCR 权重；版本和安装说明清楚。选择网络/模型下载行为必须显式报告。

**Task 1.1 通过门禁**：

1. Frozen V2.4 DTO 与 Protocol 未改变，现有全量 pytest 不回退。
2. `parse()` 对合成图像扫描 PDF 和至少一个真实中文扫描页（模型可用条件下）输出结构正确的 partial `Document`。
3. 对 GB50010 文件报告总页数 **441**、被选择页和未处理页；抽查 PDF 页面文本层没有可提取文字，不把“无文本层”当空白/完成。
4. OCR 的真实原文、bbox、reading_order、身份、状态可追溯；至少一张 OCR overlay 人工目测结果可用。
5. 缺模型、损坏 PDF、非法页码等错误可诊断，不伪造成功。
6. 提交测试报告，区分通过、跳过、未验证；不冒称已完成高级结构识别。

## J. 结束报告（必填）

以 Markdown 汇报：

1. Git/冻结确认、原始全量测试结果、修改的代码文件。
2. PDF 引擎、中文 OCR 引擎及真实依赖版本/许可证/模型加载方式。
3. 公开接口保持不变的证据；实现类及依赖注入方法。
4. 真实 GB 50010 选页清单及每页 OCR 结果概况；未实际运行要写明原因。
5. `page_count`、部分提取状态、1-based 页码、bbox 坐标、ID 和 warnings 的验证。
6. 合成真实 OCR / Fake 单测 / 真实 GB 烟测的**分别统计**。
7. 单模块测试、全项目 pytest、Ruff lint/format 真实结果。
8. 质量不足和风险清单，Task 1.2–1.6 的待办，不做提前实现。
9. **本轮完成后立即停止，等待维护者验收 Task 1.1，未经指示不得开始 Task 1.2。**

## K. 如果现有仓库尚未真正 Frozen

用户在对话中已批准冻结，但你必须对实际源码状态负责：若 `AGENTS.md` 仍写 Task 0.2、`README` 仍写 READY_FOR_REVIEW，先检查是否只是文档未同步；若 Git 冻结提交/tag 尚未创建，则**停止 Parser 代码实施**并报告需先完成上一轮 Freeze Release 的真实 Git/document 操作。不得把旧源码直接当成 Frozen 已落盘，也不得代替用户决定覆盖 tag 或自动推送。

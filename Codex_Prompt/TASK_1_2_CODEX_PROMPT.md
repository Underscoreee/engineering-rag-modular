# Architecture Task 1.2 — MinerU 单引擎本地部署、真实 PDF 解析测试及 V2.4 适配

> **直接交给 Codex 执行。** 本文件替代旧 Task 1.2（MinerU vs PaddleOCR）任务书。本轮**仅部署和测试 MinerU**，不安装、不比较、不实现 PaddleOCR/PP-StructureV3，不制作引擎优劣选型报告。**优先真实跑通，再做内部适配。**

## 0. 强制范围及禁令

### 本次要实际做成

1. 在当前开发机（用户通常使用 Windows + WSL；按运行环境真实检测）安装并配置一个**真实可运行**的本地 MinerU 版本和需要的模型。
2. 对用户提供的真实扫描 PDF《混凝土结构设计规范（2015 年版）GB 50010—2010》进行指定页面的实际本地推理；先单页烟测，随后按 `TASK_1_2_EVALUATION_CASES.json` 完成 18 个候选案例的批处理/逐例执行。
3. 保存 **MinerU 原始 MiddleJson/ZIP/Markdown/图片**（按当前版本真实支持的格式）、清晰的运行日志、参数、模型及资源记录，并输出检查表与可复核的页面 bbox overlay；人工分析文字、版面、表格、公式。
4. 基于**运行后实际得到的** MinerU 输出，建立 Parser 内部单一 MinerU adapter 与私有归一化模型；在信息足够且冻结类型可表达时，映射为合法的 `Document Schema V2.4` 部分文档。无法无损转换的内容保存在 raw sidecar 并记录诊断。
5. 提交实际的部署步骤、命令、版本锁定、测试结果、异常页分析及下一阶段需要补足的领域能力。

### 不得做

- **禁止**下载、安装、比较或开发 PaddleOCR、PP-StructureV3、PaddleOCR-VL 作为本任务必要步骤；不需要双引擎性能对照、排名或推荐谁更好。
- 不修改 `src/engineering_rag/contracts/` 内被冻结的 Pydantic V2.4 模型、公共 Protocol、版本常量和关联校验；若遇到数据不能映射，只在内部适配层处理/记录缺口，不为迁就第三方结果篡改 Schema。
- 不提前实现 Task 1.3（真正的跨页表格恢复）、Task 1.4（工程规范公式与符号解释语义组装）、Task 1.5（Chapter/Clause、强条、条文说明关联）算法。
- 不将实际 PDF 上传官网、第三方云 API 或外部日志平台；**默认为本地推理**。下载官方模型权重和软件依赖可以进行，但须记录来源及版本、避免在公开仓库提交模型或扫描 PDF。
- 不以 FakeOCR、fixture、Markdown 样本或 `mineru --help` 代替实际 MinerU 模型推理；没有真实完成则明确标记 `blocked / not_run`。

## 1. 项目和硬件预检（先做，并记录）

按顺序阅读：

- 项目根目录 `AGENTS.md`、`README.md`、`docs/data-contracts.md`、`docs/schema-v2.4-freeze-record.md`（若存在）和接口文档。
- `src/engineering_rag/contracts/documents.py`、`contracts/protocols.py`、`contracts/common.py`。
- `src/engineering_rag/modules/document_parser/api.py`、`INTERFACE.md`、`internal/` 现有 PDF/OCR 代码和测试。
- `ARCHITECTURE_TASK_1_MASTER_PLAN.md`、Task 1.1 修复审查（若存在）。
- 本文件、`TASK_1_2_MINERU_ADAPTER_DESIGN.md`、`TASK_1_2_EVALUATION_CASES.json`、`TASK_1_2_ACCEPTANCE_CHECKLIST.md`。

运行基线 `python -m pytest -q`，记录结果。检查 `document-schema-v2.4` tag/冻结记录及实际公共代码差异；若看不到 Git 历史，写 `not_verified`，不伪造 tag。

检查并记录：`uname -a` / Windows / WSL 版本、Python、pip/uv、CPU 核数、可用内存和磁盘空间；有 NVIDIA GPU 时检查 `nvidia-smi`、驱动和显存；无 GPU 不得假设可用 CUDA。

**Task 1.1 历史遗留：**检查旋转 + CropBox 的 4 个坐标边界和 FileRef sha256/size_bytes 的 2 个校验边界是否真正修复。若仍未修复，允许先在隔离 MinerU 环境**部署及原始结果测试**，但是将其列为 V2.4 正式集成的 blocker，不得绕过源文件校验或把问题归咎于 MinerU。

## 2. 部署 MinerU：只用真实官方版本与真实命令

### 2.1 推荐技术基线

优先用 MinerU **4.x 稳定版**，在独立的 Python 3.12 虚拟环境中安装；以当次官方文档和 `--help` 为权威。4.x 官方指南示例：

```bash
# 在独立工作目录，例如 .local/mineru-runtime，不要污染 Engineering RAG 主 venv
uv venv --python 3.12 .venv-mineru
source .venv-mineru/bin/activate
uv pip install -U 'mineru>=4.0,<5'
mineru version --json
mineru-kit --help
mineru-kit parse --help
```

若没装 uv，允许使用 `python3.12 -m venv` + `python -m pip install 'mineru>=4.0,<5'`；若缺 Python3.12，先检查当前 Python 是否在官方支持范围、可否隔离安装，**不要静默重装系统 Python**。若用户环境实际只能装 3.x，请先说明原因、版本/命令/数据协议差异；没有正式许可不得偷偷套用 3.x 老参数。

使用基础包 CPU/ONNX 路线保证有可运行起点；确认机器有合适 GPU/显存后**可以**额外测试官方推荐的本地加速方案（如 `mineru[full]`），但不得把高配硬件作为必需条件，也不必为了多种 GPU 模式做引擎选型。记录实际选择的 `tier`、`small_backend`、VLM engine、CPU/GPU 路径、模型源、权重、版本、参数与磁盘开销。

若 Hugging Face 受网络限制，可依官方文档在同一隔离环境中设置 `MINERU_MODEL_SOURCE=modelscope` 并记录；**不等于把 PDF 上传给 ModelScope**，仅为官方模型下载来源。优先保持 PDF 本地处理。

### 2.2 必须识别 MinerU 4.x 的 CLI / 协议差异

- 无状态批处理/落盘使用 `mineru-kit parse`，不要以 `mineru parse --json` 的命令状态/摘要冒充结构化 MiddleJson。
- 4.x 的 MiddleJson 使用序列化 `schema="docvortex.middle"`、`schema_version="2.0"`，顶层为 `pages[]`，页面 `page_idx` 从 **0** 开始；不要按老版 `pdf_info`、`_backend`、`_version_name` 盲目解析。若实际安装的版本发生变化，保存**原始真实 JSON** 并以当次官方协议调整 MinerU **私有** adapter。
- `mineru-kit parse` 官方支持 `--format middle_json`、`--format zip` 等格式；每一个真实输出的**输出路径形态、参数和扩展名**需通过当次 `--help` 核验。
- **扫描页必须使用模型 OCR 路线**，不能使用只读取 PDF 文本层的 `--tier flash --ocr-mode txt` 伪装扫描识别。
- MinerU 无状态 CLI 若不显式 `--pages`，可能解析**所有**页面。本任务绝不默认对 441 页全本发起推理；在命令中显式传选页参数，或者构造已记录原始页映射的小型选页 PDF。

首次烟测应选 GB 50010 第 16 页（正文文字）或其他实际可获得的清晰扫描单页。先运行真正的 `mineru-kit parse --format middle_json --tier standard --ocr-mode ocr --pages 16 ...`（具体命令排列以本机 `--help` 为准），确认文件存在、`schema` 标识正确、包含实际 OCR 结果、原始物理页码映射正确。再测试 ZIP/Markdown 导出。

**优先部署并运行成功，之后才写适配器，不要用 fixture 通过测试就宣称部署完成。**

## 3. 测试真实 GB50010 扫描 PDF

使用 `TASK_1_2_EVALUATION_CASES.json` 的 **18 个候选案例、21 个不同物理页**。重点案例：

- 第 16 页：中文 OCR、条文编号文本；
- 第 24、50 页：连续编号公式、LaTeX 与符号解释；
- 第 28–29 页：表 3.5.2 跨页续表及表注；
- 第 37–38 页：表 4.2.2-2 多级表头和续表；
- 第 126–127 页：表 9.1.2 跨页与第 9.1.3 条边界；
- 第 275–282 页：正文尾部到条文说明区段；
- 第 301 页：条文说明的无印刷编号公式候选（人工确认前不能写为已核实）。

### 3.1 执行顺序（降低首次下载/模型失败风险）

1. **部署证明**：执行 `mineru version --json`、`mineru-kit parse --help` 并记录安装环境。
2. **烟雾测试**：第 16 页，至少保存真实 OCR 文本和 raw MiddleJson。
3. **小批次重点**：第 24、50 页公式；第 28–29 页续表；逐步扩展至复杂表格第 37–38、126–127 页和第 301 页。
4. **覆盖全清单**：其他案例全部真实尝试或逐条记录 `failed/blocked/not_run` 的具体原因；**不能仅提交执行脚本而不运行**。
5. 跨页组分别测试连续双页输入与独立单页输入，以观察 MinerU 本身是否给出跨页关联信息；不强制本阶段成功拼成一张表。

### 3.2 可复现性与资源边界

保存：原始 PDF SHA256、原始 1-based PDF 页号、小 PDF 的原始页映射与 SHA256、版本、模型源、解析 tier/OCR 参数、DPI/旋转和裁剪、输入路径映射、命令、返回码、开始结束时间、耗时、峰值 RAM/VRAM（如可测）、输出大小、错误日志、是否首次下载模型/冷热缓存。

PDF 文件始终保存在本地，不能把 PDF 本体提交 git/ZIP 供公开发布。页面选择、进程超时、输出磁盘空间/文件大小应有限制，命令使用安全参数数组而非 `shell=True`，临时 ZIP 解压需防路径遍历。崩溃后可重试单案例，不覆盖之前成功产物或隐藏原始错误。

**不得发明准确率：**全部 18 例初始状态为 `candidate_pending_human_review`，`ground_truth=null`。没有人工核实标注，就不能报告“表格准确率 95%”或 CER/TEDS 等真值指标。可以报告原生结构化输出是否存在、OCR/公式/表格候选数量、页级成功率、运行时间和资源。不要把案例中的提示标签当成真正金标。

### 3.3 每个成功案例必须保存的产物

建议产物目录：

```text
data/eval/task1_2_mineru/
  deployment/environment.md
  deployment/mineru_version.json
  runs/<run_id>/manifest.json
  runs/<run_id>/<case_id>/input_pages.json
  runs/<run_id>/<case_id>/raw/           # MinerU MiddleJson / ZIP / Markdown / images（按真实产物）
  runs/<run_id>/<case_id>/normalized.json
  runs/<run_id>/<case_id>/diagnostics.json
  runs/<run_id>/<case_id>/overlay/       # bbox 叠加图片
  runs/<run_id>/<case_id>/stdout.log
  runs/<run_id>/<case_id>/stderr.log
  reports/mineru_real_pdf_test_report.md
```

真实大文件与扫描截图须加入 `.gitignore`；提交的测试 fixture 必须是最小、可分享、无敏感内容的材料。诊断写明每个元素在当前阶段是否有文字、bbox、公式 LaTeX、表格结构、置信度及其状态。

## 4. MinerU 内部适配器与 V2.4（必须在真实部署测试后进行）

在 `document_parser/internal/` 内实现**一个** MinerU adapter；不要在 `contracts/` 引入第三方类。参阅 `TASK_1_2_MINERU_ADAPTER_DESIGN.md`。

### 4.1 最小内部模型

建议 `MinerUParseResult` / `ParsedPage` / `ParsedElement` 含：MinerU 4.x schema_id 与 producer_version、原始物理页索引、类型、内容、bbox、坐标约定、读取顺序、公式/表格原文对象或引用、置信度、诊断状态、运行元数据与原始文件引用。**只从已观察到的实际 MinerU 输出字段构建**，未知数据使用 `null`、状态和诊断，不杜撰。

### 4.2 物理页与坐标

- MinerU 原始 `page_idx`（0-based）必须通过真实映射还原 PDF 物理页号（1-based）；对选页 PDF **绝不能简单认为 `page_idx+1` 就是原始 441 页 PDF 的页码**。
- `bbox` 必须转换到冻结 V2.4 的 pdf_points/top_left，考虑分辨率、缩放、裁剪、旋转以及 MinerU 4.x `extensions.docvortex_layout` 的真实几何信息；若不能可靠换算就保留在内部结果，不制造一个假的 PageBlock bbox。
- 读取顺序优先 MinerU 的正确顺序；bbox overlay 允许人工核对。

### 4.3 转换边界与强约束

- `DocumentParser.parse(ParseRequest) -> Document` 不变，选择 MinerU 属 Parser 私有配置；继续支持原 Task 1.1 现有后端，不破坏其行为。
- 通用 MinerU 元素 type 不能直接映射中国规范的 13+unknown 页面类型；不能确认时 `page_type=unknown`。
- Block 类型只能 `title/body/table/image/formula`；来源不明或缺 bbox 的元素留在 sidecar 并记录丢弃原因。
- 表格的物理片段 `PageBlock(table_id=...)` 必须引用 `Document.tables[]` 唯一 `LogicalTable`；数据不完整可在冻结契约允许范围设 `data=null`、`extraction_status=structure_only`，不能假造 `columns/data`、`raw_grid` 或跨页归属。
- 公式每条 `formula_id` 唯一，`equation_number=null` 时区分“确认无号”与“尚未识别”：未经核对使用 `equation_number_status=unknown`。符号说明不得凭模型未提供的数据虚构。
- `sections=[]`，`clauses.normative=[]`、`clauses.explanations=[]` 为本阶段正常情况；不要臆造 GB 条文语义、强制性或说明关联。
- 映射后的任何完整/部分 Document 必须通过冻结 Pydantic V2.4 校验和 JSON dump/load；标明 `processing.partial=true`、未完成领域解析的状态。无法构造合法 Document 时明确**adapter blocked**，保留 raw MinerU 结果供后续使用，而不是修改 Schema。
- 不允许通过“把所有 OCR 文字都当做一个整页 bbox”的方式绕过 Block 级几何约束。

## 5. Codex 应实现的脚本与测试

### 5.1 可直接执行的 CLI

名字允许与现有脚本结构一致，至少具备下列功能：

```text
scripts/mineru_env_check.py             # 版本、平台、依赖与本地模式检查
scripts/prepare_mineru_eval_cases.py    # 选页 PDF/PNG + 原始页映射
scripts/run_mineru_cases.py             # 运行真实 MinerU CLI、逐例产物、状态和失败原因
scripts/visualize_mineru_results.py     # 坐标 overlay
scripts/validate_mineru_outputs.py      # 4.x 协议、页码、结构及 V2.4 部分结果验证
```

不强制使用这些文件名，但应有 `--help`、`--pdf`、`--case-id`/`--all-cases`、`--output`、`--timeout`、`--dry-run`、明确退出码和恢复/重试策略。不许全本 441 页默认运行。

### 5.2 测试分层

**无模型单元测试（必须）：** MinerU 实际 4.x MiddleJson fixture 的协议识别、page_idx 和选页原页映射、缺字段/bbox、非法坐标、未知 type、公式未知编号、表格 fragment/logical 引用、Frozen V2.4 校验、部分处理状态、失败路径、ZIP 安全与拒绝云 API。

**本机真实集成（必须尝试并记录）：** 至少第 16 页中文 OCR、24 或 50 页公式、28–29 页跨页表格的真实推理，逐步完成清单。真实推理可以使用 `@pytest.mark.real_mineru` 独立运行，不要让默认 pytest 下载 GB 大文件/模型。

测试命令（按项目实际路径调整）：

```bash
python -m pytest -q
ruff check .
ruff format --check .
```

记录实际成功数、失败、跳过、未安装或无环境时的 blocker，不能因为 Mock fixture 通过就宣称 MinerU 部署通过。

## 6. 报告模板和验收

最终提交 `docs/task-1.2-mineru-real-test-report.md`（或 reports 目录中等效文档），至少包含：

1. 部署机器、OS/WSL、Python/MinerU **实际版本**、官方文档匹配性、模型来源/缓存、硬件与隔离方式。
2. 真实安装命令、`mineru version --json` / `mineru-kit parse --help` 的实测结果、许可证审查、是否真正本地运行。
3. 对 **18 个案例**逐一给出 `succeeded / failed / blocked / not_run`、耗时、原始产物路径及日志；如只做部分，说明其余原因，禁止写成全部通过。
4. 重点人工视觉核查：正文第16页、公式第24/50/301页、表格第28–29/37–38/126–127页的识别内容、bbox、LaTeX/表头信息有无，明确原始 MinerU 能力与**后续工程规范语义处理**之间的差距。
5. 单引擎运行统计、失败原因、需要改进项；没有金标时不提供虚构 CER/F1/TEDS。**不出现 PaddleOCR 对比、排名和选型建议**。
6. 私有 MinerU adapter → 部分 V2.4 的真实校验结果、不可映射字段和诊断信息，确认 `contracts/` / 公共 Protocol 未变化。
7. 项目 pytest、Ruff、Task 1.1 六项遗留校验结果，以及本次资源/许可证限制。
8. 是否达到“MinerU 已可重复本地解析工程扫描规范样本”，若仍有阻塞，明确阻塞和最小解决措施；**不要把本 Task 标为已通过，除非实际跑通真实模型和至少一份完整的原始结构化结果**。

## 7. 开发执行顺序（不可调换主次）

**A. 预检和安装 → B. 真实扫描单页成功 → C. 重点复杂表格/公式案例 → D. 18例完整测试/逐例状态 → E. MinerU 单后端内部适配和 V2.4 桥接 → F. 单元测试、报告与验收。**

若卡在安装/模型下载/显存，停止声称真实推理成功，但仍可提交环境诊断和部分独立适配测试作为阶段进度；必要时报告硬件/网络阻塞，让用户决定是否调整运行平台。不得未经授权改成云端 API 或切换到 PaddleOCR。

完成后**停止**，等待用户验收和后续 Task 1.3。

## 8. 官方参考（执行当日核实）

- 安装与版本：https://opendatalab.github.io/MinerU/zh/quick_start/
- CLI 与 `--pages`：https://opendatalab.github.io/MinerU/zh/usage/cli_tools/
- 4.x MiddleJson： https://opendatalab.github.io/MinerU/zh/reference/output_files/
- 模型来源与档位：https://opendatalab.github.io/MinerU/zh/usage/tiers/
- 官方源码：https://github.com/opendatalab/MinerU

> 本文件是未来在用户的 Codex 环境里执行的任务指令；**这里没有声称已经替用户安装 MinerU 或运行上述命令**。

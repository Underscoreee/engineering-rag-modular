# Task 1.4 — 工程规范公式结构化验收清单

> 任务开始时每项均为 `[ ]`，不代表通过；真实验收需填 `PASS / FAIL / BLOCKED / NOT_RUN` 并附日志/文件路径。Frozen V2.4 不能为适配算法而改变。

## A. 前置与实测真实性

- [PASS] 已阅读 AGENTS、Document V2.4 Frozen 源文件与 Parser 接口，确认 `DOCUMENT_SCHEMA_VERSION="2.4"`。
- [PASS] 记录基线 Git diff/tag、pytest、Ruff。
- [PASS] Task 1.1 的 6 项旋转/文件 hash/size 历史反例已核查。
- [PASS] 识别 MinerU 实际版本、model/tier/parse_mode、MiddleJson `schema`/`schema_version`、页号映射与源文件 SHA256。
- [PASS] 三页均有真实原始 MinerU 产物；页 24 的原 PDF 直跑失败及本地栅格回退均完整记录。
- [PASS] 不依赖假 OCR 冒充 MinerU 实测、不默认处理 441 页、不上传外部服务。

## B. 公式解析、编号与 LaTeX

- [PASS] 独立的 display equation 检测和可重放原始来源引用。
- [PASS] 公式 Block 在 `bbox` PDF points、页面宽高、rotation/CropBox、reading_order 上合法。
- [PASS] 公式 `formula_group_id` 与所有 `formula_id` 文档作用域唯一、稳定、可重入，无重复 Block。
- [PASS] `Equation.equation_number` 按独立公式关联，不以整个 group 共享一个号码。
- [PASS] `printed` 有真实 MinerU equation tag/公式图片来源，且自动解析仍为 unverified；当前无独立编号框已明确披露。
- [PASS] 无可靠编号时使用 `unknown`+`null`；`confirmed_absent` 只有人工核验且 equation verified 时使用。
- [PASS] 正文引用式号、条文号、单位括号、表号、另一组编号不能误识别为目标公式编号。
- [PASS] 多行 `aligned/cases/frac` 未被错误拆成多条 Equation；多条编号公式未被错误并成一条。
- [PASS] LaTeX 保留原式字符、上下标、希腊字母及数学结构，不执行推断性改写。
- [PASS] 图片-only / 无转写保持 `latex=null`、适当未转写状态、raw 图片和警告，不标全部完成。

## C. 符号解释及相邻正文

- [PASS] `symbol_explanations=null` 和 `items[]` 的冻结数据形状正确。
- [PASS] “式中：”跨行、多个符号、单位、上下标、中文标点、希腊字母测试通过。
- [PASS] 符号解释能用真实位置与阅读顺序关联正确的公式组；证据不足时不强归属。
- [PASS] 不删除原始 Body 来源，下一公式、新条文、新标题之后的内容未被误吞并。
- [PASS] 不新增 `intro`、`unit`、`line_index` 或 V2.4 中不存在的公式字段。
- [PASS] 现有 `derive_clause_plain_text` 的公式/符号解释回归测试仍通过，Task 1.4 不新建 Clause。

## D. 真实 GB 50010 样本

- [PASS] 物理页 24：真实 MinerU 栅格回退产物 + 两条编号公式的编号/归属复核 + 符号解释核查；原 PDF 直跑失败已保留。
- [PASS] 物理页 50：真实 MinerU 产物 + 6.2.1-1 至 6.2.1-7 编号的逐条核查 + 释义归属。
- [PASS] 物理页 301：真实 MinerU 产物 + 显示公式；机器没编号保持 `unknown`。
- [PASS] 每页保存带来源/版本的 `raw JSON`、候选列表、sidecar、bbox overlay、`Document V2.4`、诊断日志。
- [PASS] 不存在人工 Gold，未计算或宣称识别准确率。
- [PASS] 真实输入的物理页码/页脚印刷页码区别正确；来源 SHA256 可复现。

## E. 合同、工程质量、交付

- [PASS] `Document.model_validate(document.model_dump(mode="json"))` 及 JSON roundtrip 通过。
- [PASS] 不重复添加 Task 1.2 占位公式 Block，不污染 Task 1.3 table/fragment，也不删除其它 body/image block。
- [PASS] `processing.partial`、page status、machine OCR `unverified` 保持真实，没有假 `verified`。
- [PASS] 最终输出重新序列化并验证整份 Document。
- [PASS] 严格检查实际 MinerU 4.x `docvortex.middle` 2.0；旧格式显式拒绝。
- [PASS] 默认离线单测不下载模型，拒绝危险路径/ZIP 逃逸与无界大输入。
- [PASS] 有复现用 CLI `--help`、离线重放、错误处理和 artifact run manifest。
- [PASS] 原有完整 pytest、32 项公式测试、Ruff lint/format 均有真实输出。
- [PASS] 冻结 `contracts/**`、公共 Protocol 与冻结 tag 比较无改动。
- [PASS] 最终报告包括逐案例结果、真实日志、已知问题；Task 1.5 尚未启动。

## 最终结论

- **PASS**：全部关键合成负例和项目回归通过；三组真实 MinerU 页有来源/可视化与可复核处理记录；V2.4 冻结无改动；缺失内容如实披露。
- **PARTIAL**：公式后处理代码与测试基本完成，但部分实测或 LaTeX/符号归属证据不足，明确具体 gap。
- **BLOCKED**：无真实 MinerU 输入或必要环境，无法证明核心真实目标；报告具体阻塞及复现方式。

**未通过不得写“Task 1.4 已全部验收通过”。完成后停止，等待用户独立验收，不自动开始 Task 1.5。**

## 实际验收记录（2026-10-12）

- Git 基线：`a4d5f4e484902d3b594168e7f7f4d5aec3fb2663`；冻结 tag commit：`ebd9b29b3bb475401c8e91a30303ae46a8c119aa`。
- 开发前基线：`207 passed, 4 skipped`；Ruff lint/format 通过。
- Task 1.4 合成规格：`32 passed`；真实三页集成：`4 passed`。
- Parser 独立：`113 passed`；Task 1.1 历史缺陷：`6 passed`；契约：`114 passed`；七模块均可独立运行。
- 默认完整回归：`239 passed, 8 skipped`；启用真实产物：`247 passed`。
- Ruff：`check` 通过；`format --check` 通过（178 files already formatted）；`git diff --check` 通过。
- 冻结保护：相对 `document-schema-v2.4` tag，`src/engineering_rag/contracts/` 与公共 Protocol 零差异。
- 真实产物：`data/eval/task1_4_formulas/runs/final/`，33 个文件，约 1.5 MiB。
- 结论：**PASS**。页 24 原 PDF 直跑能力仍有已记录的 MinerU blocker，但真实页栅格回退、结构化输出和来源追踪达到本任务门槛；全部内容仍待人工核验。

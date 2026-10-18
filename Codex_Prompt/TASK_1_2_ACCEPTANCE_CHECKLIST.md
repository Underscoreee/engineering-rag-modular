# Task 1.2 MinerU 单引擎部署与测试 — 验收清单

> 禁止将以下待做项写成已通过；逐项用实际命令、日志和产物证明。无 PaddleOCR 对比要求。

## A. 环境与真实部署

- [x] 已阅读 AGENTS/冻结 V2.4/Task 1.1 代码与测试，并记录基线。
- [x] 检查 Task 1.1 旋转/CropBox 和 FileRef 的 6 项遗留缺陷；未解决时列为正式集成 blocker。
- [x] 实际检测 OS/WSL、Python、CPU/GPU、RAM、磁盘空间、驱动。
- [x] 在**隔离环境**安装并记录 MinerU 具体版本、模型/权重/配置、模型下载来源与许可证。
- [x] `mineru version --json`、`mineru-kit parse --help` 的真实命令与输出已保存。
- [x] 真实扫描第 16 页成功推理，获得可打开的 **真实 MinerU MiddleJson 或 ZIP**，不是 FakeOCR。
- [x] 解析默认在本地；没有外传真实 PDF 或依赖远程收费 API。

## B. 真实 GB 50010 页面测试

- [x] 验证真实 PDF 页数、SHA256、选页输入及其原始 1-based 页映射。
- [x] 第 24、50、301 页公式案例有真实输出或明确 blocker。
- [x] 第 28–29、37–38、126–127 页跨页表有真实输出或明确 blocker。
- [x] 18 个候选案例逐条填写 `succeeded/failed/blocked/not_run`；不能遗漏或假称全部成功。
- [x] 跨页案例分别试连续双页与单页独立处理，保留结构差异和日志。
- [x] 每个成功案例有 raw、manifest、耗时和资源日志、诊断及可视化 overlay。
- [x] 分开呈现 OCR/表格/公式候选覆盖情况与后续工程规范领域语义能力。
- [x] 所有待人工复核候选 `ground_truth=null`，无真值时不产生 CER/F1/TEDS“准确率”。

## C. 冻结 V2.4 内部适配

- [x] 真正从 MinerU 4.x 的 `docvortex.middle` 读取而非旧版 `pdf_info` 或命令状态 JSON。
- [x] 源页 `page_idx` 0-based → 原 PDF 物理 1-based；被截取/拼成小 PDF 时映射正确。
- [x] 转换 bbox 到 pdf_points/top_left，覆盖缩放/旋转/CropBox；无法精确转换不伪造 bbox。
- [x] TableBlock 与顶层 LogicalTable 的 `table_id` 引用一致，未完整识别标为 partial/structure_only。
- [x] FormulaID 唯一、原文编号未知与确认无号不同、LaTeX 来源真实。
- [x] 不猜测 13 类规范页面、Section/Clause 或强制性；partial 状态诚实。
- [x] 生成的全部 V2.4 JSON 通过现有模型校验和 JSON roundtrip。
- [x] 冻结 `contracts/`、Protocol 和其类型签名未修改。

## D. 代码、可复现和报告

- [x] 脚本支持显式案例、超时、输出、重试/干跑；默认不分析 PDF 全部 441 页。
- [x] 依赖可复现；主项目在不安装 MinerU 时仍能导入、运行常规测试。
- [x] subprocess 安全、ZIP 解压安全、输出文件与日志不泄漏敏感信息。
- [x] 默认 pytest、真实 MinerU 测试分别有**实际结果**；Ruff lint/format 真实运行或写明阻塞。
- [x] 提供 `docs/task-1.2-mineru-real-test-report.md`，明确结果、原始产物目录、当前局限与后续 Task 1.3 的优先问题。
- [x] **完全没有 PaddleOCR 部署/对比/排名/选型**；完成后停止等待验收。

## 通过标准

**最低通过门槛：** MinerU 本地安装并真正识别至少一页 GB 50010 扫描件，产生可复查的结构化原始数据；典型表格、公式案例实际尝试并保留证据；18 例全部有真实执行/失败/阻塞状态；V2.4 私有适配有可验证示例且公共契约不变。若 Task 1.1 残留缺陷影响正式集成，则此 Task 可在部署测试层面完成，但不得宣称生产集成完全通过。

## 2026-10-11 实际验收记录

- 18 例中 17 succeeded、1 failed（P024 `Unsupported warp settings`）；21 个模式为 20 succeeded / 1 failed。
- 23 份 normalized、23 份 partial V2.4 JSON、26 张 overlay 均已生成并回读；原始产物在 `data/eval/task1_2_mineru/runs/final/`。
- Parser 62 passed；Task 1.1 审计 6 passed；contracts 114 passed；完整 pytest 188 passed；Ruff lint/format 通过。
- 本 PDF 的 21 个候选物理页旋转均为 0，overlay 已核对实际 CropBox/页尺寸。通用旋转+CropBox 边界由 Task 1.1 回归覆盖；本轮没有伪称完成任意 MinerU 输入的旋转实测。
- 当前结论为“最低门槛通过、存在 P024 blocker”，不是 18/18 全绿或生产领域解析完成。

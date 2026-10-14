# 直接交给 Codex — Architecture Task 1.6 最终验收前定向修复

你现在负责修复 Engineering RAG `Task1_6.zip` 对应源码的独立验收缺陷。**不新增 Chunking、检索、Embedding、LLM，也不修改 Document Schema V2.4 Frozen 公共契约和 Protocol**。

请完整阅读 `AGENTS.md`、Task 1.6 开发任务书、`docs/task-1.6-end-to-end-report.md`、本次 `TASK_1_6_INDEPENDENT_AUDIT.md`、`test_task16_independent_gaps.py` 及失败日志。先在本机复现，再最小范围修复，不得删除或调整测试预期来“假通过”。

## 0. Gate 0：冻结和基线

- 记录 Git commit/工作区状态、Python 和 MinerU 版本、ruff 版本、实际依赖与运行命令。
- 运行 `python -m pytest -q` 和 `ENGINEERING_RAG_RUN_REAL_MINERU=1 python -m pytest tests/integration -q`，解释 skipped；并单独执行四个新增 RED 反例。
- 通过 Git 比较 `contracts/**` 与 Frozen V2.4 tag（tag 缺失时报告无法证明，不得擅称比对已通过）。
- 原始 MinerU middle_json 和既有历史 run 只读；在**新的 run 目录**生成所有后续结果。

## 1. P1：人工 Golden 的评价必须绑定真实 Document

修复 `internal/e2e/quality.py`、`scripts/run_document_parser_e2e.py`，务必区分三个输入：

- `gold`: 人工确认的 **reference label**，含审阅人/时间/版本/证据/来源页和 PDF hash。
- `prediction`: 从此次 `final_document` **直接构造、不可由人工标注记录冒充**的机器预测。
- `source context`: 本次实际 PDF `sha256`、标准代码/版本、原物理页、模型版本、Parser 版本、gold dataset_version、支持的 label_type。

实现必须：

1. 拒绝 Gold `source_sha256` 与实际 Document SHA 不一致、不可用页码、重复或冲突标注、reviewer/date 不全或时间无时区、未知类别；人工 Gold 中若带 `machine_predictions` 字段，不得用它作为评分权威，可拒绝或忽略并报告。
2. `verified_labels.page_types` 必须仅与 `final_document.pages` 的 `page_type` 逐页对比；CER 的 `prediction` 应由权威 OCR Block 和可验证 span 映射得到，而非从 Gold 上传的自填 prediction 取值。没有可信 Block/span 关联就记 `not_evaluated`。
3. 式号/公式条件/LaTeX/符号解释、表格、Clause 等指标同理，必须由权威 Document 与来源/人工 Gold 进行有分母的比较；不可把人工随手提交的一组 bool 当作模型事实。
4. 合法、可复现、含有刻意错误预测的测试，必须能够产生真实的错误指标，而不是全部 `not_evaluated` 或伪造 100%。
5. 保持 Parser **内部类型化接口**，不修改公共 `contracts/evaluation.py`、V2.4 或其他公共契约。

## 2. P1：PageType macro-F1 语义修复

- 对已标注而全部预测错误的用例：`macro_f1=0.0`（不是 null）。
- 只在根本没有 verified Gold / 评价分母为 0 时输出 `not_evaluated`；其余情况正确给出 class-specific TP/FP/FN、Precision、Recall、F1 和宏平均。
- 定义哪些类别进入 macro 平均，尤其 no-support labels、unknown、zero predicted positives，写出规范并增加覆盖。
- 不改变现有准确率的正确数据来源原则。

## 3. P1：原子且不可覆写的 run 创建

- 在任何 artifact/checkpoint 文件写入之前，检查 `--output` 是否包含现存 `run_manifest.json` 或之前完成的结果；没有 `--resume` 时拒绝复用同一路径，提供清楚错误。
- `--resume` 必须保留原始 run_id，且校验 source PDF、配置 hash、model_signature、批次输入和保存 artifact 哈希；成功批次绝不重新跑。
- 增加并发防护（简单的原子创建目录/锁也可），防止两个任务同时写同一 run。写文件仍用 temp + fsync + atomic rename。
- 用独立临时目录跑两次：run-A 成功后 run-B 同一路径不加 resume 必须拒绝，历史 run-A 的 manifest 和所有 artifact hash 完全不变。

## 4. P2：Replay 与 checkpoint 的符号链接约束

- 检查 `_load_result()` 和 `CheckpointStore._resolve_artifact()` 以及涉及 replay/raw ZIP 的所有文件入口，不得先 `.resolve()` 才判断 `.is_symlink()`。
- 使用可信输入根目录和路径 containment；对输入路径或路径任一父节点为不可信 symlink 的情况 fail-closed；加入安全正例与坏路径/目录穿越/符号链接目标测试。
- 不允许任何 replay 文件绕过 source SHA-256/标准身份检查。

## 5. 真实 MinerU 第 24 页失败（独立 issue，不得通过 mock 抹掉）

- 复现真实原 PDF 物理页 24 运行 `Unsupported warp settings` 的故障，检查 MinerU 4.0.12、图像 deskew/warp 参数、模型与 rasterization。
- 允许在 Parser **私有预处理**中试验严格受控的局部兼容/裁剪方案；记录原 PDF 页哈希、派生图片哈希、变换矩阵及一切来源信息。
- **不得**把现有 fallback 的成功回放报告成同条件原 PDF 实时推理已通过。即使没有解决，也应保留失败为 PARTIAL 并交付最小复现。

## 6. 真实测试与交付

最少实际运行：

```bash
python -m pytest tests/audit/test_task16_independent_gaps.py -q
python -m pytest -q
ENGINEERING_RAG_RUN_REAL_MINERU=1 python -m pytest tests/integration -q
ruff check .
ruff format --check .
```

再对真实 GB 50010 跑新的第 16 页 smoke test 和 21 页 save-raw replay，验证 `Document.model_validate_json()`、JSON roundtrip、两批 attempts 不变、最终 Document SHA 与适用条件/跨页表格/Clause 身份一致；人工 verified Gold 缺失时仍须 `not_evaluated`，但来源混入/虚假预测必须 fail-closed。

提供 `TASK_1_6_REPAIR_REPORT.md`、改动源码、4 个 GREEN 反例、pytest -rs、Ruff、Live/replay/partial 状态、质量评估数据来源证明和历史 run 未覆盖核验。对于其它规范的适配，把固定 GB PDF SHA 和 replay catalog 移到用户可配置的样本清单，不要在基础 Parser 内依赖这个标准（可作为单独 P2 任务）。

完成后停止，等待维护者独立验收，**不启动 Task 1.7 / Chunking / Retrieval / 全本 441 页推理**。

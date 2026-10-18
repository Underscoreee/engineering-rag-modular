# Task 1.6 最终验收清单

> 填表规则：每项写 `PASS / FAIL / NOT_RUN / BLOCKED`，填真实命令或证据路径；没有结果不默认勾选。

## 0. 前置冻结和 Task 1.5 风险

- [x] **PASS** — Document Schema `2.4` / Protocol 保持 FROZEN；`git diff -- src/engineering_rag/contracts` 无输出。
- [x] **PASS** — `python -m pytest tests/audit/test_task15_independent_gaps.py -q`：`4 passed`。
- [x] **PASS** — 历史输入 manifest 核验固定 SHA；`TASK_1_5_IMPLEMENTATION_REPORT.md` 存在。
- [x] **PASS** — MinerU 4.0.12 / Python 3.11.17 / WSL2 / CPU basic；模型签名和资源见 live run manifest/report。

## 1. 端到端

- [x] **PASS** — 第 16 页真实全链路 succeeded；`runs/live-p16-integrity-final-20261012/`。
- [x] **PASS** — 回放 manifest 显式声明 saved-real/no-inference；`runs/replay-representative-final-20261012/`。
- [x] **PASS** — 物理页、PDF points bbox、固定 source SHA 进入最终 Document/sidecar。
- [x] **PASS** — 严格 V2.4 构造和 JSON 往返通过；合并器拒绝重复/冲突引用。
- [x] **PASS** — `runs/replay-formula-final3-20261012/qa/semantic_integrity.json`：条件/符号重复均为 0；301 pending 保留。
- [x] **PASS** — 9.1.2 范围 126–127；Task 1.5 与 Task 1.6 real replay 回归通过。

## 2. 分批与恢复

- [x] **PASS** — 21 页 replay 为 20+1；live 隔离为最多 2 页并保护三组跨页表；最终 Document 合法。
- [x] **PASS** — 11 个成功批次 attempts 保持 1；页 24 failed 批次真实重试至 attempts=3；`qa/resume_audit.json`。
- [x] **PASS** — 源/标准/坐标/Schema/稳定 ID 的 fail-closed 单元和契约测试通过。
- [x] **PASS** — 历史输入只读；新 run 独立目录；checkpoint 使用 fsync + atomic replace。
- [x] **PASS** — 非零/超时、坏 ZIP、篡改哈希、陈旧配置/模型、磁盘提交失败有反例测试；真实页 24 无假成功。
- [x] **PASS** — 全本保护测试通过；441 页为 NOT_RUN，预算至少 23 批。

## 3. 评估和金标

- [x] **PASS** — 18 组候选/21 页 metadata 输出为 `candidate_pending_human_review`。
- [x] **PASS** — JSONL 含 reviewer/date/dataset_version/provenance 空槽和逐 Block bbox 证据；overlay 已输出。
- [x] **PASS** — evaluator 仅接受带完整审计元数据的 verified 条目；CER、分类 P/R/F1 和各结构观测保留 N/M。
- [x] **PASS** — 当前 verified=0，全部准确率为 `not_evaluated` / `0/0` / null。
- [x] **PASS** — error catalog、lineage、pending、partial/unknown 覆盖统计存在。
- [x] **PASS** — live profile 含 wall/page、batch P50/P95、RSS 测量边界、成功率和产物字节数。

## 4. 测试与产物

- [x] **PASS** — 全量 `285 passed, 18 skipped`；18 项均为未设置 real opt-in；显式 real integration `18 passed`。
- [x] **PASS** — `ruff check .` / `ruff format --check .`：通过（221 files formatted）。
- [x] **PASS** — 所有 final Document 严格校验和 JSON 往返通过。
- [x] **PASS** — 要求产物齐全；`final/artifact_manifest.json` 记录逐文件 SHA-256/大小。
- [x] **PASS** — `docs/task-1.6-end-to-end-report.md`、`task-1.6-quality-analysis.md`、`task-1.6-operations.md`。
- [x] **PASS** — 未修改后续业务模块，未推送 Git。

## 5. 结论（维护者验收填写）

| 项目 | 状态 | 证据路径 / 备注 |
|---|---|---|
| 技术链路 / 冻结契约 | PASS | contracts diff 0；P16 live succeeded |
| 真实 MinerU 推理 | PARTIAL | 代表集 20/21；P24 `Unsupported warp settings` |
| 批次和恢复 | PASS | 成功批次复用；失败批次 attempts=3 |
| 已核验 Golden 质量 | BLOCKED | 0 条人工 verified；准确率 not_evaluated |
| 回归测试 + Ruff | PASS | 285 passed / 18 opt-in skipped；real 18 passed；Ruff PASS |
| 441 页全本（可选） | NOT_RUN | 无显式授权不得运行 |
| Task 1.6 综合 | PARTIAL | 工程管线达标；P24 引擎失败与人工 Golden 待维护者处理 |

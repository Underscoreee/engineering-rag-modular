# Architecture Task 1.6 端到端实现报告

日期：2026-10-12　结论：**PARTIAL**

## 范围与冻结边界

本阶段只整合既有 PyMuPDF/FileStore、MinerU 4.x、表格、公式和语义装配器。公共
`contracts/` 和 Protocol 未修改，未开发 Chunking、Retrieval 或 LLM。源 PDF 的运行时身份为
SHA-256 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`、
154122112 字节、441 页；标准身份为 `GB 50010-2010 / 2015年版`。

## Gate 0～4 结果

| Gate | 状态 | 实际结果 |
|---|---|---|
| 0 冻结与 Task 1.5 | PASS | 四项独立反例 `4 passed`；修复前完整基线 `274 passed, 15 skipped`；`contracts/` diff 为 0 |
| 1 单页端到端 | PASS | 原 PDF 第 16 页真实 MinerU 运行成功，Document V2.4 往返通过 |
| 2 批次/恢复/合并 | PASS | 21 页计划为 20+1；另以 2 页小批次完成失败隔离；来源/版本/坐标/ID 冲突 fail-closed；resume 成功批次未重跑 |
| 3 Golden/指标 | PARTIAL | 18 个候选已导出；无维护者人工复核条目，所有准确率为 `not_evaluated` |
| 4 真实代表集 | PARTIAL | 原 PDF 20/21 页推理成功；物理页 24 稳定失败；保存的真实产物回放 21/21 成功 |

## 实现

- `internal/e2e/`：私有严格 Run/Batch 模型、受保护批次规划、原子 checkpoint、严格合并、人工核验指标。
- `scripts/run_document_parser_e2e.py`：唯一组合入口；三种模式明确分离。真实模式经注入的 FileStore 和 PyMuPDF 校验源文件，再调用本地 MinerU。
- 合并核验 `document_id`、`file_id`、SHA-256、大小、页数、标准代码/版次/修订、bbox 坐标系和 Schema 版本；拒绝重复 page/block/table/formula group/formula ID 和表 fragment 冲突。
- checkpoint 保存 planned/running/succeeded/failed，输出哈希、配置哈希和模型签名；原子写入后才能提交成功状态。
- 页面类型仅基于可见标志和已建立分区推断；不增加公共字段。孤立或不确定内容进入 unknown/pending。

## 真实运行

### 第 16 页

`data/eval/task1_6_e2e/runs/live-p16-integrity-final-20261012/`

- 状态 succeeded，1 次尝试；MinerU 批次 9.45 s，总流程 12.76 s。
- 峰值 RSS 观测约 1.26 GB。
- raw bundle 含 MiddleJson、Markdown、model output、structured content、ZIP 和 stderr；最终包含 V2.4 JSON、overlay、lineage、pending 与 QA 文件。
- 随后 `--resume`：批次 attempts 保持 1；checkpoint 对 10 个批次产物逐一验哈希，`qa/resume_audit.json` 记录复用。

### 21 页代表集

`data/eval/task1_6_e2e/runs/live-representative-batch2-20261012/`

- 12 个批次，11 succeeded、1 failed；实际页面成功率 20/21（95.24%）。
- 总流程 260.90 s，按计划页数 12.42 s/page；观测峰值 RSS 约 3.50 GB。
- 物理页 24 在原 PDF 上稳定触发 MinerU 4.0.12 `Unsupported warp settings`。失败 checkpoint 和 stderr 保留；相邻批次不受污染。
- 早先 20 页首批也因同一错误退出，证明大批失败会被显式记录。小批次定位后，其余页面全部成功。
- 两次 `--resume` 后，11 个成功批次 attempts 仍为 1；页 24 attempts 为 3，三次均为同一明确错误。

### 真实保存产物回放

- 21 页：`data/eval/task1_6_e2e/runs/replay-representative-final-20261012/`，20+1 两批、21/21 输出、5.86 s。
- 49–50 公式/跨页条文：`data/eval/task1_6_e2e/runs/replay-formula-final3-20261012/`。
- 页 24 使用此前从原页生成的本地 raster fallback，manifest 明确标注为 replay-only 派生证据，不宣称为本次原 PDF 成功推理。

## 语义完整性

49–50 回放验证 7 个唯一公式 ID；`6.2.1-1` 条件为 `ε_c ≤ ε_0`，`6.2.1-2`
为 `ε_0 < ε_c ≤ ε_cu`，未传播到 `-3`～`-5`；两组符号解释数为 6 和 2；
Clause 引用 7 条公式；条件与符号说明的独立 Body 完整重复均为 0。跨页表格范围为
3.5.2（28–29）、4.2.2-2（37–38）和 9.1.2（126–127）。所有最终 Document
均通过 `Document.model_validate()` 和 JSON 往返。

## 阻塞与结论

不能给出 PASS：页 24 的原 PDF 实时推理仍失败；18 组候选尚无人工核验 Golden，因而不能计算准确率。
441 页全本明确为 `NOT_RUN_REQUIRES_EXPLICIT_APPROVAL`，估算至少 23 个 20 页批次，未执行。

## 最终测试

- Parser 独立：`148 passed`。
- 七个业务模块独立：Parser 148，其余六个模块各 1 passed。
- 完整默认回归：`285 passed, 18 skipped`；18 项均为未设置
  `ENGINEERING_RAG_RUN_REAL_MINERU=1` 的显式真实产物测试。
- 显式真实 integration：`18 passed`。
- Task 1.5 四项独立审计：`4 passed`。
- `ruff check .`：通过；`ruff format --check .`：221 files already formatted。

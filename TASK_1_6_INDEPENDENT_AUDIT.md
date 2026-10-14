# Engineering RAG — Architecture Task 1.6 独立验收报告

**审查对象**：用户本次上传 `Task1_6.zip`，独立解压副本；**审查日期**：2026-10-13。

## 总体结论

**PARTIAL，建议先定向修复，不批准 Document Parser 最终 PASS / 生产级识别精度声明。**

理由包括：
1. 原始 PDF 的 MinerU live 代表集仅 20/21 页成功，物理页 24 有已复现的 `Unsupported warp settings`（saved log）；
2. `gold_verified.jsonl` 为空，尚无可用人工金标，识别准确率不能评估；
3. 独立编写的四个评估/运行安全反例均失败，涉及可信评估输入、错误 F1、原始输入符号链接和运行产物覆盖。

## A. 真正独立执行的通过结果

| 类别 | 结果 | 证据 |
|---|---|---|
| 完整 pytest（不启用真实标记） | **284 passed, 19 skipped** | `baseline_pytest.log` |
| 显式开启保存产物集成测试 | **18 passed** | `real_integration_tests.log` |
| 21 页保存真实 MinerU 产物回放 | **成功**，两批 20+1，21 页合法 V2.4 | `independent_replay.log`、`independent_replay_summary.json` |
| 独立回放 vs ZIP 原有 final 文档 | **JSON 完全相同** | `independent_replay_summary.json` |
| `--resume` | **两批成功复用，attempts 均保持 1** | `independent_resume.log`、`independent_replay_summary.json` |
| V2.4 内容 | 21 页、4 Sections、5 LogicalTables、10 normative Clauses、3 explanation Clauses | `independent_replay_summary.json` |
| Ruff | **NOT_RUN**，本审查环境未安装 Ruff；上传报告自述通过 | 不作为独立 PASS |
| 真实 MinerU 现场模型推理 | **NOT_RUN**；上传 ZIP 内有真实模型日志和保存产物 | 本轮重放不能当 live |

备注：Codex 项目报告记录 `285 passed, 18 skipped`，本次按上传内容重新执行为 `284 passed, 19 skipped`。不证明其报告造假；可能受环境或依赖差异影响，建议 Codex 输出 `pytest -rs` 对照跳过原因。

## B. 真实项目产物核查

- `data/eval/task1_6_e2e/runs/live-p16-integrity-final-20261012/`：保存了 PDF 第 16 页本地 MinerU raw、最终 Document、Artifact Manifest 和 overlay。
- `data/eval/task1_6_e2e/runs/live-representative-batch2-20261012/run_manifest.json`：12 批，其中 11 成功、1 失败，第 24 页 3 次失败；失败源为 MinerU 图像 warp 兼容性，不是 Schema 拒绝。
- `data/eval/task1_6_e2e/runs/replay-representative-final-20261012/`：21 页回放、两批，`gold_verified.jsonl` 为空；所有准确率 `not_evaluated`，处理覆盖不是识别准确率。
- 49–50 专项回放：Clause `6.2.1` 的七式分成 5+2 两个 FormulaGroup，条件和符号说明不重复的现有测试通过；符号内容尚未经过逐字符人工 Gold 验收。
- PDF 441 页全本没有执行，符合之前的用户授权范围。

## C. 新增独立缺陷（有复现）

### P1-1 评估过程没有可信绑定真实 Document / source identity

- 路径：`src/engineering_rag/modules/document_parser/internal/e2e/quality.py` → `evaluate_verified_records()`；以及 `scripts/run_document_parser_e2e.py` 的 `verified_gold` 入口。
- 根因：直接从待评分 JSON 读取 `machine_predictions`，不核对这些预测与此次 **final Document** 是否一致；也没有在评估时强制核对源 PDF SHA、页面范围和 dataset identity。
- 已验证反例：虚构 `source_sha256` 为另一份 PDF，传入 `gold=body` 和 `machine_predictions=body`，模块报告 **page_type_accuracy=1.0（100%）**，尽管交付的第 50 页实际解析为 `unknown`。
- 影响：未来即使填入“verified”字段，也可能给出不真实的 100% 指标。属于数据评估可信度硬门禁。
- 建议：由 final `Document` 动态提取机器预测，仅从人工 Gold 接受 reference 真值；检查 source_sha256、page numbers、reviewer、reviewed_at timezone、dataset_version、annotation identity 与内容覆盖。验证数据集与模型执行版本对应；检测重复/冲突标注。

### P1-2 PageType macro-F1 在完全错误分类时变为 null

- 路径：`internal/e2e/quality.py` → `_page_type_scores()`。
- 根因：`precision=None` 或 `recall=None` 时 F1 被标为 `None`；macro 仅平均非空类。真实带标签却全部分类错误时 macro-F1 为 `None`，不是 0.0。
- 独立测试：一条已标注 body 却预测 unknown，`page_type_accuracy=0`，macro_f1 为 `None`。
- 预期：明确计入已定义的目标类集合，TP=0 且存在 FN/FP 的分类 F1 应为 0；真正没有标注和分母为 0 才是 `not_evaluated`。确定是否包括 zero support classes，说明 macro 平均约定。

### P1-3 未加 --resume 就能覆盖现有已完成 run

- 路径：`scripts/run_document_parser_e2e.py` → `main()`、`CheckpointStore.save()`。
- 复现：先用 `--run-id run-A --output same-dir` 成功，再用 `--run-id run-B --output same-dir`（**未指定 --resume**）执行，旧 `run_manifest.json` 的 `run_id` 从 run-A 变成 run-B，且重新写入 `batches`、final 等文件。
- 风险：历史产物被覆盖，损坏审计追溯/准确率复现性，违反本阶段不覆盖原始运行证据的约束。
- 建议：首次创建在任何写入前检查目标目录状态；已有 manifest/成功产物时 fail closed；只有身份匹配的显式 `--resume` 才可复用，并保持原 `run_id`。另可实现显式 `--new-run-id`；不支持无证据的同路径覆盖。

### P2-1 回放 JSON 符号链接检查形同虚设

- 路径：`scripts/run_document_parser_e2e.py` → `_load_result()`；`internal/e2e/checkpoint.py` → `_resolve_artifact()` 类似。
- 根因：先 `path.resolve()` 再 `path.is_symlink()`，resolve 后软链接身份已丢失。
- 实测：把有效 normalized.json 建立软链接并作为回放输入，`_load_result` 接受并完成解析，而它的安全策略意图拒绝 symlink。
- 建议：在解析或跟随 symlink 前先拒绝原 path 与敏感父路径上的符号链接；工作目录/输入根目录采用可信 containment 与 no-follow 语义，错误时 fail closed。正反测试同时覆盖恶意目录跳转和正常非链接文件。

### P2-2 运行入口仍专门写死 GB 50010 的 replay 身份

- 路径：`scripts/run_document_parser_e2e.py` → `SOURCE_SHA256`、`REPLAY_CATALOG`、`_load_result()` 和 `--expected-sha256` 默认值。
- 影响：当前样本能复现，但这不是可直接复用到其它工程规范 PDF 的通用回放入口。
- 建议：将“通用 CLI / runner”与“GB 50010 的样本 catalog/标准参数”分离，来源身份从用户显式输入 / 当次校验的 PDF 与可信 run manifest 获取；确保不会混用另一份标准的 same-page 产物。
- 本项为架构泛化建议，不作为本阶段四项 Red 测试之一。

## D. 四个新增 RED 测试

`test_task16_independent_gaps.py`（已随报告打包）实际运行 **4 failed**，见 `independent_gaps_failures.log`：

1. 伪造来源及预测，独立评估入口应拒绝 / 从 Document 读取预测。目前还没有 `expected_source_sha256` / `authoritative_page_types` 这两个建议的 Parser **私有**参数，测试表现为 `TypeError`。Codex 可以采用更好的等价接口，但不得修改公共 V2.4。
2. 100% 错误分类时 `macro_f1` 应为 0.0，现在为 null。
3. symlink 的 replay 输入应被拒绝，现在被接受。
4. 在有真实原 PDF 的显式集成测试中，同一 `--output` 的新运行不得覆盖旧成功 run，现在实际覆盖。

## E. 建议完成的验收路径

1. **首先解决 P1-1、P1-2、P1-3**：建立评估数据来源可信度、宏平均计算语义和产物不可覆盖原则。
2. 修复 P2-1，重跑四个新增反例；确保原有 284+ 集成 18 仍可运行，且 Ruff 通过。
3. 对物理页 24 的 MinerU `Unsupported warp settings` 做真实根因分析；优先局部预处理/兼容性配置且保留原页图像来源哈希。raster fallback 只能作为经过标记的衍生输入，不能伪称原 PDF 同条件成功。
4. 人工复核 Gold：最低从已选的 16、24、50、126–127、282、301 开始，并构造含错误的负向标注；不能简单复制机器候选或自行标 verified。
5. 交付 `pytest -rs`、Ruff 两项、真实 live 新产物、21 页 replay 对比、source binding 负例与人工标注版本，供再次独立验收。
6. 保持 Frozen V2.4 不变；不提前进入 Chunking，也不默认开始 441 页全本推理。

**本轮 PASS 范围仅限：独立回放 / 既有测试 / Resume 行为；Task 1.6 综合结论仍为 PARTIAL。**

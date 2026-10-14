# Architecture Task 1.6 最终验收前定向修复报告

日期：2026-10-13（Asia/Shanghai）  
结论：**PARTIAL**

PARTIAL 的唯一验收门槛原因是尚无维护者核验的 Golden Dataset，因此准确率指标仍必须为
`not_evaluated`。本次四项独立反例、原 PDF 第 24 页故障、21 页代表集回放与恢复均已完成修复
或验证；未运行 441 页全本，未修改 Document Schema V2.4 Frozen 契约。

## 1. 修复前复现

命令：

```bash
ENGINEERING_RAG_REVIEW_PDF='混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  .venv/bin/python -m pytest tests/audit/test_task16_independent_gaps.py -q
```

实际结果：`4 failed in 9.38s`。

- 质量评估接口不接受可信来源/权威预测，直接读取审核文件内的 `machine_predictions`。
- 全部分类错误时 PageType macro-F1 为 `null`。
- Replay 在检查符号链接前调用 `resolve()`，符号链接被跟随。
- 已完成 Run 可在不使用 `--resume` 时被再次写入。

修复前完整基线：`285 passed, 19 skipped, 3 failed in 11.88s`；第四项因完整测试未设置真实
PDF 环境变量而跳过，但在上述独立命令中已实际复现失败。

## 2. 定向修复

### 2.1 Golden Dataset 与 PageType 指标

- 发布级 `evaluate_verified_records()` 必须绑定实际 `Document` 或明确的权威预测投影，并逐条
  校验 `source_sha256`。
- 运行脚本只把最终 `Document V2.4` 传给评估器；审核文件中的 `machine_predictions` 不参与
  发布级评分。
- 审核时间必须含时区；同一次评估的数据集版本必须一致；重复页标签、未知 PageType、Document
  中不存在的页均 fail closed。
- 无权威上下文只保留“无来源指标单元测试”兼容模式，结果显式标为
  `fixture_only_not_publishable`，不能被宣称为真实准确率。
- 当前发布级实现仅对有 Document 直接证据的 PageType 标签计分；其他未实现的人工标签类型拒绝
  计算，不接受外部布尔结论冒充机器预测。
- 有有效标注时 precision、recall 和 F1 的零分母类别按 0 处理；全部分类错误时 macro-F1 为
  `0.0`，仅无标注时为 `not_evaluated/null`。

### 2.2 Run 不可覆盖与并发保护

- 新运行通过原子目录创建取得所有权；目录已存在时无 `--resume` 立即失败，任何产物写入前即
  停止。
- 每个 Run 使用 `O_CREAT|O_EXCL|O_NOFOLLOW` 单写者锁；并发写入 fail closed，锁不进入 Artifact
  Manifest，退出时按 inode 校验后移除。
- `--resume` 要求已有 Manifest，并校验 source/config/model、全部批次产物哈希以及原
  `run_id`；Replay 输入 Manifest 必须完全相同，不再被恢复流程覆盖。

### 2.3 Replay、Checkpoint 与路径安全

- 新增 no-follow 文件读取：先用 `lstat()` 检查所有已存在路径分量，再以 `O_NOFOLLOW` 打开并用
  `fstat()` 确认普通文件和大小上限。
- Checkpoint 相对路径拒绝绝对路径、`..`、越界、文件符号链接及父目录符号链接。
- Replay 输入必须位于可信根目录；CLI 可通过 `--replay-root` 指定，默认当前工作目录。源 PDF
  SHA 由当前实际 PDF 提供，不再把外部记录中的身份当作可信事实。

### 2.4 MinerU 第 24 页根因和兼容修复

环境：MinerU 4.0.12、docvortex 0.5.16、NumPy 2.4.6、ONNX Runtime 1.31.0。

原 PDF 直接推理探针再次稳定失败。探针捕获到 OCR detector 的退化四点：

```text
[(143,58), (143,58), (143,76), (143,76)]
```

MinerU 4.0.12 在执行其已有的最小宽度过滤之前先进行透视裁剪，生成全零矩阵和 `(0,18)` 输出
尺寸，docvortex 因而抛出 `Unsupported warp settings`。这不是 PDF 页尺寸或模型缺失问题。

私有兼容钩子只在 MinerU 版本严格等于 4.0.12 时启用，将引擎本来就会丢弃的零面积 OCR 框
提前过滤，并在 stderr 写入数量标记。补丁不修改安装目录；补丁版本及文件哈希进入 live
config/model signature。使用原始 441 页 PDF 物理页 24 重新直接推理成功，未使用 raster
fallback、保存产物回放或外部 API。

证据：

- 原 PDF 失败探针：
  `data/eval/task1_6_e2e/diagnostics/p24-original-warp-probe2-20261013/direct-original.log`
  （SHA-256 `5b4489ff517d4f6069b8bd4efd962dc9260736a917f89a01ee69887968e5641b`）。
- 原 PDF 修复后 live Run：
  `data/eval/task1_6_e2e/runs/repair-live-p24-original-compat-20261013/`。
- 成功日志明确记录：
  `ENGINEERING_RAG_MINERU_COMPAT version=4.0.12 filtered_zero_area_ocr_boxes=1`。
- 输出含真实 MinerU ZIP、MiddleJson、Document V2.4 JSON、Overlay、Manifest 与资源报告。

## 3. 真实运行结果

| 运行 | 结果 | 墙钟时间 | 峰值 RSS | 关键校验 |
|---|---:|---:|---:|---|
| 原 PDF p16 live smoke | 1/1 | 14.134 s | 1,265,299,456 B | page_type=body；SHA 正确；V2.4 往返 |
| 原 PDF p24 live + 4.0.12 compat | 1/1 | 28.015 s | 2,454,433,792 B | 12 Block；1 FormulaGroup；MiddleJson；V2.4 往返 |
| 21 页 saved-real replay | 21/21 | 5.146 s | 256,380,928 B | 来源 SHA 正确；公式/跨页表完整；无 Gold 不评分 |
| 21 页 resume | 21/21 reused | 2.561 s | 256,917,504 B | attempts `[1,1]`；rerun_batches `[]` |

21 页回放目录：
`data/eval/task1_6_e2e/runs/repair-replay-representative-20261013/`。其中 p24 的历史 raster
产物仍只作为 replay-only 输入，Manifest 明确标记；它与上述原 PDF live 成功证据严格分开。

结构回归结果：

- `Document.model_validate()` 和 JSON 往返通过，21 个物理页齐全。
- Formula ID 唯一；6.2.1-1、6.2.1-2 条件正确且未传播；7 条公式完整。
- 两个公式组符号项数量为 `[6, 2]`，条件/符号 Body 重复计数均为 0。
- 跨页表 3.5.2=28–29、4.2.2-2=37–38、9.1.2=126–127。
- 没有人工核验 Gold，`golden_dataset_status=not_evaluated`，没有输出虚假准确率。

## 4. 最终测试

```text
独立四反例（真实 PDF）： 4 passed in 3.29s
Document Parser 独立测试：154 passed in 3.46s
完整 pytest：             294 passed, 19 skipped in 3.86s
真实产物 integration：    18 passed in 0.39s
ruff check .：            All checks passed
ruff format --check .：   230 files already formatted
```

`19 skipped` 是默认未开启真实 MinerU 标志的 opt-in 测试；真实产物集成已另以
`ENGINEERING_RAG_RUN_REAL_MINERU=1` 全部执行。

## 5. 冻结契约与遗留门槛

- `src/engineering_rag/contracts/` 工作区 diff 为空；Document Schema V2.4 和 Protocol 未修改。
- 未执行 441 页全本推理，未进入 Chunking、Retrieval 或 LLM。
- MinerU 4.0.12 的兼容补丁为版本锁定的局部 workaround；升级 MinerU 时默认不启用，必须重新
  验证并决定移除或迁移。
- 在维护者完成 Golden Dataset 人工复核前，质量验收结论必须保持 **PARTIAL**；不得用候选标签、
  外部自填机器预测或回放产物生成“真实准确率”。

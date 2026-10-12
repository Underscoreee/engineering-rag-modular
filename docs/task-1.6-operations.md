# Task 1.6 本地运行与恢复说明

## 模式

- `live_mineru`：读取原 PDF、核验身份并真正调用本地 MinerU。
- `replay_saved_raw`：重放已保存的真实 MinerU normalized/MiddleJson；manifest 明确声明不执行推理。
- `synthetic`：只允许显式传入测试 fixture，不得写进真实报告。

三种模式不得混用。运行前使用项目 `.venv`，MinerU 4.x 位于
`.local/mineru-runtime/.venv/`，模型在 `.local/mineru-runtime/state/models/`。

## 代表页真实运行

```bash
.venv/bin/python scripts/run_document_parser_e2e.py \
  --mode live_mineru \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --run-id live-representative \
  --output data/eval/task1_6_e2e/runs/live-representative \
  --batch-size 2 \
  --continue-on-batch-error
```

默认代表集为任务矩阵的 21 页。默认批次上限 20；28–29、37–38、49–50、126–127
只要同时选中便保持同批。441 页全选会被拒绝；隐藏确认开关只是第二道技术保护，不能替代维护者明确授权。

## 回放与恢复

```bash
.venv/bin/python scripts/run_document_parser_e2e.py \
  --mode replay_saved_raw \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --run-id replay-representative \
  --output data/eval/task1_6_e2e/runs/replay-representative

# 同一运行目录恢复
.venv/bin/python scripts/run_document_parser_e2e.py <相同参数> --resume
```

resume 会核验 source SHA、配置哈希、模型/回放输入签名和每个成功批次 Document SHA。
任一不匹配即拒绝；failed 批次会重试，succeeded 批次不重跑。manifest 通过临时文件、fsync 和
原子 replace 提交。原始历史输入只读，新产物写入独立 run 目录。

## 目录与故障处理

- `run_manifest.json`：来源、配置、模型签名、批次状态、尝试次数、耗时和错误。
- `batches/*/engine/`：原始 ZIP、MiddleJson、Markdown、结构结果和 stdout/stderr。
- `final/`：冻结 V2.4 partial Document、sidecar、lineage、pending、overlay。
- `qa/`：候选/verified JSONL、metrics、semantic integrity、error catalog、resource profile。

MinerU 非零退出/超时、坏 JSON/ZIP、哈希不符和冲突 ID 都是显式失败。使用
`--continue-on-batch-error` 时仅提交成功批次的 partial Document，整个 run 仍为 failed，调用方不能当作完整成功。

# Task 1.6 语义归属边界专项修复报告

日期：2026-10-14  
结论：**PASS**

## 范围与来源

- 冻结契约：Document Schema V2.4，未修改 `contracts/`、Protocol 或 Renderer。
- 源 PDF SHA-256：`43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。
- 输入：`gb50010-full-v2` 的 10 个只读 normalized MinerU 批次（物理页 1–50）。
- 执行模式：`replay_saved_raw`；未重新推理 441 页，未调用外部解析服务。
- 原始问题 Document SHA-256：
  `5fecad101470407f197e0793e1725d7041935c799279a0f9820b395caf347d9b`。
- 修复后 Document SHA-256：
  `c52e44f8022e0557f5454c33494a515549dd612890770754a3875942678d8be3`。

## 根因与修复

1. 第 25 页公式注释丢失：跨页公式收集器把印刷注释标为已消费，但 V2.4
   `FormulaGroup` 无 notes 字段，Renderer 因而无法输出。现在保留原来源 Body 一次，并在私有
   `FormulaPrintedNoteEvidence` 中关联 `formula_group_id`、`formula_id`、bbox 与 Block ID。
2. 第 45 页 Clause `5.2.5` 被表注吞并：相邻表注解析先按首个整数匹配，错误把 `5.2.5`
   拆成注号 5 和正文 `.2.5...`。现在三级条文边界优先于连续表注匹配。
3. 第 41 页公式引导正文被符号说明吞并：符号续行过去会无条件追加不能解析的文本。
   现在仅在“引导句词法标记 + 紧邻下一 equation”双重证据成立时停止符号收集，原 Block
   保留为 Body，并通过私有关系指向下一公式。

详细契约限制和投射决策见 `docs/adr-task1-6-formula-note-public-projection.md`。

## 真实回放结果

- 输出 50 页、117 个正文 Clause、21 个 LogicalTable；V2.4 校验及 JSON round-trip 通过。
- Clause `3.3.2`：`page_start=24`、`page_end=25`；公式注释在 plain_text 中恰好 1 次，
  并关联公式 `3.3.2-1` 的稳定 `formula_id`。
- 表 `5.2.4`：notes 为 `[1, 2, 3, 4]`；Clause `5.2.5` 独立恢复，来源 Block 未重复消费。
- Clause `4.2.6`：两条公式及各自符号解释完整；第二条公式引导正文在 plain_text 中恰好
  1 次，不再出现在 `4.2.6-1` 的 symbol description。
- 受影响页 25、41、45 的 unresolved pending 数为 0。
- 两次独立 1–50 页回放生成完全相同的 Document 与 Parser sidecar SHA-256。
- 单次保存产物回放：12.87 秒，约 0.257 秒/页；进程树边界峰值 RSS 398,217,216 bytes。

## 测试

- 修复前基线：`303 passed, 20 skipped in 16.03s`。
- 新增真实保存产物反例：`4 passed in 1.10s`。
- Document Parser 独立测试：`161 passed in 3.05s`。
- 完整 pytest：`309 passed, 20 skipped in 4.91s`（最终代码复核为 4.53s）。
- 真实产物集成：`23 passed in 1.95s`（最终代码复核为 0.47s）。
- 最终定向集合：`11 passed in 1.11s`。
- `ruff check .`：All checks passed。
- `ruff format --check .`：242 files already formatted。

测试日志位于
`data/eval/task1_6_e2e/runs/gb50010-semantic-boundary-repair-v1/logs/`。

## 交付物

交付根目录：
`data/eval/task1_6_e2e/runs/gb50010-semantic-boundary-repair-v1/`

- `review/document.v2.4.semantic-boundary-repaired.json`
- `final/parser_private_sidecars.json`
- `review/semantic_consumption_diff.json`
- `review/formula_note_lineage.json`
- `review/table_note_clause_split.json`
- `review/formula_leadin_split.json`
- `review/unresolved_pending.json`
- `review/overlays-before/` 与 `review/overlays-after/`（第 24、25、41、45 页）
- `review/overlay_manifest.json`
- `replay_inputs_manifest.json`、`run_manifest.json` 与 `qa/resource_profile.json`

`gb50010-semantic-boundary-repair-v1-idempotence/` 保存第二次独立回放结果，用于确定性核验。

## 遗留项

本专项没有阻塞问题。质量结论只覆盖保存的真实 MinerU 物理页 1–50 回放；441 页全本仍保持
`NOT_RUN_REQUIRES_EXPLICIT_APPROVAL`，本次未授权、未执行。


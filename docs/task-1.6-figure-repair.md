# Task 1.6 Figure Recognition & Semantic Aggregation Repair

日期：2026-10-16  
结论：PASS（真实保存产物回放；未重新执行 MinerU 推理）

## 原始产物调查

检查对象为 `GB50010-2010-v3-partial` 的 batch-002 ZIP 及解包目录。MinerU 4 实际交付文件名为 `middle_json.json`、`model_output.json`、`structured_content.json`、`markdown.md` 和 `images/`；该 bundle 不含字面命名为 `model.json`、`content_list.json` 或 `content_list_v2.json` 的文件。

- 物理页 55：MiddleJson 已给出一个 image body、`page_54_image_0.jpg` 和内嵌 image caption。
- 物理页 56：MiddleJson 已给出两个 image body、两个无 `tag` 的条件表达式，以及独立图题；model/layout 结果也保留了图题类别证据。
- 物理页 58：MiddleJson 已给出一个 image body、`page_57_image_5.jpg` 和内嵌 image caption；后续 6.2.16 是独立正文边界。
- 原 PDF 三页均有页面栅格图像；本修复不以 `page.get_images()` 作为唯一检测依据。由于 MinerU 已提供布局和资产证据，没有启用自研视觉 detector 或重新推理。

首次丢失位置是项目 Normalizer/Adapter：旧 Normalizer 未保留 image path/caption 的结构化字段，旧 V2.4 Adapter 又将 image/figure 以 `no_immutable_asset_reference` 明确省略。

## 算法与 Frozen Schema 投射

Parser 先执行 caption-anchored Figure 聚合，再将已消费来源键交给 Formula assembler 排除。独立图题只向上收集连续的 image/figure 片段；无正式 `\\tag` 的 equation 还必须位于图题上方，且横向中心落入相邻图像 bbox，才可作为图内文字消费。正式编号公式或任意普通正文会终止该连续视觉区。

一个逻辑 Figure 投射为一个合法 V2.4 Image Block。完整图题放在 `PageBlock.ocr.text`；图形 bbox 排除 caption；单图片引用内容 SHA-256 URN，多图片 Figure 引用确定性逻辑 manifest。V2.4 只有单一 asset 槽位，因此所有物理图片、图内标签、精确 bbox、原始 Block ID、哈希和消费去向保存在 `figure_sidecars`。公共 Schema 和 Protocol 无改动，Schema Gap 记录于 ADR-DP-001。

## 修复前后 JSON 差异摘要

| 物理页 | 修复前 | 修复后 |
|---|---|---|
| 55 | image=0, formula=3, body=2 | image=1（6.2.10）, formula=3, body=2 |
| 56 | image=0, formula=5, body=6 | image=1（6.2.11）, formula=3, body=5 |
| 58 | image=0, formula=2, table=1, body=2 | image=1（6.2.15）, formula=2, table=1, body=2 |

第 56 页删除的两个 Formula 候选是无编号的 `x ≤ h′f` 与 `x ≥ h′f`；它们连同两个图片片段统一进入图 6.2.11 的 bbox。独立图题 Body 被消费。6.2.11-1～6.2.11-3 等正式编号公式保持不变。第 58 页 Figure bbox 截止于图形区域，未包含 6.2.16 正文或公式。

最终 Figure bbox（PDF points）为：

- 6.2.10：`[66.7955, 47.2989, 331.6475, 156.4951]`
- 6.2.11：`[51.6500, 139.5609, 344.0746, 246.4214]`
- 6.2.15：`[92.4263, 285.5452, 300.1915, 375.4715]`

## 来源、Clause 与完整性

- Figure sidecar：3 条；来源消费记录：7 条；重复来源键：0。
- 三个图题在 Page Block 中各出现一次，在所属 Clause 的派生 plain text 中也各出现一次。
- Image ContentUnit 分别挂接 Clause 6.2.10、6.2.11、6.2.15。
- dangling `source_block_ids`：0；`validate_document_references()` 错误：0。
- `Document.model_validate()`、JSON 往返、同输入重复适配均通过。

## 实际运行结果

- RED 基线：`tests/document_parser/test_figure_detection.py`，7 failed。
- Figure 专项：9 passed。
- Document Parser 独立回归：161 passed。
- 完整 pytest：318 passed, 20 skipped。
- 显式真实产物集成：23 passed。
- `ruff check .`：passed。
- `ruff format --check .`：247 files already formatted。

最终回放目录：`data/eval/task1_6_e2e/runs/GB50010-2010-v3-figure-repair-candidate/`。原始 v3 MinerU bundle 只读，回放范围为物理页 49～58；未运行 441 页推理。

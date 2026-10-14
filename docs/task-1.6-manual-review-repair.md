# Task 1.6 人工核查反馈专项修复报告

- 日期：2026-10-13
- 结论：PASS
- Schema：Document V2.4 FROZEN（未修改）
- 最终运行：`data/eval/task1_6_e2e/runs/gb50010-manual-review-repair-v3/`
- 输入来源：原始全书运行保存的 89 份真实 MinerU normalized 产物
- 执行模式：`replay_saved_raw`，未执行 MinerU 推理，未修改原始 OCR/MiddleJson

## 修复内容

1. MinerU 标为标题的三段式编号（如 `2.1.1`）在 V2.4 适配时按 Clause Body 处理；章、节
   标题仍保持 Title，条文内数字分项仍保持 Body 并由语义装配器派生 ListItem。
2. 单符号说明允许说明正文包含多个分号，避免 `S` 因内部标点被误判为未完全消费。
3. 对页尾未完成的符号说明，只有相邻下一页开头、来源连续且未遇到新条文边界时才合并；
   新符号必须有 inline 公式 token 或明确的符号分隔符。印刷公式注释保存在私有 sidecar。
4. OCR 符号中的撇号仅在去掉后能由同组 Equation LaTeX 完全佐证时纠正；原始 token 和依据
   保留在 sidecar。
5. 表格后紧邻的连续编号表注按期望序号消费，遇到新条文或编号断裂立即停止；跨页续表的
   notes 聚合到同一 LogicalTable，后续新表不继承前表注释。
6. 印刷页码通过纯数字、页脚几何与 MinerU region 标签过滤；对引擎误标为 text 的页码，
   还必须有同批相邻页推导的稳定印刷/物理页偏移。`Page.page_number` 未改变。

## 真实回放结果

- 441/441 页回放重组成功，89/89 批次 `succeeded`。
- wall time：138.285 秒；0.314 秒/页；进程树峰值 RSS：560,463,872 bytes。
- 页 17～20 的三段式条文均为 Body；Chapter/Section 仍为 Title。
- 公式 `3.3.2-1`、`3.3.2-2` 保持原稳定 ID 和完整 LaTeX；`S`、跨页
  `f_c、f_s`、`a_k` 均进入同一 FormulaGroup，来源 Body 已消费。
- “注：公式（3.3.2-1）……”进入公式私有来源记录；遇到 `3.3.3` 后停止消费。
- 表 3.4.3、3.4.5、3.5.2 的 notes 数分别为 4、7、5；表 3.5.3 保持自身 6 条 notes。
- 过滤 435 个印刷页码来源；全书残留的页脚纯数字 Block 为 0。
- repaired Document 经 `Document.model_validate()`、JSON round-trip 和完整跨引用验证通过。

## 契约限制

V2.4 的 FormulaGroup 没有印刷注释字段，PageBlock bbox 也只能属于一页。因此公式印刷注释
和跨页组件 bbox 存入 Parser 私有 sidecar，未塞入 `Equation.text` 或
`symbol_explanations`。`derive_clause_plain_text()` 能表达完整公式与跨页符号说明，但不会输出
该印刷注释。详细决策见 `docs/adr-task1-6-cross-page-formula-notes.md`。

## 验证

- 修复前专项 RED：4 failed（条文类型、页码过滤、跨页公式、连续表注各 1 项）。
- 专项合成反例：5 passed。
- Document Parser 独立测试：159 passed。
- 保存真实产物专项集成：1 passed。
- 完整 pytest：303 passed, 20 skipped。
- `ruff check .`：passed。
- `ruff format --check .`：237 files already formatted。

JUnit 日志位于最终运行的 `logs/`；结构化差异、公式 lineage、表注消费、页码过滤及 Overlay
清单位于最终运行的 `final/`。

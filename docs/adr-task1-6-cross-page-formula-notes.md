# ADR：跨页公式印刷注释保留在 Parser 私有 Sidecar

- 状态：Accepted
- 日期：2026-10-13
- 适用范围：Document Parser Task 1.6 人工核查反馈修复

## 背景

Document Schema V2.4 已冻结。`FormulaGroup` 可表达独立 `Equation` 和共享
`symbol_explanations`，但没有公式组印刷注释字段；`PageBlock.bbox` 只表示其所在物理页的
坐标框。`derive_clause_plain_text()` 只渲染冻结契约中的公式和符号解释。

真实扫描件中的公式组可能跨页：前页开始符号解释，下一页继续解释、增加新符号，并包含
“注：公式……”印刷注释。把注释塞入 `Equation.text` 或符号说明会歪曲公共字段语义；给
V2.4 增加字段或改动冻结 Renderer 则违反冻结政策。

## 决策

1. 跨页续写和新符号在来源证据连续、下一页开头且尚未遇到新条文边界时，合并进同一个
   公共 `FormulaGroup.symbol_explanations`。
2. 已被完整消费的来源文本不再输出为独立 Body Block。
3. 公式印刷注释保存在 Parser 私有 `FormulaPrintedNoteEvidence` 中；记录物理页、原始
   Block ID、source index、原文、bbox、目标 FormulaGroup 和引用的印刷公式编号。
4. 公共 Formula PageBlock 的 bbox 仍只覆盖锚点页；跨页组件的独立 bbox 仅保存在私有
   sidecar，禁止把不同页面的坐标错误合成一个 PageBlock bbox。
5. 缺少下一页、来源不连续或遇到新条文时停止合并；未完成状态保留在去重覆盖报告中，
   不猜测缺失文字。

## 结果与限制

V2.4 Document 和 `derive_clause_plain_text()` 能完整表达公式本体及跨页符号解释，但不能在
不滥用字段的前提下渲染“注：公式……”印刷注释。该注释的权威来源是
`parser_private_sidecars.json` / `cross_page_formula_lineage.json`。若未来要求公共 Renderer
输出此类注释，必须升级 Schema 版本并提供显式迁移，不能修改 V2.4。

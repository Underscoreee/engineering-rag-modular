# ADR — FormulaGroup 印刷注释的 V2.4 合法投射

- 状态：Accepted
- 日期：2026-10-14
- 范围：Document Parser 私有语义关系；Document Schema V2.4 保持 Frozen

## 背景

冻结的 `FormulaGroup` 只有 `equations` 与 `symbol_explanations`，没有公式印刷注释字段；
`derive_clause_plain_text()` 只渲染 Clause 引用的 Body、Table、Formula 和 Image 权威内容。
若跨页公式后的“注：公式……”仅被 Parser sidecar 消费，注释将无法进入 Clause 的可检索正文。

## 决策

对具备原始文本、bbox、Block ID、相邻公式组及印刷公式编号证据的公式注释：

1. 在 Parser 私有 `FormulaPrintedNoteEvidence` 中记录目标 `formula_group_id`、
   `formula_id`、来源页、bbox、source index 和投射 Block ID。
2. 在公共 V2.4 Document 中将同一来源 Block 保留为一个 Body，由所属 Clause 引用。
3. sidecar 将投射状态标记为 `retained_as_body`，不再把该来源记录成被 FormulaGroup
   消费的重复 Body。
4. Clause 边界终止跨页关联；证据不足时保留 Body/pending，不推断缺失文本。

该方案使注释只存在一份权威公共语义内容，同时保留其公式关系与精细来源证据。

## 兼容性

未修改 `contracts/`、Document Schema V2.4、Protocol 或 Renderer。新增字段只存在于 Parser
私有 sidecar。未来公共 Schema 若增加公式注释类型，应通过新 Schema 版本和显式迁移替代该投射。


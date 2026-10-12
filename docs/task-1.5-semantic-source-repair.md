# Task 1.5 语义来源修复报告

## 结论

2026-10-12 完成独立评审要求的四项最小范围修复，结论 **PASS**。Document Schema V2.4 和 Protocol 没有修改；未实现 Task 1.6、Chunking、检索或 LLM 算法。

Task 1.5 的真实候选数据仍标注 **PARTIAL**：物理页 301 本身不含 4.1 Section 起点，不能在无上下文时编造 Clause 归属。

## 四项修复

1. 页面分区不再把任意编号开头文字当作正文证据。新建正文区段要求 Title Block、页顶位置、标题号与条文号层级匹配，同时排除明确的修订说明语境。真实页 301 单页无 cover/context 时为 `unknown`；页 16 的章题和 1.0.x 条文互相印证，仍为 `body`。
2. `unknown` 页面的实质内容不再静默跳过。同页连续候选合并为一个 `unclassified_content` pending，记录 block IDs、物理页、每个 bbox、原始文本 lineage 和三项阻断条件。纯数字页脚按明示政策排除。
3. 多批次合并必须一致校验 `document_id`、`file_id`、SHA-256、`page_count`、`standard_code`、`edition` 和 bbox 坐标系。缺失 SHA 时 fail closed。合并后显式检查物理页、Block、Table 唯一性及所有跨页 table fragment 的 page/table/index 一致性。
4. Block 切分保留文本完整覆盖、输入顺序和无重叠约束，并新增 `0.01` PDF point 母框包含容差与几何阅读顺序校验。不可信几何抛出 `UnsafeBlockSplitError`，原 Document 不变，异常可导出 `original_block_retained` pending 诊断。

## 真实回放与数据保护

原 `runs/final/GB-COMBINED` 保持不变。修复从六组已有真实 MinerU 4.0.12 normalized 产物重放，写入：

`data/eval/task1_5_semantics/runs/repair-20261012/GB-COMBINED/`

源 PDF SHA-256 为 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。修复文档 SHA-256 为 `1338b5480651b74b4cac62a4ed50bc83b7e3d190fa2057faa863bf50f7e7200f`。回放仍为 8 页、7 Section、14 normative Clauses、3 explanation Clauses、13 pending。GB-C01/C02/C04/C07/C08 PASS，GB-C10 因缺前置 4.1 Section 为预期 PARTIAL。

`repair_diff.json` 记录了新旧页分区依据和统计对照；`repair_replay_manifest.json` 记录 PDF、六个输入、只读 baseline 与每个新产物的 SHA-256。

## 测试证据

- 修复前：完整 pytest `4 failed, 262 passed, 15 skipped`；四反例独立运行 `4 failed`。
- 四反例：`4 passed`。
- Parser 独立测试：`137 passed`。
- contracts：`114 passed`。
- 其余六个业务模块：各 `1 passed`。
- 默认完整 pytest：`274 passed, 15 skipped`。
- 真实 Task 1.5 集成回归：`5 passed`。
- Ruff lint：`All checks passed!`。
- Ruff format：`202 files already formatted`。

修复前及修复后命令记录位于 `reports/task1_5_repair/`。

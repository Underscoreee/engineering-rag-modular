# Task 7.3 待人工复核示例（不是 Golden Dataset）

沿用 Task 6.5 的 manifest、queries、qrels、review_log 格式。8 条 query 均为自动候选，
annotation_status=draft；qrels 和 review_log 故意为空。不得将本目录用于正式质量指标。
expected_outcome=retrieve 仅表示候选流程选择检索路径，不承诺存在相关证据。

请对照真实 PDF 及固定 ChunkBatch 快照，由人工分别检查：正文条文、标准范围、条号、
公式及条件/符号、表格及表注、条文说明、权威强制性证据和证据不足。
逐条记录相关 Chunk ID、分级相关性、实际物理页、数值/单位/条件、参考答案要点及核验依据。
按 docs/task-6.5-query-evaluation.md 的复核日志/哈希规范记录审核，再升级 annotation_status。
禁止仅凭应/必须推断强制性；当前快照该标记全部为 null，需另补可信权威证据。

人工答案要点可先记入对应 query 的 notes，正式答案语义评分机制尚未定义；不要新增同名公共模型。
要执行有依据的 B 类真实规范 Smoke，需要另提供人工核验的 GenerationRequest/原始 RetrievalResult、
正文/条文说明/数值条件证据及核验记录。目前只能运行结构/来源一致性探测，不能评价规范语义正确性。

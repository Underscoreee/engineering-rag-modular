# Task 1.6 真实质量分析

## 评估口径

`TASK_1_6_TEST_MATRIX.json` 的 18 组、21 个物理页全部是机器候选，不是金标。
`qa/gold_candidates.jsonl` 为人审入口；只有同时提供 `reviewer`、`reviewed_at`、
`dataset_version`、`provenance` 和 verified labels 的记录才进入准确率分母。当前
`gold_verified.jsonl` 为空，所以 OCR CER、reading order、bbox IoU、表格、公式、条件、
符号解释、Clause 和来源准确率均为 `not_evaluated`，分子/分母为 0、value 为 null。

## 可客观核验的覆盖与完整性

真实代表集原 PDF 推理覆盖 20/21 页；缺失页 24 的原因是 MinerU 非零退出，不是 Parser
静默丢页。保存的真实 MinerU 产物回放覆盖 21/21 页，全部页面保持
`partially_transcribed` 和机器未核验语义。

回放的机器候选页面类型包含 outer/inner cover、publication notice、中英文目录、正文、
用词说明、引用标准、说明封面、修订说明、说明目录和说明正文。不确定的第 37、38、50 页
在缺少相邻章节证据时保持 unknown/pending；这不是错误率结论。

严格完整性检查结果：

- V2.4 Pydantic 校验与 JSON 往返：通过。
- 稳定 formula ID 全局唯一：通过。
- 6.2.1 七条公式、两项条件定向关联、6+2 个共享符号解释：通过。
- 条件/符号说明完整消费后 Body 重复数：0。
- 跨页表 3.5.2、4.2.2-2、9.1.2 的物理页范围：通过。
- pending 来源、bbox 和阻止关联原因：保留在私有 sidecar。

这些是契约/一致性指标，不能替代人工准确率。

## 错误目录

1. 物理页 24：原 PDF 实时解析在表格 warp 阶段失败，错误为 `Unsupported warp settings`。
2. 稀疏选页导致缺父章节/前置 Clause 的内容：保留 orphan/section pending，不强绑。
3. 物理页 301 若没有说明封面锚点：保持 unknown；代表集含已核验的 277 页锚点时才进入说明分区。
4. 页底 `σp0i` 解释跨页不完整：保持 partial，不补造缺失文字。

错误明细和 overlays 位于各 run 的 `qa/error_catalog.json` 与 `final/overlays/`。

## 下一步人工流程

维护者在 PDF 与 overlay 上逐条复核候选，复制到独立的 verified JSONL 并填写四项审计元数据；
再次运行时通过 `--verified-gold` 输入。不得直接把当前候选状态改名为 verified。页 24 应先解决
MinerU warp 兼容问题或批准有明确 provenance 的替代预处理策略，再纳入实时成功率。

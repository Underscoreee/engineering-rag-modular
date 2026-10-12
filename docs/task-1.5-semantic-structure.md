# Task 1.5 工程规范语义结构化

## 范围与结论

本阶段在 Document Parser 私有层实现页面分区、正文/说明两套 Section 树、Clause 边界、跨页延续、引用式 ContentUnit、说明关联和派生 plain text。Document Schema V2.4 与公共 Protocol 未修改。

结果为机器候选，不是人工 Golden Dataset；总体结论为 **PARTIAL**。物理页 301 从说明章节中段开始，缺少其前置 4.1 Section 题头，相关内容保留在 pending sidecar，没有补造 Section 或 Clause。

## 保守识别规则

- 页面分类先于 Clause。`body` / `explanation_body` 需要可见章、节、条文证据或已建立文档区段的连续性；277 页由标准身份和“条文说明”标记识别为 `explanation_cover`。
- 只把 Title Block 中有合法层级的章、节写入 Section；正文与说明命名空间隔离。缺父章节的节候选进入 pending。
- 只把 Body Block 段首三段式编号识别为 Clause。分项、表号、公式号、引用、页脚不创建 Clause。跨页需要连续物理页和同一内容组。
- table ContentUnit 引用 LogicalTable 的全部 fragment block；formula ContentUnit 引用一个 FormulaGroup Block 及其中真实 formula IDs。条件和“式中”解释不再生成重复 Body Unit。
- 同号说明 Clause 只在当前 Document 中存在唯一正文 Clause 时关联；否则保持 null 并记录 pending。无权威强条证据时 `is_mandatory=null`、`mandatory_evidence=[]`。
- plain text 只调用冻结 renderer。选页尾部、公式说明跨页未完或来源不完整时不写缓存。

## 真实来源与结果

源 PDF SHA-256 为 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`，共 441 个物理页。运行环境为 MinerU 4.0.12、`docvortex.middle/2.0`、basic tier、本地 CPU/ONNX；未使用外部 API。

物理页 49–50 原先缺少 49 页产物，本阶段实际补跑连续页，推理耗时 51.2001 秒，峰值子进程 RSS 2,972,692 KiB。组合回放覆盖 16、49–50、126–127、277、282、301：

- 16：识别正文章 1 和 1.0.1～1.0.4；末条位于选页边界，不缓存 plain text。
- 49–50：识别章 6、节 6.1/6.2；6.2.1 跨页，分项 1～5 保持 list item；两个公式 Unit 引用 5 式和 2 式。冻结 renderer 输出包含两个条件、7 个公式编号，两个抽检符号解释均只出现一次。Task 1.4 标注的底部跨页未完成解释使该 Clause 不缓存 plain text。
- 126–127：9.1.2 的 table Unit 引用表 9.1.2 两个 fragment；9.1.3 为独立下一条，不被表吞入。
- 277：说明封面，不创建 Clause。
- 282：说明章 1 与 1.0.1～1.0.3；组合文档中与已加载正文唯一同号条文关联。
- 301：分类为说明正文；因 4.1 父 Section 未加载，4.1.4～4.1.6 及无编号公式保留 pending，不制造章节或条文。

组合产物统计：8 页、7 个 Section、14 个正文 Clause、3 个说明 Clause、13 个 pending 关系。实际 JSON、manifest、lineage、pending、摘要、结果和八张 overlay 位于 `data/eval/task1_5_semantics/runs/final/GB-COMBINED/`。该目录由数据策略忽略，不覆盖历史 Task 1.2～1.4 产物。

## 回放与测试

```bash
python scripts/assemble_mineru_clauses.py \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --output data/eval/task1_5_semantics/runs/final/GB-COMBINED
ENGINEERING_RAG_RUN_REAL_MINERU=1 \
  python -m pytest tests/integration/test_task1_5_real_semantics.py -q
```

合成测试读取 `TASK_1_5_TEST_CASES.json` 并锁定 S01～S36 配置集合，功能断言覆盖章节树、unknown/toc、条文/分项/公式号/表号区分、跨页、几何安全拆分、续表完整引用、公式组、说明关联、三态强条、缓存、稳定 ID、来源页组和安全退化。最终命令与精确数量记录于根目录 `TASK_1_5_IMPLEMENTATION_REPORT.md`。

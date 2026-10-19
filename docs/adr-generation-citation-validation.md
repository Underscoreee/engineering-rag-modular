# ADR-GEN-002：请求级引用映射与保守答案校验

日期：2026-10-19。状态：Adopted（Task 7.2）。

## 前置与公共边界

Task 7.1 的已提交实现与注册表/服务/契约测试通过。沿用同一 GenerationContext，
不另建证据注册表，不改变 GenerationService/API、Citation、AnswerResult、其他公共模型
或检索算法。Task 7.1 的人工真实规范证据验证仍未完成，不把该限制当作已验证事实。

## 决策

1. 独立 CitationMapper 从正式校验后的私有 GenerationOutput 接收 evidence_ids 和可选
   quotes。新增私有 EvidenceQuote 只含 evidence_id/quoted_text，拒绝模型自由生成来源字段。
   Prompt 升至 engineering-generation-1.1；这是内部输出/Prompt 变化，不升级公共 Schema。
2. 复用 ContextBuilder 的唯一来源投射函数，对当前注册表与实际 Prompt 行做类型与字段
   一致性检查。保留正文/说明、强制性、类型、标准、条文及版本的未知值，不猜测。
   映射结果绑定原 Context 实例；其他请求即使也有 E1，不能复用该映射。
   模型响应仍通过原 request_id 绑定，E1 不是全局引用身份。
3. Citation 仅填写既有真实 chunk/document/clause/完整页范围及可验证 quoted_text。
   不在没有定位证据时缩窄物理页范围。公共 Citation 不含标准/条文号/来源三态字段，
   它们仍在本次输入/私有 Context，通过 chunk 身份关联；不擅自新增公共字段。
4. 引文匹配优先严格子串，仅折叠 ASCII 空格/tab/CR/LF 为一个空格。保护数字、正负号、
   LaTeX 命令/转义边界，不改值、不去掉比较符号、不做数学/语义等价。
   使用 content 实际保存格式，不 JSON 解码、Unicode 替换或自动修复引文。原提议原样保留。
   每个 evidence ID 最多一个不同 quote，同 quote 去重，不同 quote 明确冲突，避免拼接原文。
5. AnswerValidator 对公共结果做严格 Schema 校验，再核验同请求映射、完整来源、重复冲突、
   quote 与状态。不静默删除无效引用、不重新检索、不用另一个 Chunk 替换。
   来源/引文的确定性错误沿用 GenerationError，不触发无意义模型重试；既有连接/超时/
   结构化 ValueError 的有界重试策略不改。
6. 旧的“有 ID 即可保留 grounded”不足以证明整体支持。仅当整份答案等于单一已引用 content
   的完整文本（允许规定的空白差异），且无模型限制/跳过证据时保留 grounded；原文子串可能
   丢失前置否定/适用条件，不能据此证明充分支持。其余降为 partially_grounded，
   说明逐项主张未验证。所有有依据的结果仍提示来源/字面校验不等于工程事实/法律效力证明。
   insufficient_evidence 仅使用既有固定安全文本与空引用。

## 非目标与兼容性

公开 DTO/版本不变，模型旧输出省略 quotes 时仍合法，quoted_text=null。答案改写/总结现在
更保守，通常由 grounded 降为 partially_grounded；原有对应测试按此明确政策收紧，而非
删除/跳过反例。没有段落/claim 级公共字段；不宣称对自由回答中每个条文号、数值、适用条件、
规范优先级或相关性进行完整验证。需要这些能力时应另立任务，不由模型的状态声明代替。

真实 API Smoke 使用既有明确虚构示例、仅发送示例内容，不把它提升为人工核验真实规范。
无效 ID/引文以确定性离线反例验证，不把一次真实模型返回有效结果当作拒绝错误的证明。

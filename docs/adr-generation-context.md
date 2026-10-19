# ADR-GEN-001：Generation Task 7.1 的上下文与最小引用边界

日期：2026-10-19。状态：Adopted（本次任务范围）。

1. Generation 仅依赖 contracts 与本模块代码，通过 StructuredLLMClient 注入模型。
   请求/答案及其他公共契约不变，服务工厂以模块 GenerationSettings 接收模型配置与预算。
2. Chunking 的 token 计数器是私有实现，不违反模块边界复用。初版采用序列化应用输入与输出
   Schema 的字符预算，明确不是 token 计数；输出 token 上限沿用既有 StructuredLLMConfig。
   不截断公式/表格/条文整块，也不另写冒充准确 tokenizer 的估算器。
3. 注册表逐请求创建；相同 chunk_id 的来源/内容不一致即拒绝，避免伪造聚合来源。
   null 不推断，历史对话、Expansion、HyDE 不自动进入证据。
4. 私有模型输出 answer/evidence_ids/grounding_status/limitations；正式 validate_output
   校验后由注册表映射现有 Citation。quoted_text 暂为 null，不伪称完成引文/逐句支持验证。
   段落覆盖与完整答案校验留待 Task 7.2。
5. grounded 需有效 ID，无限制/跳过证据；有已知限制则保守降为 partially_grounded。
   insufficient_evidence 不发布无依据模型结论，返回固定不足文本。这不是完整语义蕴含证明。
6. 复用现有适配器和重试类别（最大 2 次）。固定传输指令中的“禁止 answer generation”
   改为“禁止 JSON 外部文本”，仅解除对新结构化生成阶段的措辞冲突；不改变协议、HTTP、
   Schema、Query、模型或排序。离线测试验证实际 HTTP 序列化的指令/证据隔离。
7. 维护者确认暂无人工核验真实 RetrievalResult，授权生成示例继续。因此真实 API Smoke
   使用明确虚构的脱敏示例，标注 human_verified_real_evidence=false；真实规范证据
   的人工质量验收仍待补齐，不把示例升级为金标。

完整接口见 [Generation INTERFACE](../src/engineering_rag/modules/generation/INTERFACE.md)。

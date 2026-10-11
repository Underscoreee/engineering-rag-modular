# Observability

`engineering_rag.infrastructure.observability.api.Observability` 提供结构化 `log`、`record_metric`、`measure`。每次调用带 `TraceContext`，实现默认不得记录整篇文档、问题全文或敏感上下文。Task 0 不绑定日志/指标厂商。


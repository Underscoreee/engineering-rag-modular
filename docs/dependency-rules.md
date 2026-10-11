# 依赖规则

允许的 import：业务模块 → `engineering_rag.contracts`；模块 → 自身 internal；基础适配器 → contracts；组合层 → contracts 与各模块公开 `api`。Hybrid、Query、Orchestrator 通过 Protocol 注入依赖。

禁止：contracts 导入 modules/infrastructure；业务模块导入另一个业务模块（尤其 `internal`）；Generation 导入检索；导入时连接网络、数据库或下载模型；循环依赖和隐式全局单例。

```python
# 未来组合根示意，不是实现
hybrid = HybridImplementation(keyword=keyword_protocol, vector=vector_protocol)
query = QueryImplementation(retriever=hybrid)
```

`tests/architecture/test_boundaries.py` 用 AST 扫描生产源文件，执行上述核心黑名单，并验证公开入口可在无外部服务环境导入。


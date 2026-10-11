# 开发指南

未来独立开发模块时：先读 `AGENTS.md` 和本模块 `INTERFACE.md`；在 contracts 不变时仅修改自身 internal；用依赖注入隔离外部适配器；在本模块 tests 使用 Fake/Stub；先跑独立测试，再跑全部契约与架构测试。

模块测试验证一个公开边界；contracts 测试验证 Schema、序列化和引用；integration 测试留给后续真实组件组合。Task 0 的 integration 目录为空，不代表外部集成已完成。

Schema 变更流程：说明用例 → 判断兼容性 → 同步模型、Protocol、示例、接口文档和测试 → 必要时增加 schema 主版本/迁移 ADR → 全量检查。Review 应确认身份作用域、空值语义、来源链、失败/幂等/排序、依赖方向、日志敏感性和无导入副作用。


# Query 接口

## 职责与非职责

`plan()` 只形成结构化检索计划；`execute()` 才可通过注入的 Hybrid Protocol 检索。Query 不访问数据库、不融合底层结果、不生成答案；Task 0 不实现改写、HyDE 或意图算法。

## 公开接口

导入路径：`engineering_rag.modules.query.api`。

```python
class QueryService(Protocol):
    def plan(self, request: QueryRequest) -> RetrievalPlan: ...
    def execute(self, request: QueryRequest) -> QueryResult: ...
```

输入含问题、历史、过滤和检索选项。计划保留原问题与显式检索模式；结果把实际计划和证据绑定。证据顺序沿用检索 rank。

## 失败与执行语义

`plan()` 无检索副作用；`execute()` 只读检索。非法计划应校验失败，空证据返回空列表；后端不存在/失败不得伪装为空命中。相同配置不承诺自然语言改写逐字相同，但必须记录实现版本以复现。

## 依赖、版本与示例

未来 execute 实现仅注入 `HybridRetrievalService` Protocol。API 版本 1，Schema `1.x`。

```python
# 接口示例，query_service 为未来注入实现。
plan = query_service.plan(request)  # 不检索
result = query_service.execute(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/query/tests -q`。


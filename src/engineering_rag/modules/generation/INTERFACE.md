# Generation 接口

## 职责与非职责

只基于请求中已给出的证据形成答案与引用。不检索、不查询数据库、不修改证据；Task 0 不实现 Prompt 或 LLM 调用。

## 公开接口

导入路径：`engineering_rag.modules.generation.api`。

```python
class GenerationService(Protocol):
    def generate(self, request: GenerationRequest) -> AnswerResult: ...
```

请求含问题、`RetrievalResult` 证据、可选历史/配置/trace。Citation 必须指向输入中真实 chunk/document/clause/page 身份；证据不足通过 grounding status 表达。

Task 7.0.1 已补齐输入证据的来源属性：RetrievalResult 2.0 提供
is_explanation/is_mandatory/content_type，null 表示未知，不能默认为正文或非强制。
GenerationRequest 的字段和 Protocol 签名未变，支持嵌套 V2 往返及历史 V1 证据兼容读取。
本模块仍只有 Protocol，**未实现 Generation 业务**；此次仅解除来源元数据准备缺口。
调用方必须同步升级公共模型，兼容策略见
[RetrievalResult V2 ADR](../../../../docs/adr-retrieval-result-v2.md)。

## 失败与执行语义

接口无检索或索引副作用。模型失败、超限和不支持配置应显式失败；不得编造引用。生成可非确定，复现需要保留配置与模型元数据；引用顺序按答案首次出现顺序。

## 依赖、版本与示例

只依赖 contracts、本模块 internal 及未来注入的模型适配器，不得依赖检索模块。
API 版本 1，外层请求/答案 Schema 仍为 `1.x`；嵌套证据为 RetrievalResult `2.0`。

```python
# 接口示例，generator 为未来注入实现。
answer = generator.generate(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/generation/tests -q`。

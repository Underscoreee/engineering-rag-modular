# Structured LLM HTTP 适配器

## 职责与入口

将公共 `StructuredLLMRequest` 发送到显式配置的 OpenAI-compatible Chat
Completions API，返回公共 `StructuredLLMResponse`。不实现 Query、检索、Embedding、
Generation，也不把模型输出当作规范证据。无新增依赖；导入、配置和构造均不调用网络。

```python
from engineering_rag.infrastructure.llm.api import (
    LLMSettings,
    OpenAICompatibleLLMClient,
    StructuredLLMClient,
    StructuredLLMRequest,
    StructuredLLMResponse,
    LLMError,
)

settings = LLMSettings.from_env()
client = OpenAICompatibleLLMClient(settings)
config = settings.structured_config("query-understanding-production")
# 把 client 与 config 注入 Query 的公开工厂；不要在业务模块中导入本适配器。
```

API：

```python
LLMSettings.from_env(environ: Mapping[str, str] | None = None) -> LLMSettings
settings.structured_config(config_id: str) -> StructuredLLMConfig
OpenAICompatibleLLMClient(settings: LLMSettings, *, transport: HTTPTransport | None = None)
client.generate(request: StructuredLLMRequest) -> StructuredLLMResponse
client.calls -> list[dict[str, object]]
```

唯一业务契约来自 `engineering_rag.contracts.llm` 和
`contracts.protocols.StructuredLLMClient`；本模块没有第二套公共请求/响应模型。
接口使用既有 LLM Schema `1.0`，不修改 Query V2.0 或 Document V2.4。

## 配置

本模块只读取进程环境，不自动打开 `.env` 或扫描凭证文件。

| 环境变量 | 含义 / 默认值 |
|---|---|
| `ERAG_LLM_PROVIDER` | 必填：`deepseek` 或 `openai_compatible` |
| `ERAG_LLM_BASE_URL` | 必填：API 根路径，例如 `https://api.deepseek.com`；自动追加 `/chat/completions` |
| `ERAG_LLM_API_KEY` | 必填，`SecretStr` 保存，不进入 repr、诊断或公共请求 |
| `ERAG_LLM_MODEL` | 必填；不猜测模型名或把其他模型静默替换为默认值 |
| `ERAG_LLM_MODEL_REVISION` | 可选期望版本；默认 null，响应必须提供可靠同名字段且一致，否则失败 |
| `ERAG_LLM_TIMEOUT_SECONDS` | 默认 60，必须大于 0 且不超过 300 |
| `ERAG_LLM_MAX_ATTEMPTS` | 默认 2，范围 1–2；供 Query 阶段配置使用，不是 HTTP 隐式重试 |
| `ERAG_LLM_TEMPERATURE` | 默认 0，范围 0–2 |
| `ERAG_LLM_MAX_OUTPUT_TOKENS` | 默认 4096，正整数 |
| `ERAG_LLM_RESPONSE_FORMAT` | 默认 `json_object`；通用兼容服务可显式选择 `json_schema` |
| `ERAG_LLM_RESPONSE_MODEL_IDS` | 可选、逗号分隔的响应模型别名白名单；默认必须与请求模型完全一致 |
| `ERAG_LLM_TOKEN_PARAMETER` | 默认 `max_tokens`；可选 `max_completion_tokens` |
| `ERAG_LLM_SEND_TEMPERATURE` | 默认 `true`；不支持该参数的服务可显式设为 `false` |

只允许 HTTPS，除非 URL 明确指定本机 loopback HTTP；禁止 URL 中嵌入账号、密码、
查询参数和 fragment。Authorization 不跟随重定向，也不自动使用代理环境变量。
内部 HTTP 连接在每次请求后关闭。无需客户端 `close()`，可复用实例。

`generate()` 使用本次 `request.config` 的 timeout、temperature、max_output_tokens；
模型身份必须与适配器的配置一致。不会以配置默认值覆盖请求指定值或截断生成预算。

## 输出与本地校验

DeepSeek 采用官方文档所述的 `json_object` 模式，并在消息中明确要求 JSON。
其 JSON 模式不是完整 JSON Schema 保证；空输出、截断和拒绝都不能视为成功。
不声称 DeepSeek 支持这里的通用 `json_schema` 模式，因此 DeepSeek 配置拒绝该选项。
参考：[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、
[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。

通用 `json_schema` 模式只转换传输用的 Schema 深拷贝：去除 schema 节点的 default、
将已声明属性全部列为 required、关闭 additionalProperties。不会改动原始
`request.output_schema`，也不会误删名称为 `default` 的合法属性。不能安全转换的开放对象
Schema 明确报错；供应商仍可能不支持某些 JSON Schema 关键字，须真实验证。

适配器严格解析外层 JSON 和 message.content JSON，拒绝重复字段、NaN/Infinity、非对象
输出、非法 UTF-8、截断、拒绝、多 choice、工具调用和无法绑定的模型身份。

调用方仍必须执行：

```python
response = client.generate(request)
validated_output = response.validate_output(request, ApplicationOutputModel)
```

这里的 `ApplicationOutputModel` 必须是调用方自己定义的 `extra='forbid'` Pydantic 模型，
且与 request.output_schema 一致。既有 Query 阶段已经执行此边界；适配器不导入其私有模型。
JSON 语法有效不等于业务类型、来源或工程事实正确。

响应模型默认要求精确匹配。只有人工配置的响应别名白名单允许绑定到请求的逻辑模型 ID；
实际模型字符串仍记录在 `calls[].actual_model`，避免隐藏模型切换。
`model_revision` 仅从响应的同名字段取得；不把 system_fingerprint、请求期望值或别名猜作版本。
请求要求版本而响应没有提供可靠同名字段时明确失败。

## 错误、重试和诊断

每次 `generate()` 只执行一次 POST，不执行 HTTP 重试。超时和连接错误分别同时属于
`LLMTimeoutError/TimeoutError`、`LLMConnectionError/ConnectionError`，让既有 Query 的
有界重试预算继续生效。结构化输出错误属于 `LLMOutputError/ValueError`，可以由调用方
按已有预算发起纠正；认证、限流、额度和服务端错误不会在本模块暗中重试。

`LLMError.code` 包括 configuration_missing、configuration_invalid、authentication、
permission、quota、rate_limit、server_error、timeout、connection、redirect_rejected、
model_mismatch、invalid_json、invalid_usage、empty_output、truncated_output 等。
错误消息不会包含供应商原始响应、密钥或原始底层异常。

请求与响应分别限制为 2 MiB，超限明确失败。HTTP timeout 是 socket 操作超时，不是 DNS、
网络和模型生成整个阶段的严格总耗时 SLA；上层需另外定义端到端时间预算。

`calls` 是线程安全的深拷贝快照，记录 request_id、stage、请求/实际模型、trace_id、
耗时、Token 用量和安全错误码；不保存 Prompt、用户问题、生成正文、认证头和密钥。
未知 Token 用量保持 null，未提供可信版本时保持 null，不推算账单成本。
成功诊断表示传输和 JSON 校验成功，不代表调用方业务 Schema 或规范事实校验通过。
网络调用会消耗真实供应商额度；不承诺请求幂等或供应商随机输出可重复。

## 独立测试与依赖注入

```bash
.venv/bin/python -m pytest tests/infrastructure/llm -q
```

这些测试只注入离线 HTTP 替身，没有真实 API 调用。传输替身使用：

```python
from engineering_rag.infrastructure.llm.api import HTTPResponse, HTTPTransport

# HTTPTransport.post(url, *, headers, body: bytes, timeout_seconds: float)
#     -> HTTPResponse(status: int, body: bytes)
```

真实 API Smoke 必须由显式运行入口、有效凭证及维护者授权触发；没有凭证时应报告
NOT RUN/BLOCKED，不能拿离线测试证明真实端到端成功。

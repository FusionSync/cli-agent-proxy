<h1 align="center">Aviary</h1>

<p align="center">
  <strong>面向 CLI Coding Agent 的沙箱优先 Runtime Gateway。</strong>
</p>

<p align="center">
  把 Claude Code、Codex、Gemini CLI、OpenCode、ACP 兼容 Agent，以及后续更多 CLI Agent，
  包装成可托管、可隔离、可审计、可私有化部署的后端运行时。
</p>

<p align="center">
  <a href="README.md">English README</a>
  ·
  <a href="docs/product-design.md">产品设计</a>
  ·
  <a href="docs/sandbox-architecture.md">沙箱架构</a>
  ·
  <a href="docs/api-schema.md">API Schema</a>
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue"></a>
  <a href="https://docs.astral.sh/uv/"><img alt="uv" src="https://img.shields.io/badge/runtime-uv-2f80ed"></a>
  <a href="#api-%E9%A2%84%E8%A7%88"><img alt="HTTP SSE API" src="https://img.shields.io/badge/API-HTTP%20%2B%20SSE-0f766e"></a>
  <a href="docs/sandbox-architecture.md"><img alt="Sandbox First" src="https://img.shields.io/badge/architecture-sandbox--first-black"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

```text
应用后端
  -> Aviary 控制面 API
    -> Sandbox Manager
      -> 每个会话一个 Runtime Sandbox
        -> Claude Code / Codex / Gemini CLI / OpenCode / ACP / future agents
```

## 一句话

很多 Agent Server 的实现只是“在服务端拉起一个 CLI 进程，然后把输出流式返回”。

Aviary 的立场不同：

```text
一个会话 -> 一个沙箱 -> 一个工作区 -> 一组短期凭证上下文
```

Aviary 不是单一牢笼，而是一组受管理的隔离生境：不同 Provider、策略、工作区、模型网关和运行时 profile 可以共存在同一个后端接口之后。

这个差异在 SaaS、多用户平台、私有化部署、离线部署、模型网关、审计、审批、工作区隔离、凭证隔离这些场景里非常关键。

## 为什么需要它

Coding Agent 正在从本地开发工具变成基础设施。

上层产品希望把 Claude Code、Codex、Gemini CLI、OpenCode 和协议型 Agent 嵌进自己的系统。但每个 Provider 都有自己的进程模型、权限模型、配置方式、事件流格式和会话生命周期。

Aviary 要补的是中间那层 Runtime：

| 问题 | Aviary 的方向 |
| --- | --- |
| 每家 Agent 都有不同接口 | 抽象统一的 Session、Message、Event、Policy、Sandbox 合约 |
| Provider 会话难以安全托管 | 每个会话一个受管理的运行环境 |
| SaaS 用户不能共享文件和密钥 | 工作区、凭证、进程、网络全部隔离 |
| 私有化部署需要接内部模型网关 | 通过 `runtime.base_url` 和服务端 secret reference 接入 |
| UI 不只需要最终文本 | 用标准 SSE 事件支持流式渲染、审计、回放、审批 |
| Provider 能力差异很大 | 通过 capabilities 暴露支持程度，而不是假装完全一致 |

## 架构观

这个项目围绕三个边界设计。

| 边界 | 负责 | 不应该负责 |
| --- | --- | --- |
| Control Plane | 公共 API、会话、策略校验、Provider 路由、事件持久化、审批状态 | Provider SDK 进程、Docker socket、原始密钥注入 |
| Sandbox Manager | 沙箱生命周期、工作区分配、资源限制、密钥投递、清理、interrupt/kill 升级 | 上层产品 API 语义 |
| Provider Runtime | Provider SDK 或 CLI 进程、Provider 参数映射、标准事件转换 | Host 工作区分配、授权判断、长期密钥管理 |

目标生产架构：

```text
Client / product backend / ChatOps adapter
        |
        | HTTP API / SSE
        v
Control Plane
  - OpenAPI surface
  - session and run registry
  - policy validation
  - provider routing
  - event and audit persistence
        |
        | internal runtime protocol
        v
Sandbox Manager
  - Docker or Kubernetes driver
  - workspace allocator
  - secret resolver
  - resource and timeout enforcement
  - graceful interrupt, then kill escalation
        |
        | per-session sandbox
        v
Provider Runtime
  - Claude Agent SDK / Codex CLI / Gemini CLI / OpenCode / ACP
  - normalized event stream
  - provider-native permissions as defense-in-depth
```

Provider 自带的 permission mode 很有价值，但它只能作为 defense-in-depth。真正的安全边界应该由外层容器、Pod 或更强的沙箱来承担。

## 当前实现状态

当前项目还处于早期，但核心架构切口已经建立。

| 模块 | 状态 |
| --- | --- |
| FastAPI HTTP/SSE 服务 | 已实现 |
| Claude Code Provider，基于 `claude-agent-sdk` | 已实现 |
| 会话创建、查询、删除 | 已实现 |
| SSE 消息流 | 已实现 |
| Provider capabilities endpoint | 已实现 |
| model/runtime/generation/policy/sandbox/provider_options DTO | 已实现 |
| `SandboxDriver` 边界 | 已实现 |
| 开发用 `LocalUnsafeSandboxDriver` | 已实现 |
| 每个 session 一个 Docker container | 规划中 |
| session/run/event/approval/audit 持久化 | 规划中 |
| secret resolver 和 workspace allocator | 规划中 |
| Codex Provider | 规划中 |
| Kubernetes pod/job driver | 规划中 |

当前开发路径：

```text
FastAPI
  -> SessionManager
    -> LocalUnsafeSandboxDriver
      -> ClaudeCodeProvider
        -> claude-agent-sdk
```

`LocalUnsafeSandboxDriver` 的名字故意带有 unsafe，因为它会在 API 进程内运行 Provider adapter。它是开发模式，不是生产隔离方案。

## 快速开始

安装依赖：

```bash
uv sync --extra dev
```

运行测试：

```bash
uv run pytest
```

启动 API：

```bash
uv run uvicorn aviary.main:app --reload --host 0.0.0.0 --port 9000
```

创建 Claude Code 会话：

```bash
curl -s http://localhost:9000/v1/sessions \
  -H 'content-type: application/json' \
  -d '{
    "provider": "claude-code",
    "conversation_id": "demo-conv",
    "model": {"name": "private-sonnet"},
    "runtime": {
      "base_url": "http://model-gateway.internal",
      "api_key_ref": "project-a/anthropic"
    },
    "sandbox": {
      "profile": "default",
      "workspace_retention": "delete",
      "timeout_seconds": 1800
    },
    "policy": {
      "execution_mode": "approve_edits",
      "filesystem": "workspace_only",
      "network": "deny_by_default",
      "allowed_hosts": ["model-gateway.internal"]
    }
  }'
```

发送流式消息：

```bash
curl -N -X POST http://localhost:9000/v1/sessions/<session_id>/messages:stream \
  -H 'content-type: application/json' \
  -d '{"message":"Inspect this repository and summarize the architecture."}'
```

## API 预览

### Provider Capabilities

```http
GET /v1/providers
GET /v1/providers/{provider}/capabilities
```

Capabilities 用来告诉客户端某个 Provider 对字段的支持程度。比如 `generation.temperature`、`policy.execution_mode`、`model.fallback` 不应该被默认假设为所有 Provider 都支持。

### 创建会话

```http
POST /v1/sessions
```

```json
{
  "provider": "claude-code",
  "conversation_id": "bamboo-conv-001",
  "model": {
    "name": "private-sonnet",
    "fallback": "private-haiku"
  },
  "runtime": {
    "base_url": "http://model-gateway:8080",
    "api_key_ref": "project-a/anthropic",
    "cwd": "/workspaces/project-a/bamboo-conv-001",
    "env": {}
  },
  "sandbox": {
    "profile": "default",
    "workspace_retention": "delete",
    "timeout_seconds": 1800
  },
  "generation": {
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 4096
  },
  "policy": {
    "execution_mode": "approve_edits",
    "allowed_tools": ["Read", "Write"],
    "disallowed_tools": ["Bash"],
    "filesystem": "workspace_only",
    "network": "deny_by_default",
    "allowed_hosts": ["model-gateway.internal"]
  },
  "system_prompt": "You are Bamboo's coding agent.",
  "provider_options": {
    "resume": "previous-claude-session-id",
    "max_turns": 5,
    "mcp_servers": {}
  },
  "metadata": {
    "external_trace_id": "trace-001"
  }
}
```

`metadata` 只能作为非权威关联信息。它不能作为鉴权依据、secret lookup key、workspace selector 或 provider option 来源。

### 流式消息

```http
POST /v1/sessions/{session_id}/messages:stream
```

返回 `text/event-stream`：

```text
event: start
data: {"type":"start","session_id":"...","data":{"provider":"claude-code"}}

event: ai_chunk
data: {"type":"ai_chunk","session_id":"...","data":{"content":"I will inspect the project..."}}

event: tool_call
data: {"type":"tool_call","session_id":"...","data":{"name":"Read","args":{"file_path":"README.md"}}}

event: end
data: {"type":"end","session_id":"...","data":{"provider_session_id":"..."}}
```

### 中断和关闭

```http
POST   /v1/sessions/{session_id}/interrupt
DELETE /v1/sessions/{session_id}
```

## Claude Code First

Claude Code 当前通过 Python `claude-agent-sdk` 接入。

```text
Provider Runtime
  -> claude-agent-sdk
    -> ClaudeSDKClient
      -> Claude Code process
        -> ANTHROPIC_BASE_URL / private model gateway
```

Claude Code / Claude Agent SDK 不提供官方 standalone HTTP daemon。Aviary 提供 HTTP/SSE 服务，并在运行时边界内使用 SDK。

Provider 细节：[docs/claude-code-provider.md](docs/claude-code-provider.md)

## 部署模型

当前 Docker 镜像：

```bash
docker build -t aviary .
docker run --rm -p 9000:9000 aviary
```

当前镜像以非 root 用户运行 API 服务。它还没有实现每个 session 一个 Docker container。

目标 Docker 部署：

```text
api container
  -> internal sandbox manager container
    -> Docker Engine
      -> provider runtime container for session A
      -> provider runtime container for session B
      -> provider runtime container for session C
```

目标 Kubernetes 部署：

```text
control plane deployment
  -> sandbox manager/controller
    -> pod or job per session
      -> network policy
      -> secret manager
      -> ephemeral or PVC-backed workspace
```

## 安全立场

我们要保留的安全默认值：

- 公共 API 容器不能挂载 Docker socket。
- Provider runtime 不应该 privileged 运行。
- Host home、SSH keys、Git credentials、`~/.claude`、`~/.codex` 不能跨会话共享。
- 不接受来自终端用户 payload 的原始 Provider API Key。
- `runtime.api_key_ref` 应该解析到服务端 secret material。
- managed mode 下 workspace 应由服务端分配和校验。
- 网络策略默认 deny-by-default。
- 权限 bypass mode 不能作为默认行为。
- 生产使用前必须持久化事件和审计记录。

## 路线图

| Milestone | Focus |
| --- | --- |
| `v0.1` | Claude Code proof of concept、local unsafe sandbox driver、SSE stream、memory storage |
| `v0.2` | durable event schema、persisted sessions/runs/events、policy validation |
| `v0.3` | Docker sandbox driver、workspace allocator、secret resolver、audit log |
| `v0.4` | approval API、network/filesystem enforcement、Docker Compose |
| `v0.5` | Codex provider、provider conformance tests |
| `v1.0` | stable OpenAPI、SDK examples、Helm chart、production hardening guide |

## 文档

| Document | Purpose |
| --- | --- |
| [Product Design](docs/product-design.md) | 产品边界、原则、路线图 |
| [Sandbox Architecture](docs/sandbox-architecture.md) | Runtime 生命周期、Driver、隔离模型 |
| [API Schema](docs/api-schema.md) | DTO 分组和 Provider capability 模型 |
| [Claude Code Provider](docs/claude-code-provider.md) | Claude Agent SDK 映射和事件标准化 |

## License

MIT

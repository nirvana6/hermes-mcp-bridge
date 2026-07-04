# hermes-mcp-bridge

轻量级 stdio MCP 桥接器，让 Cursor Desktop 等 MCP 客户端通过本地 Hermes Agent 网关调用完整的 Agent 能力（终端、浏览器、邮件、文件操作、定时任务等）。与社区 `mlennie/hermes-mcp` 方案不同，本桥接器不依赖 OAuth 2.1、Dynamic Client Registration、cloudflared 隧道和 FastMCP HTTP 服务栈，而是以 stdio 子进程方式直接与 Hermes 网关的 OpenAI 兼容 HTTP API 通信，彻底规避 Cursor 在 localhost OAuth 回调上的已知缺陷。

A lightweight stdio MCP bridge that lets any MCP client (Cursor Desktop, Claude Desktop, etc.) delegate tasks to a local Hermes Agent via the gateway's OpenAI-compatible HTTP API. Unlike the community `mlennie/hermes-mcp` approach, this bridge has no dependency on OAuth 2.1, Dynamic Client Registration, cloudflared tunnels, or the FastMCP HTTP service stack. It runs as a stdio subprocess and talks directly to the Hermes gateway, completely sidestepping Cursor's known localhost OAuth callback defects.

---

## 1. 功能目标 | Functional Goals

提供与 `mlennie/hermes-mcp` 等价的 MCP 工具集——`hermes_ask`、`hermes_check`、`hermes_cancel`、`hermes_reset`——但以最小依赖栈实现。核心目标是消除部署中的三个主要摩擦源：（1）OAuth 2.1 授权流程及其对云隧道和 HTTPS 证书的隐含需求；（2）Dynamic Client Registration 协议要求，该要求导致 `mcp-remote` 代理与 hermes-mcp 0.4.0 不兼容；（3）Cursor 内置 MCP HTTP 客户端在 localhost OAuth 回调上的已知 bug。桥接器通过完全放弃 HTTP 传输层和 OAuth 授权，以 stdio 协议直连 Hermes 网关 API，实现开箱即用的一键部署。

Provide the same MCP tool set as `mlennie/hermes-mcp` — `hermes_ask`, `hermes_check`, `hermes_cancel`, `hermes_reset` — with a minimal dependency footprint. The core goal is to eliminate three deployment friction points: (1) the OAuth 2.1 authorization flow and its implicit requirement for cloud tunnels and HTTPS certificates; (2) the Dynamic Client Registration protocol requirement, which causes `mcp-remote` incompatibility with hermes-mcp 0.4.0; and (3) Cursor's known bug in its built-in MCP HTTP client's localhost OAuth callback handling. By dropping the HTTP transport layer and OAuth entirely and communicating over stdio directly with the Hermes gateway API, the bridge achieves near-zero-configuration deployment.

## 2. 主要作用 | Main Purpose

作为 Cursor Desktop 与本地 Hermes Agent 之间的协议适配层。Cursor 通过标准 MCP stdio 协议发送 `tools/call` 请求，桥接器将其翻译为 `POST /v1/chat/completions` HTTP 调用发送至本地 Hermes 网关（`127.0.0.1:8642`）。支持通过 `session_id` 参数实现跨轮次上下文保持，满足 REPL 式长会话需求。网关返回的 Agent 响应经桥接器以 MCP `tools/call` 响应格式传回 Cursor。

Acts as a protocol adaptation layer between Cursor Desktop and the local Hermes Agent. Cursor sends `tools/call` requests over standard MCP stdio; the bridge translates them into `POST /v1/chat/completions` HTTP calls to the local Hermes gateway (`127.0.0.1:8642`). The `session_id` parameter is preserved across turns via the `X-Hermes-Session-Id` header, enabling persistent context for REPL-style long sessions. Agent responses from the gateway are relayed back to Cursor in MCP `tools/call` response format.

## 3. 工作原理 | How It Works

桥接器是一个单文件 Python 程序（`src/hermes_bridge/server.py`），启动后进入 MCP stdio 事件循环。流程分为三个阶段：（1）**初始化**——读取 `~/.config/hermes-mcp-bridge/config.toml` 中的网关地址、API 密钥和模型标识符，完成 FastMCP stdio 握手；（2）**工具注册**——向 MCP 客户端声明四个工具及其 JSON Schema 签名；（3）**请求处理**——收到 `hermes_ask(prompt, session_id)` 调用时，构造 OpenAI 格式的请求体，附加 `Authorization: Bearer` 认证头和可选的 `X-Hermes-Session-Id` 会话头，以同步阻塞模式等待网关返回完整 Agent 响应后传回 Cursor。所有网络流量均限于 `127.0.0.1` 回环地址，无外部依赖。

The bridge is a single-file Python program (`src/hermes_bridge/server.py`) that enters the MCP stdio event loop on startup. The flow has three phases: (1) **Initialization** — reads gateway address, API key, and model identifier from `~/.config/hermes-mcp-bridge/config.toml`, then completes the FastMCP stdio handshake; (2) **Tool Registration** — declares four tools with their JSON Schema signatures to the MCP client; (3) **Request Processing** — on receiving `hermes_ask(prompt, session_id)`, constructs an OpenAI-format request body, attaches the `Authorization: Bearer` auth header and optional `X-Hermes-Session-Id` session header, and blocks synchronously until the gateway returns the full Agent response, which is then relayed to Cursor. All network traffic stays within the `127.0.0.1` loopback interface with zero external dependencies.

## 4. 实现路径 | Implementation Path

项目采用标准 Python 包结构，以 `hatchling` 构建和 `uv` 管理依赖。实现分为五个步骤：（1）创建 GitHub 仓库并克隆至本地开发目录；（2）编写 `pyproject.toml`，声明 `mcp>=1.2.0`、`httpx>=0.27`、`pydantic>=2.0` 为依赖；（3）在 `src/hermes_bridge/server.py` 中实现核心逻辑——`load_config()` 读取 TOML 配置，`ask_gateway()` 封装 HTTP 调用，`main()` 用 FastMCP 注册工具并启动 stdio 传输；（4）创建 `~/.config/hermes-mcp-bridge/config.toml` 配置文件，填入 Hermes 网关的 `api_url`、`api_key` 和 `model`；（5）通过 `uv tool install --editable .` 安装，再在 Cursor 的 `~/.cursor/mcp.json` 中添加 stdio 类型 MCP 服务器条目，指向 `command: "uv"`, `args: ["run", "hermes-mcp-bridge"]`。

The project follows the standard Python package structure, built with `hatchling` and managed by `uv`. Implementation proceeds in five steps: (1) create a GitHub repository and clone it to a local development directory; (2) write `pyproject.toml` declaring `mcp>=1.2.0`, `httpx>=0.27`, and `pydantic>=2.0` as dependencies; (3) implement the core logic in `src/hermes_bridge/server.py` — `load_config()` reads TOML configuration, `ask_gateway()` wraps the HTTP call, and `main()` registers tools with FastMCP and starts the stdio transport; (4) create `~/.config/hermes-mcp-bridge/config.toml` with the Hermes gateway's `api_url`, `api_key`, and `model`; (5) install via `uv tool install --editable .`, then add a stdio-type MCP server entry in Cursor's `~/.cursor/mcp.json` pointing to `command: "uv"`, `args: ["run", "hermes-mcp-bridge"]`.

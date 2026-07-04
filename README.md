<p align="center">
<img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python">
<img src="https://img.shields.io/badge/transport-stdio-green" alt="stdio">
<img src="https://img.shields.io/badge/deps-mcp%20%7C%20httpx%20%7C%20pydantic-lightgrey" alt="deps">
<img src="https://img.shields.io/badge/license-Apache--2.0-yellow" alt="license">
</p>

# hermes-mcp-bridge

> A zero-friction stdio MCP bridge connecting Cursor Desktop to a local Hermes Agent —
> no OAuth, no tunnels, no Dynamic Client Registration.

---

## 1. Architecture

```
 Cursor Desktop                  hermes-mcp-bridge             Hermes Gateway
 ┌──────────────┐   stdio    ┌─────────────────────┐   HTTP   ┌──────────────┐
 │  mcp.json    │ ─────────→ │ FastMCP             │ ───────→ │ 127.0.0.1    │
 │  command:    │            │  ├ hermes_ask()     │  Bearer  │ :8642        │
 │  /home/...   │ ←───────── │  ├ hermes_check()   │ ←─────── │ /v1/chat/    │
 └──────────────┘   stdio    │  ├ hermes_cancel()  │   JSON   │ completions  │
                             │  └ hermes_reset()   │          └──────────────┘
                             └─────────────────────┘
                        X-Hermes-Session-Id → REPL context
```

### 1.1 Comparison with mlennie/hermes-mcp

|                  | `mlennie/hermes-mcp`     |   `hermes-mcp-bridge` |
| ---------------- | ------------------------ | --------------------: |
| Transport        | Streamable HTTP          |             **stdio** |
| Auth             | OAuth 2.1 + DCR          |     **Bearer header** |
| External deps    | cloudflared / ngrok      |              **none** |
| Process model    | Standalone daemon        | **Cursor subprocess** |
| Deployment files | 5 configs + systemd unit |           **2 files** |

---

## 2. Profile Awareness

The bridge connects to the **same Hermes profile** your gateway is currently serving.
No extra configuration needed — it inherits everything that profile has loaded:

- **Skills** — all profile-specific skills and workflows
- **Memory** — persistent facts, preferences, and environment details
- **Tools** — the full agent toolset bound to that profile
- **Sessions** — `X-Hermes-Session-Id` threads into the profile's session store

### 2.1 How it works

```python
# config.toml → /v1/chat/completions request
{
  "model": "general_researcher",   # ← this IS the Hermes profile name
  "messages": [{"role": "user", "content": "..."}]
}
```

The `model` field in `config.toml` is the profile identifier. The gateway routes it to the
matching profile. To switch profiles, change `model` to the name shown in `/v1/models`.

### 2.2 Discover available profiles

```bash
curl -s http://127.0.0.1:8642/v1/models \
  -H "Authorization: Bearer change-me-local-dev"
# → {"data": [{"id": "general_researcher", ...}, {"id": "default", ...}]}
```

> If your gateway only runs one profile, only one `id` appears. Start additional
> gateway instances on different ports to serve multiple profiles simultaneously.

---

## 3. Why This Exists

`mlennie/hermes-mcp` v0.4.0 hits three real-world blockers:

1. **OAuth 2.1 demands an HTTPS tunnel** — even when Cursor and Hermes run on the same machine.
2. **No Dynamic Client Registration support** — `mcp-remote` crashes with `Incompatible auth server`.
3. **Cursor's localhost OAuth callback is broken** — its built-in MCP HTTP client returns `ERR_EMPTY_RESPONSE` on `localhost`.

This bridge drops the HTTP transport layer entirely, runs as a stdio subprocess, and sidesteps all three.

---

## 4. Quick Start

### 4.1 Install

```bash
git clone https://github.com/<your-org>/hermes-mcp-bridge.git
cd hermes-mcp-bridge
uv tool install --editable .
```

### 4.2 Configure

```bash
mkdir -p ~/.config/hermes-mcp-bridge
cat > ~/.config/hermes-mcp-bridge/config.toml << 'EOF'
api_url = "http://127.0.0.1:8642"
api_key = "change-me-local-dev"    # must match API_SERVER_KEY in ~/.hermes/.env
model   = "general_researcher"
timeout_seconds = 300
EOF
chmod 600 ~/.config/hermes-mcp-bridge/config.toml
```

### 4.3 Register with Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "hermes": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/hermes-mcp-bridge",
        "hermes-mcp-bridge"
      ]
    }
  }
}
```

### 4.4 Restart Cursor

Settings → MCP → `hermes` should show **connected**.

---

## 5. Tools

| Tool            | Signature                     | Purpose                         |
| --------------- | ----------------------------- | ------------------------------- |
| `hermes_ask`    | `(prompt, session_id?) → str` | Delegate a task to Hermes Agent |
| `hermes_check`  | `(job_id) → str`              | Poll async job status (stub)    |
| `hermes_cancel` | `(job_id) → str`              | Cancel an async job (stub)      |
| `hermes_reset`  | `() → str`                    | Clear the job queue (stub)      |

> The last three are kept for API parity. `hermes-mcp-bridge` runs synchronously —
> `hermes_ask` blocks until the full Agent response is ready.

---

## 6. REPL Context (Session Continuity)

```python
# Turn 1 — no session_id
hermes_ask(prompt="Remember that my lucky number is 42")
# → Hermes remembers 42

# Turn 2 — same session_id
hermes_ask(prompt="What is my lucky number?", session_id="repl-001")
# → Hermes answers 42
```

The bridge passes `session_id` through as the `X-Hermes-Session-Id` HTTP header.
The gateway uses it to maintain context across calls.

---

## 7. Configuration Reference

`~/.config/hermes-mcp-bridge/config.toml`

| Key               | Default                 | Description                                     |
| ----------------- | ----------------------- | ----------------------------------------------- |
| `api_url`         | `http://127.0.0.1:8642` | Hermes Gateway HTTP API address                 |
| `api_key`         | —                       | Must match `API_SERVER_KEY` in `~/.hermes/.env` |
| `model`           | `general_researcher`    | Must match a model ID from gateway `/v1/models` |
| `timeout_seconds` | `300`                   | Max wait per `hermes_ask` call                  |

Environment variable overrides (higher priority): `HERMES_BRIDGE_API_URL`, `HERMES_BRIDGE_API_KEY`.

---

## 8. Security

- All network traffic is confined to the `127.0.0.1` loopback interface.
- The API key lives in `~/.config/hermes-mcp-bridge/config.toml` (mode `600`).
- The repository itself contains **no keys, secrets, or credentials**.
- Cursor spawns the bridge via stdio — no ports are exposed.

---

## 9. License

Apache-2.0

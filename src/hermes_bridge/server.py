"""Lightweight stdio MCP bridge to a local Hermes Agent gateway.

Why this exists:
  mlennie/hermes-mcp 0.4.0 is incompatible with mcp-remote because it lacks
  Dynamic Client Registration. Cursor's own OAuth callback has a localhost bug.
  This bridge is ~80 lines: it speaks MCP stdio to Cursor and plain HTTP to the
  Hermes gateway's OpenAI-compatible /v1/chat/completions. No OAuth, no DCR.

Configuration:
  Read from ~/.config/hermes-mcp-bridge/config.toml
  Fields: api_url (default http://127.0.0.1:8642), api_key, model (default
  "general_researcher"), timeout_seconds (default 300).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tomllib
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("hermes_bridge")

CONFIG_PATH = Path.home() / ".config" / "hermes-mcp-bridge" / "config.toml"


def load_config() -> dict:
    """Read config.toml; fall back to env vars and sensible defaults."""
    cfg: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as f:
            cfg = tomllib.load(f)

    # Env overrides (12-factor)
    if "HERMES_BRIDGE_API_URL" in os.environ:
        cfg["api_url"] = os.environ["HERMES_BRIDGE_API_URL"]
    if "HERMES_BRIDGE_API_KEY" in os.environ:
        cfg["api_key"] = os.environ["HERMES_BRIDGE_API_KEY"]

    cfg.setdefault("api_url", "http://127.0.0.1:8642")
    cfg.setdefault("model", "general_researcher")
    cfg.setdefault("timeout_seconds", 300)

    if "api_key" not in cfg or not cfg["api_key"]:
        logger.error("api_key missing in %s or HERMES_BRIDGE_API_KEY env", CONFIG_PATH)
        sys.exit(2)

    return cfg


def ask_gateway(cfg: dict, prompt: str, session_id: str | None) -> str:
    """POST /v1/chat/completions and return the assistant content."""
    url = cfg["api_url"].rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["X-Hermes-Session-Id"] = session_id

    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        with httpx.Client(timeout=cfg["timeout_seconds"]) as client:
            r = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return f"[hermes-bridge] gateway timeout after {cfg['timeout_seconds']}s"
    except httpx.HTTPError as e:
        return f"[hermes-bridge] gateway request failed: {e}"

    if r.status_code == 401:
        return "[hermes-bridge] gateway rejected API key (401)"
    if r.status_code != 200:
        logger.debug("gateway error body: %s", r.text[:500])
        return f"[hermes-bridge] gateway returned HTTP {r.status_code}"

    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        return f"[hermes-bridge] malformed gateway response: {e}"

    if not isinstance(content, str):
        return f"[hermes-bridge] unexpected content type: {type(content).__name__}"
    return content.strip()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    cfg = load_config()
    logger.info(
        "hermes-mcp-bridge starting (gateway=%s, model=%s)",
        cfg["api_url"], cfg["model"],
    )

    mcp = FastMCP("hermes-mcp-bridge")

    @mcp.tool(
        description=(
            "Delegate a task to Hermes Agent on this user's machine.\n\n"
            "Use for things the calling LLM cannot do directly: scheduling cron jobs, "
            "browser-driven web search, sending email, creating/editing local documents, "
            "anything that should persist after this chat ends.\n\n"
            "Args:\n"
            "  prompt: Natural-language instruction for Hermes.\n"
            "  session_id: Optional. Pass the same id across multiple calls in one chat "
            "to let Hermes remember prior steps (draft → refine → save).\n\n"
            "Returns: Hermes's final answer text."
        )
    )
    def hermes_ask(prompt: str, session_id: str | None = None) -> str:
        return ask_gateway(cfg, prompt, session_id)

    # Stubs for API parity with hermes-mcp
    @mcp.tool(description="Not implemented. Kept for API parity with hermes-mcp.")
    def hermes_check(job_id: str) -> str:
        return json.dumps({"status": "unsupported", "reason": "hermes-mcp-bridge is sync-only"})

    @mcp.tool(description="Not implemented. Kept for API parity with hermes-mcp.")
    def hermes_cancel(job_id: str) -> str:
        return json.dumps({"status": "unsupported"})

    @mcp.tool(description="Not implemented. Kept for API parity with hermes-mcp.")
    def hermes_reset() -> str:
        return json.dumps({"status": "unsupported"})

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

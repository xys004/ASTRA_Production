"""Install or update ASTRA's MCP entry for Google Antigravity.

The default is a workspace-scoped configuration in .agents/mcp_config.json so
ASTRA is exposed only when this repository is open. Use --global deliberately
to write ~/.gemini/config/mcp_config.json instead.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def target_path(global_scope: bool) -> Path:
    if global_scope:
        return Path.home() / ".gemini" / "config" / "mcp_config.json"
    return ROOT / ".agents" / "mcp_config.json"


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Refusing to overwrite invalid JSON at {path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"Refusing to overwrite non-object JSON at {path}")
    return data


def venv_python_path(platform_name: str | None = None) -> Path:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        return ROOT / "venv" / "Scripts" / "python.exe"
    return ROOT / "venv" / "bin" / "python"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Configure Antigravity globally instead of only in this workspace.",
    )
    args = parser.parse_args()

    python = venv_python_path()
    server = ROOT / "mcp_server" / "server.py"
    if not python.is_file():
        raise SystemExit(f"ASTRA virtual environment not found: {python}")
    if not server.is_file():
        raise SystemExit(f"ASTRA MCP server not found: {server}")

    target = target_path(args.global_scope)
    config = load_config(target)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"mcpServers must be a JSON object in {target}")
    servers["astra"] = {
        "command": str(python),
        "args": [str(server)],
        "cwd": str(ROOT),
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)
        print(f"Backup: {backup}")
    target.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Antigravity MCP configured: {target}")
    print("Open Antigravity Settings > MCP Servers and choose Refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

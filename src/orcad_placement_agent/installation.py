"""Generate client configuration snippets without changing client settings."""

import json
import os
from pathlib import Path
import sys

from .session import write_new
from .diagnostics import ConfigurationError


CLIENTS = ("codex", "claude", "copilot", "vscode")


def configuration(client: str, executable: Path, knowledge_database: Path | None = None) -> str:
    if client not in CLIENTS:
        raise ConfigurationError("Choose codex, claude, copilot, or vscode.")
    executable = Path(os.path.abspath(executable.expanduser()))
    if not executable.is_file():
        raise FileNotFoundError(f"The Python executable is unavailable: {executable}")
    args = ["-I", "-X", "utf8", "-m", "orcad_placement_agent.mcp_server"]
    if knowledge_database is not None:
        args += ["--knowledge-db", str(knowledge_database.expanduser().resolve())]
    environment = {}
    if os.environ.get("LOCALAPPDATA"):
        environment["LOCALAPPDATA"] = os.environ["LOCALAPPDATA"]
    if client == "codex":
        content = (
            "[mcp_servers.orcad-placement]\n"
            f"command = {json.dumps(str(executable), ensure_ascii=False)}\n"
            f"args = {json.dumps(args, ensure_ascii=False)}\n"
            "startup_timeout_sec = 30\n"
            "tool_timeout_sec = 180\n"
        )
        if environment:
            content += "\n[mcp_servers.orcad-placement.env]\n"
            content += "\n".join(
                f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in environment.items()
            ) + "\n"
        return content
    server: dict[str, object] = {"command": str(executable), "args": args}
    if environment:
        server["env"] = environment
    key = "mcpServers"
    if client == "copilot":
        server.update({"type": "local", "tools": ["*"]})
    elif client == "vscode":
        key = "servers"
        server["type"] = "stdio"
    else:
        server["type"] = "stdio"
    return json.dumps({key: {"orcad-placement": server}}, indent=2, ensure_ascii=False) + "\n"


def write_configurations(
    output: Path, clients: tuple[str, ...] = CLIENTS, *,
    executable: Path | None = None, knowledge_database: Path | None = None,
) -> list[Path]:
    executable = executable if executable is not None else Path(sys.executable)
    contents = [
        (client, configuration(client, executable, knowledge_database)) for client in clients
    ]
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for client, content in contents:
        path = output / f"{client}-mcp.{'toml' if client == 'codex' else 'json'}"
        encoded = content.encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise FileExistsError(f"Refusing to replace a different configuration snippet: {path}")
        else:
            write_new(path, encoded)
        paths.append(path)
    return paths

"""Install into a versioned local environment; never edit client/global settings."""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def local_data():
    if sys.platform != "win32":
        raise RuntimeError("Native PCB integration requires local Windows.")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    value = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 28, None, 0, value) != 0 or not value.value:
        raise RuntimeError("Windows LocalApplicationData is unavailable.")
    return Path(value.value)


def run(arguments, **options):
    subprocess.run([str(item) for item in arguments], check=True, **options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("all", "codex", "claude", "copilot", "vscode"), default="all")
    parser.add_argument("--environment-directory", type=Path)
    parser.add_argument("--books", type=Path, help="Optional operator-owned PDF directory to index locally.")
    parser.add_argument("--plan", action="store_true", help="Print the plan without creating or installing anything.")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Run this script with an explicit Python 3.12+ interpreter; legacy Python is not modified.")
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise RuntimeError("Invalid plugin version.")
    data = local_data()
    environment = (args.environment_directory or data / "OrCadPlacementAgent" / "plugin-envs" / version).absolute()
    python = environment / "Scripts" / "python.exe"
    marker = environment / ".orcad-placement-environment.json"
    configurations = environment / ("client-configs-with-books" if args.books is not None else "client-configs")
    knowledge = data / "OrCadPlacementAgent" / "knowledge.sqlite3"
    if args.plan:
        print(json.dumps({
            "version": version, "environment": str(environment), "python": str(python),
            "client_configurations": str(configurations),
            "knowledge_database": str(knowledge) if args.books is not None else None,
            "bundled_expertise": True, "pdf_dependencies": args.books is not None,
            "client_settings_modified": False, "native_board_operations": False,
            "py_launcher_available": shutil.which("py") is not None,
        }, indent=2))
        return
    if not python.is_file():
        if environment.exists():
            raise RuntimeError("Destination exists without a usable environment; choose a fresh directory. Nothing was deleted.")
        run([sys.executable, "-I", "-m", "venv", environment])
        with marker.open("x", encoding="utf-8") as output:
            json.dump({"schema_version": 1, "package": "orcad-placement-agent", "version": version}, output)
    if not marker.is_file() or marker.stat().st_size > 4096:
        raise RuntimeError("Existing environment is not marked as owned by this installer; choose a fresh directory.")
    identity = json.loads(marker.read_text(encoding="utf-8"))
    if identity != {"schema_version": 1, "package": "orcad-placement-agent", "version": version}:
        raise RuntimeError("Environment ownership/version marker does not match; nothing was installed.")
    inspect = subprocess.run(
        [str(python), "-I", "-c",
         "import importlib.util, importlib.metadata as m; print(m.version('orcad-placement-agent') "
         "if importlib.util.find_spec('orcad_placement_agent') else '')"],
        check=True, capture_output=True, text=True,
    )
    installed = inspect.stdout.strip()
    if installed and installed != version:
        raise RuntimeError("A different package version occupies this environment; choose a fresh directory.")
    if not installed:
        lock = environment / ".install-lock"
        lock.mkdir()
        try:
            run([python, "-I", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                 str(root) + "[integrations]"])
        finally:
            lock.rmdir()
    run([python, "-I", "-c",
         "from orcad_placement_agent import expertise; expertise.catalog(); "
         "from orcad_placement_agent.mcp_server import create_server; create_server()"])
    if args.books is not None:
        run([python, "-I", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             str(root) + "[integrations,knowledge]"])
        run([python, "-I", "-X", "utf8", "-m", "orcad_placement_agent", "knowledge", "index",
             "--books", args.books, "--database", knowledge])
    command = [python, "-I", "-X", "utf8", "-m", "orcad_placement_agent", "integration-config",
               "--client", args.client, "--output-directory", configurations]
    if args.books is not None:
        command += ["--knowledge-db", knowledge]
    run(command)
    print(f"Installed runtime: {python}")
    print("Review the generated snippets and add only the orcad-placement server in your client.")
    print("No client settings, PATH, Cadence settings, board files, or execution policies were changed.")
    if shutil.which("py") is None:
        print("The marketplace bootstrap requires the Windows py launcher. Without it, use the generated absolute-path MCP configurations.")


if __name__ == "__main__":
    main()

"""Start the installed local server without PowerShell or automatic installation."""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def local_data():
    if sys.platform != "win32":
        raise RuntimeError("This native PCB plugin requires local Windows.")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    value = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 28, None, 0, value) != 0 or not value.value:
        raise RuntimeError("Windows LocalApplicationData is unavailable.")
    return Path(value.value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-directory", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / "plugin.json").read_text(encoding="utf-8"))["version"]
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise RuntimeError("Invalid plugin version.")
    data = local_data()
    environment = args.environment_directory or data / "OrCadPlacementAgent" / "plugin-envs" / version
    python = environment.absolute() / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError("Runtime not installed. Review and run scripts\\install.py with Python 3.12+ first.")
    marker = environment.absolute() / ".orcad-placement-environment.json"
    if not marker.is_file() or marker.stat().st_size > 4096:
        raise RuntimeError("Runtime ownership marker is missing; use the reviewed installer in a fresh directory.")
    if json.loads(marker.read_text(encoding="utf-8")) != {
        "schema_version": 1, "package": "orcad-placement-agent", "version": version,
    }:
        raise RuntimeError("Runtime ownership/version marker does not match this plugin.")
    result = subprocess.run(
        [str(python), "-I", "-c", "from orcad_placement_agent import __version__; print(__version__)"],
        check=True, capture_output=True, text=True,
    )
    if result.stdout.strip() != version:
        raise RuntimeError("Plugin and runtime versions differ; install the matching version separately.")
    environment_values = dict(os.environ)
    environment_values["LOCALAPPDATA"] = str(data)
    if not environment_values.get("OPA_KNOWLEDGE_DB"):
        environment_values["OPA_KNOWLEDGE_DB"] = str(data / "OrCadPlacementAgent" / "knowledge.sqlite3")
    # Explicit standard handles preserve MCP pipes on Windows. os.execve does
    # not provide a reliable process/pipe handoff for this launcher there.
    with subprocess.Popen(
        [str(python), "-I", "-X", "utf8", "-m", "orcad_placement_agent.mcp_server"],
        stdin=sys.stdin.buffer, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer,
        env=environment_values,
    ) as child:
        try:
            return child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

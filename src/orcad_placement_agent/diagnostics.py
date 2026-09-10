"""Read-only discovery; installation alone never establishes live access."""

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sys


DEFAULT_CADENCE_ROOT = Path(r"C:\Cadence\OrCADX_25.1")


class ConfigurationError(ValueError):
    """An explicitly reported unsupported or missing configuration."""


@dataclass(frozen=True)
class EnvironmentReport:
    python_executable: str
    python_version: str
    platform: str
    editor_executable: str
    runtime_directory: str
    issues: tuple[str, ...]
    live_access: str = "unproven"

    @property
    def ready(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "environment_ready": self.ready,
            **asdict(self),
        }


def default_runtime_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise ConfigurationError(
            "LOCALAPPDATA is unavailable; supply an explicit --runtime-dir."
        )
    return Path(local_app_data) / "OrCadPlacementAgent" / "sessions"


def inspect_environment(
    cadence_root: Path, runtime_directory: Path
) -> EnvironmentReport:
    """Inspect prerequisites without starting Cadence or creating directories."""
    editor = cadence_root.expanduser().resolve() / "tools" / "bin" / "allegro.exe"
    runtime = runtime_directory.expanduser().resolve()
    issues: list[str] = []
    if sys.version_info < (3, 12):
        issues.append("Python 3.12 or newer is required; leave legacy Python intact.")
    if sys.platform != "win32":
        issues.append("The initial live adapter supports Windows only.")
    if not editor.is_file():
        issues.append(f"PCB Editor executable not found: {editor}")
    if not str(runtime).isascii():
        issues.append(
            "The Cadence runtime directory must be ASCII-safe; choose --runtime-dir. "
            "The repository itself may have a Unicode path."
        )
    if runtime.exists() and not runtime.is_dir():
        issues.append(f"Runtime directory is an existing non-directory: {runtime}")
    return EnvironmentReport(
        python_executable=sys.executable,
        python_version=".".join(str(part) for part in sys.version_info[:3]),
        platform=sys.platform,
        editor_executable=str(editor),
        runtime_directory=str(runtime),
        issues=tuple(issues),
    )

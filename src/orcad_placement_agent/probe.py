"""Stage a trusted, one-shot read-only SKILL probe for manual loading."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import tempfile

from .diagnostics import ConfigurationError


@dataclass(frozen=True)
class ProbeStage:
    session_directory: str
    bootstrap_file: str
    startup_script: str
    report_file: str
    load_command: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def stage_probe(runtime_directory: Path, skill_directory: Path) -> ProbeStage:
    runtime = runtime_directory.expanduser().resolve()
    if not str(runtime).isascii():
        raise ConfigurationError("The probe staging directory must be ASCII-safe.")
    source = skill_directory.expanduser().resolve() / "probe.il"
    if not source.is_file():
        raise ConfigurationError(f"Trusted probe source not found: {source}")
    runtime.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="probe-", dir=runtime))
    staged_source = session / "probe.il"
    shutil.copyfile(source, staged_source)
    bootstrap = session / "bootstrap.il"
    script = session / "probe.scr"
    report = session / "probe-report.txt"
    # Only trusted bootstrap configuration is generated, not an evaluated request.
    bootstrap.write_text(
        f"opaProbeOutput = {json.dumps(str(report))}\n"
        f"load({json.dumps(str(staged_source))})\n",
        encoding="ascii",
    )
    load_command = f"skill load({json.dumps(str(bootstrap))})"
    script.write_text(
        f"setwindow pcb\n{load_command}\nopa_probe\n", encoding="ascii"
    )
    return ProbeStage(
        session_directory=str(session),
        bootstrap_file=str(bootstrap),
        startup_script=str(script),
        report_file=str(report),
        load_command=load_command,
    )

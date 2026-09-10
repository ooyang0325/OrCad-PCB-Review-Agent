"""Read-only environment discovery and trusted probe staging."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .diagnostics import (
    ConfigurationError,
    DEFAULT_CADENCE_ROOT,
    default_runtime_directory,
    inspect_environment,
)
from .probe import stage_probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orcad-placement-agent",
        description="Local, human-approved access to classic PCB Editor 25.1.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser(
        "doctor", help="Inspect prerequisites without starting or modifying Cadence."
    )
    doctor.add_argument("--cadence-root", type=Path, default=DEFAULT_CADENCE_ROOT)
    doctor.add_argument("--runtime-dir", type=Path)
    doctor.add_argument("--json", action="store_true")
    probe = commands.add_parser("stage-probe", help="Stage a trusted read-only SKILL probe.")
    probe.add_argument("--runtime-dir", type=Path)
    probe.add_argument("--skill-dir", type=Path, default=Path("skill"))
    probe.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        runtime = args.runtime_dir if args.runtime_dir is not None else default_runtime_directory()
        if args.command == "stage-probe":
            staged = stage_probe(runtime, args.skill_dir)
            if args.json:
                print(json.dumps(staged.to_dict(), indent=2))
            else:
                print("Probe staged; no editor connection has been established.")
                print(f"In the dedicated PCB Editor: {staged.load_command}")
                print("Then run: opa_probe")
                print(f"Report: {staged.report_file}")
            return 0
        report = inspect_environment(args.cadence_root, runtime)
    except (ConfigurationError, OSError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Python: {report.python_executable} ({report.python_version})")
        print(f"PCB Editor: {report.editor_executable}")
        print(f"Runtime directory: {report.runtime_directory}")
        for issue in report.issues:
            print(f"ERROR: {issue}")
        print("Live editor, license, and SKILL access remain unproven.")
    return 0 if report.ready else 1

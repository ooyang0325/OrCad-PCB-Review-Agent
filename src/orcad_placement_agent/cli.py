"""Explicit, human-approved control of one dedicated PCB Editor session."""

import argparse
import json
from pathlib import Path
import sys
import uuid

from . import __version__
from .diagnostics import (
    ConfigurationError,
    DEFAULT_CADENCE_ROOT,
    default_runtime_directory,
    inspect_environment,
)
from .probe import stage_probe
from .protocol import ProtocolError, Request
from .proposals import approve_and_apply, load_proposal, propose, proposal_summary
from .session import Session, SessionError, stage_session
from .transport import IndeterminateDelivery, TransportError, WindowsAPI


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
    doctor.add_argument("--json", action="store_true", help="Print structured diagnostics.")
    probe = commands.add_parser(
        "stage-probe",
        help="Stage a trusted read-only SKILL probe without starting Cadence.",
    )
    probe.add_argument("--runtime-dir", type=Path)
    probe.add_argument("--skill-dir", type=Path, default=Path("skill"))
    probe.add_argument("--json", action="store_true")
    commands.add_parser("editors", help="List visible classic editor identities; do not select one.")
    stage = commands.add_parser("stage", help="Copy a source board and trusted adapter into a fresh session.")
    stage.add_argument("source", type=Path)
    stage.add_argument("--runtime-dir", type=Path)
    stage.add_argument("--skill-dir", type=Path, default=Path("skill"))
    attach = commands.add_parser("attach", help="Bind the staged copy to an explicit editor through a read-only handshake.")
    attach.add_argument("--session", type=Path, required=True)
    attach.add_argument("--hwnd", type=lambda value: int(value, 0), required=True)
    for command, help_text in [
        ("snapshot", "Read fresh board state."),
        ("reconcile", "Read a late receipt without replaying the request."),
        ("propose", "Prepare and review an exact single-component pose."),
        ("apply", "Ask for exact proposal approval, then apply in memory."),
        ("save", "Ask before saving the current fixture to a new revision."),
    ]:
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("--session", type=Path, required=True)
        if command == "propose":
            sub.add_argument("--refdes", required=True)
            sub.add_argument("--x", required=True, help="Absolute X in millimeters.")
            sub.add_argument("--y", required=True, help="Absolute Y in millimeters.")
            sub.add_argument("--angle", required=True, help="Absolute degrees: 0, 90, 180, 270.")
        if command == "apply":
            sub.add_argument("--proposal", required=True, help="The full SHA256 proposal identifier.")
    args = parser.parse_args(argv)

    try:
        if args.command == "editors":
            from dataclasses import asdict

            print(json.dumps([asdict(item) for item in WindowsAPI().windows()], indent=2))
            return 0
        if args.command in {"attach", "snapshot", "reconcile", "propose", "apply", "save"}:
            return _session_command(args)
        runtime = (
            args.runtime_dir
            if args.runtime_dir is not None
            else default_runtime_directory()
        )
        if args.command == "stage":
            root = stage_session(args.source, runtime, args.skill_dir)
            bootstrap = json.dumps(str(root / "bootstrap.il"))
            print(f"Session: {root}")
            print(f"Open only this copy in the dedicated editor: {root / 'working.brd'}")
            print(f"Load the trusted adapter: skill load({bootstrap})")
            print("Then run editors and attach with the explicit HWND and --session path.")
            return 0
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
    except IndeterminateDelivery as error:
        print(f"INDETERMINATE: {error}", file=sys.stderr)
        return 3
    except (ConfigurationError, SessionError, ProtocolError, TransportError, OSError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except EOFError:
        print("Approval cancelled: no confirmation was supplied.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Reconcile any pending operation before continuing.", file=sys.stderr)
        return 130

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Python: {report.python_executable} ({report.python_version})")
        print(f"PCB Editor: {report.editor_executable}")
        print(f"Runtime directory: {report.runtime_directory}")
        for issue in report.issues:
            print(f"ERROR: {issue}")
        if report.ready:
            print("Environment prerequisites found.")
        print("Live editor, license, and SKILL access remain unproven.")
    return 0 if report.ready else 1


def _session_command(args: argparse.Namespace) -> int:
    session = Session(args.session)
    if args.command == "attach":
        receipt = session.bind(WindowsAPI().inspect(args.hwnd))
    elif args.command == "reconcile":
        receipt = session.reconcile()
    elif args.command == "apply":
        proposal = load_proposal(session, args.proposal)
        print(proposal_summary(proposal))
        print(f"Working copy: {session.working}")
        confirmation = input(f"Type APPLY {args.proposal} to authorize exactly this change: ")
        receipt = approve_and_apply(session, args.proposal, confirmation)
    else:
        receipt = session.exchange(Request(session.nonce, uuid.uuid4().hex, "snapshot"))
        if receipt.status == "snapshot" and args.command == "propose":
            digest, proposal = propose(
                session, receipt, args.refdes, args.x, args.y, args.angle
            )
            print(proposal_summary(proposal))
            print(f"Proposal: {digest}")
            print("Not applied. Apply requires approval and fresh native preconditions.")
            return 0
        if receipt.status == "snapshot" and args.command == "save":
            snapshot_id = receipt.one("snapshot")[1]
            filename = f"revision-{uuid.uuid4().hex}.brd"
            print(f"Save current state of {session.working} to {session.root / filename}")
            if input(f"Type SAVE {snapshot_id} to save this revision: ") != f"SAVE {snapshot_id}":
                raise SessionError("Save was not approved; no save request was sent.")
            receipt = session.exchange(Request(
                session.nonce, uuid.uuid4().hex, "save", snapshot_id, destination=filename
            ))
    print(json.dumps(receipt.to_dict(), indent=2))
    return 0 if receipt.status in {"snapshot", "applied", "saved"} else 1

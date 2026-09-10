"""Explicit, human-approved control of one dedicated PCB Editor session."""

import argparse
import json
from pathlib import Path
import sqlite3
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
from . import knowledge
from .advisory import TOPIC_QUERIES, build_context
from .resources import asset_directory
from .installation import CLIENTS, write_configurations


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
    probe.add_argument("--skill-dir", type=Path, help="Explicit trusted source override; packaged assets are the default.")
    probe.add_argument("--json", action="store_true")
    commands.add_parser("editors", help="List visible classic editor identities; do not select one.")
    stage = commands.add_parser("stage", help="Copy a source board and trusted adapter into a fresh session.")
    stage.add_argument("source", type=Path)
    stage.add_argument("--runtime-dir", type=Path)
    stage.add_argument("--skill-dir", type=Path, help="Explicit trusted source override; packaged assets are the default.")
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
    references = commands.add_parser(
        "knowledge", help="Index and search local PCB reference PDFs; no network or board access."
    )
    reference_commands = references.add_subparsers(dest="knowledge_command", required=True)
    for operation in ("index", "catalog", "search", "page"):
        sub = reference_commands.add_parser(operation)
        sub.add_argument("--database", type=Path, default=knowledge.DEFAULT_DATABASE)
        sub.add_argument("--json", action="store_true")
        if operation == "index":
            sub.add_argument("--books", type=Path, default=knowledge.DEFAULT_BOOKS)
            sub.add_argument("--rebuild", action="store_true", help="Re-extract all PDFs, including unchanged metadata.")
        elif operation == "search":
            sub.add_argument("query")
            sub.add_argument("--limit", type=int, default=5)
        elif operation == "page":
            sub.add_argument("source", help="Exact source name returned by search/catalog.")
            sub.add_argument("--page", type=int, required=True, dest="page_number")
            sub.add_argument("--offset", type=int, default=0)
            sub.add_argument("--characters", type=int, default=1500)
    context = commands.add_parser(
        "agent-context", help="Prepare a local evidence packet for read-only PCB expert agents."
    )
    context.add_argument("--goal", required=True)
    context.add_argument("--database", type=Path, default=knowledge.DEFAULT_DATABASE)
    context.add_argument("--topic", action="append", choices=tuple(TOPIC_QUERIES))
    context.add_argument("--snapshot", type=Path, help="Optional saved snapshot receipt JSON; never a .brd.")
    context.add_argument("--visual", type=Path, help="Optional visual observation metadata; links its PNG and matching snapshot.")
    context.add_argument("--output-directory", type=Path, default=Path(".runtime") / "advisory")
    context.add_argument("--json", action="store_true")
    install_config = commands.add_parser(
        "integration-config", help="Generate client MCP snippets without editing client settings."
    )
    install_config.add_argument("--client", choices=(*CLIENTS, "all"), default="all")
    install_config.add_argument("--output-directory", type=Path, required=True)
    install_config.add_argument("--knowledge-db", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "integration-config":
            paths = write_configurations(
                args.output_directory,
                clients=CLIENTS if args.client == "all" else (args.client,),
                knowledge_database=args.knowledge_db,
            )
            print(json.dumps({
                "generated": [str(path) for path in paths],
                "client_settings_modified": False,
                "instruction": "Merge only the named server entry into your client settings, or use its MCP add command.",
            }, indent=2))
            return 0
        if args.command == "agent-context":
            path, context = build_context(
                args.goal, args.database,
                topics=tuple(args.topic) if args.topic else ("placement", "decoupling", "return-paths"),
                snapshot=args.snapshot, visual=args.visual, output_directory=args.output_directory,
            )
            if args.json:
                print(json.dumps({
                    "path": str(path), "evidence_candidates": len(context["evidence"]),
                    "authority": context["authority"],
                }, indent=2))
            else:
                cwd = Path.cwd().resolve()
                display_path = path.relative_to(cwd) if path.is_relative_to(cwd) else path
                print(f"Advisory context: {display_path}")
                print(f"Evidence candidates: {len(context['evidence'])}; no board or model operation was performed.")
                print("Use pcb-placement-orchestrator for a staged mission, or the planner/reviewer for a focused review.")
            return 0
        if args.command == "knowledge":
            return _knowledge_command(args)
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
            root = stage_session(
                args.source, runtime, args.skill_dir if args.skill_dir is not None else asset_directory("skill")
            )
            bootstrap = json.dumps(str(root / "bootstrap.il"))
            print(f"Session: {root}")
            print(f"Open only this copy in the dedicated editor: {root / 'working.brd'}")
            print(f"Load the trusted adapter: skill load({bootstrap})")
            print("Then run editors and attach with the explicit HWND and --session path.")
            return 0
        if args.command == "stage-probe":
            staged = stage_probe(
                runtime, args.skill_dir if args.skill_dir is not None else asset_directory("skill")
            )
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
    except (ConfigurationError, SessionError, ProtocolError, TransportError,
            knowledge.KnowledgeError, sqlite3.Error, OSError, json.JSONDecodeError) as error:
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


def _knowledge_command(args: argparse.Namespace) -> int:
    if args.knowledge_command == "index":
        result = knowledge.index_books(args.books, args.database, rebuild=args.rebuild)
    elif args.knowledge_command == "catalog":
        result = {"documents": knowledge.catalog(args.database)}
    elif args.knowledge_command == "search":
        result = knowledge.search(args.query, args.database, limit=args.limit)
    else:
        result = knowledge.page(
            args.source, args.page_number, args.database,
            offset=args.offset, characters=args.characters,
        )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    elif "documents" in result:
        if args.knowledge_command == "index":
            print(f"Updated {result['updated']}; unchanged {result['unchanged']}; removed {result['removed']}.")
        for item in result["documents"]:
            print(
                f"{item['source']}: {item['indexed_pages']}/{item['pdf_pages']} pages; "
                f"{item['status']}; fresh={item['fresh']}; {len(item['notices'])} notice(s)"
            )
        print("No OCR is performed. Use --json to inspect per-document/page notices.")
    elif "hits" in result:
        print(f"Match mode: {result['match_mode']}")
        for hit in result["hits"]:
            print(f"\n{hit['citation']}\n{hit['excerpt']}")
        if not result["hits"]:
            print("No matching indexed evidence was found.")
    else:
        print(f"{result['citation']}\n{result['text']}")
        if result["truncated"]:
            print(f"[Excerpt at offset {result['offset']}; {result['total_characters']} characters on page.]")
    return 0

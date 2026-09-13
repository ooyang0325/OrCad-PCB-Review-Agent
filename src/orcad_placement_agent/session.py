"""Local request lifecycle with durable uncertainty and no blind replay."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Callable
import uuid

from .protocol import (
    MAX_BYTES, MAX_METADATA_BYTES, ProtocolError, Receipt, Request, identifier,
)
from .transport import (
    CommandTransport, EditorWindow, IndeterminateDelivery, TransportError,
)
from .design_copy import (
    COPY_DIRECTORY, MANIFEST_NAME, DesignCopyError, copy_board, copy_design, copy_summary,
    input_digest, plan_copy, read_manifest, relative_path, resolve_input,
)


class SessionError(RuntimeError):
    """The dedicated session is missing, busy, stale, or indeterminate."""


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_new(path: Path, content: bytes) -> None:
    """Publish a new immutable file; never replace a prior request or result."""
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    try:
        # Same-filesystem hard link publishes without overwriting an existing name.
        os.link(temporary, path)
    finally:
        temporary.unlink()


def write_json(path: Path, value: dict[str, object]) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(content) > MAX_METADATA_BYTES:
        raise SessionError("Local metadata exceeds the 8 MiB persistence limit.")
    write_new(path, content)


def stage_session(
    source: Path, runtime: Path, skill: Path, *, model: str = "fixture",
    design_root: Path | None = None, board_only: bool = False, allow_unverified_3d: bool = False,
) -> Path:
    if model not in {"fixture", "managed-board-v1"}:
        raise SessionError("Choose the fixture or managed-board-v1 native model.")
    if board_only and design_root is not None:
        raise SessionError("--board-only and --design-root cannot be combined.")
    if type(allow_unverified_3d) is not bool or (allow_unverified_3d and (model != "managed-board-v1" or board_only)):
        raise SessionError("Unverified embedded 3D data requires explicit full-design managed-board staging.")
    try:
        source = resolve_input(source)
    except (DesignCopyError, OSError) as error:
        raise SessionError(str(error)) from error
    runtime = runtime.expanduser().resolve()
    if source.suffix.lower() != ".brd" or not source.is_file():
        raise SessionError("An existing source .brd is required.")
    if not str(runtime).isascii():
        raise SessionError("The Cadence staging directory must be ASCII-safe.")
    names = ("adapter.il", "protocol.il", "placement.il")
    if model == "managed-board-v1":
        names += ("managed_board.il", "library_setup.il")
    for name in names:
        if not (skill / name).is_file():
            raise SessionError(f"Trusted adapter source is unavailable: {name}")
    plan = None
    if not board_only:
        try:
            plan = plan_copy(source, runtime, design_root)
        except (DesignCopyError, OSError) as error:
            raise SessionError(str(error)) from error
    source_size = source.stat().st_size
    try:
        digest = input_digest(source, source_size)
    except (DesignCopyError, OSError) as error:
        raise SessionError(str(error)) from error
    runtime.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="board-", dir=runtime))
    working = root / "working.brd"
    manifest = None
    try:
        if plan is not None:
            manifest = copy_design(plan, root)
            preserved_board = root / COPY_DIRECTORY / relative_path(manifest["board_relative"])
            copy_board(preserved_board, working, digest)
        else:
            copy_board(source, working, digest)
        if input_digest(source, source_size) != digest:
            raise DesignCopyError("Source changed during copying; staging is not valid.")
    except (DesignCopyError, OSError) as error:
        raise SessionError(
            f"Design staging failed; no session was published. Partial artifacts: {root}. {error}"
        ) from error
    for name in names:
        shutil.copyfile(skill / name, root / name)
    nonce = uuid.uuid4().hex
    bootstrap = (
        f"opaRoot = {json.dumps(str(root))}\n"
        f"opaNonce = {json.dumps(nonce)}\n"
        f"opaBoardPath = {json.dumps(str(working))}\n"
        f"opaBoardModel = {json.dumps(model)}\n"
        f"opaUnverified3DNonce = {json.dumps(nonce if allow_unverified_3d else '')}\n"
        f"load({json.dumps(str(root / 'protocol.il'))})\n"
        f"load({json.dumps(str(root / 'placement.il'))})\n"
    )
    if model == "managed-board-v1":
        bootstrap += f"load({json.dumps(str(root / 'managed_board.il'))})\n"
        bootstrap += f"load({json.dumps(str(root / 'library_setup.il'))})\n"
    bootstrap += f"load({json.dumps(str(root / 'adapter.il'))})\n"
    write_new(root / "bootstrap.il", bootstrap.encode("ascii"))
    metadata = {
        "schema_version": 1, "nonce": nonce, "source": str(source),
        "source_sha256": digest, "working": str(working),
    }
    if model == "managed-board-v1":
        metadata.update({"schema_version": 2, "model": model})
    if manifest is not None:
        write_json(root / MANIFEST_NAME, manifest)
        metadata.update({"schema_version": 3, "model": model,
                         "design_copy_sha256": file_digest(root / MANIFEST_NAME)})
    if allow_unverified_3d:
        metadata.update({"schema_version": 4, "allow_unverified_3d": True})
    write_json(root / "session.json", metadata)
    return root


class Session:
    def __init__(
        self, root: Path, transport: CommandTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = root.expanduser().resolve(strict=True)
        if not str(self.root).isascii():
            raise SessionError("Session directory must be ASCII-safe.")
        metadata = self._read_json("session.json")
        fields = {"schema_version", "nonce", "source", "source_sha256", "working"}
        version = metadata.get("schema_version")
        opted_3d = type(version) is int and version == 4
        bundled = type(version) is int and version in {3, 4}
        managed = metadata.get("schema_version") == 2 and metadata.get("model") == "managed-board-v1"
        extra = {"model", "design_copy_sha256"} if bundled else {"model"} if managed else set()
        if opted_3d:
            extra |= {"allow_unverified_3d"}
        if (
            set(metadata) != fields | extra or type(version) is not int
            or (not bundled and not managed and version != 1)
            or (bundled and (not isinstance(metadata["model"], str)
                             or metadata["model"] not in {"fixture", "managed-board-v1"}))
            or (opted_3d and (metadata.get("allow_unverified_3d") is not True or metadata["model"] != "managed-board-v1"))
            or not all(isinstance(metadata[key], str) for key in
                       ("nonce", "source", "source_sha256", "working"))
        ):
            raise SessionError("Unsupported session metadata.")
        self.model = metadata["model"] if bundled else "managed-board-v1" if managed else "fixture"
        self.allow_unverified_3d = opted_3d
        self.nonce = identifier(metadata["nonce"])
        self.source = Path(metadata["source"]).resolve(strict=True)
        self.source_digest = metadata["source_sha256"]
        if re.fullmatch(r"[0-9a-f]{64}", self.source_digest) is None:
            raise SessionError("Invalid preserved source fingerprint.")
        self.working = Path(metadata["working"]).resolve(strict=True)
        if self.working != self.root / "working.brd" or self.source == self.working:
            raise SessionError("Session source/working-copy boundary is invalid.")
        self.design_copy = None
        if bundled:
            try:
                self.design_copy = read_manifest(self.root, metadata["design_copy_sha256"])
                origin = Path(self.design_copy["source_root"]) / relative_path(self.design_copy["board_relative"])
                selected = next(item for item in self.design_copy["files"]
                                if item["path"] == self.design_copy["board_relative"])
                if origin != self.source or selected["sha256"] != self.source_digest:
                    raise DesignCopyError("The copied project does not match the preserved source board.")
            except (DesignCopyError, StopIteration) as error:
                raise SessionError(str(error) or "The staged board is missing from its manifest.") from error
        self.transport = transport if transport is not None else CommandTransport()
        self.clock = clock
        self.sleep = sleep

    def design_summary(self) -> dict[str, object] | None:
        return copy_summary(self.root, self.design_copy) if self.design_copy is not None else None

    def _read_json(self, name: str) -> dict[str, object]:
        path = self.root / name
        if path.stat().st_size > MAX_METADATA_BYTES:
            raise SessionError(f"Oversized local metadata: {name}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SessionError(f"Invalid local metadata: {name}")
        return value

    def verify_source(self) -> None:
        if file_digest(self.source) != self.source_digest:
            raise SessionError("The preserved source changed; stop and stage a new copy.")

    def editor(self) -> EditorWindow:
        value = self._read_json("editor.json")
        if set(value) != {"hwnd", "pid", "started", "executable", "title"}:
            raise SessionError("Invalid editor binding.")
        if any(type(value[key]) is not int or value[key] <= 0
               for key in ("hwnd", "pid", "started")):
            raise SessionError("Invalid editor process identity.")
        if not all(isinstance(value[key], str) for key in ("executable", "title")):
            raise SessionError("Invalid editor executable/title.")
        return EditorWindow(**value)

    def bind(self, editor: EditorWindow, timeout: float = 30.0, *, library_setup: bool = False) -> Receipt:
        if (self.root / "editor.json").exists():
            raise SessionError("This session is already bound; stage a fresh session to retarget.")
        if library_setup and (self.model != "managed-board-v1" or self.design_copy is None):
            raise SessionError("Library setup needs a managed-board session with a complete staged design copy.")
        operation = "library_snapshot" if library_setup else "snapshot"
        receipt = self.exchange(Request(self.nonce, uuid.uuid4().hex, operation), editor, timeout)
        if receipt.status != "snapshot":
            raise SessionError(f"Adapter refused the handshake: {receipt.message}")
        observed = Path(receipt.one("board")[1]).resolve()
        if observed != self.working:
            raise SessionError("Handshake returned a different board; binding was refused.")
        if library_setup:
            from .library_load import setup_inventory

            setup_inventory(receipt)
        elif self.model == "managed-board-v1":
            from .board import from_receipt

            from_receipt(receipt)
        elif any(row[0] == "model" for row in receipt.records):
            raise SessionError("Native board model does not match the staged session.")
        write_json(self.root / "editor.json", asdict(editor))
        return receipt

    def exchange(
        self, request: Request, editor: EditorWindow | None = None,
        timeout: float = 30.0,
    ) -> Receipt:
        if not 0 < timeout <= 60:
            raise SessionError("Receipt timeout must be greater than 0 and at most 60 seconds.")
        if request.nonce != self.nonce:
            raise SessionError("Request nonce does not match this session.")
        payload = request.encode()
        self.verify_source()
        selected = editor if editor is not None else self.editor()
        lock = self.root / ".inflight"
        try:
            lock.mkdir()
        except FileExistsError as error:
            raise SessionError("Session is busy or has an abandoned in-flight lock.") from error
        try:
            if (self.root / "pending.json").exists():
                raise SessionError("An operation is unresolved; reconcile before sending another.")
            if request.operation in {"apply", "save", "load_libraries"}:
                for path in self.root.glob("library-approval-*.json"):
                    digest = path.name.removeprefix("library-approval-").removesuffix(".json")
                    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                        raise SessionError("Malformed library approval state blocks writes.")
                    approval = self._read_json(path.name)
                    if (set(approval) != {"proposal", "request_id", "confirmation"}
                            or approval.get("proposal") != digest or approval.get("confirmation") != f"LOAD {digest}"):
                        raise SessionError("Invalid library approval state blocks writes.")
                    if request.operation == "load_libraries" and approval.get("request_id") == request.request_id:
                        continue
                    verified_path = self.root / f"library-verified-{digest}.json"
                    if not verified_path.is_file():
                        raise SessionError("A library load lost asset-lock continuity; inspect its status and stage a fresh copy before writes.")
                    from .library_load import library_status

                    if library_status(self, digest)["status"] not in {"libraries_loaded", "library_partial", "rejected"}:
                        raise SessionError("Invalid library completion state blocks writes.")
            write_new(self.root / f"{request.request_id}.request.csv", payload)
            write_json(self.root / "pending.json", {
                "request_id": request.request_id, "operation": request.operation,
            })
            deadline = self.clock() + timeout
            try:
                self.transport.send(
                    selected, f"opa_{request.operation}", request.request_id,
                    timeout_ms=max(1, int(timeout * 1000)),
                )
            except IndeterminateDelivery:
                raise
            except TransportError:
                # The transport rejected before dispatch; there is no queued move.
                (self.root / "pending.json").unlink()
                raise
            result = self.root / f"{request.request_id}.result.csv"
            while not result.exists():
                if self.clock() >= deadline:
                    raise IndeterminateDelivery(
                        "No matching receipt arrived. State is unresolved; do not replay."
                    )
                self.sleep(0.05)
            return self._finish(request.request_id, request.operation)
        finally:
            lock.rmdir()

    def _finish(self, request_id: str, operation: str) -> Receipt:
        result = self.root / f"{request_id}.result.csv"
        if result.stat().st_size > MAX_BYTES:
            raise ProtocolError("Oversized adapter result.")
        receipt = Receipt.decode(result.read_bytes(), self.nonce, request_id)
        allowed = {
            "snapshot": {"snapshot", "rejected"},
            "library_snapshot": {"snapshot", "rejected"},
            "load_libraries": {"libraries_loaded", "library_partial", "rejected"},
            "apply": {"applied", "rejected", "rolled_back"},
            "save": {"saved", "rejected"},
        }
        if receipt.status == "indeterminate":
            if operation == "load_libraries":
                receipt_path = self.root / f"{request_id}.receipt.json"
                if not receipt_path.exists():
                    write_json(receipt_path, receipt.to_dict())
            raise IndeterminateDelivery(receipt.message)
        if receipt.status not in allowed[operation]:
            raise ProtocolError("Receipt status does not match the requested operation.")
        if receipt.records:
            receipt.unverified_3d_attachments
            opted = receipt.attachment_policy == "allow-unverified-embedded-3d-v1"
            if opted != self.allow_unverified_3d:
                raise ProtocolError("Native attachment-verification policy differs from the staged operator choice.")
        receipt_path = self.root / f"{request_id}.receipt.json"
        if not receipt_path.exists():
            write_json(receipt_path, receipt.to_dict())
        self.verify_source()
        (self.root / "pending.json").unlink()
        return receipt

    def reconcile(
        self, *, expected_request_id: str | None = None,
        expected_operation: str | None = None,
    ) -> Receipt:
        """Read only a late terminal receipt. Never replay or assume rollback."""
        lock = self.root / ".inflight"
        try:
            lock.mkdir()
        except FileExistsError as error:
            raise SessionError("The session is still in use; do not reconcile concurrently.") from error
        try:
            pending = self._read_json("pending.json")
            if set(pending) != {"request_id", "operation"}:
                raise SessionError("Invalid unresolved-operation metadata.")
            request_id = identifier(pending["request_id"])
            if pending["operation"] not in {"snapshot", "apply", "save", "library_snapshot", "load_libraries"}:
                raise SessionError("Invalid unresolved operation.")
            if expected_request_id is not None and request_id != expected_request_id:
                raise SessionError("A different request is pending; nothing was reconciled.")
            if expected_operation is not None and pending["operation"] != expected_operation:
                raise SessionError("The pending operation changed; nothing was reconciled.")
            if not (self.root / f"{request_id}.result.csv").exists():
                raise IndeterminateDelivery(
                    "No terminal receipt is available. Inspect the dedicated board "
                    "before abandoning this session; no request was resent."
                )
            return self._finish(request_id, pending["operation"])
        finally:
            lock.rmdir()

"""Local request lifecycle with durable uncertainty and no blind replay."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Callable
import uuid

from .protocol import (
    MAX_BYTES, ProtocolError, Receipt, Request, identifier,
)
from .transport import (
    CommandTransport, EditorWindow, IndeterminateDelivery, TransportError,
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
    write_new(
        path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    )


def stage_session(source: Path, runtime: Path, skill: Path) -> Path:
    source = source.expanduser().resolve(strict=True)
    runtime = runtime.expanduser().resolve()
    if source.suffix.lower() != ".brd" or not source.is_file():
        raise SessionError("An existing source .brd is required.")
    if not str(runtime).isascii():
        raise SessionError("The Cadence staging directory must be ASCII-safe.")
    names = ("adapter.il", "protocol.il", "placement.il")
    for name in names:
        if not (skill / name).is_file():
            raise SessionError(f"Trusted adapter source is unavailable: {name}")
    digest = file_digest(source)
    runtime.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="board-", dir=runtime))
    working = root / "working.brd"
    shutil.copyfile(source, working)
    if file_digest(working) != digest or file_digest(source) != digest:
        raise SessionError("Source changed during copying; staging is not valid.")
    for name in names:
        shutil.copyfile(skill / name, root / name)
    nonce = uuid.uuid4().hex
    bootstrap = (
        f"opaRoot = {json.dumps(str(root))}\n"
        f"opaNonce = {json.dumps(nonce)}\n"
        f"opaBoardPath = {json.dumps(str(working))}\n"
        f"load({json.dumps(str(root / 'protocol.il'))})\n"
        f"load({json.dumps(str(root / 'placement.il'))})\n"
        f"load({json.dumps(str(root / 'adapter.il'))})\n"
    )
    write_new(root / "bootstrap.il", bootstrap.encode("ascii"))
    write_json(root / "session.json", {
        "schema_version": 1, "nonce": nonce, "source": str(source),
        "source_sha256": digest, "working": str(working),
    })
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
        if (
            set(metadata) != {"schema_version", "nonce", "source", "source_sha256", "working"}
            or metadata["schema_version"] != 1
            or not all(isinstance(metadata[key], str) for key in
                       ("nonce", "source", "source_sha256", "working"))
        ):
            raise SessionError("Unsupported session metadata.")
        self.nonce = identifier(metadata["nonce"])
        self.source = Path(metadata["source"]).resolve(strict=True)
        self.source_digest = metadata["source_sha256"]
        self.working = Path(metadata["working"]).resolve(strict=True)
        if self.working != self.root / "working.brd" or self.source == self.working:
            raise SessionError("Session source/working-copy boundary is invalid.")
        self.transport = transport if transport is not None else CommandTransport()
        self.clock = clock
        self.sleep = sleep

    def _read_json(self, name: str) -> dict[str, object]:
        path = self.root / name
        if path.stat().st_size > MAX_BYTES:
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

    def bind(self, editor: EditorWindow, timeout: float = 10.0) -> Receipt:
        if (self.root / "editor.json").exists():
            raise SessionError("This session is already bound; stage a fresh session to retarget.")
        receipt = self.exchange(Request(self.nonce, uuid.uuid4().hex, "snapshot"), editor, timeout)
        if receipt.status != "snapshot":
            raise SessionError(f"Adapter refused the handshake: {receipt.message}")
        observed = Path(receipt.one("board")[1]).resolve()
        if observed != self.working:
            raise SessionError("Handshake returned a different board; binding was refused.")
        write_json(self.root / "editor.json", asdict(editor))
        return receipt

    def exchange(
        self, request: Request, editor: EditorWindow | None = None,
        timeout: float = 10.0,
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
            write_new(self.root / f"{request.request_id}.request.csv", payload)
            write_json(self.root / "pending.json", {
                "request_id": request.request_id, "operation": request.operation,
            })
            try:
                self.transport.send(
                    selected, f"opa_{request.operation}", request.request_id,
                    timeout_ms=min(5000, max(1, int(timeout * 1000))),
                )
            except IndeterminateDelivery:
                raise
            except TransportError:
                # The transport rejected before dispatch; there is no queued move.
                (self.root / "pending.json").unlink()
                raise
            deadline = self.clock() + timeout
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
            "apply": {"applied", "rejected", "rolled_back"},
            "save": {"saved", "rejected"},
        }
        if receipt.status == "indeterminate":
            raise IndeterminateDelivery(receipt.message)
        if receipt.status not in allowed[operation]:
            raise ProtocolError("Receipt status does not match the requested operation.")
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
            if pending["operation"] not in {"snapshot", "apply", "save"}:
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

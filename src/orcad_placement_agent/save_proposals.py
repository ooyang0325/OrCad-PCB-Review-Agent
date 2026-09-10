"""Exact, separate, single-use approval for saving a managed board revision."""

from pathlib import Path
import re
import uuid

from .protocol import ProtocolError, Receipt, Request, canonical_digest, identifier
from .proposals import check_snapshot
from .session import Session, SessionError, write_json


def prepare_save(session: Session, snapshot: Receipt) -> tuple[str, dict[str, object]]:
    check_snapshot(snapshot)
    if snapshot.nonce != session.nonce:
        raise ProtocolError("Save snapshot belongs to another session.")
    value = {
        "schema_version": 1, "operation": "save", "nonce": session.nonce,
        "snapshot_id": snapshot.one("snapshot")[1], "scene_digest": snapshot.scene_digest,
        "snapshot": snapshot.to_dict(), "destination": f"revision-{uuid.uuid4().hex}.brd",
    }
    digest = canonical_digest(value)
    write_json(session.root / f"save-proposal-{digest}.json", value)
    return digest, value


def load_save(session: Session, digest: str) -> dict[str, object]:
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ProtocolError("Expected the exact save proposal identifier.")
    value = session._read_json(f"save-proposal-{digest}.json")
    if set(value) != {
        "schema_version", "operation", "nonce", "snapshot_id", "scene_digest", "snapshot", "destination",
    } or canonical_digest(value) != digest:
        raise ProtocolError("Save proposal changed or has an unsupported schema.")
    if value["schema_version"] != 1 or value["operation"] != "save" or value["nonce"] != session.nonce:
        raise ProtocolError("Save proposal belongs to another session or operation.")
    identifier(value["snapshot_id"])
    snapshot = Receipt.from_dict(value["snapshot"])
    check_snapshot(snapshot)
    if (snapshot.nonce != session.nonce or snapshot.one("snapshot")[1] != value["snapshot_id"]
            or snapshot.scene_digest != value["scene_digest"]):
        raise ProtocolError("Save proposal lacks its exact reviewed scene.")
    if not isinstance(value["destination"], str) or re.fullmatch(r"revision-[0-9a-f]{32}\.brd", value["destination"]) is None:
        raise ProtocolError("Save destination must be a managed new-revision filename.")
    return value


def approve_save(session: Session, digest: str, confirmation: str) -> Receipt:
    value = load_save(session, digest)
    if confirmation != f"SAVE {digest}":
        raise SessionError("Exact save approval was not supplied; no Save was sent.")
    if (session.root / value["destination"]).exists():
        raise SessionError("The new revision already exists; nothing was overwritten.")
    request_id = uuid.uuid4().hex
    write_json(session.root / f"save-approval-{digest}.json", {
        "proposal": digest, "request_id": request_id, "confirmation": confirmation,
    })
    return session.exchange(Request(session.nonce, request_id, "save", value["snapshot_id"],
                                    destination=value["destination"]))


def save_status(session: Session, digest: str) -> dict[str, object]:
    value = load_save(session, digest)
    path = session.root / f"save-approval-{digest}.json"
    if not path.is_file():
        return {"status": "not_dispatched", "message": "This revision has no consumed save approval."}
    approval = session._read_json(path.name)
    if (set(approval) != {"proposal", "request_id", "confirmation"}
            or approval["proposal"] != digest or approval["confirmation"] != f"SAVE {digest}"):
        raise ProtocolError("Save approval record does not match the proposal.")
    request_id = identifier(approval["request_id"])
    receipt_path = session.root / f"{request_id}.receipt.json"
    if receipt_path.is_file():
        receipt = Receipt.from_dict(session._read_json(receipt_path.name))
    elif (session.root / "pending.json").is_file():
        receipt = session.reconcile(expected_request_id=request_id, expected_operation="save")
    else:
        return {"status": "indeterminate", "message": "Save approval was consumed but no terminal receipt is recorded. Do not resend."}
    if receipt.nonce != session.nonce or receipt.request_id != request_id:
        raise ProtocolError("Save receipt belongs to another operation.")
    result = {"status": receipt.status, "receipt": receipt.to_dict(), "reopened": False}
    if receipt.status == "saved":
        destination = session.root / value["destination"]
        result["destination"] = str(destination)
        result["artifact_available"] = destination.is_file()
        if Path(receipt.one("saved")[1]).resolve() != destination.resolve():
            raise ProtocolError("Native Save returned a different revision path; do not retry.")
        result["message"] = "Native Save reported a separate revision. Reopen verification has not been performed."
    return result

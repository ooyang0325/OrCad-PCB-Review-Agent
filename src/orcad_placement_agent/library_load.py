"""Exact approved loading from verified staged files; no placement or implicit save."""

from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import uuid

from .design_copy import (
    COPY_DIRECTORY, DesignCopyError, _bounded_hash, _pinned_path, relative_path,
)
from .protocol import (
    ProtocolError, Receipt, Request, canonical_digest, encode_rows, identifier, number,
)
from .session import Session, SessionError, write_json, write_new
from .transport import IndeterminateDelivery


MODEL = "library-setup-v1"
MAX_ASSETS = 512
MAX_ASSET_BYTES = 64 * 1024 * 1024
PACKAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}")
EXTENSIONS = {".psm", ".pad", ".fsm", ".ssm"}
ROOT_SUFFIXES = EXTENSIONS | {".bsm", ".osm", ".dra"}


def _package_name(value: object) -> str:
    if (not isinstance(value, str) or PACKAGE_NAME.fullmatch(value) is None
            or value.endswith(".") or Path(value).suffix.casefold() in ROOT_SUFFIXES):
        raise ProtocolError("Unsupported package-library root name.")
    relative_path(value + ".psm")
    return value


def setup_inventory(receipt: Receipt) -> dict[str, object]:
    if receipt.status != "snapshot":
        raise ProtocolError("A fresh library-setup snapshot is required, not a placement snapshot.")
    identifier(receipt.one("snapshot")[1])
    return _inventory(receipt)


def _inventory(receipt: Receipt) -> dict[str, object]:
    if receipt.one("model") != ("model", MODEL):
        raise ProtocolError("Library inventory must use the setup-only native model.")
    if receipt.one("units") != ("units", "millimeters", "4", "10000"):
        raise ProtocolError("Library setup requires the supported millimeter database.")
    if not receipt.scene.startswith("OPA-BOARD-1;"):
        raise ProtocolError("Library setup lacks its complete native scene.")
    components, definitions, pads, pins = {}, set(), set(), set()
    for row in receipt.records:
        if row[0] == "component":
            if len(row) != 9 or row[1] in components or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", row[1]) is None:
                raise ProtocolError("Library setup inventory has invalid component references.")
            if (row[6] != "0" or row[7] not in {"0", "1"} or row[8] != "0"
                    or any(number(value) != 0 for value in row[3:6])):
                raise ProtocolError("Library preparation requires all logical components unplaced.")
            components[row[1]] = _package_name(row[2])
        elif row[0] == "definition":
            if len(row) != 3 or row[1] not in {"PACKAGE", "FLASH", "SHAPE", "MECHANICAL", "FORMAT"}:
                raise ProtocolError("Unsupported native definition inventory.")
            key = (row[1], row[2].casefold())
            if not row[2] or key in definitions:
                raise ProtocolError("Duplicate or missing native definition name.")
            definitions.add(key)
        elif row[0] == "padstack":
            if len(row) != 2 or not row[1] or row[1].casefold() in pads:
                raise ProtocolError("Invalid native padstack inventory.")
            pads.add(row[1].casefold())
        elif row[0] == "logical-pin":
            if len(row) != 4 or not row[2] or (row[1], row[2]) in pins:
                raise ProtocolError("Invalid logical pin inventory.")
            pins.add((row[1], row[2]))
    if not 1 <= len(components) <= 256 or any(ref not in components for ref, _ in pins):
        raise ProtocolError("Library setup requires a complete nonempty logical inventory.")
    if any(not any(ref == name for ref, _ in pins) for name in components):
        raise ProtocolError("A logical component lacks pin associations.")
    package_names = {}
    for value in components.values():
        package_names.setdefault(value.casefold(), value)
    packages = [package_names[key] for key in sorted(package_names)]
    missing = [name for name in packages if ("PACKAGE", name.casefold()) not in definitions]
    return {"components": components, "required_packages": packages, "missing_packages": missing,
            "existing_definitions": sorted(definitions), "existing_padstacks": sorted(pads),
            "unverified_3d_attachments": receipt.unverified_3d_attachments}


def _asset_path(session: Session, entry: dict) -> Path:
    path = session.root / COPY_DIRECTORY / relative_path(entry["path"])
    if not path.is_relative_to(session.root / COPY_DIRECTORY):
        raise ProtocolError("Library asset left the staged design tree.")
    return path


def select_assets(session: Session, missing: list[str]) -> list[dict]:
    if session.design_copy is None:
        raise SessionError("Library loading requires complete design staging, not a board-only session.")
    candidates = {}
    for entry in session.design_copy["files"]:
        relative = relative_path(entry["path"])
        if relative.suffix.casefold() in EXTENSIONS:
            candidates.setdefault(relative.name.casefold(), []).append(entry)
    selected = {}
    for package in missing:
        filename = _package_name(package).casefold() + ".psm"
        if filename not in candidates:
            raise SessionError(f"Required package file is absent from the staged project: {filename}")
        selected[filename] = candidates[filename]
    for filename, entries in candidates.items():
        if Path(filename).suffix != ".psm":
            selected[filename] = entries
    if not 1 <= len(selected) <= MAX_ASSETS:
        raise SessionError("Library bundle exceeds the bounded asset count.")
    result, total = [], 0
    for filename, entries in sorted(selected.items()):
        if not filename.isascii():
            raise SessionError(f"Native library loading requires ASCII library filenames: {filename!r}")
        identities = {(entry["size"], entry["sha256"]) for entry in entries}
        if len(identities) != 1:
            raise SessionError(f"Conflicting staged library definitions: {filename}. Select an unambiguous project tree.")
        entry = min(entries, key=lambda item: item["path"])
        total += entry["size"]
        if total > MAX_ASSET_BYTES:
            raise SessionError("Library bundle exceeds 64 MiB.")
        result.append({**entry, "filename": filename})
    return result


def prepare_libraries(session: Session, snapshot: Receipt) -> tuple[str, dict]:
    inventory = setup_inventory(snapshot)
    if snapshot.nonce != session.nonce or Path(snapshot.one("board")[1]).resolve() != session.working:
        raise ProtocolError("Library snapshot belongs to another staged board.")
    missing = inventory["missing_packages"]
    if not missing:
        raise SessionError("All required package definitions are already embedded; no load is needed.")
    assets = select_assets(session, missing)
    cache_id = uuid.uuid4().hex
    cache = session.root / f"library-{cache_id}"
    cache.mkdir()
    try:
        for entry in assets:
            source = _asset_path(session, entry)
            with _pinned_path(source):
                if source.stat().st_size != entry["size"]:
                    raise SessionError(f"Staged library changed: {entry['path']}")
                with source.open("rb") as stream:
                    if _bounded_hash(stream, entry["size"]) != entry["sha256"]:
                        raise SessionError(f"Staged library changed: {entry['path']}")
                    stream.seek(0)
                    payload = stream.read(entry["size"] + 1)
                    if len(payload) != entry["size"]:
                        raise SessionError("Staged library changed during cache preparation.")
                    write_new(cache / entry["filename"], payload)
    except (DesignCopyError, OSError) as error:
        raise SessionError(f"Library preparation failed; no native load was sent. {error}") from error
    control = encode_rows([
        ("OPA_LIBRARIES", "1", session.nonce, cache_id, snapshot.one("snapshot")[1]),
        *(("package", name) for name in missing), ("end", cache_id),
    ])
    write_new(session.root / f"library-{cache_id}.csv", control)
    value = {
        "schema_version": 1, "operation": "load-libraries", "nonce": session.nonce,
        "snapshot_id": snapshot.one("snapshot")[1], "scene_digest": snapshot.scene_digest,
        "snapshot": snapshot.to_dict(), "cache_id": cache_id, "packages": missing,
        "assets": assets, "control_sha256": canonical_digest({"text": control.decode("ascii")}),
        "source_manifest": session._read_json("session.json")["design_copy_sha256"],
    }
    digest = canonical_digest(value)
    write_json(session.root / f"library-proposal-{digest}.json", value)
    return digest, value


def load_library_proposal(session: Session, digest: str) -> dict:
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ProtocolError("Expected the exact library proposal identifier.")
    value = session._read_json(f"library-proposal-{digest}.json")
    if set(value) != {
        "schema_version", "operation", "nonce", "snapshot_id", "scene_digest", "snapshot",
        "cache_id", "packages", "assets", "control_sha256", "source_manifest",
    } or canonical_digest(value) != digest:
        raise ProtocolError("Library proposal changed or has an unsupported schema.")
    if value["schema_version"] != 1 or value["operation"] != "load-libraries" or value["nonce"] != session.nonce:
        raise ProtocolError("Library proposal belongs to another operation or session.")
    identifier(value["cache_id"])
    snapshot = Receipt.from_dict(value["snapshot"])
    inventory = setup_inventory(snapshot)
    if (snapshot.nonce != session.nonce or snapshot.one("snapshot")[1] != value["snapshot_id"]
            or snapshot.scene_digest != value["scene_digest"]
            or inventory["missing_packages"] != value["packages"]
            or select_assets(session, value["packages"]) != value["assets"]
            or session._read_json("session.json").get("design_copy_sha256") != value["source_manifest"]):
        raise ProtocolError("Library proposal no longer matches the reviewed inventory or staged assets.")
    return value


@contextmanager
def _unchanged_cache(cache: Path):
    if os.name != "nt":
        raise SessionError("Native library loading requires Windows cache-change monitoring.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
    kernel.FindFirstChangeNotificationW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
    kernel.FindCloseChangeNotification.restype = wintypes.BOOL
    # File handles protect existing bytes, but a directory handle permits new
    # children. A latched notification also detects add-then-remove races.
    handle = kernel.FindFirstChangeNotificationW(str(cache), True, 0x11F)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise SessionError(f"Cannot monitor the approved library cache: Windows error {ctypes.get_last_error()}.")

    def check():
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 0:
            raise SessionError("Library cache changed during its protected interval; do not replay LOAD or continue writes.")
        if result != 0x102:
            raise SessionError(f"Library cache monitoring failed: Windows error {ctypes.get_last_error()}.")

    try:
        yield check
        check()
    finally:
        if not kernel.FindCloseChangeNotification(handle):
            raise SessionError(f"Cannot close library cache monitoring: Windows error {ctypes.get_last_error()}.")


@contextmanager
def pinned_library_bundle(session: Session, proposal: dict):
    cache = session.root / f"library-{proposal['cache_id']}"
    control = session.root / f"library-{proposal['cache_id']}.csv"
    with ExitStack() as stack:
        stack.enter_context(_pinned_path(cache))
        check_cache = stack.enter_context(_unchanged_cache(cache))
        stack.enter_context(_pinned_path(control))
        with control.open("rb") as stream:
            content = stream.read(65537)
        try:
            text = content.decode("ascii")
        except UnicodeDecodeError as error:
            raise ProtocolError("Library control file is no longer ASCII.") from error
        if len(content) > 65536 or canonical_digest({"text": text}) != proposal["control_sha256"]:
            raise ProtocolError("Library control file changed after preparation.")
        expected = {entry["filename"] for entry in proposal["assets"]}
        if {path.name for path in cache.iterdir()} != expected:
            raise ProtocolError("Library bundle inventory changed after preparation.")
        for entry in proposal["assets"]:
            source = _asset_path(session, entry)
            cached = cache / entry["filename"]
            for path in (source, cached):
                stack.enter_context(_pinned_path(path))
                if path.stat().st_size != entry["size"]:
                    raise ProtocolError("Library asset size changed after preparation.")
                with path.open("rb") as stream:
                    if _bounded_hash(stream, entry["size"]) != entry["sha256"]:
                        raise ProtocolError("Library asset changed after preparation.")
        check_cache()
        yield


def approve_libraries(session: Session, digest: str, confirmation: str) -> Receipt:
    proposal = load_library_proposal(session, digest)
    if confirmation != f"LOAD {digest}":
        raise SessionError("Exact library-load approval was not supplied; nothing was sent.")
    with pinned_library_bundle(session, proposal):
        request_id = uuid.uuid4().hex
        write_json(session.root / f"library-approval-{digest}.json",
                   {"proposal": digest, "request_id": request_id, "confirmation": confirmation})
        receipt = session.exchange(Request(session.nonce, request_id, "load_libraries",
                                           proposal["snapshot_id"], destination=f"library-{proposal['cache_id']}.csv"),
                                   timeout=60)
        _validate_outcome(session, proposal, request_id, receipt)
    write_json(session.root / f"library-verified-{digest}.json", {
        "proposal": digest, "request_id": request_id,
        "status": receipt.status, "receipt_digest": canonical_digest(receipt.to_dict()),
        "asset_locks_held_through_native_outcome": True,
    })
    return receipt


def _validate_outcome(session: Session, proposal: dict, request: str, receipt: Receipt) -> None:
    if (receipt.nonce != session.nonce or receipt.request_id != request
            or receipt.status not in {"libraries_loaded", "library_partial", "rejected"}):
        raise ProtocolError("Receipt is not the exact terminal library-load outcome.")
    loaded, missing = [], []
    for row in receipt.records:
        if row[0] in {"library-loaded", "library-missing"}:
            if len(row) != 2:
                raise ProtocolError("Malformed library outcome inventory.")
            (loaded if row[0] == "library-loaded" else missing).append(row[1])
    if receipt.status == "rejected":
        if loaded:
            raise ProtocolError("Rejected library load reports loaded packages; state is uncertain.")
        return
    requested = set(proposal["packages"])
    if (len(loaded) != len(set(loaded)) or len(missing) != len(set(missing))
            or set(loaded) & set(missing) or set(loaded) | set(missing) != requested
            or (receipt.status == "libraries_loaded") != (not missing)):
        raise ProtocolError("Library outcome does not account for exactly the approved package set.")
    inventory = _inventory(receipt)
    before = setup_inventory(Receipt.from_dict(proposal["snapshot"]))
    if (Path(receipt.one("board")[1]).resolve() != session.working
            or inventory["components"] != before["components"]
            or inventory["unverified_3d_attachments"] != before["unverified_3d_attachments"]
            or receipt.attachment_policy != Receipt.from_dict(proposal["snapshot"]).attachment_policy
            or set(inventory["missing_packages"]) != set(missing)):
        raise ProtocolError("Library outcome disagrees with the actual native package inventory.")


def library_status(session: Session, digest: str) -> dict:
    proposal = load_library_proposal(session, digest)
    path = session.root / f"library-approval-{digest}.json"
    if not path.is_file():
        return {"status": "not_dispatched", "message": "This library plan has no consumed approval."}
    approval = session._read_json(path.name)
    if (set(approval) != {"proposal", "request_id", "confirmation"}
            or approval.get("proposal") != digest or approval.get("confirmation") != f"LOAD {digest}"):
        raise ProtocolError("Library approval does not match its proposal.")
    request = identifier(approval.get("request_id"))
    receipt_path = session.root / f"{request}.receipt.json"
    if receipt_path.is_file():
        receipt = Receipt.from_dict(session._read_json(receipt_path.name))
    elif (session.root / "pending.json").is_file():
        try:
            receipt = session.reconcile(expected_request_id=request, expected_operation="load_libraries")
        except IndeterminateDelivery:
            if not receipt_path.is_file():
                raise
            receipt = Receipt.from_dict(session._read_json(receipt_path.name))
            if receipt.status != "indeterminate":
                raise
    else:
        return {"status": "indeterminate", "message": "Approval was consumed without a terminal outcome. Do not resend."}
    if receipt.nonce != session.nonce or receipt.request_id != request:
        raise ProtocolError("Receipt belongs to a different library-load request.")
    if receipt.status == "indeterminate":
        return {
            "status": "indeterminate", "native_status": receipt.status, "receipt": receipt.to_dict(),
            "requires_restaging": True, "placement_ready": False, "saved": False,
            "message": "Native library preservation was not established. This approval cannot be replayed; writes remain blocked.",
        }
    verified_path = session.root / f"library-verified-{digest}.json"
    if not verified_path.is_file():
        return {
            "status": "indeterminate", "native_status": receipt.status, "receipt": receipt.to_dict(),
            "requires_restaging": True,
            "message": "Native outcome arrived without continuous asset-lock confirmation. Do not replay or continue writes; stage a fresh copy.",
        }
    verified = session._read_json(verified_path.name)
    if (set(verified) != {"proposal", "request_id", "status", "receipt_digest", "asset_locks_held_through_native_outcome"}
            or verified.get("proposal") != digest or verified.get("request_id") != request
            or verified.get("status") != receipt.status
            or verified.get("receipt_digest") != canonical_digest(receipt.to_dict())
            or verified.get("asset_locks_held_through_native_outcome") is not True):
        raise ProtocolError("Library completion does not match its verified asset lifetime.")
    _validate_outcome(session, proposal, request, receipt)
    result = {"status": receipt.status, "receipt": receipt.to_dict(), "cache_id": proposal["cache_id"],
              "placement_ready": False, "saved": False,
              "message": "Recorded library outcome only. Run full board inspection before placement; no command was replayed."}
    if (session.root / "pending.json").is_file():
        pending = session._read_json("pending.json")
        if pending.get("operation") in {"snapshot", "library_snapshot"}:
            result["pending_inspection"] = identifier(pending.get("request_id"))
    return result

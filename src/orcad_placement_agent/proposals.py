"""Exact, inspectable proposals and one-use approval records."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
import re
import uuid

from .protocol import (
    ProtocolError, Receipt, Request, canonical_digest, decimal_text, identifier, number,
)
from .session import Session, SessionError, write_json


@dataclass(frozen=True)
class Component:
    refdes: str
    package: str
    x: Decimal
    y: Decimal
    angle: Decimal
    mirrored: bool
    fixed: bool
    placed: bool

    @classmethod
    def from_record(cls, record: tuple[str, ...]) -> "Component":
        if len(record) != 9 or record[0] != "component":
            raise ProtocolError("Invalid component record.")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", record[1]) is None:
            raise ProtocolError("Unsupported reference designator.")
        if any(value not in ("0", "1") for value in record[6:9]):
            raise ProtocolError("Invalid component state flags.")
        return cls(
            record[1], record[2], *(number(value) for value in record[3:6]),
            *(value == "1" for value in record[6:9]),
        )


def check_snapshot(receipt: Receipt) -> dict[str, Component]:
    if receipt.status != "snapshot":
        raise ProtocolError("A successful read-only snapshot is required.")
    identifier(receipt.one("snapshot")[1])
    receipt.one("board")
    receipt.one("version")
    receipt.one("scene")
    units = receipt.one("units")
    if units[1] != "millimeters" or number(units[3]) <= 0:
        raise ProtocolError("The initial fixture requires known millimeter/DBU units.")
    if not units[2].isdigit() or not 0 <= int(units[2]) <= 9:
        raise ProtocolError("Invalid board accuracy.")
    components: dict[str, Component] = {}
    for row in receipt.records:
        if row[0] == "component":
            item = Component.from_record(row)
            if item.refdes in components:
                raise ProtocolError("Duplicate reference designators in snapshot.")
            components[item.refdes] = item
    if not components:
        raise ProtocolError("No components in snapshot.")
    return components


def propose(
    session: Session, snapshot: Receipt, refdes: str, x: str, y: str, angle: str,
) -> tuple[str, dict[str, object]]:
    components = check_snapshot(snapshot)
    if snapshot.nonce != session.nonce:
        raise ProtocolError("Snapshot belongs to a different session.")
    if refdes not in components:
        raise ProtocolError("Target component is missing.")
    component = components[refdes]
    if component.fixed or not component.placed or component.mirrored:
        raise ProtocolError("Only already-placed, unfixed, top-side components are supported.")
    scale = number(snapshot.one("units")[3])
    target_x = (number(x) * scale).to_integral_value(rounding=ROUND_HALF_UP) / scale
    target_y = (number(y) * scale).to_integral_value(rounding=ROUND_HALF_UP) / scale
    target_angle = number(angle)
    if target_angle not in (0, 90, 180, 270):
        raise ProtocolError("The initial fixture supports only 0/90/180/270 degree targets.")
    if (target_x, target_y, target_angle) == (component.x, component.y, component.angle):
        raise ProtocolError("Proposal is a no-op.")
    proposal: dict[str, object] = {
        "schema_version": 1,
        "nonce": session.nonce,
        "snapshot_id": snapshot.one("snapshot")[1],
        "scene_digest": snapshot.scene_digest,
        "snapshot": snapshot.to_dict(),
        "refdes": refdes,
        "x": decimal_text(target_x),
        "y": decimal_text(target_y),
        "angle": decimal_text(target_angle),
        "units": "millimeters",
        "pivot": "component-origin",
    }
    digest = canonical_digest(proposal)
    path = session.root / f"proposal-{digest}.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != proposal:
            raise SessionError("Existing proposal content does not match its identity.")
    else:
        write_json(path, proposal)
    return digest, proposal


def load_proposal(session: Session, digest: str) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ProtocolError("Expected a SHA256 proposal identifier.")
    proposal = session._read_json(f"proposal-{digest}.json")
    expected = {
        "schema_version", "nonce", "snapshot_id", "scene_digest", "snapshot",
        "refdes", "x", "y", "angle", "units", "pivot",
    }
    if set(proposal) != expected or canonical_digest(proposal) != digest:
        raise ProtocolError("The proposal was altered or has an unsupported schema.")
    if (
        proposal["schema_version"] != 1 or proposal["nonce"] != session.nonce
        or proposal["units"] != "millimeters" or proposal["pivot"] != "component-origin"
    ):
        raise ProtocolError("The proposal belongs to another session or operation.")
    identifier(proposal["snapshot_id"])
    for key in ("x", "y", "angle"):
        number(proposal[key])
    if number(proposal["angle"]) not in (0, 90, 180, 270):
        raise ProtocolError("Unsupported target rotation.")
    return proposal


def proposal_summary(proposal: dict[str, object]) -> str:
    snapshot = proposal["snapshot"]
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("records"), list):
        raise ProtocolError("Proposal lacks its reviewed snapshot.")
    components = [
        Component.from_record(tuple(row))
        for row in snapshot["records"]
        if row[0] == "component" and row[1] == proposal["refdes"]
    ]
    if len(components) != 1:
        raise ProtocolError("Reviewed component is missing or ambiguous.")
    before = components[0]
    return (
        f"{before.refdes}: ({before.x}, {before.y}) mm, {before.angle} degrees -> "
        f"({proposal['x']}, {proposal['y']}) mm, {proposal['angle']} degrees; "
        "pivot: component origin; top side unchanged; memory only."
    )


def approve_and_apply(session: Session, digest: str, confirmation: str) -> Receipt:
    proposal = load_proposal(session, digest)
    if confirmation != f"APPLY {digest}":
        raise SessionError("Exact proposal approval was not provided; nothing was sent.")
    request_id = uuid.uuid4().hex
    write_json(session.root / f"approval-{digest}.json", {
        "proposal_sha256": digest, "request_id": request_id, "confirmation": confirmation,
    })
    # Creating the approval record consumes this proposal even if delivery becomes
    # uncertain. A second invocation cannot replay the same approved mutation.
    request = Request(
        session.nonce, request_id, "apply", proposal["snapshot_id"],
        proposal["refdes"], proposal["x"], proposal["y"], proposal["angle"],
    )
    return session.exchange(request)

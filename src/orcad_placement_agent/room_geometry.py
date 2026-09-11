"""Resolve explicit ROOM tags against preserved native room labels, not group names."""

from decimal import Decimal

from .protocol import ProtocolError


def resolve_rooms(board: dict) -> tuple[dict, list[dict], list[str]]:
    policy = board.get("design_policy")
    if policy is None:
        return {}, [], []
    labels = {}
    for assignment in policy["room_assignments"]:
        labels.setdefault(assignment["refdes"], set()).add(assignment["label"])
    rooms = {}
    for room in policy["rooms"]:
        rooms.setdefault(room["label"], []).append(room)
    bindings, blockers, unmapped = {}, [], set()
    for refdes, assigned in sorted(labels.items()):
        if len(assigned) != 1:
            blockers.append({"code": "conflicting_room_assignments", "refdes": refdes,
                             "message": "Component/function ROOM assignments disagree; no room mapping was guessed."})
            continue
        label = next(iter(assigned))
        matches = rooms.get(label, [])
        if not matches:
            unmapped.add(label)
        elif len(matches) != 1:
            blockers.append({"code": "ambiguous_room_geometry", "refdes": refdes,
                             "message": "Multiple native room drawings use this ROOM label."})
        else:
            bindings[refdes] = matches[0]
    return bindings, blockers, sorted(unmapped)


def inside_room(box: tuple[Decimal, ...], room: dict, clearance: Decimal = Decimal(0)) -> bool:
    x1, y1, x2, y2 = (Decimal(value) for value in room["bounds"])
    return (box[0] >= x1 + clearance and box[1] >= y1 + clearance
            and box[2] <= x2 - clearance and box[3] <= y2 - clearance)


def check_target_room(board: dict, refdes: str, box: tuple[Decimal, ...]) -> None:
    bindings, blockers, _ = resolve_rooms(board)
    if any(blocker["refdes"] == refdes for blocker in blockers):
        raise ProtocolError("Native ROOM assignment is ambiguous; resolve it before proposing a placement.")
    if refdes in bindings and not inside_room(box, bindings[refdes]):
        raise ProtocolError("Target footprint leaves its explicitly matched native placement room.")

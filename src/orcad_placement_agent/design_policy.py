"""Preserved native grouping facts, not placement permissions or executable policy.

Room drawings may be staging graphics outside the board. Labels, assignments
and Cset names are kept verbatim without inferring net roles or spatial rules.
The opaque native payload is fingerprinted only; it is never parsed or executed.
"""

import re

from .protocol import ProtocolError, Receipt, canonical_digest, decimal_text, field, number


MODEL = "grouped-constraints-v1"
MAX_ROOMS = 128
MAX_ASSIGNMENTS = 8192
MAX_NET_GROUPS = 128
MAX_MEMBERSHIPS = 4096
MAX_NETS = 4096
MAX_CSETS_PER_DOMAIN = 32
MAX_CHUNKS = 64
MAX_CHUNK_LENGTH = 8192
MAX_NATIVE_POLICY_LENGTH = 524288
DOMAINS = ("physical", "spacing", "sameNet")

_REFDES = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,30}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_UNSIGNED = re.compile(r"(?:0|[1-9][0-9]*)")
_FIELDS = {
    "policy-model": 2, "policy": 8, "policy-part": 3, "room": 7,
    "room-assignment": 4, "net-group": 5, "net-group-member": 3,
    "constraint-set": 3, "policy-net": 2,
}
_COUNTS = (
    ("policy-part", MAX_CHUNKS), ("room", MAX_ROOMS),
    ("room-assignment", MAX_ASSIGNMENTS), ("net-group", MAX_NET_GROUPS),
    ("net-group-member", MAX_MEMBERSHIPS),
    ("constraint-set", len(DOMAINS) * MAX_CSETS_PER_DOMAIN), ("policy-net", MAX_NETS),
)
_POLICY_KEYS = {
    "model", "digest", "rooms", "room_assignments", "net_groups", "constraint_sets", "nets",
}


def _object(value: object, keys: set[str], description: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProtocolError(f"Invalid {description} schema.")
    return value


def _items(value: object, maximum: int, description: str) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ProtocolError(f"{description} must be a list with at most {maximum} entries.")
    return value


def _text(value: object, description: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= 256:
        raise ProtocolError(f"Invalid bounded {description}.")
    return field(value)


def _names(value: object, maximum: int, description: str) -> list[str]:
    names = [_text(item, description) for item in _items(value, maximum, description)]
    if len(set(names)) != len(names):
        raise ProtocolError(f"Duplicate {description}.")
    return sorted(names)


def _rectangle(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) != 4:
        raise ProtocolError("Room bounds require four native decimal coordinates.")
    coordinates = [number(item) for item in value]
    if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ProtocolError("Room bounds must have positive area.")
    return [decimal_text(item) for item in coordinates]


def validate_policy(value: object, component_refs: set[str]) -> dict:
    """Return a fresh canonical facts dictionary; validate, but do not derive, its digest.

    Opaque native data is intentionally absent from this saved representation.
    Consequently this function cannot authenticate or reconstruct its fingerprint.
    """
    policy = _object(value, _POLICY_KEYS, "design policy")
    if policy["model"] != MODEL:
        raise ProtocolError("Unsupported design policy model.")
    digest = policy["digest"]
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ProtocolError("Design policy requires a lowercase SHA256 fingerprint.")
    if not isinstance(component_refs, set) or any(
        not isinstance(refdes, str) or _REFDES.fullmatch(refdes) is None
        for refdes in component_refs
    ):
        raise ProtocolError("Design policy requires valid native component references.")

    catalogs = _object(policy["constraint_sets"], set(DOMAINS), "constraint-set catalog")
    constraint_sets = {
        domain: _names(catalogs[domain], MAX_CSETS_PER_DOMAIN, f"{domain} constraint-set names")
        for domain in DOMAINS
    }
    if any("DEFAULT" not in names for names in constraint_sets.values()):
        raise ProtocolError("Every native constraint-set domain requires DEFAULT.")
    nets = _names(policy["nets"], MAX_NETS, "native net names")
    known_nets = set(nets)

    rooms = {}
    for item in _items(policy["rooms"], MAX_ROOMS, "rooms"):
        room = _object(item, {"name", "label", "bounds"}, "room")
        name = _text(room["name"], "room name")
        if name in rooms:
            raise ProtocolError("Duplicate native room name.")
        rooms[name] = {
            "name": name, "label": _text(room["label"], "room label"),
            "bounds": _rectangle(room["bounds"]),
        }

    assignments = {}
    for item in _items(policy["room_assignments"], MAX_ASSIGNMENTS, "room assignments"):
        assignment = _object(item, {"refdes", "owner", "label"}, "room assignment")
        refdes = assignment["refdes"]
        if (not isinstance(refdes, str) or _REFDES.fullmatch(refdes) is None
                or refdes not in component_refs):
            raise ProtocolError("Room assignment references an invalid or unknown component.")
        owner = _text(assignment["owner"], "ROOM property owner", empty=True)
        key = (refdes, owner)
        if key in assignments:
            raise ProtocolError("Duplicate component/function ROOM assignment.")
        assignments[key] = {
            "refdes": refdes, "owner": owner,
            "label": _text(assignment["label"], "ROOM assignment label"),
        }

    groups = {}
    membership_count = 0
    for item in _items(policy["net_groups"], MAX_NET_GROUPS, "net groups"):
        group = _object(item, {"name", "physical", "spacing", "same_net", "nets"}, "net group")
        name = _text(group["name"], "net-group name")
        if name in groups:
            raise ProtocolError("Duplicate native net-group name.")
        normalized = {"name": name}
        for key, domain in (("physical", "physical"), ("spacing", "spacing"), ("same_net", "sameNet")):
            cset = _text(group[key], f"{domain} constraint-set reference", empty=True)
            if cset and cset not in constraint_sets[domain]:
                raise ProtocolError(f"Net group references an unknown {domain} constraint set.")
            normalized[key] = cset
        members = _names(group["nets"], MAX_MEMBERSHIPS, "net-group members")
        if not set(members) <= known_nets:
            raise ProtocolError("Net-group membership references an unknown native net.")
        membership_count += len(members)
        if membership_count > MAX_MEMBERSHIPS:
            raise ProtocolError("Native net-group memberships exceed the supported limit.")
        normalized["nets"] = members
        groups[name] = normalized

    return {
        "model": MODEL, "digest": digest,
        "rooms": [rooms[name] for name in sorted(rooms)],
        "room_assignments": [assignments[key] for key in sorted(assignments)],
        "net_groups": [groups[name] for name in sorted(groups)],
        "constraint_sets": constraint_sets, "nets": nets,
    }


def _count(value: str, maximum: int, description: str, *, minimum: int = 0) -> int:
    if (len(value) > len(str(maximum)) or _UNSIGNED.fullmatch(value) is None
            or not minimum <= int(value) <= maximum):
        raise ProtocolError(f"Invalid native {description} count.")
    return int(value)


def decode_policy(receipt: Receipt, component_refs: set[str]) -> dict | None:
    """Decode complete native policy records, or return None for a legacy receipt.

    The surrounding receipt protocol owns non-policy record schemas and total
    wire limits. This decoder also checks row shapes/types for synthetic receipts.
    """
    if not isinstance(receipt, Receipt) or not isinstance(receipt.records, (tuple, list)):
        raise ProtocolError("Design policy requires native receipt records.")
    records = {name: [] for name in _FIELDS}
    ordered = []
    for row in receipt.records:
        if not isinstance(row, (tuple, list)) or not 1 <= len(row) <= 16:
            raise ProtocolError("Malformed native receipt record.")
        for value in row:
            field(value)
        name = row[0]
        if name not in _FIELDS:
            if not name or name.startswith(("policy-", "room-", "net-group-", "constraint-set-")):
                raise ProtocolError("Unsupported native policy record.")
            continue
        if len(row) != _FIELDS[name]:
            raise ProtocolError(f"Invalid native {name} record length.")
        records[name].append(row)
        ordered.append(row)
    if not ordered:
        return None
    if (len(records["policy-model"]) != 1
            or records["policy-model"][0][1] != MODEL or len(records["policy"]) != 1):
        raise ProtocolError("Native policy requires exactly one supported model and count header.")
    header = records["policy"][0]
    counts = [
        _count(header[index + 1], maximum, name, minimum=1 if name == "policy-part" else 0)
        for index, (name, maximum) in enumerate(_COUNTS)
    ]
    if any(len(records[name]) != count for (name, _), count in zip(_COUNTS, counts)):
        raise ProtocolError("Native policy header counts do not match the complete records.")
    parts = records["policy-part"]
    if ([row[0] for row in ordered[:2 + counts[0]]]
            != ["policy-model", "policy", *(["policy-part"] * counts[0])]):
        raise ProtocolError("Native policy model, header and chunks must appear in order without gaps.")
    if any(row[1] != str(index) or not row[2] or len(row[2]) > MAX_CHUNK_LENGTH
           for index, row in enumerate(parts)):
        raise ProtocolError("Native policy chunks are missing, empty, duplicated or out of order.")
    native_policy = "".join(row[2] for row in parts)
    if not native_policy.startswith("OPA-BOARD-1;") or len(native_policy) > MAX_NATIVE_POLICY_LENGTH:
        raise ProtocolError("Native policy lacks a complete bounded protected payload.")

    constraint_sets = {domain: [] for domain in DOMAINS}
    for _, domain, name in records["constraint-set"]:
        if domain not in constraint_sets:
            raise ProtocolError("Unsupported native constraint-set domain.")
        constraint_sets[domain].append(name)
    groups = {}
    for _, name, physical, spacing, same_net in records["net-group"]:
        if name in groups:
            raise ProtocolError("Duplicate native net-group name.")
        groups[name] = {
            "name": name, "physical": physical, "spacing": spacing,
            "same_net": same_net, "nets": [],
        }
    for _, group, net in records["net-group-member"]:
        if group not in groups:
            raise ProtocolError("Native membership references an unknown net group.")
        groups[group]["nets"].append(net)

    return validate_policy({
        "model": MODEL, "digest": canonical_digest({"native_policy": native_policy}),
        "rooms": [{"name": row[1], "label": row[2], "bounds": list(row[3:])}
                  for row in records["room"]],
        "room_assignments": [{"refdes": row[1], "owner": row[2], "label": row[3]}
                             for row in records["room-assignment"]],
        "net_groups": list(groups.values()), "constraint_sets": constraint_sets,
        "nets": [row[1] for row in records["policy-net"]],
    }, component_refs)

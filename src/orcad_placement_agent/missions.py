"""Deterministic, bounded placement planning; no native calls or board writes.

API: ``plan_mission(board, requirements)`` returns a JSON-compatible mission.
``mission_status(fresh_board, mission)`` measures *readback*, not execution
receipts. ``next_candidate(fresh_board, mission)`` returns one absolute TOP pose,
a ``{"status": "blocked", ...}`` diagnosis, or None for placement coverage only.
None never means routed, DRC-clean, reviewed, or saved. The caller must obtain
fresh native snapshots and enforce native write/approval preconditions.

Requirements (unknown keys/types are errors; missing inventories are blockers):

* expected_refdes: required, nonempty unique list of logical reference names.
* excluded_refdes: optional unique DNP list, disjoint from expected_refdes.
  Native inventory must equal their union. Physically placed DNPs block planning.
* grid_mm: required positive plain-decimal string; origin lattice is (0, 0).
* clearance_mm: required nonnegative plain-decimal string. This is the operator's
  geometric AABB spacing, NOT a derived electrical/safety clearance. The spacing
  applies to the keepin boundary, keepouts, reservations, and other footprints.
  Exact spacing is allowed; at zero spacing, rectangle edges may touch but
  positive-area intersections may not. Rectangles must have positive area.
* anchors: optional list of {refdes, kind: "mechanical-interface", x, y, angle}.
  Orthogonal TOP poses must lie on the grid. Existing placed parts are never
  moved; an anchor for an existing part must match its native pose exactly.
* functional_groups: optional list of {name, refdes: [names], critical: bool}.
  Members must be expected parts and may belong to at most one group.
* critical_nets: optional unique list of exact native net names. No electrical
  role is inferred from a component name. Critical nets receive twice the HPWL
  weight; critical groups/nets are scheduled before ordinary groups/parts.
* reserved_regions: optional list of {name, kind: "routing" | "access",
  bounds: [x1, y1, x2, y2]}. These are hard placement exclusions.
* routing: optional {stackup: {signal_layers: [native layer names], evidence: str},
  budget: {evidence: str, max_total_hpwl_mm?: decimal,
  max_net_hpwl_mm?: {native_net: decimal}}}. Either subsection may be omitted;
  a budget needs at least one nonnegative limit. Limits constrain the complete
  plan's pin-based HPWL proxy, not real routed length. Evidence is operator-
  supplied, not verified. Missing pad/via/trace/reference-plane/DRC information
  is always reported, even if this proxy budget passes.
* limits: optional positive integer overrides for max_candidates (default
  200000, hard maximum 1000000), max_search_nodes (10000, maximum 100000), and
  max_seconds (10, maximum 30). Candidate accounting covers lattice generation
  and search scoring. A wall-clock guard fails closed; it is not a score/tie
  breaker. Search exhaustion is not proof of geometric impossibility.

The normalized managed-board-v1 schema is checked locally, including bounded
finite decimal strings, orthogonal local footprint/pin geometry, and native
identity. At most 256 components, 8192 total pins, and 128 exclusions of each
kind are accepted. Inputs are not mutated. Malformed input raises MissionError.
All existing placed poses (fixed or not) are protected. Expected unplaced fixed
parts and mirrored parts are explicitly unsupported. DNPs are never candidates.

The mission_id uses the existing canonical_digest over the entire mission,
including the normalized baseline, requirements, exact ordered targets and
evidence. identity_signature separately binds immutable native board, package,
pin/net, fixed/mirrored and constraint facts, excluding dynamic poses and snapshot
IDs. This is an integrity binding, not authentication or version control.
Only current placed parts at protected/planned poses count. A changed baseline
snapshot with a reused ID or scene digest is rejected. Stateless code cannot
authenticate native provenance or detect replay of an arbitrary older snapshot;
freshness/transaction/approval checks remain the parent's responsibility.

Search is first-feasible bounded depth-first search, not a global optimizer:
anchors, critical support groups/nets, groups, then area-descending parts, with
reference-name ties. Candidate ties use incremental weighted *pin* HPWL,
functional-group envelope span, occupied envelope span, y, x, then angle.
Local geometry is rotated about the actual component origin, not its center.
Routing screening/review/verification and persistence are separate from coverage.
Bundled guidance IDs below are guidance references, not physical PDF citations.
"""

from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import PureWindowsPath
import re
import time

from .protocol import ProtocolError, canonical_digest, number


MAX_COMPONENTS = 256
MAX_PINS = 8192
MAX_REGIONS = 128
ANGLES = ("0", "90", "180", "270")
REFDES = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,30}")
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
DEFAULT_LIMITS = {
    "max_candidates": 200000, "max_search_nodes": 10000, "max_seconds": 10,
}
HARD_LIMITS = {
    "max_candidates": 1000000, "max_search_nodes": 100000, "max_seconds": 30,
}
RULES = [
    "si-package-escape-readiness",
    "pm-review-routing-corridors-and-congestion",
    "pm-reconcile-inventory-footprints-and-variants",
]


class MissionError(ProtocolError):
    """Malformed or integrity-invalid mission input; no action is safe."""


def _object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or (
        value.keys() - set(required) - set(optional)
    ):
        raise MissionError("Missing or unsupported object fields.")
    return value


def _list(value, maximum, *, nonempty=False):
    if type(value) is not list or len(value) > maximum or (nonempty and not value):
        raise MissionError("Expected a bounded list with the required inventory.")
    return value


def _string(value, *, empty=False, maximum=256, pattern=None):
    if type(value) is not str or len(value) > maximum or (not value and not empty):
        raise MissionError("Expected a bounded string.")
    if any(ord(char) < 32 for char in value) or (
        pattern is not None and pattern.fullmatch(value) is None
    ):
        raise MissionError("Invalid string or identifier.")
    return value


def _decimal(value):
    _string(value, maximum=20)
    try:
        return number(value)
    except ProtocolError as error:
        raise MissionError(str(error)) from error


def _text(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _rectangle(value):
    _list(value, 4)
    if len(value) != 4:
        raise MissionError("Rectangles need four plain-decimal coordinates.")
    box = tuple(_decimal(item) for item in value)
    if box[0] >= box[2] or box[1] >= box[3]:
        raise MissionError("Rectangles must have positive area.")
    return [_text(item) for item in box]


def _names(value, *, refs=False, maximum=MAX_COMPONENTS, nonempty=False):
    result = [
        _string(item, pattern=REFDES if refs else None)
        for item in _list(value, maximum, nonempty=nonempty)
    ]
    if len(result) != len(set(result)):
        raise MissionError("Duplicate names are not allowed.")
    return sorted(result)


def _pose(value):
    x, y = _text(_decimal(value["x"])), _text(_decimal(value["y"]))
    if type(value["angle"]) is not str or value["angle"] not in ANGLES:
        raise MissionError("Only orthogonal string angles are supported.")
    return {"x": x, "y": y, "angle": value["angle"]}


def _board(value):
    _object(value, {
        "model", "board", "snapshot_id", "scene_digest", "outline", "keepin",
        "keepouts", "layers", "components",
    })
    if value["model"] != "managed-board-v1":
        raise MissionError("A managed-board-v1 native model is required.")
    path = _string(value["board"], maximum=4096)
    if not PureWindowsPath(path).is_absolute() or ".." in PureWindowsPath(path).parts:
        raise MissionError("An absolute native Windows board path is required.")
    layers = _list(value["layers"], 128, nonempty=True)
    _names(layers, maximum=128, nonempty=True)
    result = {
        "model": "managed-board-v1", "board": path,
        "snapshot_id": _string(value["snapshot_id"], pattern=HEX32),
        "scene_digest": _string(value["scene_digest"], pattern=HEX64),
        "outline": _rectangle(value["outline"]), "keepin": _rectangle(value["keepin"]),
        "keepouts": sorted(_rectangle(item) for item in _list(value["keepouts"], MAX_REGIONS)),
        "layers": list(layers),
    }
    if not _inside(_box(result["keepin"]), _box(result["outline"]), Decimal(0)):
        raise MissionError("Native keepin must lie inside the native outline.")
    components = []
    total_pins = 0
    for item in _list(value["components"], MAX_COMPONENTS):
        _object(item, {
            "refdes", "package", "x", "y", "angle", "placed", "fixed", "mirrored",
            "bounds", "pins",
        })
        for flag in ("placed", "fixed", "mirrored"):
            if type(item[flag]) is not bool:
                raise MissionError("Native component flags must be booleans.")
        part = {
            "refdes": _string(item["refdes"], pattern=REFDES),
            "package": _string(item["package"]), **_pose(item),
            "placed": item["placed"], "fixed": item["fixed"], "mirrored": item["mirrored"],
            "bounds": _rectangle(item["bounds"]), "pins": [],
        }
        for pin in _list(item["pins"], MAX_PINS):
            total_pins += 1
            if total_pins > MAX_PINS:
                raise MissionError("Native pin inventory exceeds the bound.")
            _object(pin, {"number", "net", "x", "y"})
            part["pins"].append({
                "number": _string(pin["number"]), "net": _string(pin["net"], empty=True),
                "x": _text(_decimal(pin["x"])), "y": _text(_decimal(pin["y"])),
            })
        part["pins"].sort(key=lambda pin: pin["number"])
        if len({pin["number"] for pin in part["pins"]}) != len(part["pins"]):
            raise MissionError("Duplicate native pin numbers.")
        components.append(part)
    components.sort(key=lambda part: part["refdes"])
    if len({part["refdes"] for part in components}) != len(components):
        raise MissionError("Duplicate native references.")
    result["components"] = components
    return result


def _requirements(value):
    _object(value, {"expected_refdes", "grid_mm", "clearance_mm"}, {
        "excluded_refdes", "anchors", "functional_groups", "critical_nets",
        "reserved_regions", "routing", "limits",
    })
    expected = _names(value["expected_refdes"], refs=True, nonempty=True)
    excluded = _names(value.get("excluded_refdes", []), refs=True)
    if set(expected) & set(excluded):
        raise MissionError("Expected and DNP inventories must be disjoint.")
    if len(expected) + len(excluded) > MAX_COMPONENTS:
        raise MissionError("Combined expected and DNP inventory exceeds the component bound.")
    grid, clearance = _decimal(value["grid_mm"]), _decimal(value["clearance_mm"])
    if grid <= 0 or clearance < 0:
        raise MissionError("Supply positive grid_mm and nonnegative clearance_mm.")
    result = {
        "expected_refdes": expected, "excluded_refdes": excluded,
        "grid_mm": _text(grid), "clearance_mm": _text(clearance),
        "anchors": [], "functional_groups": [], "reserved_regions": [],
        "critical_nets": _names(value.get("critical_nets", []), maximum=MAX_PINS),
        "routing": {}, "limits": dict(DEFAULT_LIMITS),
    }
    for anchor in _list(value.get("anchors", []), MAX_COMPONENTS):
        _object(anchor, {"refdes", "kind", "x", "y", "angle"})
        ref = _string(anchor["refdes"], pattern=REFDES)
        pose = _pose(anchor)
        if ref not in expected or anchor["kind"] != "mechanical-interface":
            raise MissionError("Anchors need expected references and a mechanical-interface kind.")
        if any(_decimal(pose[axis]) % grid for axis in ("x", "y")):
            raise MissionError("Anchor origins must lie on the operator's grid.")
        result["anchors"].append({"refdes": ref, "kind": "mechanical-interface", **pose})
    result["anchors"].sort(key=lambda item: item["refdes"])
    if len({item["refdes"] for item in result["anchors"]}) != len(result["anchors"]):
        raise MissionError("Duplicate anchor references.")
    grouped = set()
    for group in _list(value.get("functional_groups", []), MAX_COMPONENTS):
        _object(group, {"name", "refdes", "critical"})
        refs = _names(group["refdes"], refs=True, nonempty=True)
        if type(group["critical"]) is not bool or not set(refs) <= set(expected) or grouped & set(refs):
            raise MissionError("Functional groups need unique expected members and a boolean critical flag.")
        grouped.update(refs)
        result["functional_groups"].append({
            "name": _string(group["name"]), "refdes": refs, "critical": group["critical"],
        })
    result["functional_groups"].sort(key=lambda item: item["name"])
    for region in _list(value.get("reserved_regions", []), MAX_REGIONS):
        _object(region, {"name", "kind", "bounds"})
        if type(region["kind"]) is not str or region["kind"] not in ("routing", "access"):
            raise MissionError("Unsupported reserved-region kind.")
        result["reserved_regions"].append({
            "name": _string(region["name"]), "kind": region["kind"],
            "bounds": _rectangle(region["bounds"]),
        })
    result["reserved_regions"].sort(key=lambda item: item["name"])
    for key in ("functional_groups", "reserved_regions"):
        if len({item["name"] for item in result[key]}) != len(result[key]):
            raise MissionError("Duplicate group or region names.")
    routing = _object(value.get("routing", {}), set(), {"stackup", "budget"})
    if "stackup" in routing:
        stackup = _object(routing["stackup"], {"signal_layers", "evidence"})
        result["routing"]["stackup"] = {
            "signal_layers": list(_list(stackup["signal_layers"], 128, nonempty=True)),
            "evidence": _string(stackup["evidence"], maximum=4096),
        }
        _names(result["routing"]["stackup"]["signal_layers"], maximum=128, nonempty=True)
    if "budget" in routing:
        budget = _object(routing["budget"], {"evidence"}, {"max_total_hpwl_mm", "max_net_hpwl_mm"})
        normalized = {"evidence": _string(budget["evidence"], maximum=4096)}
        if "max_total_hpwl_mm" in budget:
            total = _decimal(budget["max_total_hpwl_mm"])
            if total < 0:
                raise MissionError("Routing proxy limits must be nonnegative.")
            normalized["max_total_hpwl_mm"] = _text(total)
        if "max_net_hpwl_mm" in budget:
            nets = budget["max_net_hpwl_mm"]
            if type(nets) is not dict or not nets or len(nets) > MAX_PINS:
                raise MissionError("Expected a bounded, nonempty per-net proxy budget.")
            limits = {}
            for net, limit in nets.items():
                _string(net)
                value_mm = _decimal(limit)
                if value_mm < 0:
                    raise MissionError("Routing proxy limits must be nonnegative.")
                limits[net] = _text(value_mm)
            normalized["max_net_hpwl_mm"] = dict(sorted(limits.items()))
        if len(normalized) == 1:
            raise MissionError("A routing budget needs at least one explicit proxy limit.")
        result["routing"]["budget"] = normalized
    limits = _object(value.get("limits", {}), set(), set(DEFAULT_LIMITS))
    for key, limit in limits.items():
        if type(limit) is not int or not 1 <= limit <= HARD_LIMITS[key]:
            raise MissionError("Search limits must be positive bounded integers.")
        result["limits"][key] = limit
    return result


def _box(values):
    return tuple(Decimal(value) for value in values)


def _inside(box, boundary, clearance):
    return (
        box[0] >= boundary[0] + clearance and box[1] >= boundary[1] + clearance
        and box[2] <= boundary[2] - clearance and box[3] <= boundary[3] - clearance
    )


def _collides(first, second, clearance):
    return not (
        first[2] + clearance <= second[0] or second[2] + clearance <= first[0]
        or first[3] + clearance <= second[1] or second[3] + clearance <= first[1]
    )


def _rotate(x, y, angle):
    return {"0": (x, y), "90": (-y, x), "180": (-x, -y), "270": (y, -x)}[angle]


def _bounds(part, pose):
    x1, y1, x2, y2 = _box(part["bounds"])
    corners = [_rotate(x, y, pose["angle"]) for x in (x1, x2) for y in (y1, y2)]
    x, y = Decimal(pose["x"]), Decimal(pose["y"])
    return (
        x + min(point[0] for point in corners), y + min(point[1] for point in corners),
        x + max(point[0] for point in corners), y + max(point[1] for point in corners),
    )


def _merge(first, second):
    if first is None:
        return second
    return (min(first[0], second[0]), min(first[1], second[1]),
            max(first[2], second[2]), max(first[3], second[3]))


def _span(box):
    return Decimal(0) if box is None else box[2] - box[0] + box[3] - box[1]


def _net_boxes(part, pose):
    boxes = {}
    for pin in part["pins"]:
        if pin["net"]:
            dx, dy = _rotate(Decimal(pin["x"]), Decimal(pin["y"]), pose["angle"])
            x, y = Decimal(pose["x"]) + dx, Decimal(pose["y"]) + dy
            boxes[pin["net"]] = _merge(boxes.get(pin["net"]), (x, y, x, y))
    return boxes


def _identity(board):
    return {
        **{key: board[key] for key in ("model", "board", "outline", "keepin", "keepouts", "layers")},
        "components": [
            {key: part[key] for key in ("refdes", "package", "fixed", "mirrored", "bounds", "pins")}
            for part in board["components"]
        ],
    }


def _diagnosis(code, message, **details):
    return {"code": code, "message": message, **details}


def _input_blockers(board, requirements):
    parts = {part["refdes"]: part for part in board["components"]}
    expected, excluded = set(requirements["expected_refdes"]), set(requirements["excluded_refdes"])
    blockers = []
    if set(parts) != expected | excluded:
        blockers.append(_diagnosis(
            "inventory_mismatch", "Native inventory must equal expected plus explicit DNP inventory.",
            missing_refdes=sorted((expected | excluded) - set(parts)),
            unexpected_refdes=sorted(set(parts) - expected - excluded),
        ))
    if "TOP" not in board["layers"]:
        blockers.append(_diagnosis("top_layer_missing", "Native stackup has no TOP placement layer."))
    nets = {pin["net"] for part in parts.values() if part["refdes"] in expected
            for pin in part["pins"] if pin["net"]}
    budget_nets = set(requirements["routing"].get("budget", {}).get("max_net_hpwl_mm", {}))
    unknown = (set(requirements["critical_nets"]) | budget_nets) - nets
    if unknown:
        blockers.append(_diagnosis("unknown_nets", "Requested nets are absent from expected native parts.",
                                   nets=sorted(unknown)))
    stackup = requirements["routing"].get("stackup", {})
    unknown_layers = set(stackup.get("signal_layers", [])) - set(board["layers"])
    if unknown_layers:
        blockers.append(_diagnosis("stackup_mismatch", "Declared signal layers are not native layers.",
                                   layers=sorted(unknown_layers)))
    for ref in sorted(parts):
        part = parts[ref]
        if ref in excluded and part["placed"]:
            blockers.append(_diagnosis("placed_dnp", "A DNP is physically placed; no automatic removal.", refdes=ref))
        if ref in expected and part["mirrored"]:
            blockers.append(_diagnosis("mirrored_unsupported", "Mirrored placement is unsupported.", refdes=ref))
        if ref in expected and part["fixed"] and not part["placed"]:
            blockers.append(_diagnosis("fixed_unplaced", "An unplaced fixed part cannot be placed.", refdes=ref))
    return blockers


def _geometry_blockers(board, requirements, poses):
    parts = {part["refdes"]: part for part in board["components"]}
    clearance = Decimal(requirements["clearance_mm"])
    boundary = _box(board["keepin"])
    exclusions = [("keepout", str(index), _box(box)) for index, box in enumerate(board["keepouts"])]
    exclusions += [(region["kind"], region["name"], _box(region["bounds"]))
                   for region in requirements["reserved_regions"]]
    boxes, blockers = {}, []
    omitted = 0

    def report(code, message, **details):
        nonlocal omitted
        if len(blockers) < 512:
            blockers.append(_diagnosis(code, message, **details))
        else:
            omitted += 1

    for ref, pose in sorted(poses.items()):
        if ref not in parts:
            continue
        box = _bounds(parts[ref], pose)
        boxes[ref] = box
        if not _inside(box, boundary, clearance):
            report("outside_keepin", "Footprint violates keepin spacing.", refdes=ref)
        for kind, name, obstacle in exclusions:
            if _collides(box, obstacle, clearance):
                report("reserved_collision", "Footprint violates an exclusion region.",
                       refdes=ref, region=name, kind=kind)
    refs = sorted(boxes)
    for index, ref in enumerate(refs):
        for other in refs[index + 1:]:
            if _collides(boxes[ref], boxes[other], clearance):
                report("footprint_collision", "Footprints violate operator spacing.",
                       refdes=ref, other_refdes=other)
    if omitted:
        blockers.append(_diagnosis("additional_geometry_violations", "Additional violations omitted from bounded output.",
                                   count=omitted))
    return blockers


def _metrics(board, requirements, poses):
    boxes, totals, assigned = {}, {}, {}
    expected = set(requirements["expected_refdes"])
    group_boxes = {}
    groups = {ref: group["name"] for group in requirements["functional_groups"] for ref in group["refdes"]}
    for part in board["components"]:
        ref = part["refdes"]
        if ref not in expected:
            continue
        for pin in part["pins"]:
            if pin["net"]:
                totals[pin["net"]] = totals.get(pin["net"], 0) + 1
                if ref in poses:
                    assigned[pin["net"]] = assigned.get(pin["net"], 0) + 1
        if ref not in poses:
            continue
        for net, box in _net_boxes(part, poses[ref]).items():
            boxes[net] = _merge(boxes.get(net), box)
        if ref in groups:
            name = groups[ref]
            group_boxes[name] = _merge(group_boxes.get(name), _bounds(part, poses[ref]))
    per_net = {net: _text(_span(boxes.get(net))) for net in sorted(totals)}
    critical = set(requirements["critical_nets"])
    total = sum((Decimal(value) for value in per_net.values()), Decimal(0))
    weighted = sum((Decimal(value) * (2 if net in critical else 1)
                    for net, value in per_net.items()), Decimal(0))
    return {
        "total_pin_hpwl_mm": _text(total), "weighted_pin_hpwl_mm": _text(weighted),
        "per_net_hpwl_mm": per_net,
        "group_envelope_span_mm": _text(sum((_span(box) for box in group_boxes.values()), Decimal(0))),
        "connected_pin_count": sum(totals.values()),
        "unpositioned_connected_pin_count": sum(totals.values()) - sum(assigned.values()),
        "unpositioned_component_count": len(expected - set(poses)),
        "multi_terminal_net_count": sum(count >= 2 for count in totals.values()),
        "net_terminal_counts": dict(sorted(totals.items())),
        "reserved_region_count": len(requirements["reserved_regions"]),
    }


def _budget_blockers(requirements, metrics):
    budget = requirements["routing"].get("budget", {})
    blockers = []
    if "max_total_hpwl_mm" in budget and (
        Decimal(metrics["total_pin_hpwl_mm"]) > Decimal(budget["max_total_hpwl_mm"])
    ):
        blockers.append(_diagnosis("total_hpwl_budget", "Pin HPWL exceeds the operator's proxy budget."))
    for net, limit in budget.get("max_net_hpwl_mm", {}).items():
        if Decimal(metrics["per_net_hpwl_mm"].get(net, "0")) > Decimal(limit):
            blockers.append(_diagnosis("net_hpwl_budget", "Net pin HPWL exceeds its proxy budget.", net=net))
    return blockers


def _routing(board, requirements, poses, *, scope):
    metrics = _metrics(board, requirements, poses)
    blockers = _budget_blockers(requirements, metrics)
    routing = requirements["routing"]
    missing = [name for name in ("stackup", "budget") if name not in routing]
    missing += [
        "pad_and_drill_geometry", "trace_width_spacing_and_via_rules",
        "return_path_and_reference_layer_model", "routed_connectivity_and_native_drc",
    ]
    if blockers:
        screening = "budget_exceeded"
    elif metrics["unpositioned_component_count"]:
        screening = "placement_incomplete"
    elif "stackup" not in routing or "budget" not in routing:
        screening = "insufficient_design_evidence"
    else:
        screening = "within_supplied_proxy_budget"
    return {
        "scope": scope, "screening": screening, "metrics": metrics, "blockers": blockers,
        "missing_inputs": missing, "operator_evidence": deepcopy(routing),
        "review": "not_performed", "verification": "unverified", "feasibility_proven": False,
        "limitations": "Pin HPWL and AABB corridors do not prove escape, congestion, routability or DRC.",
    }


class _SearchLimit(Exception):
    pass


class _Search:
    def __init__(self, board, requirements):
        self.board, self.requirements = board, requirements
        self.parts = {part["refdes"]: part for part in board["components"]}
        self.limits = requirements["limits"]
        self.deadline = time.monotonic() + self.limits["max_seconds"]
        self.candidates = 0
        self.nodes = 0
        self.leaf_budget_failures = 0
        self.clearance = Decimal(requirements["clearance_mm"])
        self.groups = {ref: group["name"] for group in requirements["functional_groups"] for ref in group["refdes"]}
        self.critical = set(requirements["critical_nets"])
        self.pin_offsets = {
            ref: {angle: _net_boxes(part, {"x": "0", "y": "0", "angle": angle}) for angle in ANGLES}
            for ref, part in self.parts.items()
        }

    def check(self, *, candidate=False, node=False):
        self.candidates += int(candidate)
        self.nodes += int(node)
        if self.candidates > self.limits["max_candidates"]:
            raise _SearchLimit("max_candidates")
        if self.nodes > self.limits["max_search_nodes"]:
            raise _SearchLimit("max_search_nodes")
        if time.monotonic() >= self.deadline:
            raise _SearchLimit("max_seconds")

    def domain(self, ref, obstacles):
        part = self.parts[ref]
        boundary = _box(self.board["keepin"])
        grid = Decimal(self.requirements["grid_mm"])
        domain = []
        for angle in ANGLES:
            local = _bounds(part, {"x": "0", "y": "0", "angle": angle})
            lo_x = int(((boundary[0] + self.clearance - local[0]) / grid).to_integral_value(rounding=ROUND_CEILING))
            lo_y = int(((boundary[1] + self.clearance - local[1]) / grid).to_integral_value(rounding=ROUND_CEILING))
            hi_x = int(((boundary[2] - self.clearance - local[2]) / grid).to_integral_value(rounding=ROUND_FLOOR))
            hi_y = int(((boundary[3] - self.clearance - local[3]) / grid).to_integral_value(rounding=ROUND_FLOOR))
            count = max(0, hi_x - lo_x + 1) * max(0, hi_y - lo_y + 1)
            if count > self.limits["max_candidates"] - self.candidates:
                raise _SearchLimit("lattice_domain_exceeds_max_candidates")
            for iy in range(lo_y, hi_y + 1):
                for ix in range(lo_x, hi_x + 1):
                    self.check(candidate=True)
                    x, y = grid * ix, grid * iy
                    # Translated origins must remain in the wire decimal range.
                    if abs(x) >= Decimal(1000000000) or abs(y) >= Decimal(1000000000):
                        continue
                    box = (x + local[0], y + local[1], x + local[2], y + local[3])
                    if not any(_collides(box, obstacle, self.clearance) for obstacle in obstacles):
                        domain.append((x, y, angle, box))
        return domain

    def ranked(self, ref, domain, poses):
        net_boxes, group_boxes, occupied = {}, {}, None
        obstacles = []
        expected = set(self.requirements["expected_refdes"])
        for other, pose in poses.items():
            box = _bounds(self.parts[other], pose)
            obstacles.append(box)
            occupied = _merge(occupied, box)
            if other in expected:
                for net, pins in _net_boxes(self.parts[other], pose).items():
                    net_boxes[net] = _merge(net_boxes.get(net), pins)
            if other in self.groups:
                group = self.groups[other]
                group_boxes[group] = _merge(group_boxes.get(group), box)
        ranked = []
        for candidate in domain:
            self.check(candidate=True)
            x, y, angle, box = candidate
            if any(_collides(box, obstacle, self.clearance) for obstacle in obstacles):
                continue
            wire = Decimal(0)
            for net, local in self.pin_offsets[ref][angle].items():
                shifted = (local[0] + x, local[1] + y, local[2] + x, local[3] + y)
                before = net_boxes.get(net)
                wire += (_span(_merge(before, shifted)) - _span(before)) * (2 if net in self.critical else 1)
            group = group_boxes.get(self.groups.get(ref))
            group_cost = _span(_merge(group, box)) - _span(group) if ref in self.groups else Decimal(0)
            cost = (wire, group_cost, _span(_merge(occupied, box)), y, x, int(angle))
            ranked.append((cost, candidate))
        ranked.sort(key=lambda item: item[0])
        return ranked

    def solve(self, order, domains, poses, index=0):
        self.check(node=True)
        if index == len(order):
            if _budget_blockers(self.requirements, _metrics(self.board, self.requirements, poses)):
                self.leaf_budget_failures += 1
                return None
            return dict(poses)
        ref = order[index]
        for _, (x, y, angle, _) in self.ranked(ref, domains[ref], poses):
            poses[ref] = {"x": _text(x), "y": _text(y), "angle": angle}
            solution = self.solve(order, domains, poses, index + 1)
            if solution is not None:
                return solution
            del poses[ref]
        return None


def _order(board, requirements):
    anchors = {item["refdes"] for item in requirements["anchors"]}
    groups = {ref: group for group in requirements["functional_groups"] for ref in group["refdes"]}
    critical = set(requirements["critical_nets"])

    def key(part):
        ref = part["refdes"]
        group = groups.get(ref)
        critical_part = bool(group and group["critical"]) or any(pin["net"] in critical for pin in part["pins"])
        priority = 0 if ref in anchors else 1 if critical_part else 2 if group else 3
        box = _box(part["bounds"])
        return (priority, group["name"] if group else "", -(box[2] - box[0]) * (box[3] - box[1]), ref)

    expected = set(requirements["expected_refdes"])
    return [part["refdes"] for part in sorted(board["components"], key=key)
            if part["refdes"] in expected and not part["placed"]]


def plan_mission(board: dict, requirements: dict) -> dict:
    """Plan every in-scope unplaced part, or return an explicitly blocked mission."""
    with localcontext() as context:
        context.prec = 50
        return _plan(_board(board), _requirements(requirements))


def _plan(board, requirements):
    blockers = _input_blockers(board, requirements)
    poses = {part["refdes"]: _pose(part) for part in board["components"] if part["placed"]}
    order = _order(board, requirements)
    blockers += _geometry_blockers(board, requirements, poses)
    parts = {part["refdes"]: part for part in board["components"]}
    for anchor in requirements["anchors"]:
        ref, pose = anchor["refdes"], _pose(anchor)
        if ref not in parts:
            continue
        if ref in poses and poses[ref] != pose:
            blockers.append(_diagnosis("protected_anchor_conflict", "An anchor would move a preserved part.", refdes=ref))
        else:
            poses[ref] = pose
    if not blockers:
        blockers += _geometry_blockers(board, requirements, poses)
    search = None
    solution = None
    if not blockers:
        search = _Search(board, requirements)
        free = [ref for ref in order if ref not in poses]
        obstacles = [_box(box) for box in board["keepouts"]]
        obstacles += [_box(region["bounds"]) for region in requirements["reserved_regions"]]
        obstacles += [_bounds(parts[ref], pose) for ref, pose in poses.items()]
        try:
            domains = {}
            for ref in free:
                domains[ref] = search.domain(ref, obstacles)
                if not domains[ref]:
                    blockers.append(_diagnosis(
                        "no_legal_candidate", "No legal grid pose for this part with fixed constraints.", refdes=ref,
                    ))
                    break
            if not blockers:
                solution = search.solve(free, domains, dict(poses))
                if solution is None:
                    blockers.append(_diagnosis(
                        "no_all_component_solution",
                        "No all-component solution found on the bounded grid with the supplied proxy budgets.",
                    ))
        except _SearchLimit as error:
            blockers.append(_diagnosis(
                "search_limit", "Search is incomplete, not proof of insufficient room.",
                limit=str(error),
            ))
    targets = [{"refdes": ref, **solution[ref], "side": "TOP"} for ref in order] if solution is not None else []
    actual = {part["refdes"]: _pose(part) for part in board["components"] if part["placed"]}
    mission = {
        "model": "placement-mission-v1", "baseline": board, "requirements": requirements,
        "identity_signature": canonical_digest(_identity(board)),
        "requirements_signature": canonical_digest(requirements),
        "targets": targets, "blockers": blockers,
        "status": "blocked" if blockers else "ready" if targets else "placement_complete",
        "evidence": {
            "rules": list(RULES), "inventory": {
                "expected_refdes": requirements["expected_refdes"],
                "excluded_refdes": requirements["excluded_refdes"],
                "native_refdes": sorted(parts),
            },
            "unplanned_refdes": sorted(set(requirements["expected_refdes"]) - set(actual)) if solution is None else [],
            "protected_refdes": sorted(actual),
            "search": {
                "algorithm": "bounded-first-feasible-orthogonal-grid-dfs",
                "candidate_evaluations": search.candidates if search else 0,
                "search_nodes": search.nodes if search else 0,
                "leaf_budget_failures": search.leaf_budget_failures if search else 0,
                "limits": requirements["limits"],
                "optimality_proven": False,
            },
            "score": "Incremental critical-weighted pin HPWL, group span, occupied span, y, x, angle.",
            "geometry": "Operator AABB spacing; not electrical clearance, escape or DRC verification.",
            "routing": _routing(board, requirements, solution if solution is not None else actual,
                                scope="intended_poses" if solution is not None else "native_placed_poses"),
            "persistence": "unverified",
        },
    }
    mission["mission_id"] = canonical_digest(mission)
    return mission


def _bounded_json(value):
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > 200000 or depth > 20:
            raise MissionError("Mission exceeds structural limits.")
        if type(item) is dict:
            if len(item) > MAX_PINS:
                raise MissionError("Mission object exceeds limits.")
            for key, child in item.items():
                _string(key, maximum=4096)
                stack.append((child, depth + 1))
        elif type(item) is list:
            _list(item, MAX_PINS)
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            _string(item, empty=True, maximum=4096)
        elif type(item) not in (bool, int, type(None)) or (type(item) is int and abs(item) > 10**12):
            raise MissionError("Mission is not a bounded JSON document.")


def _mission(value):
    _bounded_json(value)
    _object(value, {
        "model", "baseline", "requirements", "identity_signature", "requirements_signature",
        "targets", "blockers", "status", "evidence", "mission_id",
    })
    if value["model"] != "placement-mission-v1":
        raise MissionError("Unsupported mission model.")
    _string(value["mission_id"], pattern=HEX64)
    _string(value["identity_signature"], pattern=HEX64)
    _string(value["requirements_signature"], pattern=HEX64)
    core = {key: item for key, item in value.items() if key != "mission_id"}
    if canonical_digest(core) != value["mission_id"]:
        raise MissionError("Mission integrity binding no longer matches.")
    baseline, requirements = _board(value["baseline"]), _requirements(value["requirements"])
    if (
        canonical_digest(_identity(baseline)) != value["identity_signature"]
        or canonical_digest(requirements) != value["requirements_signature"]
    ):
        raise MissionError("Mission identity or requirement signature mismatch.")
    order = _order(baseline, requirements)
    refs = []
    for target in _list(value["targets"], MAX_COMPONENTS):
        _object(target, {"refdes", "x", "y", "angle", "side"})
        refs.append(_string(target["refdes"], pattern=REFDES))
        pose = _pose(target)
        if target["side"] != "TOP" or any(
            _decimal(pose[axis]) % Decimal(requirements["grid_mm"]) for axis in ("x", "y")
        ):
            raise MissionError("Mission target is not a TOP grid pose.")
    _list(value["blockers"], 8192)
    for blocker in value["blockers"]:
        _object(blocker, {"code", "message"}, {
            "refdes", "other_refdes", "region", "kind", "count", "missing_refdes",
            "unexpected_refdes", "nets", "layers", "net", "limit",
        })
        _string(blocker["code"])
        _string(blocker["message"], maximum=4096)
    if refs != (order if not value["blockers"] else []):
        raise MissionError("Mission does not bind the exact complete ordered target inventory.")
    expected_status = "blocked" if value["blockers"] else "ready" if refs else "placement_complete"
    if value["status"] != expected_status:
        raise MissionError("Mission status contradicts its bound target inventory.")
    if not value["blockers"]:
        intended = {part["refdes"]: _pose(part) for part in baseline["components"] if part["placed"]}
        intended.update({target["refdes"]: _pose(target) for target in value["targets"]})
        if any(intended.get(anchor["refdes"]) != _pose(anchor) for anchor in requirements["anchors"]):
            raise MissionError("Mission target does not honor the supplied anchor.")
        if (
            _input_blockers(baseline, requirements)
            or _geometry_blockers(baseline, requirements, intended)
            or _budget_blockers(requirements, _metrics(baseline, requirements, intended))
        ):
            raise MissionError("Mission targets violate the bound native or operator constraints.")
    return baseline, requirements


def mission_status(board: dict, mission: dict) -> dict:
    """Reconcile immutable facts and exact placement coverage against native readback."""
    with localcontext() as context:
        context.prec = 50
        current = _board(board)
        baseline, requirements = _mission(mission)
        return _status(current, mission, baseline, requirements)


def _status(board, mission, baseline, requirements):
    blockers = deepcopy(mission["blockers"])
    blockers += _input_blockers(board, requirements)
    if board["board"] != baseline["board"]:
        blockers.append(_diagnosis("board_identity_changed", "The readback belongs to a different board path."))
    immutable_ok = canonical_digest(_identity(board)) == mission["identity_signature"]
    if not immutable_ok:
        blockers.append(_diagnosis(
            "immutable_facts_changed", "Native inventory, footprints, pins/nets, flags or board constraints changed.",
        ))
    changed = any(board[key] != baseline[key] for key in board if key not in ("snapshot_id", "scene_digest"))
    freshness_ok = True
    if board["snapshot_id"] == baseline["snapshot_id"] and (
        changed or board["scene_digest"] != baseline["scene_digest"]
    ):
        freshness_ok = False
        blockers.append(_diagnosis("reused_snapshot_id", "Changed native state reused the baseline snapshot ID."))
    if changed and board["scene_digest"] == baseline["scene_digest"]:
        freshness_ok = False
        blockers.append(_diagnosis("reused_scene_digest", "Changed native state reused the baseline scene digest."))
    parts = {part["refdes"]: part for part in board["components"]}
    protected = {part["refdes"]: _pose(part) for part in baseline["components"] if part["placed"]}
    targets = {target["refdes"]: _pose(target) for target in mission["targets"]}
    intended = {**protected, **targets}
    for ref, pose in protected.items():
        current = parts.get(ref)
        if current is None or not current["placed"] or _pose(current) != pose:
            blockers.append(_diagnosis("protected_part_changed", "A preserved placed part moved or became unplaced.", refdes=ref))
    for ref, part in parts.items():
        if part["placed"] and ref not in protected and (
            ref not in targets or _pose(part) != targets[ref]
        ):
            blockers.append(_diagnosis("unexpected_placed_pose", "Native placed state is not an exact mission target.", refdes=ref))
    actual = {ref: _pose(part) for ref, part in parts.items() if part["placed"]}
    blockers += _geometry_blockers(board, requirements, actual)
    routing = _routing(board, requirements, actual, scope="native_placed_poses")
    blockers += routing["blockers"]
    verified = []
    if immutable_ok and freshness_ok:
        verified = [
            ref for ref in requirements["expected_refdes"]
            if ref in actual and ref in intended and actual[ref] == intended[ref]
        ]
    remaining = sorted(set(requirements["expected_refdes"]) - set(verified))
    complete = bool(requirements["expected_refdes"]) and not remaining and not blockers
    return {
        "model": "placement-mission-status-v1", "mission_id": mission["mission_id"],
        "board": board["board"], "snapshot_id": board["snapshot_id"], "scene_digest": board["scene_digest"],
        "status": "blocked" if blockers else "placement_complete" if complete else "in_progress",
        "placement": {
            "expected_count": len(requirements["expected_refdes"]),
            "excluded_count": len(requirements["excluded_refdes"]),
            "initially_placed_count": len(set(protected) & set(requirements["expected_refdes"])),
            "planned_count": len(targets), "verified_placed_count": len(verified),
            "verified_refdes": verified, "remaining_refdes": remaining,
            "unplanned_refdes": sorted(set(remaining) - set(intended)), "complete": complete,
        },
        "blockers": blockers, "routing": routing, "persistence": {"status": "unverified"},
        "evidence": {
            "readback_only": True,
            "snapshot_link": "baseline" if board["snapshot_id"] == baseline["snapshot_id"] else "later_snapshot",
            "native_freshness_must_be_verified_by_caller": True,
            "approval_or_execution_receipts_count_as_placement": False,
        },
    }


def next_candidate(board: dict, mission: dict) -> dict | None:
    """Return exactly one unplaced TOP target; never approval or a native command."""
    status = mission_status(board, mission)
    if status["blockers"]:
        return {
            "status": "blocked", "mission_id": mission["mission_id"],
            "snapshot_id": status["snapshot_id"], "scene_digest": status["scene_digest"],
            "blockers": status["blockers"], "placement": status["placement"],
        }
    if status["placement"]["complete"]:
        return None
    remaining = set(status["placement"]["remaining_refdes"])
    for index, target in enumerate(mission["targets"]):
        if target["refdes"] in remaining:
            return {
                "status": "candidate", **deepcopy(target), "mission_id": mission["mission_id"],
                "board": status["board"], "snapshot_id": status["snapshot_id"],
                "scene_digest": status["scene_digest"], "sequence": index + 1,
                "remaining_count": len(remaining), "requires_native_prepare_and_human_approval": True,
                "placement": status["placement"],
            }
    return {
        "status": "blocked", "mission_id": mission["mission_id"],
        "snapshot_id": status["snapshot_id"], "scene_digest": status["scene_digest"],
        "blockers": [_diagnosis("unplanned_inventory", "Placement is incomplete with no remaining target.")],
        "placement": status["placement"],
    }

"""Validated native inventory/geometry for managed, unrouted placement boards."""

import re

from .protocol import ProtocolError, Receipt, decimal_text, identifier, number
from .boundaries import MAX_VERTICES, board_boundaries


MODEL = "managed-board-v1"
REFDES = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,30}")


def _rectangle(values: tuple[str, ...]) -> list[str]:
    if len(values) != 4:
        raise ProtocolError("Expected a native rectangle.")
    coordinates = [number(value) for value in values]
    if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ProtocolError("Native rectangle is empty or reversed.")
    return [decimal_text(value) for value in coordinates]


def from_receipt(receipt: Receipt) -> dict[str, object]:
    """Return planning facts only when the native adapter supplied a complete model."""
    if receipt.status != "snapshot" or receipt.one("model")[1] != MODEL:
        raise ProtocolError("A fresh managed-board-v1 native snapshot is required.")
    identifier(receipt.one("snapshot")[1])
    if not receipt.scene.startswith("OPA-BOARD-1;"):
        raise ProtocolError("Managed board lacks its complete native scene.")
    units = receipt.one("units")
    if units != ("units", "millimeters", "4", "10000"):
        raise ProtocolError("Managed placement currently requires millimeters at four-digit accuracy.")
    outline = _rectangle(receipt.one("outline")[1:])
    keepin = _rectangle(receipt.one("keepin")[1:])
    components = {}
    bounds = {}
    pins = {}
    layers = []
    contours = {}
    vertices = {"outline": [], "keepin": []}
    for row in receipt.records:
        if row[0] == "component":
            refdes = row[1]
            if REFDES.fullmatch(refdes) is None or refdes in components or not row[2]:
                raise ProtocolError("Invalid or duplicate native component.")
            if row[6] not in {"0", "1"} or row[7] not in {"0", "1"} or row[8] not in {"0", "1"}:
                raise ProtocolError("Invalid native component flags.")
            if row[5] not in {"0", "90", "180", "270"}:
                raise ProtocolError("Nonorthogonal component pose is not supported.")
            components[refdes] = {
                "refdes": refdes, "package": row[2],
                "x": decimal_text(number(row[3])), "y": decimal_text(number(row[4])),
                "angle": row[5], "mirrored": row[6] == "1", "fixed": row[7] == "1",
                "placed": row[8] == "1",
            }
        elif row[0] == "bounds":
            if row[1] in bounds:
                raise ProtocolError("Duplicate local footprint bounds.")
            bounds[row[1]] = _rectangle(row[2:])
        elif row[0] == "pin":
            key = (row[1], row[2])
            if not row[2] or key in pins:
                raise ProtocolError("Duplicate or unnamed native pin.")
            pins[key] = {"number": row[2], "net": row[3],
                         "x": decimal_text(number(row[4])), "y": decimal_text(number(row[5]))}
        elif row[0] == "layer":
            if not row[1] or row[1] in layers:
                raise ProtocolError("Missing or duplicate conductor layer.")
            layers.append(row[1])
        elif row[0] == "boundary":
            if row[1] not in vertices or row[1] in contours:
                raise ProtocolError("Unknown or duplicate native contour.")
            if not row[2].isdigit() or not 3 <= int(row[2]) <= MAX_VERTICES:
                raise ProtocolError("Native contour vertex count is invalid.")
            contours[row[1]] = (int(row[2]), row[3])
        elif row[0] == "boundary-point":
            if row[1] not in vertices or row[2] != str(len(vertices[row[1]])):
                raise ProtocolError("Native contour vertices are unknown, missing, duplicated or out of order.")
            if len(vertices[row[1]]) >= MAX_VERTICES:
                raise ProtocolError("Native contour exceeds the vertex bound.")
            vertices[row[1]].append([row[3], row[4]])
    if not 1 <= len(components) <= 256 or set(bounds) != set(components):
        raise ProtocolError("A known nonempty inventory with bounds for every component is required.")
    if not {"TOP", "BOTTOM"} <= set(layers):
        raise ProtocolError("Native conductor-layer inventory is incomplete.")
    if any(refdes not in components for refdes, _ in pins):
        raise ProtocolError("Native pin has no logical component.")
    for refdes, component in components.items():
        component["bounds"] = bounds[refdes]
        component["pins"] = [pins[key] for key in sorted(pins) if key[0] == refdes]
        if not component["pins"]:
            raise ProtocolError("A logical component lacks native pin/footprint associations.")
    result = {
        "model": MODEL, "board": receipt.one("board")[1],
        "snapshot_id": receipt.one("snapshot")[1], "scene_digest": receipt.scene_digest,
        "outline": outline, "keepin": keepin,
        "keepouts": [_rectangle(row[1:]) for row in receipt.records if row[0] == "keepout"],
        "layers": layers, "components": [components[name] for name in sorted(components)],
    }
    if any(row[0] == "boundary-model" for row in receipt.records):
        if receipt.one("boundary-model") != ("boundary-model", "polygon-v1") or set(contours) != set(vertices):
            raise ProtocolError("Native boundary model is unsupported or incomplete.")
        for role, (count, error) in contours.items():
            if len(vertices[role]) != count:
                raise ProtocolError("Native contour is incomplete.")
            result[role + "_boundary"] = {"vertices": vertices[role], "error_mm": error}
        for role, boundary in zip(("outline", "keepin"), board_boundaries(result)):
            result[role + "_boundary"] = boundary.to_dict()
    elif contours or any(vertices.values()):
        raise ProtocolError("Contour data lacks an explicit native boundary model.")
    return result

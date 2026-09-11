"""Conservative whole-footprint containment in simple native outline contours.

Vertices are ordered, implicitly closed, and describe one simple polygon with
no holes. error_mm bounds the native circular-arc chord/rounding deviation; it
is added to the operator's geometric clearance, never subtracted. Bounding
boxes are search accelerators, not evidence of containment in a concavity.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from functools import lru_cache

from .protocol import ProtocolError, decimal_text, number


MAX_VERTICES = 512
MAX_ERROR_MM = Decimal("0.01")
Point = tuple[Decimal, Decimal]
Box = tuple[Decimal, Decimal, Decimal, Decimal]


def _cross(a: Point, b: Point, c: Point) -> Decimal:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    return (_cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def _intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    if (max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0])
            or max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1])):
        return False
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return ((ab_c * ab_d < 0 and cd_a * cd_b < 0)
            or (ab_c == 0 and _on_segment(a, b, c)) or (ab_d == 0 and _on_segment(a, b, d))
            or (cd_a == 0 and _on_segment(c, d, a)) or (cd_b == 0 and _on_segment(c, d, b)))


def _cuts_open_box(a: Point, b: Point, box: Box) -> bool:
    # Separating axes for a segment and an open rectangle. Merely touching its
    # perimeter is allowed, but a notch wholly between corners is still caught.
    if (max(a[0], b[0]) <= box[0] or min(a[0], b[0]) >= box[2]
            or max(a[1], b[1]) <= box[1] or min(a[1], b[1]) >= box[3]):
        return False
    sides = [_cross(a, b, p) for p in _corners(box)]
    return min(sides) < 0 < max(sides)


def _corners(box: Box) -> tuple[Point, ...]:
    return ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))


def footprint_box(bounds: Box, x: Decimal, y: Decimal, angle: str) -> Box:
    if angle not in ("0", "90", "180", "270"):
        raise ProtocolError("Footprint bounds require an orthogonal pose.")
    with localcontext() as context:
        context.prec = 60
        points = [{"0": (a, b), "90": (-b, a), "180": (-a, -b), "270": (b, -a)}[angle]
                  for a, b in _corners(bounds)]
        return (x + min(a for a, _ in points), y + min(b for _, b in points),
                x + max(a for a, _ in points), y + max(b for _, b in points))


@dataclass(frozen=True)
class Boundary:
    vertices: tuple[Point, ...]
    error: Decimal
    bounds: Box

    def contains_point(self, p: Point) -> bool:
        inside = False
        for a, b in zip(self.vertices, self.vertices[1:] + self.vertices[:1]):
            cross = _cross(a, b, p)
            if cross == 0 and _on_segment(a, b, p):
                return True
            if (a[1] > p[1]) != (b[1] > p[1]):
                if (cross > 0) == (b[1] > a[1]):
                    inside = not inside
        return inside

    def contains_box(self, box: Box, clearance: Decimal = Decimal(0)) -> bool:
        if clearance < 0 or not clearance.is_finite() or box[0] >= box[2] or box[1] >= box[3]:
            raise ProtocolError("Containment requires a positive-area box and nonnegative finite clearance.")
        with localcontext() as context:
            context.prec = 60
            margin = clearance + self.error
            expanded = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
            if (expanded[0] < self.bounds[0] or expanded[1] < self.bounds[1]
                    or expanded[2] > self.bounds[2] or expanded[3] > self.bounds[3]):
                return False
            if len(self.vertices) == 4 and set(self.vertices) == set(_corners(self.bounds)):
                return True
            if not all(self.contains_point(point) for point in _corners(expanded)):
                return False
            return not any(_cuts_open_box(a, b, expanded)
                           for a, b in zip(self.vertices, self.vertices[1:] + self.vertices[:1]))

    def to_dict(self) -> dict[str, object]:
        return {"vertices": [[decimal_text(x), decimal_text(y)] for x, y in self.vertices],
                "error_mm": decimal_text(self.error)}


@lru_cache(maxsize=64)
def _validated(points: tuple[Point, ...], error: Decimal) -> Boundary:
    with localcontext() as context:
        context.prec = 60
        if len(set(points)) != len(points):
            raise ProtocolError("Boundary contains duplicate vertices or an explicit duplicate closing point.")
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
        if area == 0:
            raise ProtocolError("Boundary has zero signed area.")
        edges = list(zip(points, points[1:] + points[:1]))
        for i, (a, b) in enumerate(edges):
            c = points[(i + 2) % len(points)]
            if _cross(a, b, c) == 0 and (
                (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) <= 0
            ):
                raise ProtocolError("Boundary doubles back along an adjacent edge.")
            for j in range(i + 1, len(edges)):
                if j == i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                if _intersect(a, b, *edges[j]):
                    raise ProtocolError("Boundary is self-intersecting or self-touching.")
        if area < 0:
            points = tuple(reversed(points))
        start = min(range(len(points)), key=lambda i: points[i])
        points = points[start:] + points[:start]
        return Boundary(points, error, (
            min(x for x, _ in points), min(y for _, y in points),
            max(x for x, _ in points), max(y for _, y in points),
        ))


def parse_boundary(value: object) -> Boundary:
    if not isinstance(value, dict) or set(value) != {"vertices", "error_mm"}:
        raise ProtocolError("Boundary requires only ordered vertices and an explicit error_mm.")
    vertices = value["vertices"]
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= MAX_VERTICES:
        raise ProtocolError(f"Boundary requires 3-{MAX_VERTICES} vertices in one simple contour.")
    points = []
    for point in vertices:
        if not isinstance(point, list) or len(point) != 2:
            raise ProtocolError("Boundary vertices must be coordinate pairs.")
        points.append((number(point[0]), number(point[1])))
    error = number(value["error_mm"])
    if not 0 <= error <= MAX_ERROR_MM:
        raise ProtocolError("Boundary approximation error must be between 0 and 0.01 mm.")
    return _validated(tuple(points), error)


def board_boundaries(board: dict) -> tuple[Boundary, Boundary]:
    result = []
    for role in ("outline", "keepin"):
        box = tuple(number(item) for item in board[role])
        if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
            raise ProtocolError("Missing positive-area native boundary extents.")
        if role + "_boundary" not in board:
            result.append(Boundary(_corners(box), Decimal(0), box))
            continue
        boundary = parse_boundary(board[role + "_boundary"])
        if any(abs(actual - declared) > boundary.error
               for actual, declared in zip(boundary.bounds, box)):
            raise ProtocolError("Boundary contour and declared native extents disagree.")
        result.append(boundary)
    return tuple(result)

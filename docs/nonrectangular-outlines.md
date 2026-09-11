# Nonrectangular outline support

Managed placement supports a single simple closed contour for the design
outline and package keepin. Concave notches are part of the boundary, not empty
space within a rectangular board. Every footprint must lie inside **both**
contours; a keepin extending outside the outline cannot permit off-board
placement.

The native reader retains the source boundary geometry in the protected scene
and exports ordered polygon contours for planning. Straight edges are exact.
Circular edges are converted to chords with a bounded deviation and coordinate
rounding margin. That margin is **added** to geometric clearance. It is not a
permission to place outside an arc.

The native reader uses arc endpoints, center (`xy`) and clockwise direction;
it does not assume an undocumented `arc.radius` field. Chords span at most a
quarter circle and use an 8-DBU sagitta budget, with 4 additional DBUs reserved
for endpoint consistency, coordinate rounding and binary64 calculation error
within the bounded radius/coordinate domain. The reported margin for contours
containing arcs is **0.0012 mm**. This is numerical conservatism, not a universal
engineering clearance. Exceeding the vertex budget is an error, not permission
to coarsen the contour.

## Placement checks

Component origins and all four corners fitting inside a boundary are not enough:
a concave notch can cross between the corners. The planner checks the entire
clearance-expanded footprint rectangle and rejects any contour edge entering
its interior. The native placement gate independently performs whole-footprint
containment before committing a change. Native DRC remains a separate check.
As an additional check, it intersects an in-memory footprint rectangle with
the original native curved boundary and requires geometric equality with the
whole rectangle. Empty results are not containment, and operation failure is
not interpreted as an empty/successful result. Native polygon operations have
documented edge-case limits, so this supplements rather than replaces the
conservative contour check or DRC.

Bounding rectangles are used only to limit the search grid and reject obvious
misses. The planner never uses them as final proof of containment. Existing
placed components, anchors, initial-placement candidates, fresh-readback
mission status and exact polygon-board proposals use the contour checks.
Rotation is about the component origin, including footprints with offset origins.

Rectangular legacy snapshots remain supported. Existing mission documents
without contour fields retain their original schema and rectangular checks.
A newly generated polygon mission binds both contours and their approximation
margins; changing a notch while keeping the same bounding rectangle invalidates
the mission.

## Snapshot format

The existing `outline` and `keepin` records retain their native extents.
Polygon-capable snapshots additionally contain:

```text
boundary-model,polygon-v1
boundary,outline,<vertex-count>,<error-mm>,<source-edge-count>
boundary-point,outline,0,<x-mm>,<y-mm>
...
boundary-source,outline,0,<opaque-native-edge-data>
...
boundary,keepin,<vertex-count>,<error-mm>,<source-edge-count>
boundary-point,keepin,0,<x-mm>,<y-mm>
...
boundary-source,keepin,0,<opaque-native-edge-data>
...
```

Both contours are required when `boundary-model` is present. Each has 3-512
ordered vertices and an implicit closing edge: the first point is not repeated
at the end. Missing/duplicate/out-of-order points, unknown roles, unsupported
versions, self-intersections, touching loops and degenerate edges are rejected.
Native extents must agree with each contour within its reported error.
Complete, ordered source-edge data is hashed into `source_digest` on each
normalized contour. It is never evaluated as SKILL. This binds exact native
arc changes even when chord rounding leaves the sampled vertices unchanged.
The digest is an approval/mission precondition, not a version-control system.
The ordinary overall wire and persisted-metadata limits still apply.
Native contour spans are bounded to 67,108,863 DBUs per axis so integer
orientation products remain exactly representable in the chosen arithmetic.
Coincident-endpoint/full-circle arcs are rejected; a circular boundary may
instead have distinct, connected arc segments within the same vertex budget.

Normalized board facts include `outline_boundary` and `keepin_boundary`:

```json
{
  "vertices": [["0", "0"], ["12", "0"], ["12", "4"], ["4", "4"], ["4", "12"], ["0", "12"]],
  "error_mm": "0"
}
```

Coordinates and error are decimal strings in millimeters. This example is
synthetic geometry, not a clearance recommendation. The contour API accepts
an error bound from 0 through 0.01 mm; increasing it only makes placement more
conservative. Project clearance and grid requirements remain explicit inputs.

## Limits

This change concerns board outline and package keepin geometry, not arbitrary
footprint geometry or routing. Multiple islands, holes/cutouts, self-crossing
contours, unsupported curves, oversized boundaries, and ambiguous native
outline identities remain explicit blockers. Internal exclusions can still
use the supported rectangular package keepouts.

Other managed-model restrictions, native acceptance requirements, exact human
approval and separate Save authorization remain unchanged. A board rejected
for through-hole pads, missing footprints, unsupported text or other geometry
does not become fully supported merely because its outline is now supported.
Do not simplify or discard design objects to force acceptance.

If both `DESIGN_OUTLINE` and the legacy `OUTLINE` exist, their complete native
edge geometry must agree, not merely their extents. Comparison ignores traversal
order/direction and accounts for arc centers and clockwise direction. Different
edge segmentation is conservatively rejected even if the shapes might be
geometrically equivalent; it is not silently treated as one authoritative shape.

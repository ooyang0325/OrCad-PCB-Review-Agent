# Executable placement missions

The mission engine produces a complete set of concrete target poses and advances
one component at a time using fresh native readback. It is not merely an agent
handoff prompt. Initial placement still requires a logical design: the source
board must contain the intended components, pin/net assignments and usable
embedded footprint definitions. An empty database is not a circuit specification.

The experimental `managed-board-v1` adapter is a separate, explicitly selected
model. The original fixture model remains the default. Unsupported geometry,
libraries, routing or constraint features must fail closed rather than being
silently ignored. Native acceptance is separate from Python/fake-editor tests.

### Current native boundary

The implementation accepts 1-256 logical components with embedded, matching
PACKAGE definitions; zero or more may be physically placed. It requires
millimeters/4/10000, top-side orthogonal poses, simple closed
[nonrectangular outline/keepin contours](nonrectangular-outlines.md), rectangular
top keepouts, straight supported package linework and simple rectangular, square
or circular SMT pads. A PRIMARY stackup may have 2-32 positive conductor
layers. Required placement DRC must already be enabled and current.

[Flat groups, placement rooms and named constraint sets](grouped-constraints.md)
are preserved as native design policy. Positive plane layers are included in
the complete constraint readback. Room labels and component/function ROOM tags
are matched explicitly; unmatched tags are not mapped to staging boxes by guesswork.

Logical function instances are supported only with complete checked
definition and forward/reverse pin associations. Cadence-owned attachments are
preserved read-only as complete exported bytes plus native metadata, never
deleted from the board; stored and expanded sizes are bounded separately.

Missing/unloaded footprints, package/unattached text, unmapped logical functions, mechanical-only
symbols, through-hole/complex pads, unsupported package shapes, routed copper,
nested/component groups, regions, oversized/unreadable attachments, electrical
Csets and class/region overrides are rejected.
Do not remove design information or silently substitute a simpler board to
force acceptance. These are implementation limits, not evidence that Cadence
cannot support those designs. Live enumeration and PNG inspection have passed on the original fixture.
Native creation and rollback still need dedicated acceptance before using this
model on valuable designs.

## Prepare the actual design

Use a disposable, operator-approved test design first. Stage a copy; never load
the adapter into the user's unrelated active design:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage 'C:\design\unplaced.brd' --model managed-board-v1
```

Open only the printed working copy in a dedicated editor, load its printed
bootstrap, and attach using that exact session and HWND. Staging does not open
Cadence, import a schematic, mutate the source, or grant approval.

The native snapshot supplies logical placed/unplaced inventory, local footprint
bounds and pin coordinates, nets, outline, keepin, keepouts and conductor layers.
General scenes are transmitted in bounded ordered chunks, not truncated into
apparently complete state. Native full-scene checks remain independent of the
mission's inventory/geometry checks.

The wire remains bounded to 1 MiB. Persisted JSON has a separate 8 MiB bound to
account for escaping, indentation and embedded receipts/proposals; both readers
and writers enforce that bound. These are transport/storage limits, not a claim
that every board within them satisfies the supported native model.

## Explicit requirements

The following is a **synthetic schema example**, not a board-specific clearance
recommendation. Use the actual refdes inventory and approved project values.

```json
{
  "expected_refdes": ["J1", "U1", "R1"],
  "excluded_refdes": [],
  "grid_mm": "0.5",
  "clearance_mm": "0.5",
  "anchors": [
    {"refdes": "J1", "kind": "mechanical-interface", "x": "5", "y": "5", "angle": "0"}
  ],
  "functional_groups": [
    {"name": "controller", "refdes": ["U1", "R1"], "critical": true}
  ],
  "critical_nets": [],
  "reserved_regions": [
    {"name": "access", "kind": "access", "bounds": ["20", "10", "25", "15"]}
  ]
}
```

`expected_refdes` is required and nonempty; its union with explicitly excluded
DNP parts must match the native logical inventory exactly. Placed DNPs are not
automatically removed. All existing placed components are protected, including
unfixed ones. An anchor may not move an existing placed component.

`grid_mm` and `clearance_mm` are required decimal strings. Clearance is a
conservative geometric AABB spacing around bodies, keepin and exclusions, not
an electrical clearance or safety-isolation calculation. Native DRC remains an
additional independent gate. The grid must be a multiple of the model's native
0.0001 mm DBU, and anchors must lie on that grid. Mission targets are not rounded
after planning; preparation rejects a target that is not exactly representable.

Optional `routing.stackup` supplies `signal_layers` and a nonempty `evidence`
description. Optional `routing.budget` supplies evidence and
`max_total_hpwl_mm` and/or `max_net_hpwl_mm`. These bound a pin-based
half-perimeter wire-length **proxy**, not actual routed length. Operator-supplied
evidence does not become verified electrical intent.

Optional search limits are `max_candidates`, `max_search_nodes` and
`max_seconds`. Defaults are 200,000, 10,000 and 10; hard maxima are 1,000,000,
100,000 and 30. Exhausting a bound means search is incomplete, not that no
possible placement exists. The engine uses deterministic bounded
first-feasible search, not a global-optimum claim.

## Closed loop through MCP or app tools

1. Call `pcb_plan_placement` with the exact managed session and
   `requirements_json`. Examine its actual PNG and complete target plan.
   Resolve blockers before any execution. The plan is stored locally and
   cannot be silently rewritten.
2. Retain the top-level **`mission`** handle from that result. This is a
   32-character session handle; the nested `plan.mission_id` is a different
   64-character integrity binding, not the tool argument.
3. Have the independent reviewer assess the target set, constraints, applicable
   bundled rules and routing consequences. Search rank and a low cost are not
   engineering approval.
4. Call `pcb_prepare_next_placement` with that mission handle. It inspects the
   current native scene, reconciles protected state and prepares exactly one
   remaining target with its image. An unplaced component is explicitly
   identified as `UNPLACED` in the approval summary.
5. The executor calls `pcb_apply_placement`. The existing genuine human UI must
   authorize that exact proposal. Inspect the native result and post-image;
   a plan, approval or successful dispatch does not increment placement coverage.
6. Repeat from fresh readback until `pcb_placement_status` reports all expected
   components actually placed at their intended poses. Changed inventory,
   footprints, nets, protected poses or planning geometry block continuation.
   Rejected, denied, rolled-back and uncertain operations do not count.

If native execution is indeterminate, use the exact proposal's
`pcb_execution_status`, not another Apply. A separate pending snapshot is
reconciled only by its exact `pcb_inspection_status` request.

CLI equivalents for the read-only mission steps:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent mission plan --session '<managed-session>' --requirements 'requirements.json'
.\.venv\Scripts\python.exe -m orcad_placement_agent mission next --session '<managed-session>' --mission '<top-level-mission>'
.\.venv\Scripts\python.exe -m orcad_placement_agent mission status --session '<managed-session>' --mission '<top-level-mission>'
```

CLI output includes the captured PNG path. A textual description is not visual
inspection. Agents use the bounded image-returning tools, not a shell workaround.

## Routing and persistence are separate

Search prioritizes anchors and critical groups/nets, reserves routing/access
regions, and ranks candidate poses using transformed **pin** geometry, weighted
HPWL and group/occupied envelopes. It handles orthogonal rotation about actual
footprint origins rather than assuming centered footprints.

This is routing-aware placement screening, not routing feasibility proof.
Fanout, vias, pad escape, trace rules, reference-plane continuity, SI/PI,
thermal performance and manufacturing review still need applicable evidence.
The engine explicitly reports routing review as not performed and routability
as unverified; the independent reviewer must assess the relevant gates.

For persistence, call `pcb_prepare_save`, examine its scene/image and destination,
then use `pcb_save_revision`. This obtains a **separate exact SAVE approval** and
writes only a new managed revision. It never overwrites the source. Recover an
uncertain save using `pcb_save_status` without resending it. A missing post-image
does not erase a recorded Save outcome.

Native Save success and file existence are reported separately from reopening;
the save tools do not automatically reopen the design or claim that check ran.
Do not call a result reopened, routed, or manufacturing-ready without the
corresponding evidence. Portable writes remain disabled by default, and
Autopilot/auto-answering clients remain unsupported for native mutations.

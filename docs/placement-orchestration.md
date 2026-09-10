# PCB placement orchestration

**PCB placement orchestrator** is the supervising agent above the planner,
independent reviewer, and executor. The portable equivalent is the explicitly
invoked `pcb-placement-orchestrate` skill.

It manages an end-to-end placement **workflow**, including the prerequisites
between an empty board and a fully placed, routing-reviewed layout. It is not
a new native initial-placement API, autorouter, or approval authority.

Select **PCB placement orchestrator** in a client supporting repository agents,
or invoke `pcb-placement-orchestrate` from the installed plugin. Supply the
mission intake below and a current evidence packet; do not supply a generic
"place everything" request without a verified design inventory. Version 0.3.0
adds the coordinator and capability declarations. Existing direct MCP installs
should be deliberately upgraded/restarted to receive the new declaration.

Prepare routing-focused reference context without opening or changing a board:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent agent-context `
    --goal "Coordinate staged placement and identify routing-readiness requirements" `
    --topic placement --topic routing-readiness --topic return-paths
```

Provide the resulting packet plus the mission intake to the coordinator. A
reference packet alone is not a schematic, a component inventory, or a native
board snapshot.

## Current capability boundary

`pcb_sessions` now returns a `capabilities` declaration alongside the recorded
sessions. It identifies the current backend's supported and unsupported
operations. This is software scope, not proof of a live license or open board.

| Operation | Current backend |
|---|---|
| Inspect the supported board and return PNG/native evidence | Supported after staging/attachment |
| Move/rotate an already-placed original-fixture symbol | Implemented, subject to exact approval and native gates |
| Import a schematic/netlist or resolve arbitrary libraries | Not implemented |
| Initially place an unplaced logical component | Not implemented |
| Write arbitrary production boards | Not supported |
| Route traces or prove routing feasibility | Not implemented |

Consequently, a zero-placement native mission currently stops at the
initial-placement capability gate. The coordinator may still organize an
offline floorplan, reference review and explicit operator/backend prerequisites.
It must not claim that the current move tool can place an unplaced symbol, or
delegate raw commands to work around the gap.

If a future adapter genuinely adds these capabilities, update its declaration
and native acceptance before allowing the coordinator to advance those steps.
An older server without a declaration is unknown, not implicitly capable.

## Mission intake

Establish a mission identifier and the exact design/session, or mark it
unbound. Record the operator-supplied source of every required input:

| Input | Why it is needed |
|---|---|
| Schematic/netlist, BOM variant, expected refdes and explicit DNP exclusions | Defines what must be placed; an empty database is not an empty completed design |
| Footprint/padstack and pin/net mappings | Establishes physical parts and electrical connections |
| Outline, origin/units, keepouts, mechanical/fixed interfaces and heights | Establishes legal placement and protected constraints |
| Stackup, reference planes and allowed via technology | Establishes escape and routing choices |
| Critical-net topology, edge rates, timing/length budgets, currents and isolation requirements | Makes routing-aware reasoning design-specific |
| Device layout guidance, thermal, assembly and test requirements | Establishes constraints that geometry alone cannot supply |

Distinguish **no logical design**, **logical design with zero placed symbols**,
**partially placed**, and **already routed/partly routed**. Never invent missing
parts, roles or connectivity. Never discard fixed placements or rip up routing
to manufacture a clean starting state.

## Phases and responsibility

| Phase | Owner and output | Exit gate |
|---|---|---|
| Intake and capability check | Coordinator: inventory, constraints, missing-input/backend queue | Expected assembly and supported operations are explicit |
| Functional floorplan | Planner: regions, signal/power flow, anchors and alternatives | Reviewer accepts the assumptions for human engineering review |
| Mechanical anchors | Planner/reviewer/executor loop | Exact supported poses, human approval and fresh native/visual readback |
| Critical groups | Same loop: ICs/converters/clock/RF/analog with their confirmed local passives | Escape and critical loop/return requirements remain feasible |
| Remaining groups | Same loop: dependency-ordered, bounded batches | Reserved routing channels, thermal and assembly access preserved |
| Coverage closure | Coordinator + native evidence | Every expected in-scope refdes is observed placed; no unexplained missing/extra parts |
| Routing-aware closure | Independent reviewer | Each routing gate has evidence or a justified not-applicable result |
| Persistence handoff | Operator via separate approved save workflow | Explicit saved/unsaved state; never infer saving from Apply |

The coordinator delegates only the three named PCB roles. Its `agent`/`todo`
tools support coordination and tracking, not general coding, shell access, or
permission bypass. The three workers retain their existing scope. All four
agents inspect actual PNGs and reference corresponding native facts.

Serialize native editor access, including overlapping inspections. Offline
analysis can be parallel when it does not compete for the editor. Every worker
gets complete context; do not assume it inherits the coordinator's history.

## Handoff contract

Each work package states:

- Mission and exact session; current phase and backend capability limits.
- Expected/in-scope placed/remaining/excluded inventory and its evidence source.
- Fixed or protected objects, relevant pin/net functions and device constraints.
- The bounded component group and dependency order; exact proposal IDs only
  after the planner has prepared them through a supported tool.
- Snapshot and visual observation IDs, source/PDF-page citations, input paths,
  and unresolved questions.
- Routing constraints and reserved areas, required result format, success
  criteria, and explicit stop conditions.

The planner returns alternatives, targets, rationale and tradeoffs. The
reviewer returns independent findings and missing inputs, not authorization.
The executor returns the native result and post-image; it does not invent a
replacement pose or approve itself. A denied/rolled-back/unknown result never
advances the placed inventory.

If the host cannot delegate, use explicit sequential role handoffs and disclose
the lack of independent execution contexts. Do not pretend a skill name is a
callable native subagent type or label self-review as independent review.

## Routing-aware gates

| Gate | Required review |
|---|---|
| Escape/fanout | Pin access, BGA/fine-pitch escape, via technology, layer budget before surrounding placement |
| Corridors/congestion | Reserved channels, bottlenecks, crossing concentration, assembly/access conflicts |
| Critical topology | Device-required topology, differential/matched groups, timing/length feasibility |
| Return paths | Actual reference planes, discontinuities, layer transitions and return continuity |
| Power and sensitive regions | Confirmed switch/current loops, decoupling connections, noisy/sensitive coupling |
| Physical integration | Isolation/keepouts, thermal paths, fabrication, assembly and test access |

Do not defer all small passives: confirmed local bypass and termination parts
belong with their critical groups. A routing bottleneck can require revisiting
placement, but no revision may erase protected constraints or prior approvals.

Use wire-length, crossing and density estimates only as proxies. They cannot
prove detailed routing, impedance, SI/PI, EMI, thermal performance or assembly
success. If a supported trial-routing tool is unavailable, do not invent one.

## Completion and recovery

Maintain separate ledger fields for:

| Field | Rule |
|---|---|
| Placement coverage | Known, nonempty expected inventory; all in-scope parts observed placed |
| Routing review | Each gate reviewed or explicitly justified not-applicable; unknown is not a pass |
| Routing verification | Independent evidence if performed; otherwise `unverified` |
| Native execution | No unresolved/indeterminate requests counted as success |
| Persistence | Saved artifact evidence or an explicit `in memory only` statement |

**Zero expected and zero placed is not completion** when the design has not
been supplied. Planned positions, a successful dispatch, a favorable review,
or an unchanged DRC count are not completion evidence either.

A valid final description may be **fully placed, routing reviewed; routability
unverified**. It must not become **fully routed** or **manufacturing-ready**
without the corresponding independent evidence.

After an uncertain operation, reconcile its exact request/proposal before
continuing. Never retry an Apply, clear unrelated pending state, substitute a
different board, enable writes, change client modes, or answer approval prompts.
Planning may run autonomously; physical changes still require the existing
genuine interactive human-approval workflow.

## Local reference starting points

These guide retrieval, not automatic design rules:

- `40 PCB Design Tips Every Designer Should Know.pdf`, physical PDF pages 20-21:
  fixed/critical placement priorities and escape planning before surrounding parts.
- `addc6240-6ef2-4c26-aef3-3ad945773b19.pdf`, physical PDF page 78:
  functional floorplanning, early critical passives, routing channels and references.
- `8dff1002-5362-4168-84a6-20e1c4b760cd.pdf`, physical PDF page 151:
  congestion feedback into placement. This is a historical P-CAD source; its
  product commands are not Cadence APIs.

Retrieve relevant context for the actual circuit and cite applicable pages.
No textbook, native board, or local evidence artifact is redistributed here.

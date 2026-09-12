# OrCAD placement agent

A local, human-approved placement-access prototype for classic OrCAD X PCB
Editor / Allegro X PCB Editor 25.1 on Windows.

## Install in your coding client

[Installation and marketplace instructions](docs/installation.md) cover Codex,
Claude Code, GitHub Copilot CLI/app, and direct VS Code MCP configuration.
The repository includes portable and Claude-compatible plugin manifests,
marketplace catalogs, shared skills, and a standard local MCP server.

From a trusted checkout, use an existing Python 3.12+ interpreter:

```powershell
& 'C:\path\to\Python3\python.exe' -I -X utf8 scripts\install.py --client all
```

This prepares a versioned environment and non-overwriting client snippets;
it does not edit client settings or install/license Cadence. Marketplace
bootstrapping additionally needs the Windows `py` launcher. Portable installs
are read-only by default; interactive writes require deliberate operator
configuration and genuine human input, never Autopilot or auto-answer hooks.

Development is gated by the [milestones](docs/milestones.md). The synthetic
fixture and native read-only bridge are working in PCB Editor 25.1 S050.
Exact proposal approval and guarded native apply/save handlers are implemented,
but live mutation, rollback, Undo, and saved-revision acceptance still require
explicit approval. `doctor` alone does not establish a licensed connection.

## Development setup

Use a separate Python 3.12+ installation. Do not replace Cadence's runtime or
legacy Python installations. See [setup](docs/setup.md).

```powershell
& '<absolute-path-to-python3.exe>' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m orcad_placement_agent doctor
.\.venv\Scripts\python.exe -m orcad_placement_agent stage-probe
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Intended access boundary

The [`stage` command](docs/design-staging.md) copies the complete containing
design folder, preserving project files and libraries under `design-data`
alongside an isolated editable `working.brd`. Use `--design-root` for a larger
project tree or `--board-only` to copy just the board. File copying does not
implicitly load libraries or change editor settings.

The controller sends bounded requests to a small SKILL adapter in a
dedicated visible editor holding a disposable board copy. Every mutation
requires its exact proposal and fresh board-state preconditions. Library LOAD,
placement APPLY and revision SAVE are separately approved operations.

Arbitrary production boards, raw schematic/netlist import, arbitrary library
acquisition, routing, Presto, headless execution, remote access, and arbitrary
SKILL evaluation remain outside the supported native boundary.

The experimental [placement mission workflow](docs/placement-missions.md)
adds concrete all-component planning, native initial-placement handling and
separate revision-save approval for explicitly staged `managed-board-v1`
designs. It starts with a known imported logical inventory and embedded simple
SMT footprints, including zero physically placed components. Native acceptance
of this new model remains pending; Python/fake-editor tests are not that proof.

[Nonrectangular outlines](docs/nonrectangular-outlines.md) are checked as
complete simple contours, including concave notches and bounded circular-arc
approximation. Both native gates and planning reject footprint crossings;
the outline's bounding rectangle is not treated as usable board area.
Other footprint, routing and native-approval limitations still apply.

[Group-aware constraints](docs/grouped-constraints.md) preserve flat room/net
groups, named physical/spacing/same-net sets, and ROOM assignments instead of
requiring users to delete them. Missing package definitions remain an explicit
library-preparation blocker until separately resolved; group support does not
silently import footprints.

Version 0.9.0 adds [approved library setup](docs/library-loading.md) for
all-unplaced `managed-board-v1` designs with known logical inventory.
The operator uses `attach --library-setup`; `pcb_inspect_libraries` and
`pcb_prepare_library_load` inspect and prepare exact missing definitions from
a bounded, verified staged PSM/PAD/FSM/SSM cache. Only the executor requests
the human's exact LOAD through `pcb_load_libraries`; recover with
`pcb_library_load_status`, never a replay. Loading is non-atomic and in memory
only: partial/uncertain outcomes are possible. It is not import, refresh of
existing definitions, placement, Save, persistence or global configuration.
Full `pcb_inspect` must separately pass the supported placement-geometry gates.
**Native library-load acceptance is pending.**

The supplied `doc` manuals and `pcb_design_book` references remain local-only.
Do not commit them, vendor libraries, or native working board files.
The user-supplied `design` directory also remains local-only.

`stage-probe` copies the trusted read-only SKILL probe to a fresh user-local
directory and prints manual loading instructions. It does not start Cadence,
create a board, or establish live access by itself.

## Development history

Use Git commits for implementation history, with checkpoints after coherent
changes. The source-board fingerprint and proposal digest are safety checks:
they detect source changes and bind approval to exact content. They are not a
version-control system or a substitute for Git.

`stage`, `attach`, `snapshot`, and `reconcile` implement the read-only bridge;
`propose` prepares the exact reviewed pose without changing the board.
The initial native model accepts only the original self-contained synthetic
fixture. A supplied real board can be read using the separate probe, but is
explicitly rejected by the placement adapter rather than treated as safe.
`apply` and `save` remain experimental until M3/M4 acceptance is approved and
completed.

## Built-in PCB expertise

The package ships **36 original guidance cards** covering signal/routing,
power/thermal, and placement/manufacturing. Agents retrieve complete principles,
required inputs, actionable checks, tradeoffs and limits immediately: **no books,
PDF index, model training or extra knowledge setup required**. Bibliography
records development-time synthesis from selected source sections, not runtime
book access. Raw books and copied extracts are not distributed.

[Reference search and rule lookup](docs/reference-search.md) work through MCP,
the app tools and CLI. Local PDFs remain optional enrichment; only their
extraction requires `.[knowledge]`. Retrieval makes no network/model calls.

## PCB expert agents

The [agent workflow](docs/agents.md) provides **PCB placement orchestrator**
above **PCB placement planner**, **PCB layout reviewer**, and **PCB placement
executor**. They use
bundled expertise, distinguish board facts from assumptions, and cite stable
rule IDs (or optional PDF excerpts actually read). All can inspect the bound Cadence image through
bounded tools; none has unrestricted shell or file-edit access.

Start with the installed reference tools and your design inputs; a packet is
optional. To create one without starting Cadence or calling a model:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent agent-context `
    --goal "Review decoupling placement and return paths" `
    --topic decoupling --topic return-paths
```

If using a packet, give its printed path to the planner, then the same packet and its
response to the reviewer. The executor can submit an exact visually grounded
proposal to the [interactive approval workflow](docs/agent-execution.md).
Approval is collected from the human by the host UI, never supplied by the
model. No implicit Save is performed; the selected native model's limits remain.

For a full mission, select **PCB placement orchestrator** or invoke the portable
`pcb-placement-orchestrate` skill. It manages intake, functional floorplanning,
dependency-ordered batches, independent review, execution handoffs and
[routing-aware completion gates](docs/placement-orchestration.md).
It now uses an executable mission engine, not just role handoffs:
`pcb_plan_placement`, `pcb_prepare_next_placement`, and `pcb_placement_status`.
The default fixture model stays unchanged. The explicit managed model implements
initial placement under its restricted geometry/library conditions.
**Raw empty-design import remains an intake blocker. Missing definitions may
use the separate approved setup workflow; unresolved libraries and unsupported
geometry still block placement. Native end-to-end acceptance is not yet
complete.** No empty inventory is reported complete and no routing or electrical
certification is implied.

## Portable clients

The optional [local MCP interface](docs/mcp.md) exposes the bounded tools to
other MCP-capable clients. Install `.[integrations]` from this trusted repository
and use an isolated Python command; do not install an unrelated similarly named
package from a registry. Wheels include the original native runtime assets,
not the local books or board files.

# Visual, approval-gated agent placement

The project extension in `.github\extensions\pcb-placement` connects the
Copilot agents to the existing local Python controller. It exposes bounded
operations, not shell access or arbitrary SKILL evaluation.

## Agent roles

| Role | Native capabilities |
|---|---|
| PCB placement orchestrator | Inspect mission/setup state, track phases and delegate the three workers; no direct prepare/apply/load/save authority |
| PCB placement planner | Inspect the bound board or library setup visually and prepare an exact proposal |
| PCB layout reviewer | Independently inspect placement/setup evidence and read recorded execution outcomes |
| PCB placement executor | Inspect, request exact interactive Apply, LOAD or separate SAVE approval, and inspect the outcome |

All four profiles include `pcb_inspect` and must examine the returned PNG.
None has unrestricted `execute`, `edit`, or `web` tools. Only the orchestrator
has delegation/task-tracking tools, constrained by its PCB-role handoff policy.
If a host does not provide the named tools or image understanding, the agent
must report the missing capability instead of using a shell/GUI workaround.

## Bounded tools

| Tool | Effect |
|---|---|
| `pcb_reference_catalog` | List bundled expertise and stable rule IDs, without books or a board |
| `pcb_reference_search` | Retrieve bounded bundled-rule candidates |
| `pcb_reference_rule` | Read a complete rule with conditions, checks, limits and synthesis provenance |
| `pcb_sessions` | List recorded staged sessions and declared backend scope; neither proves live readiness |
| `pcb_inspect` | Read fresh native state around capture of only the bound Cadence window |
| `pcb_inspection_status` | Report an unresolved read-only snapshot, or reconcile its exact request ID without replay |
| `pcb_inspect_libraries` | Inspect the bound all-unplaced library-setup inventory and actual PNG; not full placement readiness |
| `pcb_prepare_library_load` | Prepare exact missing package definitions from verified staged files with fresh PNG evidence; no loading |
| `pcb_load_libraries` | Obtain exact human LOAD approval and load only the reviewed in-memory definitions once |
| `pcb_library_load_status` | Read/reconcile the exact LOAD outcome without replay; full placement inspection remains separate |
| `pcb_plan_placement` | Plan a complete managed-board mission from explicit requirements and native pin/footprint data |
| `pcb_placement_status` | Reconcile fresh native placement coverage and routing screening |
| `pcb_prepare_next_placement` | Prepare one remaining mission target from fresh state and image |
| `pcb_prepare_placement` | Prepare a supported exact pose, including unplaced managed-board components; no mutation |
| `pcb_apply_placement` | Obtain the human's exact confirmation through the host UI, then apply once in memory |
| `pcb_execution_status` | Read or reconcile the result of an already prepared proposal without replaying it |
| `pcb_prepare_save` | Prepare a visually bound new-revision save proposal, without saving |
| `pcb_save_revision` | Obtain separate exact human SAVE approval and save a new managed revision |
| `pcb_save_status` | Read/reconcile the exact Save result without replay; report reopen separately |

Board tools accept a managed session name such as `board-<id>`, never an arbitrary
directory, executable, native command, or output path. The session must already
be staged and attached by the operator's documented CLI workflow. Do not choose
an unrelated session just because it appears first in the list.

For [library setup](library-loading.md), the operator must explicitly attach
with `--library-setup` to a managed-board-v1 session with known nonempty logical
inventory and no placed symbols. Every role examines the actual setup PNG;
only the planner prepares the verified staged PSM/PAD/FSM/SSM cache proposal,
and only the executor requests LOAD. Loading does not import logical designs,
refresh existing definitions, place components, save, guarantee persistence or
change global settings. It is non-atomic and can leave a partial or uncertain
outcome. Never infer rollback or replay a LOAD; use `pcb_library_load_status`.
Ordinary `pcb_inspect` must still pass full placement gates afterward, including
the separate unsupported-complex-geometry checks.

Bundled reference tools need no session, index, or local textbooks and do not
open Cadence. They accept only a bounded query or stable card ID, not file paths.
The app interface serves bundled synthesis; optional PDF enrichment remains
available through the portable MCP interface or an explicit CLI context packet.

The binding contains the exact PID, HWND, executable and process creation time.
Recorded titles may retain a startup directory; the native full board path and
session handshake are authoritative. Large Windows process timestamps are
represented as decimal strings across the JavaScript tool boundary to avoid
rounding.

## Visual evidence

An observation contains a PNG, capture metadata, and before/after native
snapshot IDs. The board and modeled scene must remain unchanged during capture.
The capture workflow first requests an acknowledged, board-guarded display-only
fit. This changes viewport framing, not component positions. The native adapter
must be the current staged version; a missing fit receipt is an explicit error.
The image and its metadata are immutable, uniquely named files in the managed
session directory; the tool returns the PNG to the model as an image, not merely
a path or a textual description.

Tool text omits opaque native scene blobs to keep the model context readable.
Use the persisted before/after receipt paths for complete machine-readable
data, rather than treating the abbreviated tool display as a native receipt.

Only the bound Cadence window is eligible. No desktop/screen fallback may
capture unrelated applications. A failed, blank, minimized, unavailable, or
ambiguous capture must be reported rather than replaced with an imagined view.
Framing and visible layers limit what an image shows; a screenshot is not
proof of full geometry coverage, DRC, SI/PI, EMI, thermal, or manufacturing
correctness.

To attach an archived observation to a reference packet:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent agent-context `
    --goal "Review the visible placement and reference evidence" `
    --visual '<managed-session>\visual-<observation-id>.json'
```

The packet links the actual PNG and its matching saved snapshot. It remains
archived evidence; use `pcb_inspect` for current state.

## Approval and outcome

The execution tool's model-visible schema contains only session and proposal
identifiers. There is deliberately no `confirmation`, `approved`, `yes`, or
override input for an agent to populate.

The extension reads the frozen proposal and visual binding, displays the exact
refdes/pose/pivot/board, and asks the human to type `APPLY <proposal-id>` through
the host's interactive elicitation UI. No default answer is supplied. Missing
UI support, cancellation, unavailability, or a different answer means no Apply
is dispatched. A planner recommendation or reviewer disposition is not consent.
Before prompting for library setup, the app loader validates access to the
actual proposal PNG. It displays the exact package list and staged asset
filenames, source-relative paths and sizes, then requests `LOAD <proposal-id>`.
Missing image access blocks that prompt; successful access is not proof that
the agents examined the image. Revision saving requests a separately prepared
`SAVE <proposal-id>`. Neither phrase authorizes either of the other operations.
If the operator staged with the optional unverified-3D policy, both snapshot
forms disclose the exact unverified names and warnings; LOAD, Apply and SAVE
descriptions retain the warning. Carry it through every review and handoff.
No tool field can toggle this staging policy, and approval does not verify
3D content or mechanical clearance.

The app extension checks that session mode is `interactive` before and after
the prompt. It refuses Autopilot, plan, unknown modes, and missing mode/UI
support, and never changes modes itself. This matters because clients can
automatically handle elicitation in autonomous modes.

The [portable MCP package](installation.md) is read-only by default and requires
separate operator opt-in for interactive writes. Standard elicitation does not
attest human provenance; auto-answer hooks and unattended modes are unsupported.

For placement, after approval the controller consumes the proposal once and
the native adapter rechecks the full scene. An accepted Windows message is not success:
the explicit native receipt determines `applied`, `rejected`, `rolled_back`,
or `indeterminate`. The tool then captures the resulting placement and compares
that observation with the recorded outcome where available.

If the post-image fails after a move, the native outcome still stands. The
tool reports the visual failure without pretending that the move rolled back.
Use `pcb_execution_status`; never resend Apply or create a duplicate proposal
to evade an uncertain result. Saving remains separate through `pcb_prepare_save`
and `pcb_save_revision`, with `pcb_save_status` for recovery. The extension does
not implicitly save or expose an Undo tool.

A post-operation image may time out on its own read-only snapshot after the
placement receipt is already complete. Execution status preserves that receipt
and reports the pending inspection separately. Use `pcb_inspection_status`
first to identify it, then supply that exact request ID to reconcile its late
result. It refuses a pending placement or a different request; it does not
silently clear unrelated state.

The default native write model remains limited to the original synthetic
fixture. Explicit managed-board-v1 adds conditional initial placement and
separate all-unplaced library setup, not arbitrary real-board support.
A board rejected by the selected full placement model does not become editable
merely because its image is visible or library loading succeeded.

Current native evidence establishes window capture, useful fitted framing,
scene correlation, visually grounded proposal preparation, and denial when
the exact UI response is absent. The first live move has not been dispatched
because approval was not supplied. Apply/rollback/Undo/save acceptance must not
be inferred from successful screenshots or fake-backend approval tests.
Native library-LOAD acceptance is also pending; no successful loading,
partial-failure recovery or persistence is claimed from packaging or mock tests.

## Extension setup and validation

Open this repository in a Copilot host that supports project extensions. The
SDK is supplied by the host; no npm package installation is required. Reload
extensions after changes and ensure `pcb-placement` is ready. A separate
standalone CLI does not automatically provide these app-extension tools.

After upgrading profiles or tools, start a new client session or restart the
client and verify the selected roles' actual allowlists. An extension-only hot
reload may expose new tools without updating pre-existing cached agents. This
occurred with a cached PCB reviewer that still lacked `pcb_inspect_libraries`
and `pcb_library_load_status` despite updated profile source. Reviewing an
archived actual PNG/manifest and reporting that gap does not satisfy a fresh
setup inspection gate.

The reported live LOAD attempt used the genuine human UI directly during
controlled developer acceptance. It was not a completed orchestrator mission
or acceptance of the full three-role live workflow. Its indeterminate native
outcome remains separate from client lifecycle/tool-discovery evidence.

The Python process uses this worktree's `.venv\Scripts\python.exe`. Requests are
JSON on stdin to a fixed module with `shell: false`; responses and images are
bounded. The extension requests no sensitive environment variables or external
model credentials.

Python tests use the existing unittest suite. Extension handler tests can also
run under that suite when `OPA_NODE` identifies an existing Node.js 20+ runtime:

```powershell
$env:OPA_NODE = '<absolute-path-to-node.exe>'
.\.venv\Scripts\python.exe -m unittest tests.test_extension_tools tests.test_agent_actions tests.test_visuals
```

Tests simulate human responses only in isolated fake backends. They do not
authorize live operations. Native movement, rollback, Undo and persistence
claims still require the separately approved live acceptance.

Images returned to Copilot are processed by the configured service/model, just
like reference excerpts. Do not upload them or board files to additional
services. The local runtime and artifacts are not a security boundary against
another malicious process running as the same Windows user.

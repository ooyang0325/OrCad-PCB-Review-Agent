# Visual, approval-gated agent placement

The project extension in `.github\extensions\pcb-placement` connects the
Copilot agents to the existing local Python controller. It exposes bounded
operations, not shell access or arbitrary SKILL evaluation.

## Agent roles

| Role | Native capabilities |
|---|---|
| PCB placement planner | Inspect the bound board visually and prepare an exact proposal |
| PCB layout reviewer | Independently inspect current placement and read recorded execution outcomes |
| PCB placement executor | Inspect, request interactive human approval, apply the exact proposal in memory, and inspect the outcome |

All three profiles include `pcb_inspect` and must examine the returned PNG.
None has unrestricted `execute`, `edit`, `web`, or agent-delegation tools.
If a host does not provide the named tools or image understanding, the agent
must report the missing capability instead of using a shell/GUI workaround.

## Bounded tools

| Tool | Effect |
|---|---|
| `pcb_sessions` | List recorded staged sessions; does not prove which board is open |
| `pcb_inspect` | Read fresh native state around capture of only the bound Cadence window |
| `pcb_inspection_status` | Report an unresolved read-only snapshot, or reconcile its exact request ID without replay |
| `pcb_prepare_placement` | Prepare an absolute millimeter/orthogonal-angle pose linked to current visual evidence; no movement |
| `pcb_apply_placement` | Obtain the human's exact confirmation through the host UI, then apply once in memory |
| `pcb_execution_status` | Read or reconcile the result of an already prepared proposal without replaying it |

Tools accept a managed session name such as `board-<id>`, never an arbitrary
directory, executable, native command, or output path. The session must already
be staged and attached by the operator's documented CLI workflow. Do not choose
an unrelated session just because it appears first in the list.

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

After approval, the controller consumes the proposal once and the native
adapter rechecks the full scene. An accepted Windows message is not success:
the explicit native receipt determines `applied`, `rejected`, `rolled_back`,
or `indeterminate`. The tool then captures the resulting placement and compares
that observation with the recorded outcome where available.

If the post-image fails after a move, the native outcome still stands. The
tool reports the visual failure without pretending that the move rolled back.
Use `pcb_execution_status`; never resend Apply or create a duplicate proposal
to evade an uncertain result. Saving remains separate; this extension does not
implicitly save or expose a Save/Undo tool.

A post-operation image may time out on its own read-only snapshot after the
placement receipt is already complete. Execution status preserves that receipt
and reports the pending inspection separately. Use `pcb_inspection_status`
first to identify it, then supply that exact request ID to reconcile its late
result. It refuses a pending placement or a different request; it does not
silently clear unrelated state.

The initial native write model remains limited to the original synthetic
fixture. A real board rejected by that model does not become editable merely
because its image is visible.

Current native evidence establishes window capture, useful fitted framing,
scene correlation, visually grounded proposal preparation, and denial when
the exact UI response is absent. The first live move has not been dispatched
because approval was not supplied. Apply/rollback/Undo/save acceptance must not
be inferred from successful screenshots or fake-backend approval tests.

## Extension setup and validation

Open this repository in a Copilot host that supports project extensions. The
SDK is supplied by the host; no npm package installation is required. Reload
extensions after changes and ensure `pcb-placement` is ready. A separate
standalone CLI does not automatically provide these app-extension tools.

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

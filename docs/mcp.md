# Portable local MCP interface

`orcad-placement-mcp` and `python -I -m orcad_placement_agent.mcp_server` expose
the same bounded controller through standard **stdio MCP**. No HTTP listener,
cloud service, public endpoint, automatic Cadence startup, or unattended save
is provided.

Install from the trusted checkout:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[integrations]"
.\.venv\Scripts\python.exe -I -X utf8 -m orcad_placement_agent.mcp_server
```

The second command waits for an MCP client; stdout is the protocol. Do not add
banner output to launchers. The optional `integrations` extra uses the official
MCP Python SDK 2.2 series. The underlying controller still supports Windows
classic PCB Editor 25.1. The fixture model remains default; experimental
managed-board-v1 must be explicitly staged and still requires native acceptance.

## Tools

The server exposes `pcb_sessions`, `pcb_inspect`, `pcb_prepare_placement`,
`pcb_apply_placement`, `pcb_execution_status`, and `pcb_inspection_status`.
Inspection/preparation return native PNG image blocks and bounded structured
metadata. Use the saved receipt paths for full native scene data.

`pcb_reference_catalog`, `pcb_reference_search`, and `pcb_reference_rule` expose
36 bundled original PCB rules immediately, without books, a database, or PDF
dependencies. Search returns stable `card_id` citations; rule lookup returns
applicability, required inputs, checks, tradeoffs, failure modes, limits and
development-time bibliography. It does not claim to read original books at runtime.

Optionally set `--knowledge-db <path>` or `OPA_KNOWLEDGE_DB` to enrich results
with local PDF evidence; no database path is accepted from a model argument.
Bundled matches are in `hits`; optional PDF matches are in `supplement_hits`,
with distinct `source_kind` values. Missing/stale/corrupt supplements produce
warnings without disabling real bundled expertise. `pcb_reference_page` is
strictly for original PDF excerpts and errors when no local index is configured.
Install `.[knowledge]` only when extracting PDFs; catalog notices expose gaps.
The server has twenty tools; all reference operations are read-only.

`pcb_inspect_libraries`, `pcb_prepare_library_load`, `pcb_load_libraries`, and
`pcb_library_load_status` implement separate [approved library setup](library-loading.md).
The LOAD tool is default-disabled with other portable writes, uses its own
hidden exact-human approval, and does not place components or save the board.
The operator first uses `attach --library-setup` for explicitly staged,
all-unplaced managed-board-v1 inventory. Preparation is limited to a verified
bounded staged PSM/PAD/FSM/SSM cache. LOAD is non-atomic and in memory only,
with partial/uncertain outcomes possible: it is not import, existing-definition
refresh, placement, Save, persistence or global configuration. Full
`pcb_inspect` is still required afterward and may reject complex geometry.
Native LOAD acceptance is pending.

`pcb_plan_placement`, `pcb_prepare_next_placement`, and `pcb_placement_status`
implement the [closed-loop mission workflow](placement-missions.md). They
return actual images and native-derived planning facts, but do not mutate a
board. `pcb_prepare_save`, `pcb_save_revision`, and `pcb_save_status` provide a
separate visually grounded, one-use SAVE approval and outcome-reconciliation
path. Save success is not automatic reopen verification.

## Human approval across protocol versions

Portable installs are **read-only by default**. Only the operator may add
`--allow-interactive-writes`, and only when the client uses genuine interactive
input with no automatic elicitation answers. The flag is not a model tool
argument, and no installer or marketplace manifest enables it.

Apply, LOAD and SAVE have only `session` and `proposal` as model-visible
arguments. A hidden SDK dependency requests an exact form response. It asks on both
legacy MCP connections and the newer multi-round-trip protocol; the SDK binds
continuation state to the originating request and question.

There is no default answer, model confirmation parameter, per-call override,
or automatic fallback. The response must exactly match the selected operation's
`APPLY <proposal-id>`, `LOAD <load-proposal-id>` or separately prepared
`SAVE <save-proposal-id>`.
Decline/cancel, wrong answers, missing form elicitation, or an unavailable
human do not dispatch the mutation. The client must render genuine human input;
protocol capability negotiation
and an accepted response do not prove a human answered. Copilot Autopilot and
Claude auto-answering elicitation hooks are specifically unsupported for writes.
Annotations and automatic tool-call approval are not substitutes.

The existing controller still rechecks the visually bound proposal and native
scene and consumes approval once. A transport retry cannot approve a second
placement. Missing post-images preserve the recorded native outcome; use the
bounded recovery tools rather than replaying Apply, LOAD or SAVE. Reconcile a
partial/uncertain LOAD with `pcb_library_load_status`; do not claim atomic
rollback or retry to recover a missing image.

## Installed packages

Wheels include the original SKILL adapter, probe, synthetic fixture recipe,
and the three original JSON expertise packs.
They do not include vendor libraries, books, PCB binaries, screenshots, or
indexes. Native staging resolves these trusted package assets rather than
looking in the client's arbitrary working directory.

Generated client commands and capture workers use Python isolated mode so
untrusted working-directory modules or `PYTHONPATH` cannot shadow the installed
controller. No global PATH, Python 2.7, Cadence settings or execution policy
changes are required.

Images and excerpts returned over MCP are processed by the selected client
and model. This is local tool execution, not a promise of offline inference.
Native mutation acceptance remains separately approval-gated.

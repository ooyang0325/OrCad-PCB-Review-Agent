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
classic PCB Editor 25.1 and only the documented synthetic fixture for writes.

## Tools

The server exposes `pcb_sessions`, `pcb_inspect`, `pcb_prepare_placement`,
`pcb_apply_placement`, `pcb_execution_status`, and `pcb_inspection_status`.
Inspection/preparation return native PNG image blocks and bounded structured
metadata. Use the saved receipt paths for full native scene data.

`pcb_reference_catalog`, `pcb_reference_search`, and `pcb_reference_page` read
an operator-configured local index. Set `--knowledge-db <path>` or
`OPA_KNOWLEDGE_DB`; no database path is accepted from a model tool argument.
Install `.[knowledge]` when extracting PDFs. Missing indexes and extraction
gaps are explicit errors/notices, not fabricated expertise.

## Human approval across protocol versions

Portable installs are **read-only by default**. Only the operator may add
`--allow-interactive-writes`, and only when the client uses genuine interactive
input with no automatic elicitation answers. The flag is not a model tool
argument, and no installer or marketplace manifest enables it.

Apply has only `session` and `proposal` as model-visible arguments. A hidden
SDK dependency requests an exact form response. It asks on both
legacy MCP connections and the newer multi-round-trip protocol; the SDK binds
continuation state to the originating request and question.

There is no default answer, model confirmation parameter, per-call override,
or automatic fallback. The response must exactly match `APPLY <proposal-id>`.
Decline/cancel, wrong answers, missing form elicitation, or an unavailable
human do not dispatch Apply. The client must render genuine human input;
protocol capability negotiation
and an accepted response do not prove a human answered. Copilot Autopilot and
Claude auto-answering elicitation hooks are specifically unsupported for writes.
Annotations and automatic tool-call approval are not substitutes.

The existing controller still rechecks the visually bound proposal and native
scene and consumes approval once. A transport retry cannot approve a second
placement. Missing post-images preserve the recorded native outcome; use the
bounded recovery tools rather than replaying Apply.

## Installed packages

Wheels include the original SKILL adapter, probe, and synthetic fixture recipe.
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

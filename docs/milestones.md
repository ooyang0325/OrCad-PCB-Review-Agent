# Development milestones

These are development gates, not dates or GitHub milestones.

| Milestone | Deliverable | Completion condition | Current state |
|---|---|---|---|
| M0 | Isolated environment and synthetic fixture | Python setup plus live, read-only licensed SKILL capability probe | Complete |
| M1 | Reliable read-only live bridge | Externally triggered, correlated board snapshots from the selected editor | Complete |
| M2 | Deterministic proposals and approval | Exact proposals with explicit approval and stale-scene rejection | Proposal flow ready; mutation-dependent cases pending approval |
| M3 | Transactional placement | Approved movement, DRC rollback, accurate readback, and native Undo | Handlers implemented; native acceptance awaiting approval |
| M4 | Explicit persistence and handoff | New-revision save/reopen, source preservation, and documented recovery | Save handler implemented; native acceptance awaiting approval |
| M5 | Local PCB reference grounding | Local extraction/search with page citations, freshness and coverage notices | Complete |
| M6 | Advisory expert agents | Read-only planner/reviewer profiles and bounded, citation-bearing context packets | Complete for Copilot-profile advisory workflow |
| M7 | Visual agent execution | All profiles inspect actual Cadence PNGs; bounded tool execution obtains exact human approval and reports native/post-image outcomes | Visual/tools complete; first live move awaiting exact approval |
| M8 | Portable client distribution | Standard MCP, packaged native assets, safe setup/config generation, and Codex/Claude/Copilot plugin-marketplace manifests | Complete packaging; client prerequisites and repository access required |

The environment doctor is an M0 prerequisite, not completion of M0.
Read-only live access must be established before board-editing work begins.

Python isolation, package setup, read-only diagnostics, trusted probe staging,
and the original fixture specification are implemented. After the user closed
the existing OrCAD session, native probes completed on the empty board and
the saved synthetic working copy in OrCAD X Professional Plus, 25.1-2025 S050.
The original three-component fixture has six connected pins, R3 fixed,
explicit placement bounds, enabled placement rules, and no baseline DRCs.
The Python protocol, request lifecycle, bounded Windows transport, and exact
proposal approval are implemented. Actual Windows-triggered snapshots and native
request parsing now satisfy M1. Fine rule values and rectangle fill are included
in fresh scene preconditions; they are not rounded or silently omitted.
This does not establish native apply, DRC rollback, or persistence.
See [live acceptance](live-acceptance.md).

The initial fixture has a rectangular board/keepin, explicit component
placement bounds, no routing, a few top-side components, one fixed component,
and controlled boundary/keepout or overlap failure cases. Unsupported
geometry must be reported, never silently treated as safe.

Apply changes memory only. Saving a new revision requires a separate request.
No operation may overwrite a source board. Lost completion feedback is an
indeterminate outcome, not a reason to replay a move.

The user requested moving to agent expertise while native mutation approvals
remain outstanding. M5/M6 are an independent advisory track and do not bypass
M2-M4. They add no automatic Apply, Save, model-service credentials, or native
support for arbitrary production boards. See [the agent workflow](agents.md)
and [the original PCB reasoning rubric](pcb-expertise.md).

The initial local library catalog contains 40 PDFs and 5,663 indexed text pages
from 37 documents. Two PDFs are encrypted and one has no extractable text;
partially extracted sources include page-level notices. No OCR or model
training is claimed. Planner/reviewer behavior has been exercised against a
real citation packet, but profile discovery depends on the user's Copilot
client and is not a separate standalone model service.

M7 extends the profiles with named bounded tools, not unrestricted shell access.
The planner prepares visual proposals, the reviewer inspects them independently,
and the execution role uses an interactive approval UI. Visual capture is
limited to the bound Cadence window; a lost image cannot trigger replay of a
completed move. Native mutation acceptance still requires actual approval.

Window-only capture and acknowledged display fitting are working on the
dedicated native fixture. A visually grounded R1 proposal was prepared through
the app tool, but its exact UI confirmation was not supplied. The tool denied
Apply and execution status reports no dispatch. No native move or implicit
save is claimed from that run.

M8 supplies a portable root manifest, a Claude-compatible adapter manifest,
shared skills, two marketplace catalogs, and a local stdio MCP implementation.
The Python installer does not modify client settings or execution policy.
Portable writes are read-only by default because an MCP elicitation response
does not establish human provenance; only an operator may opt into genuine
interactive use without auto-answer hooks. Actual client marketplace UIs and
native write acceptance are not implied by package/SDK conformance.

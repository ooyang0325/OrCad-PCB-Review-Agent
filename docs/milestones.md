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
| M9 | Placement mission coordinator | Fourth agent/portable workflow delegates intake, floorplanning, batches and routing-aware review with explicit inventory/capability gates | Coordinator implemented; now backed by the M11 mission engine |
| M10 | Bundled PCB expertise | Original source-grounded knowledge ships in packages and works through all agent/reference flows without books or an index | 36 cards and no-book retrieval implemented; native capability limits unchanged |
| M11 | Executable zero-placed missions | Concrete all-component targets, initial placement, fresh-readback progression, routing screening and separate revision approval | Managed readback/PNG and six native reader cases pass; initial placement/mutation/save acceptance pending human approval |
| M12 | Nonrectangular outlines | Native line/arc contours and whole-footprint concave containment through mission/proposal/readback | Native contour checks and read-only howto outline extraction pass; unrelated full-board restrictions remain |
| M13 | Preserved group/room constraints | Flat room/net groups, complete named Csets, immutable policy identity and explicit room matching | Implemented; native grouped-Cset reads pass on a separate saved copy; missing package definitions still block full attachment |
| M14 | Complete project staging | Recursive design copy, explicit project root, library inventory, isolated controller and source-preservation checks | Implemented; copying is separate from native library loading and placement |
| M15 | Separately approved library setup | All-unplaced managed-board-v1 setup binding, verified staged PSM/PAD/FSM/SSM cache, exact human LOAD and outcome recovery | Implemented in 0.9.0; native LOAD acceptance pending; full placement geometry and persistence remain separate |

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

M9 adds supervision above the existing three workers. It must distinguish
no logical design from zero physical placements, reject vacuous 0/0 completion,
and report routing review separately from proven routability or completed
routing. M11 now implements initial placement for explicit managed-board-v1
inventory with supported embedded geometry; the default fixture is unchanged.
Adding the coordinator does not import a circuit or make an unsupported
blank-board mission executable. See [placement orchestration](placement-orchestration.md).

M15 adds a separate operator `attach --library-setup` binding for known logical
inventory with no placed symbols. `pcb_inspect_libraries` and planner
`pcb_prepare_library_load` provide actual PNG and verified staged-file evidence;
only the executor requests exact human LOAD via `pcb_load_libraries`.
`pcb_library_load_status` reconciles an exact outcome without replay. Loading
is non-atomic and in memory only, with partial/uncertain outcomes possible; it
is not import, refresh of existing definitions, placement, Save, persistence or
global configuration. A successful LOAD still requires ordinary full
`pcb_inspect`, which can reject unsupported complex geometry. Portable writes
remain default-disabled and require operator opt-in with genuine interactive
input. Native LOAD validation is pending; implementation/tests do not establish
acceptance. See [library loading](library-loading.md).

During M15 read-only setup on 2026-09-12, existing ACIS attachments up to
2,072,773 bytes exceeded the previous 64 KiB guard. Native snapshots now retain
attachment metadata and, under the strict default, streaming SHA-256 fingerprints of every exported byte
under the explicit `sha256-expanded-v1` marker, without truncating or deleting
attachments. Stored and expanded sizes each have an 8 MiB per-attachment limit;
aggregate stored and aggregate expanded sizes each have a separate 16 MiB
limit. Wire bounds remain unchanged.

The signed 32-bit native SHA-256 implementation passed independent Python
`hashlib` comparisons at 0, 1, 55, 56, 63, 64, 65, 511, 512, 513 and 1 MiB
input sizes, covering all byte values and padding boundaries. Native
oversized-budget rejection passed. SKILL `cputime()` reports ticks of
1/60 second; the 1 MiB SHA case took 176 ticks, about 2.93 CPU seconds, not
176 seconds. Fresh hashing contributes to inspection latency;
session round trips now default to 30 seconds, with a 60-second maximum and
one shared dispatch/receipt deadline instead of a separate five-second dispatch
cutoff. These fingerprint/guard results do not establish LOAD acceptance.

Subsequent explicitly authorized unverified-3D setup for `board-trbxtw8s`
returned 46 logical components, 16 missing definitions and an actual PNG.
The setup handshake took 16.78 wall seconds, mostly scene canonicalization;
read-only bound PNG capture and proposal preparation succeeded.
This is evidence for that opt-in setup, not strict 3D-content verification.
After one invocation of the exact-human LOAD tool, all 16 required PACKAGE
definitions were observed in memory, zero symbols were placed, and raw
`psmpath`/`padpath` values were restored. The terminal result nevertheless remains
**INDETERMINATE**: full post-load readback encountered
`Attached text is supported only on a protected placement-room drawing.`
Definition-owned attached text is under diagnosis. This is live evidence of
observed definitions, **not protected-after-state acceptance or an accepted
LOAD**. Native writes are halted; no completion certificate or Save exists.
The original receipt remains indeterminate regardless of later diagnostic
success; it must not be rewritten or treated as a retrospectively accepted LOAD.
The genuine human UI was exercised directly during controlled developer
acceptance, not a completed orchestrator mission or full three-role live
execution acceptance. Extension hot reload exposed the new tools, but a cached
reviewer retained an old allowlist and could inspect only archived PNG/manifest
evidence. Upgrades require a new client session or restart and explicit
role-tool verification.

The optional 3D-content scope is now implemented as operator
`stage --model managed-board-v1 --allow-unverified-3d`, requiring full-folder
staging and rejecting `--board-only`. Schema 4 metadata records
`allow_unverified_3d=true` and binds it to the nonce-bound native bootstrap;
there is no agent-tool policy toggle. Strict verification remains the default.
Only exact nonempty `3D:`/`ACIS` attachment content is waived, without deleting
or modifying models; metadata comparisons and supported non-3D streamed
SHA-256 checks remain. Both snapshot forms disclose exact unverified names and
warnings, retained in LOAD/Apply/SAVE descriptions. This does not establish
3D/mechanical clearance or a fresh accepted native LOAD.

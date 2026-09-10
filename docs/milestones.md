# Development milestones

These are development gates, not dates or GitHub milestones.

| Milestone | Deliverable | Completion condition | Current state |
|---|---|---|---|
| M0 | Isolated environment and synthetic fixture | Python setup plus live, read-only licensed SKILL capability probe | Complete |
| M1 | Reliable read-only live bridge | Externally triggered, correlated board snapshots from the selected editor | Complete |
| M2 | Deterministic proposals and approval | Exact proposals with explicit approval and stale-scene rejection | Proposal flow ready; mutation-dependent cases pending approval |
| M3 | Transactional placement | Approved movement, DRC rollback, accurate readback, and native Undo | Handlers implemented; native acceptance awaiting approval |
| M4 | Explicit persistence and handoff | New-revision save/reopen, source preservation, and documented recovery | Save handler implemented; native acceptance awaiting approval |

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

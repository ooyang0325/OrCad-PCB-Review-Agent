# Development milestones

These are development gates, not dates or GitHub milestones.

| Milestone | Deliverable | Completion condition | Current state |
|---|---|---|---|
| M0 | Isolated environment and synthetic fixture | Python setup plus live, read-only licensed SKILL capability probe | Native read-only probe passed; fixture in progress |
| M1 | Reliable read-only live bridge | Externally triggered, correlated board snapshots from the selected editor | Controller ready; native integration pending |
| M2 | Deterministic proposals and approval | Exact proposals with explicit approval and stale-scene rejection | Controller ready; native acceptance pending |
| M3 | Transactional placement | Approved movement, DRC rollback, accurate readback, and native Undo | Pending |
| M4 | Explicit persistence and handoff | New-revision save/reopen, source preservation, and documented recovery | Pending |

The environment doctor is an M0 prerequisite, not completion of M0.
Read-only live access must be established before board-editing work begins.

Python isolation, package setup, read-only diagnostics, trusted probe staging,
and the original fixture specification are implemented. After the user closed
the existing OrCAD session, a fresh native probe completed on an empty board:
OrCAD X Professional Plus, 25.1-2025 S050. The synthetic fixture is in progress.
The Python protocol, request lifecycle, bounded Windows transport, and exact
proposal approval are implemented; this does not establish native apply,
DRC rollback, or persistence. See [live acceptance](live-acceptance.md).

The initial fixture has a rectangular board/keepin, explicit component
placement bounds, no routing, a few top-side components, one fixed component,
and controlled boundary/keepout or overlap failure cases. Unsupported
geometry must be reported, never silently treated as safe.

Apply changes memory only. Saving a new revision requires a separate request.
No operation may overwrite a source board. Lost completion feedback is an
indeterminate outcome, not a reason to replay a move.

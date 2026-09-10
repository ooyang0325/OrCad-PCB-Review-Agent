# Native M1 acceptance

This is an explicit, opt-in licensed-editor test, not part of unittest discovery.
Use only a dedicated editor with a session staged from the original synthetic
fixture source. Load that session's trusted `bootstrap.il` first. Do not open a
production board or invoke the helper against an unverified PID/HWND.

From the repository root:

```powershell
.\.venv\Scripts\python.exe tests\native\accept_m1.py `
    --session C:\Users\<user>\AppData\Local\OrCadPlacementAgent\sessions\board-<stage> `
    --pid <owned-pid> --hwnd <owned-window-handle>
```

The helper sends **only `opa_snapshot` commands**, using the actual bounded
Windows transport. It requires real, correlated native receipts. It checks
metadata, components, fixed state, complete canonical scene stability, malformed
and partial inputs, nonce/ID mismatches, duplicate publication, and unchanged
source/working files. Reports remain in the local session directory.

`protocol_checks.il` is a separate opt-in pure native validation helper. Stage
and load this original file, then run `opa_m1_protocol_checks`. It checks decimal
grammar, exact DBU positions (including sub-DBU precision traps), exact
orthogonal requested angles, lossless fine numeric changes in scene atoms
and dictionary keys, and the required fill state on each supported geometry
layer. It invokes neither placement nor persistence.

## Native scene representation

`OPA-FIXTURE-1` is a lossless, canonical data representation, not SKILL code and
not a replacement for Git history. It includes all modeled component/pin/pad and
explicit rectangular geometry, properties, connectivity, design DRC modes and
values, physical/spacing/same-net modes and default constraint sets on both
layers, layer material/thickness/polarity, and constraint options. DFA tables
and enabled IC assembly checks are explicitly unsupported; their absence/modes
are checked rather than silently omitted. Equal layer settings share one record
naming both layers; no layer is omitted. Only non-placement audit properties
(`VERSION_ID`, `LAST_SAVED_NAME`, `EDIT_TIME`) are excluded.

Sorted atoms use a front-coded dictionary. Counts below 62 are one base-62
character; larger counts are `~<decimal>;`. Each dictionary entry contains the
shared-prefix length, suffix length, and exact suffix. A delimiter precedes the
tree. Parenthesized lists contain atom indices; repeated lists refer to prior
nodes using `~<base-62-index>`. Dots separate adjacent scalar indices when needed.
`decode_scene` reconstructs the data without evaluating atom text. The native
adapter rejects, rather than truncates, any scene exceeding 8,192 characters.

## Safety and unverified milestones

The public commands are general gates that reject an active editor command.
A private interactive, non-undoable callback performs read-only inspection,
including a restored selection/filter enumeration to reject unmodeled objects.
Apply has a separate private interactive callback registered with `?undo t`;
it never calls `axlShell`, opens a board, or saves a board. The general Save gate
uses a separately approved, fresh managed revision destination.

Claims and closed-result publication prevent request replay. Snapshot caches
contain data only, never DBIDs, and are invalidated on native open/close/save
triggers and adapter mutations. The documented 25.1 trigger interface provides
no undo/redo hook; fresh full-scene comparison is always required. A manual
change followed by undo back to the identical scene is not an observable event
history guarantee. Native undo behavior needs the separately approved tests.

M1 does **not** execute apply, rollback, negative placement cases, native Undo,
or revision Save. Those implementations must remain labelled unverified until
exact mutation and save approvals are supplied and their native receipts,
restoration, and persistence behavior are actually checked.

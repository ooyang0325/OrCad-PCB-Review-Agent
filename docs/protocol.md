# Local adapter protocol (version 1)

The controller sends only registered commands with a 32-character lowercase
hexadecimal request ID. The command line contains no board paths, coordinates,
SKILL expressions, or user-generated code:

```text
opa_snapshot <request-id>
opa_apply <request-id>
opa_save <request-id>
```

The trusted bootstrap binds a private runtime directory, random session nonce,
and exact working-board path. A session is additionally bound to the selected
Windows PID, HWND, process creation time, and executable path. A correlated
read-only handshake is required before the binding is stored.

## Files

Each request is published as `<request-id>.request.csv` in the session
directory. The adapter publishes `<request-id>.result.csv` only after it has
closed the completed result. Partial files are not completion signals.
Existing request/result names are never overwritten.

Fields are printable ASCII, CSV-quoted where needed, with no embedded control
characters or newlines. Limits are 1 MiB per message, 4,096 rows, 16 fields per
row, and 8,192 characters per field. Numeric inputs use finite, bounded plain
decimal notation; expressions, exponents, NaN, and infinity are invalid.

Requests have exactly three rows:

```text
OPA,1,<nonce>,<request-id>,<operation>
params,<snapshot-id>,<refdes>,<x>,<y>,<angle>,<destination>
end,<request-id>
```

For `snapshot`, all six parameter fields are empty. `apply` supplies a prior
snapshot ID, reference designator and absolute target pose; its destination
is empty. `save` supplies a snapshot ID and a managed filename matching
`revision-<32-lowercase-hex-digits>.brd`, with empty pose fields.

Positions are absolute millimeters quantized to the board's DBU scale. The
initial fixture accepts only target angles 0, 90, 180, and 270 degrees.
Rotation is around the component origin; side remains unchanged.

## Results

Results begin with the same session/request identifiers and end with the
matching completion marker:

```text
OPA,1,<nonce>,<request-id>,<status>
message,<explicit explanation>
<zero or more result records>
end,<request-id>
```

| Status | Meaning |
|---|---|
| `snapshot` | A fresh read-only snapshot is available |
| `applied` | The exact approved pose was applied in memory |
| `rejected` | The operation was not permitted |
| `rolled_back` | A failed tentative change was rolled back and restoration established |
| `saved` | The new revision was saved; not merely applied in memory |
| `indeterminate` | The resulting state could not be established; stop further writes |

Record layouts:

| Record | Fields after record name |
|---|---|
| `board` | Full working-board path |
| `units` | Unit name, accuracy, DBU per user unit |
| `version` | Native editor version |
| `snapshot` | Native snapshot identifier |
| `component` | Refdes, package, X, Y, angle, mirrored, fixed, placed |
| `scene` | Canonical native scene description, quoted as CSV data |
| `saved` | Saved revision path |

State flags are `0` or `1`. A valid proposal requires exactly one board,
units, version, snapshot, and scene record and unique component refdes values.
The scene must cover all inputs relevant to the supported fixture, not merely
the selected component. A client-side digest is not a replacement for native
precondition comparison immediately before editing.

Native floating-point scene values use explicit round-trip precision, including
inside shared-list dictionary keys; ambient SKILL print precision must not
merge different rule values. Every modeled rectangle also checks its expected
filled/unfilled state. Unsupported fill or geometry is rejected rather than
omitted from the approval preconditions.

## Approval and uncertain outcomes

The controller stores the complete reviewed snapshot and target pose in a
content-addressed proposal. The operator must enter `APPLY <full-SHA256>`.
A one-use approval record is written before dispatch; retrying the same
approval cannot send the move again. A native state change after review still
causes rejection, even when the proposal file is unchanged.

Saving requires a separate `SAVE <snapshot-id>` confirmation. It neither
overwrites the original source nor implies that Apply automatically saved.

Only one request is in flight. The controller persists `pending.json` before
dispatch. A timed-out send, missing receipt, malformed receipt, or failed
restoration leaves the operation unresolved. `reconcile` only reads a matching
late terminal receipt; it does not resend the command.

If no trustworthy receipt exists, inspect the dedicated board before
abandoning the session and staging a new copy. Do not delete a live lock or
pending record to force another write. This protocol does not promise
exactly-once execution across an editor or controller crash.

The trust boundary is the local Windows user. These controls protect against
accidental replay, stale state, and malformed requests; they do not protect
against another malicious process with the same user's file access.

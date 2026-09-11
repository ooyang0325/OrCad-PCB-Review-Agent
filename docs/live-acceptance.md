# Live acceptance status

## Managed-board mission implementation

The new experimental managed-board-v1 model implements initial placement and
movement for already-logical components with embedded simple SMT footprints.
The mission engine computes complete target sets, preserves existing placed
parts, reserves routing/access regions and reconciles fresh native readback.
MCP/app tools expose the loop and separately approved new-revision saves.
Pure and fake-editor tests exercise these interfaces, but are not native proof.

On 2026-09-11 a fresh copy of the original fixture was opened in a dedicated
25.1 S050 window. Its managed-board handshake and actual before/after PNG
inspection now succeed. The first live read exposed incorrect assumptions
that static tests could not detect:

- Saved boards contain Cadence-owned attachments. These are now preserved in
  the complete scene, not deleted or ignored. Binary exports require `rb` file
  reads; `string` truncates at NUL. Exported data can be decompressed and differ
  in length from native stored size, so both sizes and full bytes are recorded.
- The simple SMT padstack has the legacy pad-suppression flag enabled.
  The flag is preserved alongside actual pad geometry, rather than rejected.
- Surface cross-section entries can have a nil layer type and `SURFACE`
  function. Those entries are retained, including their material data.
- Ordinary logical components have function instances and function-pin links.
  Forward/reverse ownership and definition mappings are now checked and modeled.
- Automatic ratsnests can have `ratsPlaced=t` with `userDefined=nil`. That state
  is recorded; locked/user-defined scheduling remains unsupported.
- Ordinary physical pins report fixed against independent pin movement.
  Component mobility now uses the component/symbol query, which also covers
  fixed children. R1/R2 are correctly movable and R3 remains fixed.
- Objects whose property pointer is nil are not sent to a property API that
  rejects their object type. Nonempty property pointers still require readback.

Six actual read-only native checks passed: all 256 byte values, byte-limit
rejection, repeated complete attachment reads, parent/pin fixed semantics,
logical function mappings and the five-entry fixture cross-section. The
reusable test source is `tests\native\managed_readonly.il`; local reports and
binary test inputs remain outside Git.

First-symbol creation, pose changes, DRC rollback, Undo and save/reopen still
require exact interactive human authorization and native acceptance. The
operator was unavailable when asked to switch from Autopilot to Interactive;
no Apply or Save was inferred or dispatched. This is not yet a demonstrated
end-to-end Cadence placement result. See
[the supported boundary and workflow](placement-missions.md).

To help complete acceptance, keep the dedicated fixture window open, switch
the chat to **Interactive**, and allow the executor to present a fresh exact
proposal. The first documented case moves R1 from (10,10)/0 to (12,12)/90 in
memory only. This is not blanket permission for later cases or Save. A full
initial-placement test additionally needs a separately prepared fixture with
logical components present but physical symbols unplaced; the current fixture
starts with all three symbols placed.

API research used locally installed Cadence engineering notes under
`share\pcb\examples\skill\DOC\FUNCS` and `DOC\QIR\CHANGE`. Their README warns
that entries may be inaccurate or unsupported and their version metadata is
older than 25.1. Documented signatures informed the implementation, but do not
establish licensed native behavior. Those vendor files are not redistributed.

## Current status

The previous startup blocker cleared after the user closed the existing
OrCAD session. A fresh dedicated read-only editor completed the SKILL probe
on an empty board, reporting OrCAD X Professional Plus, 25.1-2025 S050.
The original synthetic fixture was then constructed, saved to a protected
source, copied, reopened, and independently read by the probe. M0 is complete.
The working copy has three placed components, six connected pins, R3 fixed,
millimeter units with 10,000 DBU/mm, and zero baseline DRCs. All three required
placement-rule modes are enabled. Native bridge integration now satisfies M1.

The Python request/receipt protocol, bounded Windows transport, exact
proposal approval and uncertain-outcome handling are implemented. The native
read-only acceptance run covers 19 cases and 18 actual snapshots; 56 pure native
checks cover parsing, exact coordinates/angles, lossless numeric scene identity,
and required geometry fill. The complete scene is 7,977 characters within the
8,192-character bound. Original source and saved working content are unchanged.
Native placement, rollback, Undo, and save/reopen acceptance remain outstanding.

The supplied `design\howto_manufacturing.brd` was opened only through a staged
read-only copy. It contains 46 components. The fixture-scoped placement adapter
explicitly rejected its unsupported topology; this is not support for editing
arbitrary boards. Both the supplied original and copy were left unchanged.

## Pending exact approval

The later visual execution workflow now returns actual, fitted Cadence PNGs
with matching before/after native snapshots. The three fixture components
and keepout are visible; the capture is limited to the bound window, with no
desktop fallback. An exact R1 proposal from (10, 10) / 0 degrees to
(12, 12) / 90 degrees was prepared through the extension. Its interactive
confirmation was not supplied, so Apply was denied before dispatch and the
proposal has no consumed approval. This does not complete M3/M4.

The operator was asked to authorize the bounded synthetic-fixture acceptance
batch below, but was unavailable. No approval was inferred, no Apply or Save
request was executed, and no native mutation acceptance result is claimed.

| Target | Absolute pose in millimeters / degrees | Purpose |
|---|---|---|
| R1 | (12, 12) / 90 | Valid move, followed by native Undo to (10, 10) / 0 |
| R3 | (31, 10) / 0 | Fixed-target rejection |
| R1 | (0, 0) / 0 | Boundary rejection or rollback |
| R1 | (20, 10) / 0 | Overlap rollback |
| R1 | (27, 21) / 0 | Keepout rollback |
| R2 | (20, 12) / 0 | Invalidate an older R1 proposal, then Undo R2 to (20, 10) / 0 |
| R1 | (12, 12) / 90 | Injected post-transform validation failure and rollback, then normal Apply |

All parts stay top-side and rotate about their component origin. Use the
synthetic working copy only, never the supplied board. Saving a new revision
requires separate explicit approval after successful Apply. Regenerate
proposals from the currently bound session; previous editor bindings and
snapshot IDs are invalid after a restart or restaging.

## Read-only bridge workflow

After constructing the fixture, stage its protected source:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage '<fixture-directory>\source.brd'
```

Open only the printed working copy in the dedicated classic editor, load the
printed bootstrap command, list `editors`, then `attach` using its exact HWND
and session path. `snapshot --session <path>` reads fresh state.
`propose --session <path> --refdes R1 --x 12 --y 12 --angle 90` prepares a
reviewable proposal without applying it. The CLI requires exact confirmation
before Apply or Save.

## Historical startup blocker

The isolated Python environment, environment doctor, and read-only SKILL
probe staging are available. The initial native Cadence attempt was blocked as described below.

Observed behavior:

- The installed executable responds to the documented `-versionLong` query.
- A clean, read-only startup in an isolated directory displays:
  "allegro cannot be launched because the application is already running.
  Close the running instance and try again."
- No complete SKILL probe report or synthetic fixture was produced.
- No agent board mutation or save operation was performed.

This is an existing-instance/startup blocker, not evidence that the license
is missing, SKILL is unsupported, or Windows messaging is unavailable.
The owned diagnostic dialogs were closed. Do not terminate unrelated editor
or Cadence service processes or delete shared lock/configuration files to
bypass this gate.

## Follow-up investigation

An existing user layout session and Capture session were observed. The
message/product servers belong to the existing layout session, not this
prototype. They were left untouched. This does not establish which client
or retained process record triggers the startup guard.

The original owned product-help process reports a terminated native exit
status but remains in Windows process listings. Microsoft documents that
process objects can remain while handles exist. That does not establish how
Cadence implements this guard, and is not grounds for closing another
process's handles or repeatedly attempting termination.

Additional supported diagnostics were attempted:

- The installed `allegro_cmd.bat` documents direct executable invocation;
  global PATH/CDSROOT changes are not a justified workaround.
- The installed Presto shortcut targets `orcadx.exe`. It was not used as a
  substitute for the agreed classic PCB Editor target.
- Cadence's `InstallDiagnose` utility was opened, `SPB 25.1` was confirmed,
  and **Run** was invoked. **Repair** was not invoked. The utility exited
  normally, but no result report was captured; this is not a diagnostic pass
  or proof of license entitlement.
- No verified vendor procedure for clearing this exact guard while retaining
  the active user design session was found.

Do not restart shared Cadence services, delete locks, change product
identities, or add undocumented launch flags. Further native work requires a
supported dedicated-session startup or a user-approved session transition.

References:

- [Cadence 25.1 Windows installation guide, diagnostic utility](https://support.ema-eda.com/sites/default/files/OrCAD-Allegro-251-Install-Guide.pdf)
- [Microsoft: terminating a process and process-object lifetime](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process)
- [Microsoft: closing owned Process handles](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.close)

## Fixture acceptance gate

Use only the dedicated classic PCB Editor session, not a user design session.

Prepare the [synthetic fixture](../fixtures/access-proof/README.md) locally,
then stage a fresh probe from the repository root:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage-probe
```

Load the printed trusted bootstrap command in that dedicated editor and run
`opa_probe`. Inspect the generated report and record the actual selected
licensed product separately. A complete report must end with
`probe_complete t` and identify the expected fixture and components.

The current M0 fixture has completed this procedure. Repeat it when rebuilding
the fixture. Python-only results or an installed executable do not satisfy the
gate. M3-M4 remain pending, and no end-to-end placement or persistence
capability is claimed yet.

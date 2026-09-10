# Synthetic access-proof fixture

`create.il` constructs this original fixture in a dedicated, writable classic
OrCAD X / Allegro X PCB Editor. It creates its own embedded padstack and package
definition; no vendor board, footprint, padstack, or example library is used.
`opa_fixture_device.txt` is the original four-record logical device declaration.
Do not commit the resulting `.brd` files, runtime reports, or vendor material.

Use an isolated working directory under the staged probe/session directory.
Keep the source fixture and the agent's disposable working copy separate.

| Item | Specification |
|---|---|
| Units | Millimeters; record the actual accuracy and DBU scale |
| Board outline | Rectangle from (0, 0) to (40, 30), without cutouts |
| Placement keepin | Rectangle from (1, 1) to (39, 29) |
| Components | Three original two-pin, top-side parts; 4 by 2 mm explicit rectangular placement bounds |
| Identifiers | R1, R2, R3 |
| Initial origins | R1 at (10, 10); R2 at (20, 10); R3 at (30, 10) |
| Initial rotation | 0 degrees |
| Fixed target | R3 has the native fixed property |
| Connectivity | Pin 1 of all three parts on TEST_NET; pin 2 on TEST_RETURN |
| Routing | No routed traces, vias, or copper planes |
| Controlled keepout | Rectangle from (24, 18) to (30, 24) |

## Fixed construction recipe

The registered `opa_fixture_create` command accepts no arguments and is not an
agent placement API. Its trusted bootstrap binds `opaFixtureDirectory` to one
fresh ASCII directory named `fixture-*` beneath
`%LOCALAPPDATA%\OrCadPlacementAgent\sessions`.

The command refuses existing destination files and anything except a new
`unnamed.brd` in that exact directory. Its nonempty-board checks cover logical
objects, definitions, shapes, and all selectable figures, including invisible
figures. The sole permitted figure is the editor's immutable drawing-origin
marker. It never opens or replaces an arbitrary input board.

Construction uses a short native transaction with rollback on failure. Units
are set before the transaction. After geometry/connectivity/fixed/rule checks
pass, the transaction is committed and baseline DRC is run. The native save
performs the normal database check, creates **`source.brd` once**, copies it to
**`working.brd`**, and reopens only that disposable copy. The source must never
be saved again. The forced-open mode is used only after the newly constructed
board has been saved; it is not exposed for opening other boards. This 25.1
build still presents an existing-file confirmation when reopening the copy.

Any failure is visible as `OPA FIXTURE: ...` in the editor command pane.
Do not bypass the guards or delete an original source to retry. Investigate the
failure and use a new dedicated directory/empty editor.

## Run from the repository root

Use the licensed classic editor, not Presto or a viewer. Obtain operator
approval for fixture construction first, and close only an owned empty probe
editor if replacing a read-only session. Do not close user/production boards.
The following stages only project-authored inputs and a trusted startup script;
it does not change global Cadence configuration:

```powershell
$editor = 'C:\Cadence\OrCADX_25.1\tools\bin\allegro.exe'
$root = Join-Path $env:LOCALAPPDATA 'OrCadPlacementAgent\sessions'
$runtime = Join-Path $root ('fixture-' + [guid]::NewGuid().ToString('N'))
if ($runtime -match '[^\x00-\x7f]') { throw 'An ASCII runtime path is required.' }
New-Item -ItemType Directory -Path $runtime -ErrorAction Stop | Out-Null
Copy-Item 'fixtures\access-proof\create.il','fixtures\access-proof\opa_fixture_device.txt' $runtime
$bootstrap = Join-Path $runtime 'bootstrap.il'
$script = Join-Path $runtime 'fixture.scr'
$runtimeLiteral = ConvertTo-Json -InputObject $runtime -Compress
$createLiteral = ConvertTo-Json -InputObject (Join-Path $runtime 'create.il') -Compress
$bootstrapLiteral = ConvertTo-Json -InputObject $bootstrap -Compress
[IO.File]::WriteAllText($bootstrap,
    "opaFixtureDirectory = $runtimeLiteral`nload($createLiteral)`n",
    [Text.Encoding]::ASCII)
[IO.File]::WriteAllText($script,
    "setwindow pcb`nskill load($bootstrapLiteral)`nopa_fixture_create`n",
    [Text.Encoding]::ASCII)
$owned = Start-Process -FilePath $editor -WorkingDirectory $runtime -PassThru `
    -ArgumentList @('-safe','-orcad','-p',$runtime,'-s',$script)
$owned.Id
Wait-Process -Id $owned.Id
```

If the native existing-file confirmation appears, check that it names **only
the new `$runtime\working.brd`**, then choose **Yes** to complete opening that
copy. Never confirm a prompt naming `source.brd` or a user board. The observed
confirmation did not change either saved file's hash.

Keep the launching session attached while the editor is in use. Do not add
`-readonly`: this recipe creates a new synthetic database. No production board
path is accepted. A window title or successful command dispatch is not proof
that SKILL completed; read the actual receipt.

After the command completes, inspect `$runtime\fixture-receipt.txt` and require
`fixture_verified t`. It is written only after the saved working copy has been
reopened and checked. The controller's staging step automatically checks that
the source and newly copied working board match and protects the source from
later changes. Do not maintain a manual checksum history; use Git commits for
the project-authored fixture inputs.
Stage the independent read-only access probe with:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage-probe
```

Load that fresh stage's printed `load_command` into the dedicated editor and
run `opa_probe`. Its separate local report must identify `working.brd`, contain
three components, and end with `probe_complete t`. Neither this probe nor the
construction receipt proves licensed entitlement beyond the observed session.

## Native geometry and capability surface

The recipe was executed and its saved copy reopened in classic OrCAD X
Professional Plus **25.1-2025 S050**. The observed database units are
`("millimeters" 4 10000)`: four decimal places, 10,000 DBU/mm.

| Native object | Recorded geometry / attributes |
|---|---|
| `OPA_FIXTURE_SMD` | Embedded, undrilled top-only rectangular SMT pad, 0.8 by 1.0 mm |
| `OPA_FIXTURE_TWO_PIN` | Embedded package; pin offsets (-1.2, 0), (1.2, 0) mm |
| Place bound | Filled rectangle on `PACKAGE GEOMETRY/PLACE_BOUND_TOP`, relative (-2, -1)-(2, 1); `PACKAGE_HEIGHT_MAX` 1 mm |
| R1 bounds | (8, 9)-(12, 11) mm |
| R2 bounds | (18, 9)-(22, 11) mm |
| R3 bounds | (28, 9)-(32, 11) mm; native `FIXED` property on the physical symbol |
| Outline | Unfilled rectangles on `BOARD GEOMETRY/DESIGN_OUTLINE` and legacy `BOARD GEOMETRY/OUTLINE` |
| Keepin | Unfilled native `PACKAGE KEEPIN/ALL` polygon |
| Keepout | Filled native `PACKAGE KEEPOUT/TOP` shape |
| Silkscreen | Original small unfilled rectangle per package; not used as placement bounds |

Logical components expose `name`, `package`, `symbol`, and `pins`. Their physical
symbols expose `xy`, `rotation`, `isMirrored`, `children`, and `etchChildren`.
Pin `number`, `net->name`, `xy`, `name` (padstack), and `definition` establish
physical connectivity. Use `axlDBIsFixed(symbol)` rather than interpreting the
root design's `readOnly` attribute. That root attribute is always true; a new
writable board can also initially have `axlSaveEnable()` return nil. In this
build the raw symbol `readOnly` attributes also reported `t`, while the native
`axlDBIsReadOnly(symbol)` API correctly returned `nil` for all three. Use the
native API; do not infer access mode from the raw attribute.

Explicit child shapes/polygons expose `layer`, `bBox`, `isRect`, `nSegs`, and
`segments`; each segment exposes `objType`, `startEnd`, and `width`. Verification
requires native `isRect t` and four segments. The receipt uses the actual
place-bound child, never the symbol's generic bounding box.
`design->designOutline` and `design->keepinPlace` expose native boundaries;
`axlDBGetShapes("PACKAGE KEEPOUT/TOP")` exposes the controlled keepout.
Cached DBID attributes must be refreshed after construction; saving/opening
invalidates prior DBIDs.

The following design rules were available and enabled (`on`), with master
`drcEnable t`, `drcState t`, and **zero baseline DRCs**:

- `Package_to_Package_Spacing`
- `Package_to_Place_Keepin_Spacing`
- `Package_to_Place_Keepout_Spacing`

The native baseline call is `axlDRCUpdate(nil)`; its mode argument is required.
`axlCNSDesignModeGet` reports rule availability/settings, `axlDRCItem` can check
objects, and `design->drcs` exposes markers. Documented marker attributes include
`name`, `type`, `xy`, `actual`, `expected`, `source`, and `violations`; this clean
baseline has no violation instance with which to prove every marker field.
Native file copying uses `axlOSFileCopy(source working nil)`, not `copyFile`.
These are observations for this installed build, not a cross-version promise.

Required cases include an allowed R1 translation/rotation, an attempted R3
move, an R1 move outside the board, an R1/R2 overlap, and an R1 move into the
keepout. **Those mutation/negative cases are not executed by this recipe.**
Construction and native baseline access are verified; the fixture is not yet
accepted for agent placement until exact separately approved cases demonstrate
the expected native violations, rollback, and persistence behavior.

Fixture construction is operator-assisted M0 setup. It is not an agent
initial-placement capability.

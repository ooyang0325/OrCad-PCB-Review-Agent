# Local setup

## Prerequisites

- Windows and a separately installed Python 3.12+ interpreter.
- Classic OrCAD X PCB Editor / Allegro X PCB Editor 25.1 with a suitable license.
- A disposable, synthetic board fixture. Never start with a production design.

Installation detection is not proof of license entitlement or API support.
Those are the M0 live capability gate.

## Python isolation

Use an absolute interpreter path to avoid accidentally invoking Python 2.7.
Create a repository-local virtual environment and install this package:

```powershell
& '<absolute-path-to-python3.exe>' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

On the initial development machine, a separate Python 3.13 interpreter is
installed under `%LOCALAPPDATA%\OrCadPlacementAgent\Python313`. Its installer
does not replace Python 2.7, change PATH, install a launcher, or change file
associations.

No third-party runtime packages are required. The package uses setuptools as
its build backend and Python's built-in unittest runner.

## Read-only discovery

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent doctor --json
```

The default editor location is
`C:\Cadence\OrCADX_25.1\tools\bin\allegro.exe`. Override it with
`--cadence-root <installation-directory>`.

The intended runtime location is
`%LOCALAPPDATA%\OrCadPlacementAgent\sessions`. Override it with
`--runtime-dir <ASCII-safe-directory>`. Repository paths may contain Unicode;
only the Cadence staging/transport directory must initially be ASCII-safe.
The doctor command creates neither directory nor board files.

Exit code 0 means environment prerequisites were found, not that a licensed
editor connection exists. Code 1 reports unavailable prerequisites; code 2
reports invalid configuration or an inaccessible path.

## Native editor safety

For complete design staging, see [design-folder copying](design-staging.md).
The default includes the selected board's containing folder and nested
supporting files; controller code remains separate. Save source changes first,
and do not mistake copied library files for definitions loaded into the editor.

Use a dedicated visible classic PCB Editor session. Do not alter global
`allegro.ilinit`, vendor installation files, or shared Cadence settings.
Native Apply and Save handlers are present, but their live acceptance remains
approval-gated. Do not treat implementation or read-only snapshots as proof
that transaction rollback, Undo, or revision persistence has been established.

## Stage and run the M0 read-only probe

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage-probe
```

This stages our original `skill\probe.il` and trusted bootstrap in a new
ASCII-safe directory. It prints the exact `skill load(...)` command; paste
that command into the dedicated classic PCB Editor, then run `opa_probe`.
Do not load this command into a production-board session.

Use the [fixture specification](../fixtures/access-proof/README.md) to prepare
the small local board. The one-shot probe only reads board metadata and
component identities. It reports available required functions but does not
execute placement, DRC update, or save operations.

Inspect the emitted `probe-report.txt`. A complete report ends with
`probe_complete t`; an absent or incomplete report is not success. Stage a
new probe directory to retry rather than reusing an existing result.

Record the selected licensed product separately. Function availability and
the product display name do not prove entitlement to every operation.
Do not proceed to M1 until a suitable licensed session and the local fixture
are available and the probe completes on that fixture.

The resolved startup history, current milestone evidence, and pending approval
are recorded in [live acceptance](live-acceptance.md). Do not mistake the staged
probe files alone for a successful live run.

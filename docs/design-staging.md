# Copy a complete design for staging

`stage` copies the selected board's **containing folder recursively** by default,
including project data, package footprints, padstacks, flash symbols, schematics,
netlists and subfolders. It does not move or overwrite source files.

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage `
    'C:\design\your-board.brd' --model managed-board-v1
```

The resulting layout separates copied project data from the controller:

```text
board-<id>\
  working.brd              <- open this copy in the dedicated editor
  bootstrap.il            <- load only this generated bootstrap
  adapter.il
  placement.il
  managed_board.il
  protocol.il
  session.json
  design-copy.json         <- copied-file inventory, fingerprints and exclusions
  design-data\
    your-board.brd         <- preserved project snapshot; not the working board
    cap0603.psm
    cap0603.pad
    ...
```

Files retain their relative paths, bytes and modification times. Empty included
directories are preserved. A project file named `session.json`, `bootstrap.il`,
`adapter.il`, `allegro.ilinit` or `env` stays under `design-data`; it cannot replace
the trusted files in the session root. Copied scripts are **data**, not executed
or automatically loaded.

## Include sibling library folders

For this layout:

```text
C:\design\project\
  allegro\your-board.brd
  libraries\packages\...
  libraries\pads\...
```

Select the common project root explicitly:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage `
    'C:\design\project\allegro\your-board.brd' `
    --model managed-board-v1 --design-root 'C:\design\project'
```

The tree appears under `design-data\allegro`, `design-data\libraries`, and so on.
The editable board is still the session-root `working.brd`.

Use a dedicated project directory, not a drive or home folder. External
references outside the selected root are **not followed or rewritten**. Choose
an appropriate `--design-root` for project-owned sibling assets; this is not an
automatic dependency resolver for arbitrary external libraries or absolute paths.

## Optional, explicit unverified-3D policy

**Strict attachment-content verification remains the default.** The following
is an opt-in example only for an operator who has explicitly chosen to waive
the limited 3D-content check; it is not recommended default setup:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage `
    'C:\design\your-board.brd' --model managed-board-v1 --allow-unverified-3d
```

`--allow-unverified-3d` requires `managed-board-v1` and full design-folder
staging. It cannot be combined with `--board-only`; use `--design-root` if the
project includes sibling assets. The opted-in session uses schema 4 metadata
with `allow_unverified_3d=true` and a nonce-bound native bootstrap. This is an
operator choice at staging, not a mutable agent-tool field or permission to
edit an existing session's metadata.

Only attachment names matching `3D:<nonempty-name>` with the exact `ACIS`
class qualify. Their **content verification only** is waived: there is no
3D-model deletion or modification, and their metadata remains in native state
comparisons. Supported non-3D attachments retain full streamed SHA-256 content
protection. The flag does not suppress arbitrary attachment errors or change
placement geometry, library, approval or persistence requirements.

Both full-placement and library-setup snapshots disclose the exact unverified
3D names and warnings. LOAD, Apply and SAVE descriptions retain the warning;
agents must carry it through review and handoff. This policy does **not** verify
3D models or mechanical clearance. Library setup remains all-unplaced, and
neither staging nor this flag authorizes a LOAD.

## Explicit single-board mode

To retain the original behavior:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage `
    'C:\design\your-board.brd' --model managed-board-v1 --board-only
```

`--board-only` cannot be combined with `--design-root` or
`--allow-unverified-3d`. Existing single-board and strict design-folder session
schemas remain readable. Design-folder sessions bind their copy manifest to
the session metadata; the optional unverified-3D policy uses schema 4 as
described above.

## What is excluded

The copy report lists exclusions. Defaults exclude:

- Version-control, environment and cache entries: `.git` (file or folder),
  `.hg`, `.svn`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.runtime`,
  `.copilot`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`.
- Locks, logs, journals, temporary files and backups: `.lck`, `.lock`, `.log`,
  `.jrl`, `.tmp`, `.temp`, `.pyc`, `.pyo`, `.bak`, `.swp`, `.swo`, Office `~$`
  files and Cadence numbered backups such as `board.brd,1`.
- Runtime/OS metadata such as `.inflight`, `.DS_Store`, `Thumbs.db`, `desktop.ini`.
- The configured staging-output subtree when it is inside the design tree.
  Newly created ancestors used solely for that output are excluded too.

The copier never recursively follows symlinks, junctions, or unknown reparse
points. Recognized OneDrive/cloud placeholders can be read as ordinary project
data; unavailable data produces an explicit error rather than an empty copy.
Case-insensitive destination collisions and invalid Windows filenames are rejected.

On Windows, no-follow attribute handles pin the input ancestor chain during
resolution, enumeration and copying, denying replacement or concurrent writes.
An input that resolves to a different location is rejected, not adopted as a
new project root. A sharing/access error requires closing writers or making
cloud files available locally; staging does not relax the guard to proceed.

## Copy limits and integrity

Limits are 10,000 files, 20,000 traversed entries, 32 directory levels,
512 MiB per file and 2 GiB total included file data. Exceeding a limit stops
staging; it does not silently omit the remaining design.

Save project changes before staging. Copying reads files on disk, not unsaved
Cadence or Capture state. File identity, size, modification time and content
are checked during copying, followed by a rescan of included paths. Changed,
added or removed included files stop publication of `session.json`. A mid-copy
failure reports its partial artifact directory; that directory is not a usable
published session. No partial copy is presented as success.
Verification reads are bounded to the expected file size plus one byte for
growth detection, including the selected board and copied-file rereads.

Fingerprints record copy preservation, not development history. Use Git for code
history. Supporting files are a frozen staging-time snapshot and do not
automatically synchronize after the source project changes.

## Library availability is not library loading

Output reports the copied `psmpath` and `padpath` **candidate directories**, plus
package/padstack/flash counts. Duplicate library filenames in separate folders
are preserved and flagged. The separate bounded loader rejects conflicting
same-named file contents; it does not choose a search-order winner.
Non-ASCII library-directory paths are reported for native compatibility review.

**Staging does not configure Cadence paths or load package definitions.**
It also does not open the editor, import a netlist, place components or save a
board. The copied files make subsequent [explicit library setup](library-loading.md)
possible. For all-unplaced managed-board-v1 inventory, `attach --library-setup`
binds the staged editor without claiming full placement readiness. Preparation
verifies staged PSM/PAD/FSM/SSM files and creates a bounded cache; only a separate
exact human LOAD authorizes in-memory definition loading. Full placement
inspection remains required afterward and can reject unsupported geometry.
Loading is non-atomic, may be partial/uncertain, and does not refresh existing
definitions or establish persistence. Native LOAD acceptance is pending.

Add `--json` for a structured result containing the session/working-board paths,
load command, copy counts, library directories and warnings. Recorded sessions
also expose the copy summary through the existing session-listing tool.

The supplied howto project was exercised locally: 109 files were copied,
including 18 `.psm`, 20 `.pad` and one `.fsm`, with 49 runtime/cache exclusions.
The copied bytes matched the source. No native library load or board edit was
performed by that copy check.

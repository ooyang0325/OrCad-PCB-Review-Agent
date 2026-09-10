# OrCAD placement agent

A local, human-approved placement-access prototype for classic OrCAD X PCB
Editor / Allegro X PCB Editor 25.1 on Windows.

Development is gated by the [milestones](docs/milestones.md). The synthetic
fixture and native read-only bridge are working in PCB Editor 25.1 S050.
Exact proposal approval and guarded native apply/save handlers are implemented,
but live mutation, rollback, Undo, and saved-revision acceptance still require
explicit approval. `doctor` alone does not establish a licensed connection.

## Development setup

Use a separate Python 3.12+ installation. Do not replace Cadence's runtime or
legacy Python installations. See [setup](docs/setup.md).

```powershell
& '<absolute-path-to-python3.exe>' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m orcad_placement_agent doctor
.\.venv\Scripts\python.exe -m orcad_placement_agent stage-probe
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Intended access boundary

The controller sends bounded requests to a small SKILL adapter in a
dedicated visible editor holding a disposable board copy. Every change will
require approval of its exact target pose and current board state. Apply and
save will be separate operations.

AI optimization, arbitrary production boards, initial placement, routing,
Presto, headless execution, remote access, and arbitrary SKILL evaluation are
outside the initial release.

The supplied `doc` manuals and `pcb_design_book` references remain local-only.
Do not commit them, vendor libraries, or native working board files.
The user-supplied `design` directory also remains local-only.

`stage-probe` copies the trusted read-only SKILL probe to a fresh user-local
directory and prints manual loading instructions. It does not start Cadence,
create a board, or establish live access by itself.

## Development history

Use Git commits for implementation history, with checkpoints after coherent
changes. The source-board fingerprint and proposal digest are safety checks:
they detect source changes and bind approval to exact content. They are not a
version-control system or a substitute for Git.

`stage`, `attach`, `snapshot`, and `reconcile` implement the read-only bridge;
`propose` prepares the exact reviewed pose without changing the board.
The initial native model accepts only the original self-contained synthetic
fixture. A supplied real board can be read using the separate probe, but is
explicitly rejected by the placement adapter rather than treated as safe.
`apply` and `save` remain experimental until M3/M4 acceptance is approved and
completed.

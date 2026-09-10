# OrCAD placement agent

A Windows-only, human-approved PCB Editor access prototype. This first
development step provides read-only environment discovery, not board access.

Use a separate Python 3.12+ interpreter without replacing Python 2.7 or changing
Cadence settings:

```powershell
& '<absolute-path-to-python3.exe>' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m orcad_placement_agent doctor
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`doctor` checks local prerequisites without starting Cadence. Licensed live
access remains unproven. Keep supplied manuals, books, designs, and generated
board files local-only. Use Git for implementation history.

# Live acceptance status

## Current status

The previous startup blocker cleared after the user closed the existing
OrCAD session. A fresh dedicated read-only editor completed the SKILL probe
on an empty board, reporting OrCAD X Professional Plus, 25.1-2025 S050.
The original synthetic fixture was then constructed, saved to a protected
source, copied, reopened, and independently read by the probe. M0 is complete.
The working copy has three placed components, six connected pins, R3 fixed,
millimeter units with 10,000 DBU/mm, and zero baseline DRCs. All three required
placement-rule modes are enabled. Native bridge integration is in progress.

The Python request/receipt protocol, bounded Windows transport, exact
proposal approval and uncertain-outcome handling are implemented. Native
placement, rollback, and save/reopen acceptance remain outstanding.

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

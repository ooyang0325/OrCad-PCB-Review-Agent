# Agent-assisted footprint loading

Copying project files makes libraries available on disk; it does not embed
their definitions in an open Cadence database. Library preparation is now a
separate, exact-approval workflow before placement.

Version 0.9.0 implements this bounded setup path. **Native LOAD acceptance is
pending**; documentation, packaged tools and Python/fake-editor tests do not
establish native loading, failure recovery or persistence.

## Short operator workflow

1. Stage the complete design folder with `stage --model managed-board-v1`.
   Keep package `.psm`, padstack `.pad`, and flash/shape `.fsm`/`.ssm` files
   within the selected project tree. Use `--design-root` for sibling libraries.
2. Open only the printed `working.brd` in a dedicated classic editor and load
   its generated bootstrap.
3. If package definitions are missing and every logical component is unplaced,
   attach for **library setup only**:

   ```powershell
   .\.venv\Scripts\python.exe -m orcad_placement_agent attach `
       --session '<printed-session-folder>' --hwnd 123456 --library-setup
   ```

   Replace the folder and window number with the actual values. This binding
   establishes the correct board/window, not full placement readiness. It is
   available only for explicitly staged `managed-board-v1`, not the default
   fixture model. Placed or empty designs are blockers, not permission to remove
   parts or invent a logical inventory.
4. In an **Interactive** client, ask the agent:

   > Inspect library setup for session `board-XXXX`. Prepare the missing
   > package definitions from its staged project files, show me the exact
   > package/file list and image, and request my LOAD approval. Do not place
   > components or save the board.

The planner calls `pcb_inspect_libraries` and `pcb_prepare_library_load`;
the reviewer independently checks the exact package/file list and actual PNG.
Only the executor requests the exact human phrase through `pcb_load_libraries`.
The coordinator delegates only these bounded roles and never loads directly.
`pcb_library_load_status` reads or reconciles the outcome without repeating it.
No model-visible `confirmation` field is accepted by the app/MCP tools.

CLI equivalents are `libraries inspect`, `libraries prepare`, `libraries load`
and `libraries status`, each with `--session`; load/status also take the exact
`--proposal`. CLI load requires an interactive terminal and an exact LOAD phrase.
Never manufacture input through a script, pseudo-terminal or auto-answer hook.

## Optional 3D-content exception, never the default

Strict verification remains the default. Only if the operator explicitly
waives content verification for the supported 3D attachment class may they
stage a fresh copy with:

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent stage `
    'C:\design\unplaced.brd' --model managed-board-v1 --allow-unverified-3d
```

This optional example is not recommended default enablement. The flag requires
**full design-folder staging** and cannot be combined with `--board-only`.
The resulting schema 4 session records `allow_unverified_3d=true` in metadata
and binds the policy into its nonce-bound native bootstrap. Agents cannot
toggle the policy through tool fields or by editing session metadata. Continue
with the separate operator `attach --library-setup` step above; the logical
inventory must still be nonempty and entirely unplaced.

Only attachments named `3D:<nonempty-name>` of the exact `ACIS` class may skip
content checks. The models are not deleted or modified; their metadata still
participates in native comparisons. All supported non-3D attachments remain
fully protected by streamed SHA-256 fingerprints. Other attachment failures
remain blockers.

Full-placement and setup snapshots report the exact unverified names and
warnings, and LOAD, Apply and SAVE descriptions retain that warning. Preserve
these disclosures in every review and handoff: neither 3D-content integrity nor
3D/mechanical clearance is verified for the waived models. The flag does not
approve a LOAD, waive geometry checks or change an earlier indeterminate result.
See [the staging policy](design-staging.md#optional-explicit-unverified-3d-policy).

## What preparation does

The read-only `library-setup-v1` snapshot is intentionally different from a
placement snapshot. It requires known nonempty logical inventory and no physical
symbols, and retains the supported board/constraint/group state plus existing
library data. It does not invent unplaced pin coordinates or footprint bounds.
It cannot authorize placement or Save.

The controller matches missing package names to the staged `.psm` inventory.
It includes the staged padstack and flash/shape support files, verifies their
staging fingerprints, and creates a separate flat `library-<id>` cache. Unused
package `.psm` files are not loaded. Conflicting same-named files with different
content are rejected rather than choosing a search-order winner. Identical
duplicates are deduplicated deterministically.

Only package roots from the captured native inventory are requested. The
prepared cache contains no scripts, and the native operation never searches
arbitrary model-supplied paths. Asset count/size bounds and file identities are
checked before loading.

## Attachment preservation and inspection latency

Cadence-owned attachments remain in the board. By default, fresh native snapshots
preserve their metadata and a streaming SHA-256 fingerprint of **every exported byte**,
explicitly marked `sha256-expanded-v1`. This is a hash-based state-preservation
check, not truncation, attachment deletion or a backup of the exported payload.
The exported/expanded size can differ from the stored native size.

The attachment limits are **8 MiB per attachment**, checked independently for
stored and expanded sizes, and **16 MiB aggregate stored** plus a separate
**16 MiB aggregate expanded** limit. Under the strict policy, oversized or
unreadable attachments are blockers, not permission to omit them. Only the
explicitly scoped 3D-content exception above can waive that content check;
non-3D protection is unchanged. These are attachment-processing budgets;
the existing 1 MiB wire bound is unchanged because snapshots carry fingerprints,
not the exported attachment bytes.

Read-only setup encountered ACIS attachments up to 2,072,773 bytes, exposing the
previous 64 KiB guard. The signed 32-bit native SHA-256 implementation matched
independent Python `hashlib` results at 0, 1, 55, 56, 63, 64, 65, 511, 512, 513
and 1 MiB input sizes, covering all byte values and padding boundaries; native
oversized-budget rejection also passed. These checks validate the fingerprint
primitive and size guards, **not full setup or LOAD acceptance**. The current
native run status is recorded below; fingerprint checks alone do not establish
protected post-load state.

Fresh snapshots must export and hash these attachments, so inspection can take
longer, particularly when PNG capture requires before/after native reads.
The installed SKILL documentation defines `cputime()` units as ticks of
1/60 second: the 1 MiB SHA test's 176 ticks are about **2.93 CPU seconds**,
not 176 seconds. The successful opt-in setup handshake took **16.78 wall
seconds**, mostly in scene canonicalization. CPU benchmark time and complete
handshake wall time are different measurements.
The session's bounded round-trip timeout now defaults to **30 seconds**, with
a **60-second maximum**. Dispatch and native-receipt waiting share that deadline;
dispatch no longer has a separate five-second cutoff while native hashing
continues. This is a per-round-trip bound, not a promise that an entire
multi-read visual inspection completes in 30 seconds. A timeout is not evidence
of a successful inspection or a reason to replay a LOAD; use the exact pending
read or proposal recovery path.

## Current native evidence: outcome remains indeterminate

The explicitly authorized unverified-3D setup for `board-trbxtw8s` returned
native inventory and an actual PNG: 46 logical components and 16 missing
package definitions. Read-only bound PNG capture and proposal preparation also
succeeded. This used the optional 3D-content exception, not a pass
of strict attachment-content verification. The exception does not delete or
modify 3D models; their metadata remains checked and reported, while supported
non-3D attachments retain full streamed SHA-256 protection. It does not verify
3D models or mechanical clearance.

The exact-human LOAD tool was invoked once, directly through the genuine human
UI during controlled developer acceptance. This was not a completed
orchestrator mission or full three-role live execution acceptance: a cached
reviewer lacked the new fresh-setup tools and reviewed archived actual PNG/
manifest evidence only. After upgrading, start a new client session or restart
the client and verify each role's tool availability; extension-only hot reload
is insufficient evidence. See [agent lifecycle requirements](agents.md).

All 16 required PACKAGE definitions
were subsequently observed **in memory**, with zero symbols placed and the
raw `psmpath`/`padpath` values restored. However, the terminal outcome is
**INDETERMINATE**, not an accepted or certified load: full post-load readback
stopped at `Attached text is supported only on a protected placement-room drawing.`
The definition-owned attached-text case is under diagnosis. Later diagnostic
success cannot retrospectively change that original indeterminate receipt.

These are live observations, not fake-editor tests. Observing the definitions
does not establish protected-after-state acceptance. Native writes are halted;
there is **no completion certificate and no Save**. Do not replay LOAD or
advance placement from this outcome. Full LOAD acceptance remains pending.

## Approval, load and recovery

Before prompting, the app loader validates access to the actual proposal PNG.
Its approval message lists the packages and staged asset filenames,
source-relative paths and sizes. Missing image access blocks the prompt; an
access check is not a substitute for the agents examining the actual image.

`LOAD <proposal-id>` authorizes only the listed in-memory definition loading.
It does not approve component placement, schematic import, replacement of
existing embedded definitions, or saving a board. It is not a persistence
guarantee. Existing embedded pad/flash data remains authoritative and must be
preserved, not refreshed from disk.

The native operation temporarily uses only the verified cache for its current
editor `psmpath`/`padpath`, then restores the previous values even on failure.
It does not write a global `env` file or change Windows/Cadence installation
settings. Missing dependencies are errors, not a reason to search elsewhere.

Loading may finish completely or partially; it is a **non-atomic** operation,
not a rollback-capable placement transaction. The outcome reports actual
loaded/missing definitions and rechecks protected state. An uncertain native
result is never treated as a rollback or a reason to replay the same approval.

Individual no-write/delete file handles pin the verified existing bytes through
the native outcome. Windows directory handles do **not** freeze the child
namespace or prevent new files. Separate, latched Windows directory-change
notifications cover cache verification through the native outcome. A detected
cache change, including a transient addition/removal, prevents a completion
certificate and blocks further writes until the operator stages a fresh copy.

A timeout or worker interruption without confirmed continuous file locks and
cache-change monitoring also blocks later writes in that session. A late native
receipt is still reported, but does not erase a detected change or uncertain
protection interval: inspect status and stage a fresh copy rather than retrying.

Portable writes remain disabled by default; only the operator may enable them
in a genuinely interactive client without automatic elicitation answers. The
app tool separately refuses noninteractive/Autopilot operation.

## After loading

Use ordinary `pcb_inspect` and examine its fresh native state and actual PNG
to validate the **full placement model**. Successful library loading does not
prove that through-hole pads, text, complex package geometry, routed copper or
every board feature is supported. Placement still requires its own exact
proposals and human approval, and Save is separate.

Unused definitions can be purged by Cadence during save/refresh/manual-placement
operations. Do not assume that saving and reopening an all-unplaced board will
retain them; re-inspect the actual active database.

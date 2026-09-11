# Preserved groups, rooms and named constraints

An attach rejection mentioning `groups` is a native-model limitation, not a
PowerShell quoting or HWND error. Do not ungroup a design, delete room drawings,
or remove constraint assignments just to make the handshake pass.

The managed reader supports these bounded forms:

- Flat `NET_GROUP` objects containing native nets, including their physical,
  spacing and same-net Cset assignments.
- Flat `GENERIC` groups containing one rectangular `BOARD GEOMETRY/TOP_ROOM`
  drawing with one attached label.
- Standalone rectangular TOP_ROOM drawings after deliberate operator ungrouping,
  without recreating or changing their groups. Their protected identifiers use
  `@ungrouped:<label>`; this is not an invented native group.
- Empty, property-free conductor-named `WIRE_PROFILE` metadata. Wire-profile
  rules, class tables, nested groups, module groups and arbitrary grouped
  geometry remain outside this model.

Room geometry, labels, text-block settings, fixed/read-only flags, group
membership and property data are included in the protected native scene.
Non-default physical, spacing and same-net Csets are read on **every conductive
layer**, including positive plane layers. Their full values are preserved, not
replaced with DEFAULT or with planner-selected numbers. Electrical Csets and
class/region override tables remain unsupported.

Named Cset references must resolve to the corresponding native catalog. Native
DRC and the no-new-violation check remain independent gates. Room DRC must remain
enabled when room drawings or ROOM assignments are present. Nothing in this
feature enables DRC modes, changes Csets, moves/deletes room drawings, or grants
approval for a board edit.

## Room labels are not net-group names

The native component and function `ROOM` properties are preserved separately.
When their unique common label matches exactly one native room drawing label,
the planner and native gate enforce whole-footprint containment in that room.
This is an additional conservative placement policy, not a replacement for
Cadence's room evaluation; the native room DRC remains enabled independently.
Conflicting component/function labels or duplicate matching room drawings block
placement rather than selecting one silently.

Unmatched ROOM tags are reported as unresolved spatial metadata; they are not
matched to a net-group name or interpreted as an off-board placement keepin.
For example, numerical quick-placement page boxes `1`, `2`, `3` are not
automatically the spatial constraints for tags `UC`, `POWER`, `SD`, `LCD`.
The source tags are not changed, and native room DRC still applies. Explicit
operator functional groups and engineering review remain separate from this
metadata; no electrical role is inferred from a label.

## Complete policy identity

New snapshots include a `grouped-constraints-v1` policy section with bounded,
ordered native-policy chunks and exact record counts for rooms, assignments,
net groups, memberships, Cset catalogs and nets. The opaque data is not evaluated
as SKILL. It produces a safety digest for the complete protected policy.

Normalized `design_policy` facts and that digest are bound to a mission.
Changing a Cset value, group membership, ROOM tag or room drawing invalidates
the mission even if component positions have not changed. Legacy snapshots
without policy records remain supported; partial policy sections cannot
silently fall back to legacy behavior.

## The reported howto session

Initial read-only inspection found three quick-placement room groups and two
net groups: `DB` uses `SIGNAL` physical/spacing sets and `POWER` uses `POWER`
sets. The operator then changed groups, confirmed those edits, saved them
separately and closed Cadence. The implementation did not undo those changes.
A separately approved read-only copy was used for subsequent validation.

In that saved copy, native repeated reads preserved two net groups, fourteen
memberships, seven Csets and eighty-four component/function ROOM assignments.
No room drawing remained in that particular saved version. Native Cset values
were read across TOP, L2, L3 and BOTTOM without changing the board.

The full handshake now reaches a different prerequisite: **sixteen required
embedded package definitions are missing**. The board has 46 logical unplaced
components, but its only embedded symbol definition is the `AB00` flash
definition, not their package footprints. The adapter reports missing package
preparation before unrelated unused-padstack restrictions. It does not load
libraries implicitly or substitute approximate footprints.

Group support therefore does not by itself establish complete placement
readiness for this file. Operator-controlled library preparation, the other
documented geometry limits, and exact human placement/Save approvals still
apply. All diagnostic reports and board/library binaries remain local-only.

Unused package definitions may be purged when an all-unplaced board is saved.
Library preparation therefore needs to make the correct definitions available
in the active staged editor before attachment; saving a library-loaded but
still-unplaced board is not proof that the definitions will survive reopening.
This release does not add an automatic library-loading/import operation.

# PCB placement reasoning rubric

This is an original advisory rubric, not a replacement for applicable
device datasheets, manufacturing requirements, or engineering sign-off. It
guides the planner and reviewer; it does not certify a design or authorize a
native operation.

## Shipped knowledge

The canonical, original knowledge lives in
`src\orcad_placement_agent\_knowledge` and is included in installed packages.
No books, index or PDF dependencies are needed to use it.

| Pack | Cards | Scope |
|---|---|---|
| `signal-routing` | 12 | Return paths, edge rates, topology, termination, differential pairs, crosstalk, clock/sensitive regions, fanout and routing readiness |
| `power-thermal` | 12 | Decoupling, PDN and mounting inductance, converter loops, switch/feedback/sense separation, Kelvin connections and thermal paths |
| `placement-manufacturing` | 12 | Inventory, mechanical anchors, floorplans, early critical passives, corridors, assembly/rework, polarity, depanelization, test and isolation inputs |

Each rule includes applicability, required inputs, actionable checks, tradeoffs,
failure modes and limits, plus bibliography and physical PDF-page provenance.
Three independent synthesis workers inspected selected source sections and
wrote original cards. This is not a reproduction, comprehensive digest of all
40 local books, trained model, standards database, or PCB certification.
Bibliographic uncertainty is retained in each source's `identity_note`.

Use `pcb_reference_search` then `pcb_reference_rule`, or the CLI
`knowledge search` and `knowledge rule`. Cite the stable card ID and release
version; the source bibliography explains development-time grounding, not live
book consultation. Rules have no invented PDF page. The complete card, not its
search excerpt alone, is the unit of engineering guidance.

Rules are conditional and subordinate to applicable device/project and safety
requirements. Contradictions or missing board facts must be resolved explicitly.
Native access and approval remain entirely independent of this knowledge.

## Maintaining the packs

Keep IDs stable; record guidance changes in Git, not bespoke content hashes.
Review new cards for technical applicability, source identity, actual physical
page support, original wording and missing conditions. Do not add copyrighted
extracts, tables, diagrams, proprietary designs, or unqualified numeric rules.
The loader validates schema, IDs, citations and bounds; tests exercise retrieval
and no-book behavior, not electrical truth. A bibliography reference does not
replace engineering review of a changed rule.

## Evidence and authority

| Evidence | Permitted conclusion |
|---|---|
| Explicit board snapshot fields | Observed geometry/state at that snapshot, not current live state |
| Confirmed schematic, pin/net roles, project requirements | Design-specific intent within their stated scope |
| Applicable device datasheet or manufacturer reference layout | Device-specific recommendation subject to its conditions |
| Bundled original rule, including checks and limits | Conditional engineering guidance; source provenance is historical, not a live PDF read |
| Relevant book/application-note page | A principle or heuristic, not an automatically applicable numerical rule |
| Agent inference | A hypothesis to explain and verify, never an established board fact |

Resolve contradictory constraints with the engineer. Do not silently choose
the most convenient source. Technical depth, device applicability, edition,
frequency regime, and assumptions matter more than search rank. A document's
metadata title may be incomplete or misleading; cite its exact local filename
and physical PDF page.

## Review dimensions

| Dimension | Establish first | Reasoning and tradeoffs |
|---|---|---|
| Mechanical placement | Outline, mounting interfaces, keepouts, connectors, fixed parts, height restrictions | Preserve interfaces and datum constraints before optimizing local interconnects |
| Functional grouping | Confirmed circuit blocks, signal flow, noisy and sensitive nodes | Group by electrical function; refdes prefixes do not establish component roles |
| Decoupling and PDN | Supply/ground pins, net association, device guidance, stackup, mounting/via topology | Consider the complete current path and connection inductance, not body-to-body distance alone |
| Power conversion | Converter topology, switching states, input/output capacitor functions, switch node | Identify actual high-di/dt loops; avoid a generic loop diagram for every regulator or LDO |
| Return paths and coupling | Reference planes, discontinuities, layer transitions, edge rates and coupling victims | Favor controlled return paths; closer spacing can increase unwanted coupling |
| Thermal behavior | Dissipation, copper/plane paths, airflow, thermal limits and sensitive neighbors | Short electrical connections may conflict with heat spreading or sensor accuracy |
| Assembly and routing | Fabricator/assembler constraints, courtyard/height, access, test points, routing corridors | Preserve access and routability; compact placement is not sufficient evidence of manufacturability |

Do not prescribe universal spacing, capacitor values, clearance/creepage,
trace widths, or thermal-via patterns. Those require the applicable electrical,
mechanical, manufacturing, and safety requirements. In particular, a generic
textbook example is not an approved high-voltage isolation rule.

## Qualifications that prevent misleading advice

- A reference designator such as `C17` does not prove that a component is a
  bypass capacitor, nor which IC or rail it serves.
- A low DRC count is not evidence of good SI, PI, EMI, thermal performance,
  or preserved design intent. Compare relevant violations individually.
- A shorter visible connection can leave the return-current path worse.
  Examine the full loop and reference geometry.
- A discrete capacitor across reference structures is not an unlimited
  high-frequency remedy: mounting/loop inductance and ESR can dominate.
- Do not impose analog/digital ground splits or star grounding as universal
  rules. Determine the actual return paths and applicable device guidance.
- An example for a switch-mode converter does not automatically apply to
  every linear regulator. Identify topology and transient current paths.
- The reference index cannot read diagrams without text or perform OCR.
  Missing extraction is missing evidence, not absence of a design concern.
- A supplied real board remains outside the fixture-only native write model.
  Advisory reasoning does not expand the editor adapter's supported scope.

## Optional original-source navigation

These are development-library navigation seeds, not runtime prerequisites.
Built-in rules are usable without these files. If using optional original
excerpts for a new claim, retrieve the actual page context; do not copy historical
citations onto a claim without checking the text.

| Local reference | Physical PDF page | Relevant starting point |
|---|---|---|
| `40 PCB Design Tips Every Designer Should Know.pdf` | 20 | Mechanically fixed and electrically/thermally critical placement items |
| `40 PCB Design Tips Every Designer Should Know.pdf` | 37 | Regulator/converter current-loop layout; qualify advice by actual topology |
| `76d8f6e1-a049-4a5e-97ca-e528b4233269.pdf` (metadata: Carrier Board Design Guide) | 15 | Bypass connections at power-input pins; applicability depends on the circuit |
| `70d823f6-f7f1-461a-9fc5-eed2d9acf535.pdf` | 202 | Loop inductance and complete current loops |
| `70d823f6-f7f1-461a-9fc5-eed2d9acf535.pdf` | 283 | Limits of discrete capacitance for high-frequency return-path transitions |

The books themselves, extracted text, index, and evidence packets remain
local-only. This rubric contains original synthesis, not a redistributed
textbook or trained-model claim.

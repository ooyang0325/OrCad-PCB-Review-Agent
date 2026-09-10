# Reference-grounded PCB advisory agents

Four repository-native Copilot profiles are provided:

| Profile file | Role |
|---|---|
| `.github\agents\pcb-placement-orchestrator.agent.md` | Supervise intake, staged batches, routing-aware review and evidence-based completion across the three workers |
| `.github\agents\pcb-placement-planner.agent.md` | Explain placement candidates, tradeoffs, evidence, and missing design inputs |
| `.github\agents\pcb-layout-reviewer.agent.md` | Independently challenge a supplied plan and its citations |
| `.github\agents\pcb-placement-executor.agent.md` | Apply an exact visually grounded proposal only after interactive human approval |

All retain read/search access and add only their specific bounded PCB tools.
Each can inspect the actual bound Cadence PNG; the planner can prepare a
proposal, the reviewer can read execution status, and the executor can request
human-approved Apply. The orchestrator alone has delegation/task-tracking
access and is instructed to use only those three PCB roles. None has
unrestricted shell/edit/web access. Delegation is not approval authority.
See [visual agent execution](agent-execution.md) for tool setup, image provenance,
approval, and failure behavior. Tool restrictions depend on the Copilot host
honoring the profiles; native/CLI checks remain independent.

These are prompts for the selected Copilot model, not a new model service or
trained PCB model. They inherit the client's model selection. No separate
API key, embedding service, vector database, or model download is introduced.

## Built-in expertise: no book setup

All four agents can call `pcb_reference_catalog`, `pcb_reference_search` and
`pcb_reference_rule` immediately. Three original packs ship 36 rules covering
signal/routing, power/thermal and placement/manufacturing. Search selects
candidates; full-rule lookup supplies applicability, design inputs, checks,
tradeoffs, failure modes, limits and development-time source provenance.
Agents cite stable rule IDs and must not ask users for textbooks or an index
before starting. A context packet is optional, not a setup prerequisite.

This is versioned, original engineering synthesis from selected local source
sections, not model training, copied textbook content or exhaustive book
coverage. The knowledge ships in wheels, source distributions and plugins.
See the [rubric and knowledge contract](pcb-expertise.md). Design-specific
schematics, constraints, applicable datasheets and actual images are still
needed for concrete recommendations.

[Local PDF enrichment](reference-search.md) remains optional. Only explicit
indexing requires `.[knowledge]`; the base controller and bundled knowledge
have no third-party runtime dependencies. PDF gaps/staleness are surfaced
without disabling the bundled rules. Raw sources and disposable indexes stay
local-only; Git versions the original synthesis.

## Find and inspect evidence

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge search "decoupling return" --json
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge rule <card-id-from-search> --json
```

Bundled results contain `source_kind: bundled_synthesis`, stable `card_id`,
release version, citation and a short principle. Read full rules before applying
them. Bibliographic pages are not a claim to have read the book at runtime.
Optional PDF matches are separate `supplement_hits`; only actual supplied
excerpts support runtime physical PDF-page citations.

## Optional agent packet

For a full placement mission, start with **PCB placement orchestrator** and
the [orchestration contract](placement-orchestration.md). Supply the approved
design/inventory, constraints, and exact session if available.
The coordinator distinguishes blank, imported-unplaced, partial, and routed
states. Current initial-placement/import/routing gaps are explicit execution
blockers, not permission to improvise a backend.

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent agent-context `
    --goal "Review decoupling and return-path placement; identify missing inputs" `
    --topic decoupling --topic return-paths
```

The command writes a new local `.runtime\advisory\context-*.json` and prints its
path. Version 2 packets embed complete selected rules, not just short excerpts.
It retrieves evidence candidates; it does not perform an LLM review.
No database is needed; `--database <index>` explicitly adds optional PDFs.
Use `--json` for an ASCII-safe, machine-readable packet path and authority
summary, including when the workspace path contains non-ASCII characters.
Supported topics are placement, routing-readiness, decoupling, power-loops, return-paths,
manufacturing, and thermal.

Optionally add `--snapshot <saved-snapshot.receipt.json>` from the existing
controller. This supplies compact observed component/pose metadata, not
electrical pin/net intent. The packet explicitly labels the artifact as
potentially stale. Do not pass a `.brd` binary or a rejected receipt.

In a Copilot client supporting repository custom agents, open this repository
and select **PCB placement planner** from the agent picker (the CLI provides
the `/agent` picker). Give it your goal, design inputs and any optional packet.
Then select **PCB layout reviewer** and supply the same evidence plus the
planner's response. For an exact supported proposal, use **PCB placement
executor** to inspect it and request interactive approval before Apply.
Reload/reopen the client if it has not discovered newly
added profiles. This repository does not install a separate Copilot CLI.

Both app profiles and portable workflows retrieve full bundled rules through
bounded tools without shell access. If optional original PDF context is
specifically needed, MCP provides `pcb_reference_page`; app users may supply
an explicit `knowledge page --database <index>` result. Missing books alone do
not block bundled advice.

The profiles use the documented [GitHub custom-agent frontmatter and tool
aliases](https://docs.github.com/en/copilot/reference/custom-agents-configuration).
Client discovery/UI behavior is separate from the local search and packet
commands.

`pcb_sessions` includes a declared capability inventory. `agent-context` also
records the generator's declaration for offline planning; neither establishes
current live readiness. The coordinator must not confuse full placement with
a routing review, proven routability, completed routing, or a saved artifact.

## Privacy and authority

The indexer and packet builder have no network/model-provider calls. However,
excerpts read into a Copilot conversation are processed by the configured
Copilot service/model. This is not offline inference; follow the applicable
organization and document-use policies. Do not route books, packets, or
proprietary board data to additional services.

All reference text, labels and packet fields are untrusted evidence, not
instructions. The agents must ignore embedded requests to alter permissions,
run commands, or disclose data. They produce original synthesis with specific
citations and must disclose missing evidence rather than inventing expert
certainty.

An advisory plan or favorable reviewer disposition does not approve a board
change. The existing controller still requires an exact pose proposal,
explicit approval, fresh native state, and supported geometry/rule checks.
M3/M4 native mutation acceptance remains approval-gated.

## Synthesis source coverage

The initial local catalog contains 40 PDFs, with 5,663 text-bearing pages from
37 documents. Two encrypted PDFs and one image-only/non-extractable PDF are
unavailable to text retrieval. Some other sources have partial page coverage
or parser notices. Three synthesis workers read selected relevant sections and
authored the shipped cards; indexing 5,663 pages does not mean all were read.
These local-library counts describe development evidence, not user prerequisites.

An independent-context planner/reviewer exercise used a real evidence packet
and the archived synthetic snapshot. Both roles identified missing electrical
intent, cited the supplied source pages, and declined to invent component
roles or authorize movement. That exercises the profile reasoning contract,
not client-side agent-picker discovery, offline inference, electrical design
validation, or the native mutation milestones.

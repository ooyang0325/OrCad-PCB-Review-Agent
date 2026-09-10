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

## Local reference setup

Install only the optional local PDF tools in the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[knowledge]"
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge index
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge catalog --json
```

The default library is `pcb_design_book`; the default index is
`.runtime\knowledge.sqlite3`. Override `--books` or `--database` when needed.
Both directories are ignored by Git. The base Cadence controller still has
no third-party runtime dependency.

The local indexer uses pypdf, fontTools, and SQLite FTS5. It does not perform OCR,
decrypt protected PDFs, upload documents, train a model, or contact a model
provider. Encrypted, image-only, malformed, oversized and partially extracted
documents are reported explicitly. Font/parser warnings are recorded in
document notices as well as surfaced by the reader.

Incremental indexing uses ordinary file size/modification metadata. Changed
or removed indexed sources invalidate retrieval until reindexing; an extractor
revision change rebuilds the cache. Use `knowledge index --rebuild` if external
tools preserved timestamps or the PDF-reader environment changed. This is a
disposable search cache, not document version control. Use Git for project
source history, and keep the supplied books out of commits.

## Find and inspect evidence

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge search "decoupling return" --json
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge page "40 PCB Design Tips Every Designer Should Know.pdf" --page 37 --json
```

Search results contain the exact source, physical PDF page, bounded excerpt,
and excerpt offset. Multi-term searches prefer all terms, then label relaxed
any-term matches. A CJK substring fallback is labeled separately. Search rank
is not engineering authority. Read surrounding text before drawing conclusions.
PDF page numbers are one-based file pages, not the printed page numbers.

## Prepare an agent packet

For a full placement mission, start with **PCB placement orchestrator** and
the [orchestration contract](placement-orchestration.md). Supply the approved
design/inventory, constraints, exact session if available, and evidence packet.
The coordinator distinguishes blank, imported-unplaced, partial, and routed
states. Current initial-placement/import/routing gaps are explicit execution
blockers, not permission to improvise a backend.

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent agent-context `
    --goal "Review decoupling and return-path placement; identify missing inputs" `
    --topic decoupling --topic return-paths
```

The command writes a new local `.runtime\advisory\context-*.json` and prints its
path. It retrieves evidence candidates; it does not perform an LLM review.
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
the `/agent` picker). Give it the exact generated packet path and your goal.
Then select **PCB layout reviewer** and supply that same packet plus the
planner's response. For an exact supported proposal, use **PCB placement
executor** to inspect it and request interactive approval before Apply.
Reload/reopen the client if it has not discovered newly
added profiles. This repository does not install a separate Copilot CLI.

If an app agent needs more page context than its packet contains, the operator
runs `knowledge page` and supplies the bounded result. The portable workflows
can instead use their configured MCP reference tools. The app profiles
intentionally do not gain shell access just to retrieve extra text.

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

## Initial library and advisory coverage

The initial local catalog contains 40 PDFs, with 5,663 text-bearing pages from
37 documents. Two encrypted PDFs and one image-only/non-extractable PDF are
unavailable to text retrieval. Some other sources have partial page coverage
or parser notices; consult the catalog rather than assuming every page was read.

An independent-context planner/reviewer exercise used a real evidence packet
and the archived synthetic snapshot. Both roles identified missing electrical
intent, cited the supplied source pages, and declined to invent component
roles or authorize movement. That exercises the profile reasoning contract,
not client-side agent-picker discovery, offline inference, electrical design
validation, or the native mutation milestones.

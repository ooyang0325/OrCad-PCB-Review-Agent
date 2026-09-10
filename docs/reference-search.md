# Bundled PCB expertise and optional references

**No books or knowledge setup are needed by default.** The package includes
36 original guidance cards in three packs, with applicability, required design
inputs, checks, tradeoffs, failure modes, limits and synthesis provenance.

```powershell
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge catalog --json
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge search "decoupling mounting inductance" --json
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge rule <card-id-from-search> --json
```

The app extension and portable MCP expose `pcb_reference_catalog`,
`pcb_reference_search`, and `pcb_reference_rule`. Search is deterministic
keyword retrieval over packaged content, not a model or embedding service.
English technical terms match the English cards. Use the catalog/topic inventory
if a query has no match; search rank is not engineering authority.

`hits` contains `source_kind: bundled_synthesis` and stable `card_id` citations.
Retrieve a complete rule rather than applying its short search excerpt alone.
Bibliographic source IDs are scoped to their pack. Physical PDF pages within
a rule are development-time provenance, not a claim of runtime access to the
original book. A rule itself has no PDF page number. Guidance changes are tracked
in Git and carry the package version.

## Optional local PDF enrichment

The optional reference tool indexes the user-supplied PDFs without opening
Cadence, uploading documents, or calling a model provider.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[knowledge]"
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge index
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge catalog --database .runtime\knowledge.sqlite3 --json
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge search "decoupling return" --database .runtime\knowledge.sqlite3 --json
.\.venv\Scripts\python.exe -m orcad_placement_agent knowledge page "40 PCB Design Tips Every Designer Should Know.pdf" --page 37 --database .runtime\knowledge.sqlite3 --json
```

For the explicit `index` command only, the default library is `pcb_design_book`
and the default index is `.runtime\knowledge.sqlite3`. Pass `--database` to
catalog/search/page/context to select the supplement; it is not auto-discovered.
Both local directories are ignored by Git. Bundled guidance has no third-party
runtime dependencies. The low-level Python `knowledge` module retains its strict,
explicit PDF/index API; user-facing flows use the `references` facade.

Optional matches are separate `supplement_hits` with `source_kind: local_pdf`.
Missing, corrupt or stale supplements produce `warnings` and an explicit
`supplement_status`; bundled guidance remains available. Original-page retrieval
still fails explicitly if the requested local source is unavailable.

PDF extraction uses pypdf and fontTools; page retrieval uses Python's SQLite
FTS5 support. The index stores source filenames, metadata titles, physical PDF
page numbers, normalized text, extraction notices, and file metadata. It is a
disposable search cache, not version control.

## Coverage and freshness

Encrypted, image-only, malformed, oversized and partially extracted documents
are reported explicitly. No decryption, OCR, diagram interpretation, or
mathematical-layout reconstruction is performed. Font/parser warnings are
recorded as document notices and surfaced by the reader. Inspect catalog
notices before relying on coverage.

Text normalization joins line-break hyphenation and normalizes Unicode
presentation forms. Excerpts are extracted text, not a facsimile of the page.
Inspect the original local PDF when formatting or diagrams matter.

Incremental indexing uses file size and modification time. Changed or removed
indexed sources block optional PDF citation retrieval until indexing runs again; extractor
revision changes force rebuilding. Use `knowledge index --rebuild` when an
external tool preserved timestamps or the reader environment changed. Adding
a new PDF requires indexing before it becomes searchable.

Limits are 500 documents, 100 MiB and 2,000 pages per PDF, and 200,000 extracted
characters per page. Exceeded document/page limits are reported, not silently
truncated into an apparently complete index.

## Evidence, not automatic rules

Search prefers all terms, then explicitly labels relaxed any-term results.
Chinese substring fallback is labeled separately. Limit results with `--limit`
(1-20). Exact source names and one-based physical PDF pages identify evidence;
they are not necessarily printed page numbers.

Results include bounded excerpts and offsets. Use `knowledge page` with
`--offset` and `--characters` (1-4,000) for surrounding context. A table of
contents, quiz question, or partial text match is not sufficient support for a
PCB recommendation. Metadata titles can be inaccurate; filenames and PDF pages
remain the citation anchors.

No model is trained and no design is certified. A reasoning agent must
establish applicability, disclose missing inputs, compare sources, and separate
observed facts from hypotheses.

The tool has no network calls. Excerpts subsequently supplied to a Copilot
conversation are processed by that configured service/model, however; this is
not a promise of offline inference. Follow applicable document-use and
organization policies. Do not commit books, extracted text, indexes, or packets.

"""Local-only PDF page indexing and evidence retrieval for advisory agents."""

from contextlib import closing
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import sqlite3
import unicodedata
from typing import Callable


SCHEMA_VERSION = "1"
EXTRACTOR_REVISION = "1"
DEFAULT_BOOKS = Path("pcb_design_book")
DEFAULT_DATABASE = Path(".runtime") / "knowledge.sqlite3"
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
MAX_DOCUMENT_PAGES = 2000
MAX_PAGE_CHARACTERS = 200000
MAX_DOCUMENTS = 500


class KnowledgeError(ValueError):
    """Local evidence is unavailable, stale, or outside supported limits."""


@dataclass(frozen=True)
class ExtractedDocument:
    title: str
    total_pages: int
    pages: tuple[tuple[int, str], ...]
    status: str
    notices: tuple[str, ...] = ()


class _ReaderNotices(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1
        message = "Reader warning: " + " ".join(record.getMessage().split())[:300]
        if message not in self.messages and len(self.messages) < 50:
            self.messages.append(message)


def extract_pdf(path: Path) -> ExtractedDocument:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as error:
        raise KnowledgeError(
            "PDF indexing requires the optional reader: "
            r'.\.venv\Scripts\python.exe -m pip install -e ".[knowledge]"'
        ) from error
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        return ExtractedDocument(
            path.stem, 0, (), "unreadable", ("PDF exceeds the 100 MiB limit.",)
        )
    reader_notices = _ReaderNotices()
    logger = logging.getLogger("pypdf")
    logger.addHandler(reader_notices)
    try:
        with path.open("rb") as source:
            reader = PdfReader(source, strict=False)
            if reader.is_encrypted:
                return ExtractedDocument(
                    path.stem, 0, (), "encrypted",
                    ("Encrypted PDF was not opened; supply an accessible local edition.",),
                )
            title = " ".join(str((reader.metadata or {}).get("/Title") or path.stem).split())[:300]
            count = len(reader.pages)
            if count > MAX_DOCUMENT_PAGES:
                return ExtractedDocument(
                    title, count, (), "unreadable",
                    (f"PDF exceeds the {MAX_DOCUMENT_PAGES}-page limit.",),
                )
            pages = []
            notices = []
            for page_number, page in enumerate(reader.pages, 1):
                try:
                    text = page.extract_text() or ""
                except (PyPdfError, ValueError, KeyError, RecursionError) as error:
                    notices.append(f"PDF page {page_number}: extraction failed ({type(error).__name__}).")
                    continue
                if len(text) > MAX_PAGE_CHARACTERS:
                    notices.append(f"PDF page {page_number}: text exceeds the page limit; not indexed.")
                    continue
                text = re.sub(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", "", text)
                text = " ".join(unicodedata.normalize("NFKC", text).replace("\x00", " ").split())
                if text:
                    pages.append((page_number, text))
                else:
                    notices.append(f"PDF page {page_number}: no extractable text; OCR may be needed.")
            notices.extend(reader_notices.messages)
            if reader_notices.count > len(reader_notices.messages):
                notices.append(
                    f"{reader_notices.count} reader warnings occurred; duplicate/excess messages summarized."
                )
            status = "indexed" if len(pages) == count and count and not notices else "partial"
            if not pages:
                status = "no_text"
            return ExtractedDocument(title, count, tuple(pages), status, tuple(notices))
    except (PyPdfError, ValueError, KeyError, RecursionError) as error:
        return ExtractedDocument(
            path.stem, 0, (), "unreadable", (f"PDF parsing failed ({type(error).__name__}).",)
        )
    finally:
        logger.removeHandler(reader_notices)


SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    total_pages INTEGER NOT NULL,
    indexed_pages INTEGER NOT NULL,
    status TEXT NOT NULL,
    notices TEXT NOT NULL
);
CREATE TABLE pages (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(document_id, page)
);
CREATE VIRTUAL TABLE page_search USING fts5(
    text, content='pages', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER pages_insert AFTER INSERT ON pages BEGIN
    INSERT INTO page_search(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER pages_delete AFTER DELETE ON pages BEGIN
    INSERT INTO page_search(page_search, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""


def _connect(database: Path, *, write: bool = False) -> sqlite3.Connection:
    database = database.expanduser().resolve()
    if not write and not database.is_file():
        raise KnowledgeError("Local reference index is missing; run knowledge index first.")
    if write:
        database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(database) if write else database.as_uri() + "?mode=ro", uri=not write
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
    ).fetchone():
        raise KnowledgeError("This file is not a reference index.")
    values = dict(connection.execute("SELECT key,value FROM metadata"))
    if values.get("schema_version") != SCHEMA_VERSION or "books_root" not in values:
        raise KnowledgeError("Unsupported reference-index schema; use a new database path.")
    return values


def index_books(
    books: Path = DEFAULT_BOOKS, database: Path = DEFAULT_DATABASE, *,
    extractor: Callable[[Path], ExtractedDocument] = extract_pdf,
    rebuild: bool = False,
) -> dict[str, object]:
    root = books.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise KnowledgeError("The books path must be a local directory.")
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: str(path.relative_to(root)).casefold(),
    )
    if not paths:
        raise KnowledgeError("No PDF files were found in the selected library.")
    if len(paths) > MAX_DOCUMENTS:
        raise KnowledgeError(f"The library exceeds the {MAX_DOCUMENTS}-document limit.")
    for path in paths:
        if not path.resolve().is_relative_to(root):
            raise KnowledgeError(f"PDF points outside the selected library: {path.name}")
    with closing(_connect(database, write=True)) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables:
            connection.executescript(SCHEMA)
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)",
                [("schema_version", SCHEMA_VERSION), ("books_root", str(root))],
            )
            connection.commit()
        metadata = _metadata(connection)
        if Path(metadata["books_root"]) != root:
            raise KnowledgeError("Index belongs to a different library; choose a new database path.")
        rebuild = rebuild or metadata.get("extractor_revision") != EXTRACTOR_REVISION
        updated = 0
        unchanged = 0
        observed = set()
        for path in paths:
            relative = str(path.relative_to(root))
            observed.add(relative)
            stat = path.stat()
            existing = connection.execute(
                "SELECT id,size,mtime_ns FROM documents WHERE path=?", (relative,)
            ).fetchone()
            if (
                not rebuild and existing
                and (existing["size"], existing["mtime_ns"]) == (stat.st_size, stat.st_mtime_ns)
            ):
                unchanged += 1
                continue
            document = extractor(path)
            after = path.stat()
            if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                raise KnowledgeError(f"Document changed during extraction: {relative}. Run indexing again.")
            page_numbers = [number for number, _text in document.pages]
            if (
                len(page_numbers) != len(set(page_numbers))
                or any(number < 1 or number > document.total_pages for number in page_numbers)
            ):
                raise KnowledgeError(f"Invalid extracted page numbering: {relative}")
            with connection:
                connection.execute(
                    """INSERT INTO documents(path,title,size,mtime_ns,total_pages,indexed_pages,status,notices)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(path) DO UPDATE SET
                       title=excluded.title,size=excluded.size,mtime_ns=excluded.mtime_ns,
                       total_pages=excluded.total_pages,indexed_pages=excluded.indexed_pages,
                       status=excluded.status,notices=excluded.notices""",
                    (relative, " ".join(document.title.split()), stat.st_size, stat.st_mtime_ns,
                     document.total_pages, len(document.pages), document.status,
                     json.dumps(document.notices, ensure_ascii=False)),
                )
                document_id = connection.execute(
                    "SELECT id FROM documents WHERE path=?", (relative,)
                ).fetchone()[0]
                connection.execute("DELETE FROM pages WHERE document_id=?", (document_id,))
                connection.executemany(
                    "INSERT INTO pages(document_id,page,text) VALUES (?,?,?)",
                    [(document_id, number, text) for number, text in document.pages],
                )
            updated += 1
        with connection:
            removed = 0
            for row in connection.execute("SELECT id,path FROM documents").fetchall():
                if row["path"] not in observed:
                    connection.execute("DELETE FROM documents WHERE id=?", (row["id"],))
                    removed += 1
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES ('extractor_revision',?)",
                (EXTRACTOR_REVISION,),
            )
        metadata["extractor_revision"] = EXTRACTOR_REVISION
        return {
            "database": str(database.resolve()), "updated": updated,
            "unchanged": unchanged, "removed": removed,
            "documents": _catalog(connection, metadata),
        }


def _catalog(connection: sqlite3.Connection, metadata: dict[str, str]) -> list[dict[str, object]]:
    root = Path(metadata["books_root"])
    documents = []
    for row in connection.execute("SELECT * FROM documents ORDER BY path COLLATE NOCASE"):
        path = root / row["path"]
        try:
            stat = path.stat()
            fresh = (
                path.resolve().is_relative_to(root)
                and (stat.st_size, stat.st_mtime_ns) == (row["size"], row["mtime_ns"])
                and metadata.get("extractor_revision") == EXTRACTOR_REVISION
            )
        except FileNotFoundError:
            fresh = False
        documents.append({
            "source": row["path"], "title": row["title"], "pdf_pages": row["total_pages"],
            "indexed_pages": row["indexed_pages"], "status": row["status"],
            "fresh": fresh, "notices": json.loads(row["notices"]),
        })
    return documents


def catalog(database: Path = DEFAULT_DATABASE) -> list[dict[str, object]]:
    with closing(_connect(database)) as connection:
        return _catalog(connection, _metadata(connection))


def _fresh(connection: sqlite3.Connection) -> dict[str, str]:
    metadata = _metadata(connection)
    stale = [document["source"] for document in _catalog(connection, metadata) if not document["fresh"]]
    if stale:
        raise KnowledgeError(
            "Indexed references changed, disappeared, or need an extractor update; "
            "run knowledge index before citing them: "
            + ", ".join(stale[:5])
        )
    return metadata


def search(
    query: str, database: Path = DEFAULT_DATABASE, *, limit: int = 5,
) -> dict[str, object]:
    if type(limit) is not int or not 1 <= limit <= 20:
        raise KnowledgeError("Search limit must be between 1 and 20.")
    if len(query) > 500:
        raise KnowledgeError("Search query must be at most 500 characters.")
    terms = list(dict.fromkeys(re.findall(r"\w+", query.casefold(), flags=re.UNICODE)))
    if not terms or len(terms) > 16:
        raise KnowledgeError("Use between 1 and 16 search terms.")
    with closing(_connect(database)) as connection:
        metadata = _fresh(connection)
        mode = "all_terms"
        rows = []
        # Search syntax is not accepted from the user; terms are always quoted.
        for operator in (" AND ", " OR "):
            expression = operator.join('"' + term.replace('"', '""') + '"' for term in terms)
            rows = connection.execute(
                """SELECT d.path,d.title,p.page,p.text,bm25(page_search) AS rank
                   FROM page_search JOIN pages p ON p.id=page_search.rowid
                   JOIN documents d ON d.id=p.document_id
                   WHERE page_search MATCH ?
                   ORDER BY rank,d.path,p.page LIMIT ?""",
                (expression, limit),
            ).fetchall()
            if rows:
                break
            mode = "any_term"
        if not rows and any(re.search(r"[\u3400-\u9fff]", term) for term in terms):
            mode = "substring"
            predicate = " OR ".join("instr(p.text,?) > 0" for _term in terms)
            rows = connection.execute(
                f"""SELECT d.path,d.title,p.page,p.text,0 AS rank FROM pages p
                    JOIN documents d ON d.id=p.document_id WHERE {predicate}
                    ORDER BY d.path,p.page LIMIT ?""",
                (*terms, limit),
            ).fetchall()
        hits = []
        for row in rows:
            text = row["text"]
            positions = [text.casefold().find(term) for term in terms]
            start = max(0, min((position for position in positions if position >= 0), default=0) - 80)
            hits.append({
                "source": row["path"], "title": row["title"], "pdf_page": row["page"],
                "citation": f"{row['path']} (PDF page {row['page']})",
                "excerpt": text[start:start + 450], "excerpt_offset": start,
            })
        return {
            "query": query, "match_mode": mode, "hits": hits,
            "library": metadata["books_root"],
            "note": "Retrieval matches are evidence candidates, not verified PCB design rules.",
        }


def page(
    source: str, page_number: int, database: Path = DEFAULT_DATABASE, *,
    offset: int = 0, characters: int = 1500,
) -> dict[str, object]:
    if page_number < 1 or offset < 0 or not 1 <= characters <= 4000:
        raise KnowledgeError("Require a positive PDF page, nonnegative offset, and 1-4000 characters.")
    with closing(_connect(database)) as connection:
        _fresh(connection)
        row = connection.execute(
            """SELECT d.path,d.title,p.page,p.text FROM documents d
               JOIN pages p ON p.document_id=d.id WHERE d.path=? AND p.page=?""",
            (source, page_number),
        ).fetchone()
        if not row:
            raise KnowledgeError("That PDF page has no indexed text; inspect the catalog notices.")
        if offset >= len(row["text"]):
            raise KnowledgeError("Page offset is beyond the extracted text.")
        return {
            "source": row["path"], "title": row["title"], "pdf_page": row["page"],
            "citation": f"{row['path']} (PDF page {row['page']})",
            "text": row["text"][offset:offset + characters],
            "offset": offset, "total_characters": len(row["text"]),
            "truncated": offset + characters < len(row["text"]),
        }

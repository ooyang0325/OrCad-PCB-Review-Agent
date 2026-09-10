"""Bundled expertise first, with explicitly configured optional PDF enrichment."""

from pathlib import Path
import sqlite3

from . import expertise, knowledge


SUPPLEMENT_ERRORS = (knowledge.KnowledgeError, sqlite3.Error, OSError)


def catalog(database: Path | None = None) -> dict[str, object]:
    result = {"bundled": expertise.catalog(), "documents": [], "warnings": [],
              "supplement_status": "not_configured"}
    if database is not None:
        try:
            result["documents"] = knowledge.catalog(database)
            result["supplement_status"] = "available"
            if any(not document["fresh"] for document in result["documents"]):
                result["supplement_status"] = "stale"
                result["warnings"].append("Optional PDF sources changed or disappeared; reindex before using excerpts.")
            if any(document["status"] != "indexed" for document in result["documents"]):
                result["warnings"].append("Optional PDF coverage is incomplete; inspect document extraction notices.")
        except SUPPLEMENT_ERRORS as error:
            result["supplement_status"] = "unavailable"
            result["warnings"].append(f"Optional PDF supplement unavailable: {error}")
    return result


def search(
    query: str, database: Path | None = None, *, limit: int = 5, topic: str | None = None,
) -> dict[str, object]:
    result = expertise.search(query, limit=limit, topic=topic)
    result.update({"supplement_hits": [], "warnings": [], "supplement_status": "not_configured"})
    if database is not None:
        try:
            supplement = knowledge.search(query, database, limit=limit)
            result["supplement_hits"] = [
                {"source_kind": "local_pdf", **hit} for hit in supplement["hits"]
            ]
            result["supplement_status"] = "available"
            result["supplement_match_mode"] = supplement["match_mode"]
        except SUPPLEMENT_ERRORS as error:
            result["supplement_status"] = "unavailable"
            result["warnings"].append(f"Optional PDF supplement was not searched: {error}")
    return result


def page(
    source: str, page_number: int, database: Path | None = None, *,
    offset: int = 0, characters: int = 1500,
) -> dict[str, object]:
    if database is None:
        raise knowledge.KnowledgeError(
            "Original PDF pages are optional and not bundled. Configure an indexed local PDF database "
            "to read this source, or use rule lookup for complete built-in guidance."
        )
    return {"source_kind": "local_pdf", **knowledge.page(
        source, page_number, database, offset=offset, characters=characters,
    )}

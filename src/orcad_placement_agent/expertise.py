"""Original, packaged PCB guidance; no PDFs, database, network, or model needed."""

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
import re

from . import __version__
from .knowledge import KnowledgeError


TOPICS = frozenset({
    "placement", "routing-readiness", "decoupling", "power-loops",
    "return-paths", "manufacturing", "thermal",
})
PACK_IDS = ("placement-manufacturing", "power-thermal", "signal-routing")
NOTICE = (
    "Original bundled engineering synthesis, not quotations or model training. "
    "Source-page references record development-time provenance; books are not shipped "
    "or consulted at runtime. Apply only with design-specific inputs and current "
    "device, fabrication, assembly, and applicable safety requirements. Not certification."
)
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


def _text(value: object, maximum: int = 350) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _identifier(value: object) -> bool:
    return _text(value, 64) and ID_PATTERN.fullmatch(value) is not None


def _strings(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, list) and minimum <= len(value) <= maximum
        and all(_text(item) for item in value)
    )


def validate_pack(pack: object, expected_id: str) -> None:
    """Reject incomplete/corrupt package data rather than inventing missing guidance."""
    def require(condition: bool, field: str) -> None:
        if not condition:
            raise KnowledgeError(f"Invalid bundled expertise {expected_id}: {field}.")

    require(isinstance(pack, dict), "object")
    require(set(pack) == {"schema_version", "pack_id", "title", "summary", "sources", "cards"}, "fields")
    require(type(pack["schema_version"]) is int and pack["schema_version"] == 1, "schema version")
    require(pack["pack_id"] == expected_id and _identifier(expected_id), "pack identity")
    require(_text(pack["title"]) and _text(pack["summary"], 900), "title/summary")
    require(isinstance(pack["sources"], list) and 1 <= len(pack["sources"]) <= 100, "sources")
    source_ids = set()
    for source in pack["sources"]:
        require(isinstance(source, dict) and set(source) == {
            "id", "title", "authors", "edition", "year", "local_filename", "identity_note",
        }, "source fields")
        require(_identifier(source["id"]) and source["id"] not in source_ids, "source identity")
        source_ids.add(source["id"])
        require(_text(source["title"]) and _strings(source["authors"], 0, 20), "source bibliography")
        require(source["edition"] is None or _text(source["edition"]), "edition")
        require(source["year"] is None or (
            type(source["year"]) is int and 1800 <= source["year"] <= 2200
        ), "year")
        filename = source["local_filename"]
        require(_text(filename, 500) and filename.lower().endswith(".pdf")
                and "/" not in filename and "\\" not in filename, "local filename")
        require(_text(source["identity_note"], 900), "source identity note")
    require(isinstance(pack["cards"], list) and 1 <= len(pack["cards"]) <= 100, "cards")
    card_ids = set()
    fields = {
        "id", "title", "topics", "tags", "principle", "applies_when", "required_inputs",
        "checks", "tradeoffs", "failure_modes", "limits", "references",
    }
    bounds = {
        "tags": (1, 30), "applies_when": (1, 4), "required_inputs": (2, 6),
        "checks": (3, 6), "tradeoffs": (1, 3), "failure_modes": (1, 3), "limits": (1, 3),
    }
    for card in pack["cards"]:
        require(isinstance(card, dict) and set(card) == fields, "card fields")
        require(_identifier(card["id"]) and card["id"] not in card_ids, "card identity")
        card_ids.add(card["id"])
        require(_text(card["title"]) and _text(card["principle"], 900), "card title/principle")
        require(_strings(card["topics"], 1, len(TOPICS)) and set(card["topics"]) <= TOPICS, "topics")
        for field, (minimum, maximum) in bounds.items():
            require(_strings(card[field], minimum, maximum), field)
        require(isinstance(card["references"], list) and 1 <= len(card["references"]) <= 20, "references")
        for reference in card["references"]:
            require(isinstance(reference, dict) and set(reference) == {
                "source_id", "pdf_pages", "support",
            }, "reference fields")
            require(_identifier(reference["source_id"]) and reference["source_id"] in source_ids, "reference source")
            pages = reference["pdf_pages"]
            require(isinstance(pages, list) and 1 <= len(pages) <= 30
                    and all(type(page) is int and page > 0 for page in pages)
                    and len(pages) == len(set(pages)), "physical PDF pages")
            require(_text(reference["support"]), "reference support")


@lru_cache(maxsize=1)
def _packs() -> tuple[dict[str, object], ...]:
    packs = []
    ids = set()
    for pack_id in PACK_IDS:
        resource = files("orcad_placement_agent").joinpath("_knowledge", f"{pack_id}.json")
        try:
            with resource.open("rb") as stream:
                content = stream.read(102401)
            if len(content) > 102400:
                raise KnowledgeError(f"Bundled expertise {pack_id} exceeds 100 KiB.")
            pack = json.loads(content)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise KnowledgeError(f"Cannot load bundled expertise {pack_id}: {error}") from error
        validate_pack(pack, pack_id)
        for card in pack["cards"]:
            if card["id"] in ids:
                raise KnowledgeError(f"Duplicate bundled rule ID: {card['id']}.")
            ids.add(card["id"])
        packs.append(pack)
    return tuple(packs)


def catalog() -> dict[str, object]:
    packs = [{
        "pack_id": pack["pack_id"], "title": pack["title"], "summary": pack["summary"],
        "sources": pack["sources"], "card_count": len(pack["cards"]),
        "cards": [{"id": card["id"], "title": card["title"], "topics": card["topics"]}
                  for card in pack["cards"]],
    } for pack in _packs()]
    return deepcopy({
        "source_kind": "bundled_synthesis", "version": __version__,
        "card_count": sum(pack["card_count"] for pack in packs),
        "packs": packs, "notice": NOTICE,
    })


def _identity(pack: dict[str, object], card: dict[str, object]) -> dict[str, object]:
    return {
        "source_kind": "bundled_synthesis", "pack_id": pack["pack_id"],
        "card_id": card["id"], "version": __version__, "title": card["title"],
        "citation": f"Bundled PCB rule {card['id']} ({pack['title']})",
    }


def rule(card_id: str) -> dict[str, object]:
    if not _identifier(card_id):
        raise KnowledgeError("Supply a stable bundled rule ID from reference search/catalog, not a path.")
    for pack in _packs():
        for card in pack["cards"]:
            if card["id"] == card_id:
                used = {reference["source_id"] for reference in card["references"]}
                return deepcopy({
                    **card, **_identity(pack, card), "notice": NOTICE,
                    "sources": [source for source in pack["sources"] if source["id"] in used],
                })
    raise KnowledgeError(f"Unknown bundled PCB rule: {card_id}. Use reference search/catalog.")


STOP_WORDS = frozenset("a an and are as at be by for from how in is of on or pcb the to with".split())


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[^\W_]+", text.casefold()) if term not in STOP_WORDS}


def search(query: str, *, limit: int = 5, topic: str | None = None) -> dict[str, object]:
    if not _text(query, 500) or not _terms(query):
        raise KnowledgeError("Supply a nonempty technical search query of at most 500 characters.")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise KnowledgeError("Search limit must be an integer from 1 to 20.")
    if topic is not None and topic not in TOPICS:
        raise KnowledgeError("Unknown PCB guidance topic.")
    terms = _terms(query)
    ranked = []
    for pack in _packs():
        for card in pack["cards"]:
            if topic is not None and topic not in card["topics"]:
                continue
            primary = _terms(" ".join([card["title"], *card["topics"], *card["tags"]]))
            detail = _terms(" ".join([card["principle"], *card["checks"]]))
            matched = terms & (primary | detail)
            score = 4 * len(terms & primary) + len(terms & detail)
            if score:
                ranked.append((len(matched), score, card["id"], pack, card))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return {
        "query": query, "match_mode": "bundled_keywords", "notice": NOTICE,
        "hits": [{**_identity(pack, card), "excerpt": card["principle"][:450]}
                 for _, _, _, pack, card in ranked[:limit]],
    }

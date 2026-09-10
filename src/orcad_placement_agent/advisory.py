"""Build bounded evidence packets for read-only Copilot expert profiles."""

import json
from datetime import datetime, timezone
from pathlib import Path
import uuid

from . import expertise, knowledge, references
from .protocol import MAX_BYTES, ProtocolError, Receipt, identifier
from .proposals import check_snapshot
from .session import write_json
from .capabilities import backend_capabilities


TOPIC_QUERIES = {
    "placement": ("component placement fixed", "placement routing"),
    "routing-readiness": (
        "component placement routing channels", "fanout escape routing", "routing congestion",
    ),
    "decoupling": ("decoupling capacitor pin", "decoupling loop inductance"),
    "power-loops": ("switching current loop", "power converter layout"),
    "return-paths": ("return current plane", "reference plane discontinuity"),
    "manufacturing": ("component assembly clearance", "test point access"),
    "thermal": ("thermal component placement", "heat copper vias"),
}


def _snapshot_context(path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_BYTES:
        raise ProtocolError("Snapshot artifact exceeds the size limit.")
    data = json.loads(path.read_text(encoding="utf-8"))
    receipt = Receipt.from_dict(data)
    components = check_snapshot(receipt)
    return {
        "artifact": str(path.resolve()), "request_id": receipt.request_id,
        "snapshot_id": receipt.one("snapshot")[1], "board": receipt.one("board")[1],
        "units": receipt.one("units")[1], "editor_version": receipt.one("version")[1],
        "freshness": "Saved artifact only; not proof of the current live board state.",
        "components": [{
            "refdes": item.refdes, "package": item.package,
            "x": str(item.x), "y": str(item.y), "angle": str(item.angle),
            "fixed": item.fixed, "placed": item.placed, "mirrored": item.mirrored,
        } for item in components.values()],
        "limitations": [
            "This compact summary does not establish electrical function, nets, pin roles, or current paths.",
            "Do not infer capacitor purpose or signal criticality from reference designators or package names.",
            "Do not interpret the native compressed scene as verified electrical design intent.",
        ],
    }


def _visual_context(path: Path) -> tuple[dict[str, object], Path]:
    path = path.expanduser().resolve(strict=True)
    if path.stat().st_size > MAX_BYTES:
        raise ProtocolError("Visual metadata exceeds the size limit.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "pcb-visual-observation":
        raise ProtocolError("Expected captured PCB visual-observation metadata.")
    observation_id = identifier(data.get("observation_id"))
    after_id = identifier(data.get("after_request_id"))
    before_id = identifier(data.get("before_request_id"))
    image = path.parent / f"visual-{observation_id}.png"
    receipt = path.parent / f"{after_id}.receipt.json"
    if (
        path.name != f"visual-{observation_id}.json"
        or not isinstance(data.get("image_path"), str)
        or Path(data["image_path"]).resolve() != image
        or not image.is_file() or not receipt.is_file() or receipt.resolve() != receipt
    ):
        raise ProtocolError("Visual evidence paths do not match the captured observation.")
    with image.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ProtocolError("Captured image is not a PNG.")
    for dimension in ("width", "height"):
        if type(data.get(dimension)) is not int or not 0 < data[dimension] <= 8192:
            raise ProtocolError("Invalid captured image dimensions.")
    return {
        "observation_id": observation_id, "before_request_id": before_id,
        "after_request_id": after_id, "image_path": str(image),
        "metadata_path": str(path), "width": data["width"], "height": data["height"],
        "captured_at": data.get("captured_at"), "method": data.get("method"),
        "editor": data.get("editor"),
        "freshness": "Archived observation. Use pcb_inspect for a current image and native state.",
        "limitations": "Read the PNG itself. Pixels do not prove DRC, layer completeness, or electrical correctness.",
    }, receipt


def build_context(
    goal: str, database: Path | None = None, *,
    topics: tuple[str, ...] = ("placement", "decoupling", "return-paths"),
    snapshot: Path | None = None,
    visual: Path | None = None,
    output_directory: Path = Path(".runtime") / "advisory",
) -> tuple[Path, dict[str, object]]:
    if not goal.strip() or len(goal) > 2000:
        raise knowledge.KnowledgeError("Supply a nonempty review goal of at most 2000 characters.")
    if not topics or len(topics) > len(TOPIC_QUERIES) or any(topic not in TOPIC_QUERIES for topic in topics):
        raise knowledge.KnowledgeError("Select one or more of the documented PCB review topics.")
    visual_context = None
    if visual is not None:
        visual_context, visual_snapshot = _visual_context(visual)
        if snapshot is not None and snapshot.resolve() != visual_snapshot:
            raise ProtocolError("The supplied snapshot is not the visual observation's post-capture snapshot.")
        snapshot = visual_snapshot
    coverage = references.catalog(database)
    documents = coverage["documents"]
    warnings = list(coverage["warnings"])
    queries = []
    evidence: list[dict[str, object]] = []
    seen = set()
    for topic in dict.fromkeys(topics):
        for query in TOPIC_QUERIES[topic]:
            result = references.search(query, database, limit=3, topic=topic)
            warnings.extend(result["warnings"])
            queries.append({
                "topic": topic, "query": query, "match_mode": result["match_mode"],
                "hit_count": len(result["hits"]), "supplement_hit_count": len(result["supplement_hits"]),
                "supplement_status": result["supplement_status"],
            })
            for hit in [*result["hits"], *result["supplement_hits"]]:
                bundled = hit["source_kind"] == "bundled_synthesis"
                key = ("rule", hit["card_id"]) if bundled else ("pdf", hit["source"], hit["pdf_page"])
                if key in seen:
                    continue
                seen.add(key)
                entry = {"evidence_id": f"E{len(evidence) + 1}", "topic": topic, **hit}
                if bundled:
                    entry["guidance"] = expertise.rule(hit["card_id"])
                evidence.append(entry)
    snapshot_context = _snapshot_context(snapshot) if snapshot is not None else None
    if visual_context is not None and snapshot_context["request_id"] != visual_context["after_request_id"]:
        raise ProtocolError("Visual observation and snapshot content have different request IDs.")
    context: dict[str, object] = {
        "schema_version": 2, "kind": "pcb-advisory-context",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_freshness": "Bundled guidance is release-versioned synthesis, not a live book read. Optional PDF metadata is checked when configured.",
        "goal": goal.strip(), "topics": list(dict.fromkeys(topics)),
        "backend_capabilities": backend_capabilities(),
        "snapshot": snapshot_context,
        "visual": visual_context,
        "evidence": evidence, "queries": queries, "warnings": list(dict.fromkeys(warnings)),
        "coverage": {
            "bundled": coverage["bundled"],
            "supplement_status": coverage["supplement_status"],
            "documents": len(documents),
            "indexed_pages": sum(item["indexed_pages"] for item in documents),
            "incomplete_documents": [
                {
                    "source": item["source"], "status": item["status"],
                    "notice_count": len(item["notices"]), "notices": item["notices"][:3],
                    "more_notices": len(item["notices"]) > 3,
                }
                for item in documents if item["status"] != "indexed"
            ],
        },
        "authority": {
            "advisory_only": True, "approves_board_changes": False,
            "runs_cadence": False, "calls_model_provider": False,
            "notice": "This is retrieved context, not an LLM review or a PCB safety certification.",
        },
        "required_missing_inputs": [
            "Confirmed component functions and pin/net associations",
            "IC/regulator datasheets, recommended layouts, and project constraints",
            "Stackup/reference planes, edge rates, currents and voltage/isolation requirements",
            "Mechanical, assembly, fabrication and thermal requirements",
        ],
    }
    output_directory = output_directory.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    output = output_directory / f"context-{uuid.uuid4().hex}.json"
    write_json(output, context)
    return output, context

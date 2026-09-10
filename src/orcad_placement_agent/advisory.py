"""Build bounded evidence packets for read-only Copilot expert profiles."""

import json
from datetime import datetime, timezone
from pathlib import Path
import uuid

from . import knowledge
from .protocol import MAX_BYTES, ProtocolError, Receipt, encode_rows
from .proposals import check_snapshot
from .session import write_json


TOPIC_QUERIES = {
    "placement": ("component placement fixed", "placement routing"),
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
    if (
        not isinstance(data, dict)
        or set(data) != {"nonce", "request_id", "status", "message", "records"}
        or not isinstance(data["records"], list)
    ):
        raise ProtocolError("Use an original snapshot receipt JSON, not a board binary or proposal.")
    if any(not isinstance(row, list) for row in data["records"]):
        raise ProtocolError("Invalid snapshot records.")
    payload = encode_rows([
        ["OPA", "1", data["nonce"], data["request_id"], data["status"]],
        ["message", data["message"]], *data["records"], ["end", data["request_id"]],
    ])
    receipt = Receipt.decode(payload, data["nonce"], data["request_id"])
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


def build_context(
    goal: str, database: Path = knowledge.DEFAULT_DATABASE, *,
    topics: tuple[str, ...] = ("placement", "decoupling", "return-paths"),
    snapshot: Path | None = None,
    output_directory: Path = Path(".runtime") / "advisory",
) -> tuple[Path, dict[str, object]]:
    if not goal.strip() or len(goal) > 2000:
        raise knowledge.KnowledgeError("Supply a nonempty review goal of at most 2000 characters.")
    if not topics or len(topics) > len(TOPIC_QUERIES) or any(topic not in TOPIC_QUERIES for topic in topics):
        raise knowledge.KnowledgeError("Select one or more of the documented PCB review topics.")
    documents = knowledge.catalog(database)
    queries = []
    evidence: list[dict[str, object]] = []
    seen = set()
    for topic in dict.fromkeys(topics):
        for query in TOPIC_QUERIES[topic]:
            result = knowledge.search(query, database, limit=3)
            queries.append({
                "topic": topic, "query": query, "match_mode": result["match_mode"],
                "hit_count": len(result["hits"]),
            })
            for hit in result["hits"]:
                key = (hit["source"], hit["pdf_page"])
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({"evidence_id": f"E{len(evidence) + 1}", "topic": topic, **hit})
    context: dict[str, object] = {
        "schema_version": 1, "kind": "pcb-advisory-context",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_freshness": "Source metadata was checked during generation; regenerate after reference changes.",
        "goal": goal.strip(), "topics": list(dict.fromkeys(topics)),
        "snapshot": _snapshot_context(snapshot) if snapshot is not None else None,
        "evidence": evidence, "queries": queries,
        "coverage": {
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

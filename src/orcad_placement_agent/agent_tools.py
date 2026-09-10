"""Data-only process boundary used by the Copilot placement extension."""

from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
from typing import Callable

from .diagnostics import ConfigurationError, default_runtime_directory
from .capabilities import backend_capabilities
from . import expertise
from .protocol import MAX_BYTES, ProtocolError, Receipt, identifier
from .proposals import approve_and_apply, load_proposal, propose, proposal_summary
from .session import Session, SessionError, write_json
from .transport import IndeterminateDelivery, TransportError


class AgentActionError(ValueError):
    """A bounded agent action is invalid or lacks required evidence."""


def json_wire(value: object) -> object:
    """Keep Windows FILETIME identities exact across the JavaScript tool host."""
    if type(value) is int and abs(value) > 9007199254740991:
        return str(value)
    if isinstance(value, dict):
        return {key: json_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_wire(item) for item in value]
    return value


def display_payload(value: object) -> object:
    """Compact tool presentation; complete native receipts stay on disk."""
    if isinstance(value, str) and value.startswith("OPA-FIXTURE-1;"):
        return {"opaque_scene_omitted_from_display": True,
                "instruction": "Use the persisted native receipt for complete scene data."}
    if isinstance(value, dict):
        return {key: display_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [display_payload(item) for item in value]
    return json_wire(value)


def capture_visual(session: Session) -> dict[str, object]:
    from .visuals import VisualError, capture_observation

    try:
        return capture_observation(session)
    except VisualError as error:
        raise AgentActionError(f"Visual inspection is unavailable: {error}") from error


class AgentActions:
    def __init__(
        self, root: Path | None = None, *,
        session_factory: Callable[[Path], Session] = Session,
        capture: Callable[[Session], dict[str, object]] = capture_visual,
    ) -> None:
        self.root = (root if root is not None else default_runtime_directory()).resolve()
        self.session_factory = session_factory
        self.capture = capture

    def session(self, name: str) -> Session:
        if not isinstance(name, str) or re.fullmatch(r"board-[A-Za-z0-9_-]{1,64}", name) is None:
            raise AgentActionError("Use a staged board-session name, not a path or command.")
        path = (self.root / name).resolve(strict=True)
        if path.parent != self.root or not path.is_dir():
            raise AgentActionError("Session must be a direct child of the managed runtime.")
        return self.session_factory(path)

    def observation(self, session: Session) -> dict[str, object]:
        observation = self.capture(session)
        if not isinstance(observation, dict) or not isinstance(observation.get("image_path"), str):
            raise AgentActionError("Capture returned invalid visual metadata.")
        observation_id = identifier(observation.get("observation_id"))
        expected = session.root / f"visual-{observation_id}.png"
        if Path(observation["image_path"]).resolve() != expected:
            raise AgentActionError("Capture returned a non-session image path.")
        if not expected.is_file():
            raise AgentActionError("Capture did not publish an image.")
        return observation

    def snapshot(self, session: Session, observation: dict[str, object]) -> Receipt:
        request_id = identifier(observation["after_request_id"])
        receipt = Receipt.from_dict(session._read_json(f"{request_id}.receipt.json"))
        if receipt.nonce != session.nonce or receipt.request_id != request_id:
            raise AgentActionError("Visual observation and saved snapshot do not match.")
        if receipt.status != "snapshot":
            raise AgentActionError("Visual observation requires a successful read-only snapshot.")
        return receipt

    def describe(self, session: Session, digest: str) -> dict[str, object]:
        proposal = load_proposal(session, digest)
        binding = session._read_json(f"visual-proposal-{digest}.json")
        if binding.get("proposal_sha256") != digest:
            raise AgentActionError("The proposal's visual evidence binding is invalid.")
        observation_id = identifier(binding.get("observation_id"))
        observation = session._read_json(f"visual-{observation_id}.json")
        receipt = self.snapshot(session, observation)
        if (
            proposal["snapshot_id"] != receipt.one("snapshot")[1]
            or proposal["scene_digest"] != receipt.scene_digest
        ):
            raise AgentActionError("Visual evidence does not match the reviewed proposal.")
        image = session.root / f"visual-{observation_id}.png"
        if Path(observation["image_path"]).resolve() != image or not image.is_file():
            raise AgentActionError("Proposal image is missing or outside the session.")
        session.verify_source()
        return {
            "session": session.root.name,
            "proposal_sha256": digest,
            "summary": proposal_summary(proposal),
            "working_board": str(session.working),
            "snapshot_id": proposal["snapshot_id"],
            "visual": observation,
            "approval_prompt": f"APPLY {digest}",
            "warning": "Memory only. Native preconditions are rechecked after approval; this is not a save.",
        }

    def dispatch(self, request: dict[str, object]) -> dict[str, object]:
        if not isinstance(request, dict) or not isinstance(request.get("action"), str):
            raise AgentActionError("A typed action object is required.")
        action = request["action"]
        if action in {"reference-catalog", "reference-search", "reference-rule"}:
            fields = {
                "reference-catalog": {"action"},
                "reference-search": {"action", "query"},
                "reference-rule": {"action", "card_id"},
            }
            if set(request) != fields[action]:
                raise AgentActionError("Unexpected or missing bundled-reference fields.")
            try:
                if action == "reference-catalog":
                    data = expertise.catalog()
                elif action == "reference-search":
                    data = expertise.search(request["query"])
                else:
                    data = expertise.rule(request["card_id"])
            except expertise.KnowledgeError as error:
                raise AgentActionError(str(error)) from error
            return {"status": "reference", "data": data}
        if action == "sessions":
            if set(request) != {"action"}:
                raise AgentActionError("Session discovery takes no paths or additional fields.")
            sessions = []
            if self.root.is_dir():
                for path in sorted(self.root.glob("board-*")):
                    try:
                        session = self.session(path.name)
                        entry = {"session": path.name, "working_board": str(session.working)}
                        if (session.root / "editor.json").is_file():
                            entry["editor"] = asdict(session.editor())
                            entry["binding"] = "Recorded identity; not proof this board is currently open."
                        else:
                            entry["binding"] = "Not attached."
                        sessions.append(entry)
                    except (AgentActionError, ProtocolError, SessionError, TransportError, OSError, json.JSONDecodeError) as error:
                        sessions.append({"session": path.name, "error": str(error)})
            return {"status": "listed", "capabilities": backend_capabilities(), "sessions": sessions}
        allowed = {
            "inspect": {"action", "session"},
            "prepare": {"action", "session", "refdes", "x", "y", "angle"},
            "describe": {"action", "session", "proposal"},
            "apply": {"action", "session", "proposal", "confirmation"},
            "execution-status": {"action", "session", "proposal"},
            "inspection-status": {"action", "session"} | ({"request"} if "request" in request else set()),
        }
        if action not in allowed or set(request) != allowed[action]:
            raise AgentActionError("Unsupported action or unexpected/missing fields.")
        if not all(isinstance(value, str) for value in request.values()):
            raise AgentActionError("Agent action values must be strings.")
        session = self.session(request["session"])
        if action == "inspection-status":
            pending_path = session.root / "pending.json"
            requested = identifier(request["request"]) if "request" in request else None
            if not pending_path.is_file():
                return {"status": "idle", "message": "No unresolved operation is recorded; nothing was resent."}
            pending = session._read_json("pending.json")
            request_id = identifier(pending.get("request_id"))
            if pending.get("operation") != "snapshot":
                return {
                    "status": "blocked", "message": "The pending operation is not read-only. Use its proposal execution status.",
                }
            if requested is None:
                return {
                    "status": "inspection_pending", "request": request_id,
                    "result_available": (session.root / f"{request_id}.result.csv").is_file(),
                    "message": "Supply this exact request ID to reconcile only this read-only result; no command was sent.",
                }
            if requested != request_id:
                raise AgentActionError("A different inspection is pending; it was not reconciled.")
            receipt = session.reconcile(expected_request_id=request_id, expected_operation="snapshot")
            return {
                "status": "inspection_reconciled", "request": request_id,
                "receipt": receipt.to_dict(), "message": "Read-only result reconciled without replay.",
            }
        if action == "inspect":
            observation = self.observation(session)
            return {
                "status": "observed", "session": session.root.name,
                "visual": observation, "snapshot": self.snapshot(session, observation).to_dict(),
                "warning": "Pixels do not establish DRC, complete layer coverage, or electrical correctness.",
            }
        if action == "prepare":
            observation = self.observation(session)
            receipt = self.snapshot(session, observation)
            digest, proposal = propose(
                session, receipt, request["refdes"], request["x"],
                request["y"], request["angle"],
            )
            binding = session.root / f"visual-proposal-{digest}.json"
            write_json(binding, {
                "proposal_sha256": digest, "observation_id": observation["observation_id"],
            })
            return {"status": "prepared", **self.describe(session, digest)}
        if action == "execution-status":
            load_proposal(session, request["proposal"])
            approval_path = session.root / f"approval-{request['proposal']}.json"
            if not approval_path.is_file():
                return {"status": "not_dispatched", "message": "This proposal has no consumed approval."}
            approval = session._read_json(approval_path.name)
            request_id = identifier(approval.get("request_id"))
            receipt_path = session.root / f"{request_id}.receipt.json"
            if receipt_path.is_file():
                receipt = Receipt.from_dict(session._read_json(receipt_path.name))
            else:
                if not (session.root / "pending.json").is_file():
                    return {
                        "status": "indeterminate",
                        "message": "Approval was consumed but no terminal receipt is recorded. Inspect the dedicated board; do not replay.",
                    }
                pending = session._read_json("pending.json")
                if pending.get("request_id") != request_id:
                    raise AgentActionError("A different operation is unresolved; nothing was replayed.")
                receipt = session.reconcile(expected_request_id=request_id, expected_operation="apply")
            if receipt.nonce != session.nonce or receipt.request_id != request_id:
                raise AgentActionError("Execution receipt does not match the consumed approval.")
            result = {
                "status": receipt.status, "receipt": receipt.to_dict(),
                "message": "Recorded native outcome only; no command was resent.",
            }
            pending_path = session.root / "pending.json"
            if pending_path.is_file():
                pending = session._read_json("pending.json")
                if pending.get("operation") == "snapshot":
                    result["pending_inspection"] = identifier(pending.get("request_id"))
                    result["message"] += (
                        " A separate read-only snapshot remains unresolved. Use "
                        "pcb_inspection_status with its exact request ID; do not repeat Apply."
                    )
            return result
        description = self.describe(session, request["proposal"])
        if action == "describe":
            return {"status": "prepared", **description}
        # This field comes from the extension's interactive UI, never from the
        # model-visible tool schema. The existing single-use guard is reused.
        receipt = approve_and_apply(session, request["proposal"], request["confirmation"])
        result: dict[str, object] = {
            "status": receipt.status, "receipt": receipt.to_dict(),
            "proposal_sha256": request["proposal"],
            "message": "Native outcome recorded; do not repeat this approval.",
        }
        from .visuals import VisualError

        try:
            observation = self.observation(session)
            result["visual"] = observation
            if receipt.status in {"applied", "rolled_back"}:
                observed = self.snapshot(session, observation)
                if observed.one("scene")[1] != receipt.one("scene")[1]:
                    result["visual_error"] = "The scene changed after the native outcome; the image shows the later state."
                    result["message"] = "Do not retry. Compare the recorded native receipt with this later visual observation."
        except (VisualError, AgentActionError, ProtocolError, SessionError, TransportError, OSError) as error:
            result["visual_error"] = str(error)
            result["message"] = (
                f"Native outcome is {receipt.status}, but post-operation capture is unavailable. "
                "Do not retry the placement; inspect the recorded receipt and reconcile."
            )
        write_json(session.root / f"agent-execution-{receipt.request_id}.json", result)
        return result


def main() -> int:
    try:
        payload = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise AgentActionError("Agent action exceeds the input limit.")
        request = json.loads(payload.decode("utf-8"))
        response = AgentActions().dispatch(request)
        print(json.dumps(display_payload(response), ensure_ascii=True))
        return 0
    except IndeterminateDelivery as error:
        print(json.dumps({"status": "indeterminate", "error": str(error), "retry": False}))
        return 3
    except (AgentActionError, ConfigurationError, ProtocolError, SessionError, TransportError,
            OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

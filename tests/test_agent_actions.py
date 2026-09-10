import json
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.agent_tools import AgentActionError, AgentActions, json_wire
from orcad_placement_agent.protocol import Receipt, encode_rows
from orcad_placement_agent.session import SessionError, write_json, write_new
from orcad_placement_agent.transport import IndeterminateDelivery


class FakeSession:
    nonce = "a" * 32

    def __init__(self, root):
        self.root = root
        self.working = root / "working.brd"
        self.requests = []
        self.reconciliations = []
        self.scene = "unchanged fixture"

    def _read_json(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def verify_source(self):
        pass

    def exchange(self, request):
        self.requests.append(request)
        receipt = Receipt(self.nonce, request.request_id, "applied", "Applied in memory", (
            ("scene", self.scene),
        ))
        write_json(self.root / f"{request.request_id}.receipt.json", receipt.to_dict())
        return receipt

    def reconcile(self, *, expected_request_id=None, expected_operation=None):
        pending = self._read_json("pending.json")
        if expected_request_id is not None and expected_request_id != pending["request_id"]:
            raise SessionError("Different pending request")
        if expected_operation is not None and expected_operation != pending["operation"]:
            raise SessionError("Different pending operation")
        result = self.root / f"{pending['request_id']}.result.csv"
        if not result.is_file():
            raise IndeterminateDelivery("Late snapshot has not arrived.")
        receipt = Receipt.decode(result.read_bytes(), self.nonce, pending["request_id"])
        self.reconciliations.append(pending["request_id"])
        (self.root / "pending.json").unlink()
        return receipt


class AgentActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.board = self.root / "board-fixture"
        self.board.mkdir()
        self.session = FakeSession(self.board)
        self.captures = 0
        self.service = AgentActions(
            self.root, session_factory=lambda _root: self.session, capture=self.capture
        )

    def capture(self, session):
        self.captures += 1
        observation_id = f"{self.captures:032x}"
        request_id = f"{self.captures + 100:032x}"
        image = session.root / f"visual-{observation_id}.png"
        write_new(image, b"\x89PNG\r\n\x1a\nsynthetic test bytes")
        receipt = Receipt(session.nonce, request_id, "snapshot", "Read", (
            ("board", str(session.working)), ("units", "millimeters", "4", "10000"),
            ("version", "25.1"), ("snapshot", request_id), ("scene", session.scene),
            ("component", "R1", "fixture", "10", "10", "0", "0", "0", "1"),
        ))
        write_json(session.root / f"{request_id}.receipt.json", receipt.to_dict())
        metadata = {
            "observation_id": observation_id, "image_path": str(image),
            "after_request_id": request_id,
        }
        write_json(session.root / f"visual-{observation_id}.json", metadata)
        return metadata

    def prepare(self):
        return self.service.dispatch({
            "action": "prepare", "session": self.board.name,
            "refdes": "R1", "x": "12", "y": "12", "angle": "90",
        })

    def test_large_windows_process_identity_is_not_rounded_by_javascript(self):
        value = {"editor": {"started": 134334796530859671, "pid": 27208}}
        converted = json_wire(value)
        self.assertEqual(converted["editor"]["started"], "134334796530859671")
        self.assertEqual(converted["editor"]["pid"], 27208)
        self.assertEqual(value["editor"]["started"], 134334796530859671)

    def test_prepare_binds_visual_evidence_without_moving(self):
        result = self.prepare()
        self.assertEqual(result["status"], "prepared")
        self.assertTrue(Path(result["visual"]["image_path"]).is_file())
        self.assertEqual(self.session.requests, [])
        self.assertIn("(12, 12)", result["summary"])

    def test_paths_unknown_fields_and_arbitrary_actions_are_rejected(self):
        for request in [
            {"action": "inspect", "session": "..\\board-fixture"},
            {"action": "inspect", "session": str(self.board)},
            {"action": "inspect", "session": self.board.name, "command": "skill"},
            {"action": "eval", "session": self.board.name},
        ]:
            with self.subTest(request=request):
                with self.assertRaises(AgentActionError):
                    self.service.dispatch(request)
        self.assertEqual(self.captures, 0)

    def test_apply_without_exact_confirmation_never_moves(self):
        result = self.prepare()
        with self.assertRaises(SessionError):
            self.service.dispatch({
                "action": "apply", "session": self.board.name,
                "proposal": result["proposal_sha256"], "confirmation": "yes",
            })
        self.assertEqual(self.session.requests, [])

    def test_missing_visual_binding_blocks_apply(self):
        result = self.prepare()
        (self.board / f"visual-proposal-{result['proposal_sha256']}.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.service.dispatch({
                "action": "apply", "session": self.board.name,
                "proposal": result["proposal_sha256"],
                "confirmation": result["approval_prompt"],
            })
        self.assertEqual(self.session.requests, [])

    def test_mismatched_snapshot_cannot_be_reused_as_visual_approval(self):
        result = self.prepare()
        metadata_path = self.board / f"visual-{result['visual']['observation_id']}.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["after_request_id"] = "f" * 32
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            self.service.describe(self.session, result["proposal_sha256"])

    def test_apply_preserves_native_outcome_if_post_image_fails(self):
        from orcad_placement_agent.visuals import VisualError

        result = self.prepare()
        self.service.capture = lambda _session: (_ for _ in ()).throw(VisualError("No image"))
        applied = self.service.dispatch({
            "action": "apply", "session": self.board.name,
            "proposal": result["proposal_sha256"],
            "confirmation": result["approval_prompt"],
        })
        self.assertEqual(applied["status"], "applied")
        self.assertIn("visual_error", applied)
        self.assertEqual(len(self.session.requests), 1)
        status = self.service.dispatch({
            "action": "execution-status", "session": self.board.name,
            "proposal": result["proposal_sha256"],
        })
        self.assertEqual(status["status"], "applied")
        self.assertEqual(len(self.session.requests), 1)

    def test_visual_failure_does_not_prevent_recorded_execution_status(self):
        result = self.prepare()
        request_id = "d" * 32
        write_json(self.board / f"approval-{result['proposal_sha256']}.json", {
            "proposal_sha256": result["proposal_sha256"], "request_id": request_id,
        })
        Path(result["visual"]["image_path"]).unlink()
        status = self.service.dispatch({
            "action": "execution-status", "session": self.board.name,
            "proposal": result["proposal_sha256"],
        })
        self.assertEqual(status["status"], "indeterminate")
        self.assertEqual(self.session.requests, [])

    def test_late_capture_is_reconciled_separately_from_successful_apply(self):
        result = self.prepare()
        apply_id = "d" * 32
        capture_id = "e" * 32
        write_json(self.board / f"approval-{result['proposal_sha256']}.json", {
            "proposal_sha256": result["proposal_sha256"], "request_id": apply_id,
        })
        write_json(self.board / f"{apply_id}.receipt.json", Receipt(
            self.session.nonce, apply_id, "applied", "Applied", (("scene", self.session.scene),)
        ).to_dict())
        write_json(self.board / "pending.json", {"request_id": capture_id, "operation": "snapshot"})
        status = self.service.dispatch({
            "action": "execution-status", "session": self.board.name,
            "proposal": result["proposal_sha256"],
        })
        self.assertEqual(status["status"], "applied")
        self.assertEqual(status["pending_inspection"], capture_id)
        self.assertEqual(self.session.reconciliations, [])
        report = self.service.dispatch({"action": "inspection-status", "session": self.board.name})
        self.assertEqual(report["request"], capture_id)
        self.assertEqual(self.session.reconciliations, [])
        with self.assertRaises(AgentActionError):
            self.service.dispatch({
                "action": "inspection-status", "session": self.board.name, "request": "f" * 32,
            })
        with self.assertRaises(IndeterminateDelivery):
            self.service.dispatch({
                "action": "inspection-status", "session": self.board.name, "request": capture_id,
            })
        self.assertTrue((self.board / "pending.json").exists())
        write_new(self.board / f"{capture_id}.result.csv", encode_rows([
            ("OPA", "1", self.session.nonce, capture_id, "snapshot"),
            ("message", "Late read-only result"), ("scene", self.session.scene),
            ("end", capture_id),
        ]))
        restored = self.service.dispatch({
            "action": "inspection-status", "session": self.board.name, "request": capture_id,
        })
        self.assertEqual(restored["status"], "inspection_reconciled")
        self.assertEqual(self.session.reconciliations, [capture_id])
        self.assertFalse((self.board / "pending.json").exists())
        self.assertEqual(self.session.requests, [])

    def test_inspection_recovery_cannot_clear_a_pending_placement(self):
        write_json(self.board / "pending.json", {"request_id": "e" * 32, "operation": "apply"})
        result = self.service.dispatch({
            "action": "inspection-status", "session": self.board.name, "request": "e" * 32,
        })
        self.assertEqual(result["status"], "blocked")
        self.assertTrue((self.board / "pending.json").exists())
        self.assertEqual(self.session.reconciliations, [])


if __name__ == "__main__":
    unittest.main()

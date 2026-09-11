"""Closed-loop controller tests with a fake editor, not native Cadence evidence."""

import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from orcad_placement_agent.agent_tools import AgentActions, AgentActionError
from orcad_placement_agent.protocol import Receipt
from orcad_placement_agent.visuals import encode_png
from tests.test_board import managed_snapshot


class FakeManagedEditor:
    nonce = "1" * 32
    model = "managed-board-v1"

    def __init__(self, root):
        self.root = root
        self.working = root / "working.brd"
        self.working.write_bytes(b"Original fake managed editor")
        self.parts = {ref: {"x": "0", "y": "0", "angle": "0", "placed": "0"}
                      for ref in ("U1", "U2", "R1")}
        self.frames = {}
        self.requests = []
        self.fail_capture = False

    def verify_source(self):
        pass

    def _read_json(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def records(self):
        records = [
            row for row in managed_snapshot().records
            if row[0] not in {"component", "bounds", "pin", "scene", "scene-part", "snapshot", "board"}
        ]
        records.append(("board", str(self.working)))
        for ref, part in sorted(self.parts.items()):
            records.extend([
                ("component", ref, "original-package", part["x"], part["y"], part["angle"], "0", "0", part["placed"]),
                ("bounds", ref, "-2", "-1", "2", "1"),
                ("pin", ref, "1", "SIGNAL", "-1", "0"), ("pin", ref, "2", "RETURN", "1", "0"),
            ])
        records.append(("scene", "OPA-BOARD-1;" + json.dumps(self.parts, sort_keys=True)))
        return tuple(records)

    def capture(self, _session):
        if self.fail_capture:
            raise AgentActionError("Fake post-operation capture unavailable")
        request_id, observation_id = uuid.uuid4().hex, uuid.uuid4().hex
        receipt = Receipt(self.nonce, request_id, "snapshot", "Fake native readback",
                          (*self.records(), ("snapshot", request_id)))
        self.frames[request_id] = receipt
        (self.root / f"{request_id}.receipt.json").write_text(json.dumps(receipt.to_dict()), encoding="utf-8")
        image = self.root / f"visual-{observation_id}.png"
        image.write_bytes(encode_png(1, 1, bytes(4)))
        observation = {
            "observation_id": observation_id, "image_path": str(image),
            "before_request_id": request_id, "after_request_id": request_id,
            "width": 1, "height": 1,
        }
        (self.root / f"visual-{observation_id}.json").write_text(json.dumps(observation), encoding="utf-8")
        return observation

    def exchange(self, request):
        self.requests.append(request)
        expected = self.frames[request.snapshot_id]
        current = Receipt(self.nonce, request.request_id, "snapshot", "", self.records())
        if expected.scene != current.scene:
            receipt = Receipt(self.nonce, request.request_id, "rejected", "Fake stale scene", ())
        elif request.operation == "apply":
            self.parts[request.refdes].update(x=request.x, y=request.y, angle=request.angle, placed="1")
            receipt = Receipt(self.nonce, request.request_id, "applied", "Fake initial placement", self.records())
        else:
            destination = self.root / request.destination
            destination.write_text(json.dumps(self.parts), encoding="utf-8")
            receipt = Receipt(self.nonce, request.request_id, "saved", "Fake saved revision",
                              (*self.records(), ("saved", str(destination))))
        (self.root / f"{request.request_id}.receipt.json").write_text(json.dumps(receipt.to_dict()), encoding="utf-8")
        return receipt


class MissionActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        session_root = self.root / "board-mission"
        session_root.mkdir()
        self.editor = FakeManagedEditor(session_root)
        self.actions = AgentActions(self.root, session_factory=lambda _root: self.editor,
                                    capture=self.editor.capture)

    def call(self, action, **kwargs):
        return self.actions.dispatch({"action": action, "session": "board-mission", **kwargs})

    def plan(self, **overrides):
        requirements = {"expected_refdes": ["U1", "U2", "R1"], "grid_mm": "1", "clearance_mm": "0.5",
                        **overrides}
        return self.call("mission-plan", requirements_json=json.dumps(requirements))

    def test_complete_zero_placed_mission_uses_real_controller_prepare_approval_and_readback(self):
        planned = self.plan()
        self.assertEqual(planned["status"], "mission_planned")
        self.assertEqual(self.editor.requests, [])
        mission = planned["mission"]
        for count in range(3):
            prepared = self.call("mission-next", mission=mission)
            self.assertEqual(prepared["status"], "prepared")
            self.assertIn("UNPLACED", prepared["summary"])
            self.assertEqual(prepared["progress"]["placement"]["verified_placed_count"], count)
            digest = prepared["proposal_sha256"]
            # Explicit fake approval exercises the controller; it is never sent to Cadence.
            result = self.call("apply", proposal=digest, confirmation=f"APPLY {digest}")
            self.assertEqual(result["status"], "applied")
            self.assertNotIn("visual_error", result)
        status = self.call("mission-status", mission=mission)
        self.assertTrue(status["progress"]["placement"]["complete"])
        self.assertEqual(status["progress"]["routing"]["verification"], "unverified")
        self.assertEqual(status["progress"]["persistence"]["status"], "unverified")
        done = self.call("mission-next", mission=mission)
        self.assertNotIn("proposal_sha256", done)
        self.assertEqual(len(self.editor.requests), 3)
        prepared = self.call("prepare-save")
        digest = prepared["proposal_sha256"]
        result = self.call("apply-save", proposal=digest, confirmation=f"SAVE {digest}")
        self.assertEqual(result["status"], "saved")
        self.assertTrue(result["artifact_available"])
        self.assertFalse(result["reopened"])
        self.assertEqual(self.call("save-status", proposal=digest)["status"], "saved")

    def test_blocked_inventory_and_protected_state_never_prepare_a_move(self):
        self.assertEqual(self.plan(expected_refdes=["U1"])["status"], "blocked")
        planned = self.plan()
        self.editor.parts["U1"].update(x="10", y="10", placed="1")
        result = self.call("mission-next", mission=planned["mission"])
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("proposal_sha256", result)
        self.assertEqual(self.editor.requests, [])

    def test_save_post_image_failure_preserves_saved_outcome(self):
        prepared = self.call("prepare-save")
        self.editor.fail_capture = True
        digest = prepared["proposal_sha256"]
        result = self.call("apply-save", proposal=digest, confirmation=f"SAVE {digest}")
        self.assertEqual(result["status"], "saved")
        self.assertIn("visual_error", result)
        self.assertEqual(len(self.editor.requests), 1)

    def test_unrepresentable_candidate_cannot_publish_a_rounded_proposal(self):
        planned = self.plan()
        candidate = {"status": "candidate", "refdes": "U1",
                     "x": "10.00005", "y": "10.00005", "angle": "0"}
        with patch("orcad_placement_agent.missions.next_candidate", return_value=candidate):
            with self.assertRaisesRegex(AgentActionError, "representable"):
                self.call("mission-next", mission=planned["mission"])
        self.assertEqual(list(self.editor.root.glob("proposal-*.json")), [])
        self.assertEqual(self.editor.requests, [])


if __name__ == "__main__":
    unittest.main()

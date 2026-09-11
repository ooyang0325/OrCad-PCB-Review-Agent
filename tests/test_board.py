import json
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.board import from_receipt
from orcad_placement_agent.protocol import ProtocolError, Receipt
from orcad_placement_agent.proposals import propose, proposal_summary
from orcad_placement_agent.session import Session, SessionError, stage_session


def managed_snapshot(*, placed="0", extra=(), request_id="2" * 32):
    return Receipt("1" * 32, request_id, "snapshot", "Original managed fixture", (
        ("snapshot", request_id), ("board", r"C:\isolated\working.brd"),
        ("units", "millimeters", "4", "10000"), ("version", "25.1"),
        ("model", "managed-board-v1"),
        ("scene", "OPA-BOARD-1;chunks=2"), ("scene-part", "0", "OPA-BOARD-1;original;"),
        ("scene-part", "1", "complete test scene"),
        ("outline", "0", "0", "40", "30"), ("keepin", "1", "1", "39", "29"),
        ("keepout", "24", "18", "30", "24"), ("layer", "TOP"), ("layer", "BOTTOM"),
        ("component", "U1", "original-package", "0", "0", "0", "0", "0", placed),
        ("bounds", "U1", "-2", "-1", "2", "1"),
        ("pin", "U1", "1", "SIGNAL", "-1", "0"), ("pin", "U1", "2", "RETURN", "1", "0"),
        *extra,
    ))


class ManagedBoardTests(unittest.TestCase):
    def test_native_inventory_includes_unplaced_footprint_and_pin_geometry(self):
        receipt = managed_snapshot()
        decoded = Receipt.from_dict(receipt.to_dict())
        board = from_receipt(decoded)
        self.assertEqual(decoded.scene, "OPA-BOARD-1;original;complete test scene")
        self.assertFalse(board["components"][0]["placed"])
        self.assertEqual(board["components"][0]["bounds"], ["-2", "-1", "2", "1"])
        self.assertEqual(board["components"][0]["pins"][0]["net"], "SIGNAL")
        self.assertEqual(board["keepouts"], [["24", "18", "30", "24"]])

    def test_partial_reordered_and_legacy_scene_chunks_are_rejected(self):
        original = managed_snapshot()
        for records in (
            tuple(row for row in original.records if row[:2] != ("scene-part", "1")),
            tuple(("scene-part", "0", row[2]) if row[:2] == ("scene-part", "1") else row
                  for row in original.records),
            tuple(("scene", "legacy") if row[0] == "scene" else row for row in original.records),
        ):
            receipt = Receipt(original.nonce, original.request_id, "snapshot", "", records)
            with self.assertRaises(ProtocolError):
                from_receipt(receipt)

    def test_unknown_bounds_missing_pin_maps_and_duplicate_geometry_fail_closed(self):
        original = managed_snapshot()
        for records in (
            tuple(row for row in original.records if row[0] != "bounds"),
            tuple(row for row in original.records if row[0] != "pin"),
            (*original.records, ("bounds", "U1", "-2", "-1", "2", "1")),
            (*original.records, ("pin", "missing", "1", "", "0", "0")),
        ):
            with self.assertRaises(ProtocolError):
                from_receipt(Receipt(original.nonce, original.request_id, "snapshot", "", records))

    def test_unplaced_pose_proposal_requires_the_complete_managed_model(self):
        with tempfile.TemporaryDirectory() as directory:
            class FakeSession:
                root = Path(directory)
                nonce = "1" * 32

            _, proposal = propose(FakeSession(), managed_snapshot(), "U1", "10", "10", "90")
            self.assertIn("UNPLACED", proposal_summary(proposal))
            self.assertIn("memory only", proposal_summary(proposal))
            original = managed_snapshot()
            legacy = Receipt(original.nonce, original.request_id, "snapshot", "",
                             tuple(row for row in original.records if row[0] != "model"))
            with self.assertRaises(ProtocolError):
                propose(FakeSession(), legacy, "U1", "10", "10", "90")

    def test_explicit_staging_model_is_bound_and_default_remains_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skill"
            skill.mkdir()
            for name in ("protocol.il", "placement.il", "adapter.il", "managed_board.il"):
                (skill / name).write_text("; original test placeholder", encoding="ascii")
            source = root / "source.brd"
            source.write_bytes(b"Original synthetic test board bytes")
            staged = stage_session(source, root / "sessions", skill, model="managed-board-v1")
            session = Session(staged)
            self.assertEqual(session.model, "managed-board-v1")
            bootstrap = (staged / "bootstrap.il").read_text()
            self.assertLess(bootstrap.index("managed_board.il"), bootstrap.index("adapter.il"))
            self.assertIn('opaBoardModel = "managed-board-v1"', bootstrap)
            self.assertEqual(source.read_bytes(), (staged / "working.brd").read_bytes())
            legacy = stage_session(source, root / "sessions", skill)
            self.assertEqual(Session(legacy).model, "fixture")
            metadata = json.loads((legacy / "session.json").read_text())
            self.assertEqual(metadata["schema_version"], 3)
            self.assertTrue((legacy / "design-data" / "source.brd").is_file())
            with self.assertRaises(SessionError):
                stage_session(source, root / "sessions", skill, model="arbitrary-evaluation")


if __name__ == "__main__":
    unittest.main()

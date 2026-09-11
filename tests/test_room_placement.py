"""Synthetic room/group planning tests, not native placement acceptance."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.board import from_receipt
from orcad_placement_agent.agent_tools import display_payload
from orcad_placement_agent.missions import MissionError, mission_status, next_candidate, plan_mission
from orcad_placement_agent.protocol import ProtocolError, Receipt
from orcad_placement_agent.proposals import propose
from orcad_placement_agent.room_geometry import resolve_rooms
from tests.test_board import managed_snapshot
from tests.test_missions import component, snapshot, requirements, fake_apply, fresh, codes, world_box


def policy(*, label="UC", room_label="UC", bounds=("8", "1", "15", "11")):
    return {
        "model": "grouped-constraints-v1", "digest": "a" * 64,
        "rooms": [{"name": "1_QP", "label": room_label, "bounds": list(bounds)}],
        "room_assignments": [{"refdes": "U1", "owner": "", "label": label},
                             {"refdes": "U1", "owner": "F1", "label": label}],
        "net_groups": [{"name": "POWER", "physical": "POWER", "spacing": "POWER",
                        "same_net": "", "nets": ["SIGNAL"]}],
        "constraint_sets": {"physical": ["DEFAULT", "POWER"], "spacing": ["DEFAULT", "POWER"],
                            "sameNet": ["DEFAULT"]},
        "nets": ["RETURN", "SIGNAL"],
    }


class RoomPlacementTests(unittest.TestCase):
    def board(self, **options):
        board = snapshot([component("U1"), component("U2")])
        board["design_policy"] = policy(**options)
        return board

    def test_matching_room_is_a_hard_whole_footprint_boundary(self):
        board = self.board()
        mission = plan_mission(board, requirements(board))
        self.assertEqual(mission["status"], "ready")
        target = next(target for target in mission["targets"] if target["refdes"] == "U1")
        part = board["components"][0]
        box = world_box(part, target)
        self.assertGreaterEqual(box[0], Decimal("8.5"))
        self.assertLessEqual(box[2], Decimal("14.5"))
        self.assertGreaterEqual(box[1], Decimal("1.5"))
        self.assertLessEqual(box[3], Decimal("10.5"))
        for revision in range(2, 4):
            board = fake_apply(board, next_candidate(board, mission), revision)
        self.assertTrue(mission_status(board, mission)["placement"]["complete"])

    def test_anchor_outside_matched_room_is_not_a_ready_plan(self):
        board = self.board()
        anchor = {"refdes": "U1", "kind": "mechanical-interface", "x": "3", "y": "3", "angle": "0"}
        mission = plan_mission(board, requirements(board, anchors=[anchor]))
        self.assertIn("outside_room", codes(mission))
        self.assertEqual(mission["targets"], [])

    def test_unmapped_tags_do_not_force_parts_into_offboard_staging_boxes(self):
        board = self.board(label="POWER", room_label="1", bounds=("0", "40", "200", "170"))
        board["design_policy"]["rooms"][0]["name"] = "POWER"
        before = deepcopy(board)
        bindings, issues, unmapped = resolve_rooms(board)
        self.assertEqual(bindings, {})
        self.assertEqual(issues, [])
        self.assertEqual(unmapped, ["POWER"])
        mission = plan_mission(board, requirements(board))
        self.assertEqual(mission["status"], "ready")
        self.assertEqual(board, before)
        self.assertIn("unmapped_native_room_labels", mission["evidence"]["routing"]["missing_inputs"])
        self.assertEqual(mission["evidence"]["routing"]["native_policy"]["unmapped_room_labels"], ["POWER"])
        self.assertEqual(mission["evidence"]["routing"]["verification"], "unverified")

    def test_conflicting_tags_or_duplicate_spatial_labels_block_without_guessing(self):
        board = self.board()
        board["design_policy"]["room_assignments"][1]["label"] = "DIFFERENT"
        self.assertIn("conflicting_room_assignments", codes(plan_mission(board, requirements(board))))
        board = self.board()
        board["design_policy"]["rooms"].append({"name": "2_QP", "label": "UC", "bounds": ["1", "1", "7", "7"]})
        self.assertIn("ambiguous_room_geometry", codes(plan_mission(board, requirements(board))))

    def test_constraint_values_or_group_membership_changes_invalidate_mission(self):
        board = self.board()
        mission = plan_mission(board, requirements(board))
        for change in ("digest", "membership", "room", "assignment"):
            current = deepcopy(board)
            if change == "digest":
                current["design_policy"]["digest"] = "b" * 64
            elif change == "membership":
                current["design_policy"]["net_groups"][0]["nets"] = ["RETURN", "SIGNAL"]
            elif change == "room":
                current["design_policy"]["rooms"][0]["bounds"][0] = "9"
            else:
                for assignment in current["design_policy"]["room_assignments"]:
                    assignment["label"] = "OTHER"
            status = mission_status(fresh(current, 2), mission)
            self.assertIn("immutable_facts_changed", codes(status), change)
            self.assertFalse(status["placement"]["complete"])

    def test_impossible_room_never_leaks_a_partial_target_set(self):
        board = self.board(bounds=("8", "1", "9", "2"))
        result = plan_mission(board, requirements(board))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["targets"], [])

    def test_invalid_policy_and_unknown_policy_nets_fail_closed(self):
        board = self.board()
        board["design_policy"] = None
        with self.assertRaises(MissionError):
            plan_mission(board, requirements(board))
        board = self.board()
        board["design_policy"]["nets"] = ["RETURN"]
        with self.assertRaises(MissionError):
            plan_mission(board, requirements(board))


class RoomWireAndProposalTests(unittest.TestCase):
    def test_display_hides_opaque_policy_without_breaking_three_item_object_lists(self):
        payload = {"groups": [{"name": "one"}, {"name": "two"}, {"name": "three"}],
                   "nets": ["policy-part", "0", "legitimate-net"],
                   "records": [["policy-part", "0", "opaque native policy"]]}
        result = display_payload(payload)
        self.assertEqual(result["groups"], payload["groups"])
        self.assertEqual(result["nets"], payload["nets"])
        self.assertEqual(result["records"][0][:2], ["policy-part", "0"])
        self.assertNotIn("opaque native policy", result["records"][0][2])

    def receipt(self):
        base = managed_snapshot()
        return Receipt(base.nonce, base.request_id, base.status, base.message, (
            *base.records, ("policy-model", "grouped-constraints-v1"),
            ("policy", "1", "1", "1", "1", "1", "3", "2"),
            ("policy-part", "0", "OPA-BOARD-1;original-synthetic-group-policy"),
            ("room", "1_QP", "UC", "8", "1", "15", "11"),
            ("room-assignment", "U1", "", "UC"),
            ("net-group", "POWER", "DEFAULT", "DEFAULT", ""),
            ("net-group-member", "POWER", "SIGNAL"),
            ("constraint-set", "physical", "DEFAULT"),
            ("constraint-set", "spacing", "DEFAULT"),
            ("constraint-set", "sameNet", "DEFAULT"),
            ("policy-net", "SIGNAL"), ("policy-net", "RETURN"),
        ))

    def test_complete_native_policy_survives_wire_and_guides_exact_proposals(self):
        receipt = Receipt.from_dict(self.receipt().to_dict())
        board = from_receipt(receipt)
        self.assertEqual(board["design_policy"]["net_groups"][0]["nets"], ["SIGNAL"])
        with tempfile.TemporaryDirectory() as directory:
            class FakeSession:
                root = Path(directory)
                nonce = "1" * 32

            with self.assertRaisesRegex(ProtocolError, "placement room"):
                propose(FakeSession(), receipt, "U1", "3", "3", "0")
            self.assertEqual(list(Path(directory).iterdir()), [])
            _, target = propose(FakeSession(), receipt, "U1", "10", "5", "0")
            self.assertEqual(target["x"], "10")

    def test_dropped_policy_chunks_cannot_be_treated_as_a_legacy_board(self):
        receipt = self.receipt()
        records = tuple(row for row in receipt.records if row[0] != "policy-part")
        with self.assertRaises(ProtocolError):
            from_receipt(Receipt(receipt.nonce, receipt.request_id, receipt.status, "", records))


if __name__ == "__main__":
    unittest.main()

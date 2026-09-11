from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.boundaries import board_boundaries, parse_boundary
from orcad_placement_agent.protocol import ProtocolError, Receipt, canonical_digest
from orcad_placement_agent.board import from_receipt
from orcad_placement_agent.missions import MissionError, mission_status, next_candidate, plan_mission
from orcad_placement_agent.proposals import propose
from orcad_placement_agent.advisory import _snapshot_context
from orcad_placement_agent.session import write_json
from tests.test_board import managed_snapshot
from tests.test_missions import component, snapshot, requirements, fake_apply, fresh, codes


def contour(points, error="0"):
    return {"vertices": [[str(x), str(y)] for x, y in points], "error_mm": error}


L_SHAPE = [(0, 0), (12, 0), (12, 4), (4, 4), (4, 12), (0, 12)]
NOTCH = [(0, 0), (10, 0), (10, 10), (6, 10), (6, 3), (4, 3), (4, 10), (0, 10)]


def box(*values):
    return tuple(Decimal(str(value)) for value in values)


def polygon_board(points=L_SHAPE, *, parts=None, error="0"):
    xs, ys = zip(*points)
    board = snapshot(parts, outline=tuple(str(value) for value in (min(xs), min(ys), max(xs), max(ys))))
    board["outline_boundary"] = contour(points, error)
    board["keepin_boundary"] = contour(points, error)
    return board


class BoundaryTests(unittest.TestCase):
    def test_concave_cutout_is_not_its_bounding_rectangle(self):
        boundary = parse_boundary(contour(L_SHAPE))
        self.assertTrue(boundary.contains_box(box(1, 1, 3, 8)))
        self.assertTrue(boundary.contains_box(box(4, 1, 11, 3)))
        self.assertFalse(boundary.contains_box(box(5, 5, 8, 8)))
        self.assertFalse(boundary.contains_box(box(3, 3, 5, 5)))

    def test_all_corners_inside_is_insufficient_for_a_narrow_notch(self):
        boundary = parse_boundary(contour(NOTCH))
        candidate = box(2, 2, 8, 8)
        for point in ((2, 2), (8, 2), (8, 8), (2, 8)):
            self.assertTrue(boundary.contains_point(tuple(map(Decimal, point))))
        self.assertFalse(boundary.contains_box(candidate))

    def test_edge_and_concave_vertex_contacts_follow_clearance(self):
        boundary = parse_boundary(contour(L_SHAPE))
        self.assertTrue(boundary.contains_box(box(1, 1, 4, 4)))
        self.assertFalse(boundary.contains_box(box(1, 1, 4, 4), Decimal("0.0001")))
        self.assertTrue(boundary.contains_box(box("0.5", "0.5", "3.5", "3.5"), Decimal("0.5")))
        self.assertTrue(boundary.contains_box(box("0.5", "0.5", "3.5001", "3.5"), Decimal("0.5")))
        self.assertFalse(boundary.contains_box(box("0.5", "0.5", "3.5001", "3.5001"), Decimal("0.5")))
        notch = parse_boundary(contour(NOTCH))
        self.assertTrue(notch.contains_box(box(1, 1, 4, 9)))
        self.assertFalse(notch.contains_box(box(1, 1, "4.0001", 9)))

    def test_diagonal_boundary_checks_the_whole_inflated_box(self):
        triangle = parse_boundary(contour([(0, 0), (10, 0), (0, 10)]))
        self.assertTrue(triangle.contains_box(box(1, 1, 5, 5)))
        self.assertFalse(triangle.contains_box(box(1, 1, 6, 5)))
        self.assertTrue(triangle.contains_box(box(1, 1, 4, 4), Decimal(1)))
        self.assertFalse(triangle.contains_box(box(1, 1, 4, 4), Decimal("1.0001")))

    def test_arc_approximation_error_only_tightens_the_allowed_region(self):
        # Deliberately coarse synthetic chord contour; the exporter must supply
        # a bound on its approximation, never silently call it exact.
        points = [(0, 0), (10, 0), (10, 9), (9, 10), (0, 10)]
        exact = parse_boundary(contour(points))
        conservative = parse_boundary(contour(points, "0.0012"))
        candidate = box(8, 8, "9.5", "9.5")
        self.assertTrue(exact.contains_box(candidate))
        self.assertFalse(conservative.contains_box(candidate))
        self.assertTrue(conservative.contains_box(box(2, 2, 8, 8), Decimal("0.5")))

    def test_orientation_start_vertex_and_decimal_spelling_are_canonical(self):
        original = parse_boundary(contour(L_SHAPE))
        for points in (L_SHAPE[2:] + L_SHAPE[:2], list(reversed(L_SHAPE))):
            self.assertEqual(parse_boundary(contour(points)), original)
        with localcontext() as ctx:
            ctx.prec = 6
            self.assertEqual(parse_boundary(contour(L_SHAPE)), original)
            self.assertFalse(original.contains_box(box(3, 3, "4.0001", "4.0001")))

    def test_self_crossing_touching_degenerate_and_oversized_contours_fail_closed(self):
        invalid = [
            [(0, 0), (10, 10), (0, 10), (10, 0)],
            [(0, 0), (10, 0), (5, 0), (5, 10), (0, 10)],
            [(0, 0), (5, 0), (10, 0)],
            [(0, 0), (10, 0), (10, 10), (5, 0), (0, 10)],
            [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
            [(0, 0), (0, 1)],
            [(i, i % 2) for i in range(513)],
        ]
        for points in invalid:
            with self.subTest(points=points[:6]), self.assertRaises(ProtocolError):
                parse_boundary(contour(points))
        for error in ("-0.001", "0.02", "NaN", True):
            with self.subTest(error=error), self.assertRaises(ProtocolError):
                parse_boundary(contour(L_SHAPE, error))
        with self.assertRaises(ProtocolError):
            parse_boundary({**contour(L_SHAPE), "holes": []})
        with self.assertRaises(ProtocolError):
            parse_boundary({"vertices": [[0, 0], [1, 0], [0, 1]], "error_mm": "0"})

    def test_large_coordinates_and_collinear_forward_edges(self):
        offset = Decimal("999999000")
        points = [(offset + x, offset + y) for x, y in NOTCH]
        boundary = parse_boundary(contour(points))
        self.assertFalse(boundary.contains_box(tuple(offset + value for value in box(2, 2, 8, 8))))
        self.assertTrue(parse_boundary(contour([(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)])))

    def test_exhaustive_small_grid_agrees_with_analytic_concave_region(self):
        boundary = parse_boundary(contour(L_SHAPE))
        for x in range(-1, 13):
            for y in range(-1, 13):
                for width, height in ((1, 1), (2, 5), (5, 2), (6, 6)):
                    for margin in (Decimal(0), Decimal("0.5")):
                        expected = (x - margin >= 0 and y - margin >= 0
                                    and x + width + margin <= 12 and y + height + margin <= 12
                                    and (x + width + margin <= 4 or y + height + margin <= 4))
                        self.assertEqual(boundary.contains_box(box(x, y, x + width, y + height), margin),
                                         expected, (x, y, width, height, margin))


class ContourProtocolTests(unittest.TestCase):
    def receipt(self):
        original = managed_snapshot()
        records = [row for row in original.records if row[0] not in {"outline", "keepin", "keepout"}]
        records += [("outline", "0", "0", "12", "12"), ("keepin", "0", "0", "12", "12"),
                    ("boundary-model", "polygon-v1")]
        for role in ("outline", "keepin"):
            records.append(("boundary", role, str(len(L_SHAPE)), "0", str(len(L_SHAPE))))
            records.extend(("boundary-point", role, str(index), str(x), str(y))
                           for index, (x, y) in enumerate(L_SHAPE))
            records.extend(("boundary-source", role, str(index), f"original-edge-{index}")
                           for index in range(len(L_SHAPE)))
        return Receipt(original.nonce, original.request_id, original.status, original.message, tuple(records))

    def test_wire_to_normalized_board_retains_complete_contours(self):
        receipt = Receipt.from_dict(self.receipt().to_dict())
        result = from_receipt(receipt)
        expected = {**contour(L_SHAPE), "source_digest": canonical_digest({
            "edges": [f"original-edge-{index}" for index in range(len(L_SHAPE))],
        })}
        self.assertEqual(result["outline_boundary"], expected)
        self.assertFalse(board_boundaries(result)[0].contains_box(box(5, 5, 8, 8)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            write_json(path, receipt.to_dict())
            context = _snapshot_context(path)
            self.assertEqual(context["geometry"]["outline_boundary"], result["outline_boundary"])
            self.assertNotIn("scene", context)

    def test_missing_reordered_duplicate_or_unversioned_contours_are_rejected(self):
        original = self.receipt()
        invalid = [
            [row for row in original.records if row[:3] != ("boundary-point", "outline", "2")],
            [row for row in original.records if row[0] != "boundary-model"],
            [row for row in original.records if row[:2] != ("boundary", "keepin")],
            [*original.records, ("boundary", "outline", "6", "0", "6")],
            [*original.records, ("boundary-point", "keepout", "0", "1", "1")],
            [("boundary", row[1], "3", "0", "6") if row[0] == "boundary" else row for row in original.records],
            [("outline", "0", "0", "40", "30") if row[0] == "outline" else row for row in original.records],
            [row for row in original.records if row[:3] != ("boundary-source", "outline", "2")],
        ]
        for records in invalid:
            with self.subTest(records=records[-2:]), self.assertRaises(ProtocolError):
                from_receipt(Receipt(original.nonce, original.request_id, original.status, "", tuple(records)))

    def test_exact_proposal_cannot_use_the_empty_part_of_a_concave_bounding_box(self):
        with tempfile.TemporaryDirectory() as directory:
            class FakeSession:
                nonce = "1" * 32
                root = Path(directory)

            receipt = self.receipt()
            with self.assertRaisesRegex(ProtocolError, "contour"):
                propose(FakeSession(), receipt, "U1", "7", "7", "0")
            self.assertEqual(list(Path(directory).iterdir()), [])
            _, proposal = propose(FakeSession(), receipt, "U1", "2", "7", "90")
            self.assertEqual(proposal["angle"], "90")


class PolygonMissionTests(unittest.TestCase):
    def test_zero_placed_to_complete_avoids_concavity(self):
        board = polygon_board(parts=[component("U1"), component("R1"), component("R2")])
        mission = plan_mission(board, requirements(board, clearance_mm="0.5"))
        self.assertEqual(mission["status"], "ready")
        for revision in range(2, 5):
            candidate = next_candidate(board, mission)
            board = fake_apply(board, candidate, revision)
            self.assertNotEqual(mission_status(board, mission)["status"], "blocked")
        status = mission_status(board, mission)
        self.assertTrue(status["placement"]["complete"])
        self.assertEqual(status["routing"]["verification"], "unverified")

    def test_anchors_and_protected_parts_crossing_notch_are_blocked(self):
        part = component("U1", bounds=("-3", "-3", "3", "3"), x="5", y="5", placed=True)
        board = polygon_board(NOTCH, parts=[part])
        self.assertIn("outside_keepin", codes(plan_mission(board, requirements(board, clearance_mm="0"))))
        part["placed"] = False
        anchor = {"refdes": "U1", "kind": "mechanical-interface", "x": "5", "y": "5", "angle": "0"}
        self.assertIn("outside_keepin", codes(plan_mission(board, requirements(board, clearance_mm="0", anchors=[anchor]))))

    def test_keepin_can_extend_past_outline_but_never_authorizes_outside_placement(self):
        board = polygon_board(parts=[component("U1")])
        board["keepin"] = ["-1", "-1", "13", "13"]
        board["keepin_boundary"] = contour([(-1, -1), (13, -1), (13, 13), (-1, 13)])
        anchor = {"refdes": "U1", "kind": "mechanical-interface", "x": "7", "y": "7", "angle": "0"}
        self.assertIn("outside_keepin", codes(plan_mission(board, requirements(board, anchors=[anchor]))))
        mission = plan_mission(board, requirements(board))
        self.assertEqual(mission["status"], "ready")
        self.assertTrue(mission_status(fake_apply(board, next_candidate(board, mission), 2), mission)["placement"]["complete"])

    def test_contour_changes_with_identical_extents_invalidate_mission(self):
        board = polygon_board(parts=[component("U1")])
        mission = plan_mission(board, requirements(board))
        changed = deepcopy(board)
        changed["outline_boundary"]["vertices"][3] = ["3", "4"]
        status = mission_status(fresh(changed, 2), mission)
        self.assertIn("immutable_facts_changed", codes(status))
        changed = deepcopy(board)
        changed["outline_boundary"]["error_mm"] = "0.0012"
        self.assertIn("immutable_facts_changed", codes(mission_status(fresh(changed, 2), mission)))
        changed = deepcopy(board)
        del changed["outline_boundary"]
        with self.assertRaises(MissionError):
            plan_mission(changed, requirements(changed))

    def test_native_source_changes_invalidate_even_identical_rounded_chords(self):
        original = ContourProtocolTests().receipt()
        board = from_receipt(original)
        mission = plan_mission(board, requirements(board))
        changed = Receipt(original.nonce, "3" * 32, original.status, original.message, tuple(
            ("boundary-source", "outline", "0", "changed-native-arc-center")
            if row[:3] == ("boundary-source", "outline", "0") else
            ("snapshot", "3" * 32) if row[0] == "snapshot" else row for row in original.records
        ))
        current = from_receipt(changed)
        self.assertEqual(current["outline_boundary"]["vertices"], board["outline_boundary"]["vertices"])
        self.assertIn("immutable_facts_changed", codes(mission_status(current, mission)))
        invalid = deepcopy(board)
        invalid["outline_boundary"] = None
        with self.assertRaises(MissionError):
            plan_mission(invalid, requirements(invalid))

    def test_rotated_offset_footprint_and_independent_keepin_concavity(self):
        board = polygon_board(parts=[component("U1", bounds=("0", "0", "8", "2"), pins=[])])
        board["keepin_boundary"] = contour([(0, 0), (12, 0), (12, 3), (3, 3), (3, 12), (0, 12)])
        anchor = {"refdes": "U1", "kind": "mechanical-interface", "x": "3", "y": "1", "angle": "90"}
        mission = plan_mission(board, requirements(board, anchors=[anchor], clearance_mm="0"))
        self.assertEqual(mission["status"], "ready")
        anchor["x"] = "4"
        self.assertIn("outside_keepin", codes(plan_mission(board, requirements(board, anchors=[anchor], clearance_mm="0"))))

    def test_no_fit_does_not_leak_a_partial_plan(self):
        board = polygon_board(parts=[component("U1", bounds=("-3", "-3", "3", "3"), pins=[])])
        mission = plan_mission(board, requirements(board, clearance_mm="0"))
        self.assertEqual(mission["status"], "blocked")
        self.assertEqual(mission["targets"], [])
        self.assertEqual(next_candidate(board, mission)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

"""Pure planner tests with synthetic readbacks, not native Cadence validation."""

from copy import deepcopy
from decimal import Decimal, localcontext
import unittest
from unittest.mock import patch

from orcad_placement_agent.missions import (
    MissionError, mission_status, next_candidate, plan_mission,
)
from orcad_placement_agent.protocol import canonical_digest


def component(refdes, *, bounds=("-1", "-1", "1", "1"), x="0", y="0",
              angle="0", placed=False, fixed=False, mirrored=False, pins=None):
    return {
        "refdes": refdes, "package": "original-test-" + refdes,
        "x": x, "y": y, "angle": angle, "placed": placed, "fixed": fixed,
        "mirrored": mirrored, "bounds": list(bounds),
        "pins": deepcopy(pins) if pins is not None else [
            {"number": "1", "net": "SIGNAL", "x": bounds[0], "y": "0"},
            {"number": "2", "net": "", "x": bounds[2], "y": "0"},
        ],
    }


def snapshot(parts=None, *, outline=("0", "0", "16", "12"), keepouts=()):
    board = {
        "model": "managed-board-v1", "board": r"C:\isolated\original-test.brd",
        "snapshot_id": "1" * 32, "scene_digest": "2" * 64,
        "outline": list(outline), "keepin": list(outline),
        "keepouts": [list(box) for box in keepouts], "layers": ["TOP", "BOTTOM"],
        "components": parts if parts is not None else [component("U1"), component("U2"), component("R1")],
    }
    return board


def requirements(board, **overrides):
    return {
        "expected_refdes": [part["refdes"] for part in board["components"]],
        "grid_mm": "1", "clearance_mm": "0.5", **overrides,
    }


def fresh(board, revision=2):
    result = deepcopy(board)
    result["snapshot_id"] = f"{revision:032x}"
    result["scene_digest"] = canonical_digest({
        key: value for key, value in result.items() if key not in ("snapshot_id", "scene_digest")
    })
    return result


def fake_apply(board, candidate, revision):
    result = deepcopy(board)
    part = next(part for part in result["components"] if part["refdes"] == candidate["refdes"])
    part.update({axis: candidate[axis] for axis in ("x", "y", "angle")})
    part["placed"] = True
    return fresh(result, revision)


def codes(result):
    return {item["code"] for item in result["blockers"]}


def world_box(part, pose):
    x1, y1, x2, y2 = map(Decimal, part["bounds"])
    corners = []
    for x in (x1, x2):
        for y in (y1, y2):
            if pose["angle"] == "90":
                x_rot, y_rot = -y, x
            elif pose["angle"] == "180":
                x_rot, y_rot = -x, -y
            elif pose["angle"] == "270":
                x_rot, y_rot = y, -x
            else:
                x_rot, y_rot = x, y
            corners.append((x_rot + Decimal(pose["x"]), y_rot + Decimal(pose["y"])))
    return (min(point[0] for point in corners), min(point[1] for point in corners),
            max(point[0] for point in corners), max(point[1] for point in corners))


class MissionTests(unittest.TestCase):
    def assert_legal(self, board, req, targets):
        parts = {part["refdes"]: part for part in board["components"]}
        clearance = Decimal(req["clearance_mm"])
        boundary = tuple(map(Decimal, board["keepin"]))
        obstacles = [tuple(map(Decimal, box)) for box in board["keepouts"]]
        obstacles += [tuple(map(Decimal, item["bounds"])) for item in req.get("reserved_regions", [])]
        placed = [world_box(part, part) for part in parts.values() if part["placed"]]
        for target in targets:
            self.assertEqual(target["side"], "TOP")
            self.assertIn(target["angle"], ("0", "90", "180", "270"))
            for axis in ("x", "y"):
                self.assertIsInstance(target[axis], str)
                self.assertEqual(Decimal(target[axis]) % Decimal(req["grid_mm"]), 0)
            box = world_box(parts[target["refdes"]], target)
            self.assertGreaterEqual(box[0], boundary[0] + clearance)
            self.assertGreaterEqual(box[1], boundary[1] + clearance)
            self.assertLessEqual(box[2], boundary[2] - clearance)
            self.assertLessEqual(box[3], boundary[3] - clearance)
            for obstacle in obstacles + placed:
                self.assertTrue(
                    box[2] + clearance <= obstacle[0] or obstacle[2] + clearance <= box[0]
                    or box[3] + clearance <= obstacle[1] or obstacle[3] + clearance <= box[1],
                    (box, obstacle),
                )
            placed.append(box)

    def test_zero_placed_to_exact_fresh_readback_coverage_one_at_a_time(self):
        board = snapshot()
        req = requirements(board)
        before = deepcopy((board, req))
        mission = plan_mission(board, req)
        self.assertEqual((board, req), before)
        self.assertEqual(mission["status"], "ready")
        self.assertEqual(len(mission["targets"]), 3)
        self.assert_legal(board, req, mission["targets"])
        status = mission_status(board, mission)
        self.assertEqual(status["placement"]["verified_placed_count"], 0)
        self.assertFalse(status["placement"]["complete"])
        self.assertEqual(status["placement"]["planned_count"], 3)
        original_mission = deepcopy(mission)
        for revision in range(2, 5):
            candidate = next_candidate(board, mission)
            self.assertEqual(candidate["status"], "candidate")
            self.assertEqual(candidate["snapshot_id"], board["snapshot_id"])
            self.assertEqual(candidate["scene_digest"], board["scene_digest"])
            self.assertTrue(candidate["requires_native_prepare_and_human_approval"])
            board = fake_apply(board, candidate, revision)
            status = mission_status(board, mission)
            self.assertEqual(status["placement"]["verified_placed_count"], revision - 1)
        self.assertEqual(mission, original_mission)
        self.assertTrue(status["placement"]["complete"])
        self.assertEqual(status["status"], "placement_complete")
        self.assertIsNone(next_candidate(board, mission))
        self.assertEqual(status["routing"]["verification"], "unverified")
        self.assertEqual(status["routing"]["review"], "not_performed")
        self.assertFalse(status["routing"]["feasibility_proven"])
        self.assertEqual(status["persistence"]["status"], "unverified")

    def test_preserves_existing_fixed_and_unfixed_placed_parts(self):
        board = snapshot([
            component("J1", x="3", y="3", placed=True, fixed=True),
            component("U1", x="8", y="3", placed=True),
            component("R1"),
        ])
        mission = plan_mission(board, requirements(board))
        self.assertEqual(mission["status"], "ready")
        self.assertEqual([target["refdes"] for target in mission["targets"]], ["R1"])
        placed = fake_apply(board, next_candidate(board, mission), 2)
        self.assertEqual(placed["components"][:2], board["components"][:2])
        self.assertEqual(mission_status(placed, mission)["placement"]["verified_placed_count"], 3)

    def test_varied_sizes_rotation_and_origins_outside_footprints(self):
        board = snapshot([
            component("W1", bounds=("3", "2", "10", "4"), pins=[
                {"number": "1", "net": "", "x": "3", "y": "2"},
            ]),
            component("S1", bounds=("-4", "-2", "-3", "0"), pins=[]),
        ], outline=("0", "0", "4", "14"))
        req = requirements(board)
        mission = plan_mission(board, req)
        self.assertEqual(mission["status"], "ready", mission["blockers"])
        self.assert_legal(board, req, mission["targets"])
        wide = next(target for target in mission["targets"] if target["refdes"] == "W1")
        self.assertIn(wide["angle"], ("90", "270"))
        self.assertTrue(Decimal(wide["x"]) > 4 or Decimal(wide["x"]) < 0)

    def test_anchor_and_critical_group_order_precedes_ordinary_parts(self):
        board = snapshot([
            component("A1", bounds=("-2", "-2", "2", "2")),
            component("Z1"), component("Z2"), component("J1"),
        ], outline=("0", "0", "20", "16"))
        req = requirements(board, anchors=[{
            "refdes": "J1", "kind": "mechanical-interface", "x": "16", "y": "12", "angle": "270",
        }], functional_groups=[{"name": "operator-critical", "refdes": ["Z1", "Z2"], "critical": True}])
        mission = plan_mission(board, req)
        self.assertEqual([target["refdes"] for target in mission["targets"]], ["J1", "Z1", "Z2", "A1"])
        self.assertEqual(mission["targets"][0]["angle"], "270")
        self.assert_legal(board, req, mission["targets"])

    def test_critical_net_priority_uses_native_pin_membership(self):
        board = snapshot([
            component("A1", pins=[{"number": "1", "net": "", "x": "0", "y": "0"}]),
            component("Z1", pins=[{"number": "1", "net": "USER-CRITICAL", "x": "0", "y": "0"}]),
        ])
        mission = plan_mission(board, requirements(board, critical_nets=["USER-CRITICAL"]))
        self.assertEqual(mission["targets"][0]["refdes"], "Z1")

    def test_pin_cost_is_not_a_component_center_proxy(self):
        board = snapshot([
            component("J1", x="4", y="4", placed=True, fixed=True, bounds=("-2", "-1", "2", "1"),
                      pins=[{"number": "1", "net": "LINK", "x": "2", "y": "0"}]),
            component("U1", bounds=("-2", "-1", "2", "1"),
                      pins=[{"number": "1", "net": "LINK", "x": "2", "y": "0"}]),
        ], outline=("0", "0", "12", "10"))
        req = requirements(board, critical_nets=["LINK"], clearance_mm="1")
        mission = plan_mission(board, req)
        self.assertEqual(mission["status"], "ready")
        target = mission["targets"][0]
        self.assertNotEqual(target["angle"], "0")
        self.assertEqual(mission["evidence"]["routing"]["metrics"]["total_pin_hpwl_mm"], "1")
        self.assertEqual(mission["evidence"]["routing"]["metrics"]["weighted_pin_hpwl_mm"], "2")
        center_distance = abs(Decimal(target["x"]) - 4) + abs(Decimal(target["y"]) - 4)
        self.assertGreater(center_distance, 1)

    def test_deterministic_plans_costs_and_permuted_inventory(self):
        board = snapshot()
        req = requirements(board, critical_nets=["SIGNAL"])
        first = plan_mission(board, req)
        self.assertEqual(first, plan_mission(board, req))
        board["components"].reverse()
        for part in board["components"]:
            part["pins"].reverse()
        req["expected_refdes"].reverse()
        self.assertEqual(first, plan_mission(board, req))
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(first, plan_mission(board, req))

    def test_reserves_corridors_and_access_regions(self):
        board = snapshot(outline=("0", "0", "14", "12"), keepouts=[("1", "8", "4", "11")])
        req = requirements(board, reserved_regions=[
            {"name": "central-route", "kind": "routing", "bounds": ["5", "0", "8", "12"]},
            {"name": "connector-access", "kind": "access", "bounds": ["10", "8", "14", "12"]},
        ])
        mission = plan_mission(board, req)
        self.assertEqual(mission["status"], "ready")
        self.assert_legal(board, req, mission["targets"])
        self.assertEqual(mission["evidence"]["routing"]["metrics"]["reserved_region_count"], 2)

    def test_exact_boundaries_are_legal_but_positive_overlap_is_not(self):
        board = snapshot([
            component("U1", bounds=("0", "0", "2", "2"), pins=[]),
            component("U2", bounds=("0", "0", "2", "2"), pins=[]),
        ], outline=("0", "0", "4", "2"))
        req = requirements(board, clearance_mm="0", anchors=[
            {"refdes": "U1", "kind": "mechanical-interface", "x": "0", "y": "0", "angle": "0"},
            {"refdes": "U2", "kind": "mechanical-interface", "x": "2", "y": "0", "angle": "0"},
        ])
        self.assertEqual(plan_mission(board, req)["status"], "ready")
        req["anchors"][1]["x"] = "1"
        blocked = plan_mission(board, req)
        self.assertIn("footprint_collision", codes(blocked))
        self.assertEqual(blocked["targets"], [])

    def test_anchor_collision_with_corridor_or_preserved_part_is_explicit(self):
        board = snapshot([component("J1"), component("U1", x="3", y="3", placed=True)])
        req = requirements(board, anchors=[{
            "refdes": "J1", "kind": "mechanical-interface", "x": "3", "y": "3", "angle": "0",
        }])
        self.assertIn("footprint_collision", codes(plan_mission(board, req)))
        req["anchors"][0]["x"] = "9"
        req["reserved_regions"] = [{"name": "route", "kind": "routing", "bounds": ["7", "1", "11", "5"]}]
        self.assertIn("reserved_collision", codes(plan_mission(board, req)))

    def test_existing_anchor_is_a_noop_not_ripup(self):
        board = snapshot([component("J1", x="3", y="3", angle="90", placed=True, fixed=True)])
        req = requirements(board, anchors=[{
            "refdes": "J1", "kind": "mechanical-interface", "x": "3", "y": "3", "angle": "90",
        }])
        mission = plan_mission(board, req)
        self.assertEqual(mission["status"], "placement_complete")
        self.assertIsNone(next_candidate(board, mission))
        req["anchors"][0]["x"] = "4"
        self.assertIn("protected_anchor_conflict", codes(plan_mission(board, req)))

    def test_dnp_inventory_is_explicit_and_never_placed(self):
        board = snapshot([component("U1"), component("DNP1")])
        req = requirements(board, expected_refdes=["U1"], excluded_refdes=["DNP1"])
        mission = plan_mission(board, req)
        self.assertEqual([target["refdes"] for target in mission["targets"]], ["U1"])
        done = fake_apply(board, next_candidate(board, mission), 2)
        self.assertTrue(mission_status(done, mission)["placement"]["complete"])
        done["components"][1].update(placed=True, x="12", y="8")
        self.assertIn("placed_dnp", codes(mission_status(fresh(done, 3), mission)))

    def test_inventory_mismatch_never_hides_missing_or_extra_parts(self):
        board = snapshot([component("U1"), component("U2")])
        for expected in (["U1"], ["U1", "U2", "U3"], ["MISSING1"]):
            with self.subTest(expected=expected):
                mission = plan_mission(board, requirements(board, expected_refdes=expected))
                self.assertEqual(mission["targets"], [])
                self.assertIn("inventory_mismatch", codes(mission))
                status = mission_status(board, mission)
                self.assertFalse(status["placement"]["complete"])
                self.assertEqual(status["placement"]["remaining_refdes"], sorted(expected))
                self.assertEqual(next_candidate(board, mission)["status"], "blocked")

    def test_insufficient_room_does_not_return_a_partial_plan_or_none(self):
        board = snapshot([component("U1"), component("U2")], outline=("0", "0", "4", "4"))
        mission = plan_mission(board, requirements(board))
        self.assertEqual(mission["status"], "blocked")
        self.assertEqual(mission["targets"], [])
        self.assertIn("no_all_component_solution", codes(mission))
        status = mission_status(board, mission)
        self.assertEqual(status["placement"]["remaining_refdes"], ["U1", "U2"])
        self.assertEqual(status["placement"]["unplanned_refdes"], ["U1", "U2"])
        self.assertEqual(next_candidate(board, mission)["status"], "blocked")

    def test_search_backtracks_when_critical_small_part_strands_a_large_part(self):
        board = snapshot([
            component("C1", pins=[]),
            component("L1", bounds=("-2", "-2", "2", "2"), pins=[]),
        ], outline=("0", "0", "6", "4"), keepouts=[("4", "2", "6", "4")])
        req = requirements(board, clearance_mm="0", functional_groups=[
            {"name": "critical-support", "refdes": ["C1"], "critical": True},
        ])
        mission = plan_mission(board, req)
        self.assertEqual(mission["status"], "ready", mission["blockers"])
        self.assertEqual(mission["targets"][0]["refdes"], "C1")
        self.assertGreater(mission["evidence"]["search"]["search_nodes"], 3)
        self.assert_legal(board, req, mission["targets"])

    def test_oversized_footprint_has_no_legal_candidate(self):
        board = snapshot([component("U1", bounds=("-20", "-20", "20", "20"))])
        mission = plan_mission(board, requirements(board))
        self.assertIn("no_legal_candidate", codes(mission))

    def test_fixed_unplaced_and_mirrored_states_are_blockers(self):
        for part, code in (
            (component("U1", fixed=True), "fixed_unplaced"),
            (component("U1", mirrored=True), "mirrored_unsupported"),
            (component("U1", x="3", y="3", mirrored=True, placed=True), "mirrored_unsupported"),
        ):
            with self.subTest(code=code):
                board = snapshot([part])
                self.assertIn(code, codes(plan_mission(board, requirements(board))))

    def test_protected_part_movement_unplacement_or_rotation_blocks(self):
        board = snapshot([component("J1", x="3", y="3", placed=True, fixed=True), component("U1")])
        mission = plan_mission(board, requirements(board))
        for update in ({"x": "4"}, {"angle": "90"}, {"placed": False}):
            with self.subTest(update=update):
                changed = deepcopy(board)
                changed["components"][0].update(update)
                status = mission_status(fresh(changed), mission)
                self.assertIn("protected_part_changed", codes(status))
                self.assertFalse(status["placement"]["complete"])

    def test_new_missing_and_changed_native_identity_is_not_accepted(self):
        board = snapshot()
        mission = plan_mission(board, requirements(board))
        mutations = [
            lambda value: value["components"].append(component("NEW1")),
            lambda value: value["components"].pop(),
            lambda value: value["components"].clear(),
            lambda value: value["components"][0].update(package="changed"),
            lambda value: value["components"][0].update(bounds=["-2", "-1", "2", "1"]),
            lambda value: value["components"][0]["pins"][0].update(net="changed"),
            lambda value: value["components"][0]["pins"][0].update(x="0.1"),
            lambda value: value["components"][0].update(fixed=True),
            lambda value: value.update(outline=["0", "0", "20", "12"]),
            lambda value: value.update(keepin=["0", "0", "15", "12"]),
            lambda value: value["keepouts"].append(["10", "8", "12", "10"]),
            lambda value: value["layers"].append("INNER1"),
            lambda value: value["layers"].reverse(),
            lambda value: value.update(board=r"C:\isolated\different.brd"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                changed = deepcopy(board)
                mutate(changed)
                status = mission_status(fresh(changed), mission)
                self.assertIn("immutable_facts_changed", codes(status))
                self.assertEqual(status["placement"]["verified_placed_count"], 0)
                self.assertEqual(next_candidate(fresh(changed), mission)["status"], "blocked")

    def test_changed_state_cannot_reuse_baseline_snapshot_or_scene(self):
        board = snapshot([component("U1")])
        mission = plan_mission(board, requirements(board))
        changed = fake_apply(board, next_candidate(board, mission), 2)
        changed["snapshot_id"] = board["snapshot_id"]
        self.assertIn("reused_snapshot_id", codes(mission_status(changed, mission)))
        changed["snapshot_id"] = "3" * 32
        changed["scene_digest"] = board["scene_digest"]
        self.assertIn("reused_scene_digest", codes(mission_status(changed, mission)))
        self.assertEqual(mission_status(changed, mission)["placement"]["verified_placed_count"], 0)

    def test_planned_denied_rolled_back_or_wrong_pose_do_not_count(self):
        board = snapshot([component("U1")])
        mission = plan_mission(board, requirements(board))
        candidate = next_candidate(board, mission)
        self.assertEqual(candidate["placement"]["verified_placed_count"], 0)
        self.assertFalse(candidate["placement"]["complete"])
        for revision in (2, 3, 4):
            unchanged = fresh(board, revision)
            status = mission_status(unchanged, mission)
            self.assertEqual(status["placement"]["verified_placed_count"], 0)
            self.assertEqual(next_candidate(unchanged, mission)["refdes"], "U1")
        wrong = fake_apply(board, candidate, 5)
        wrong["components"][0]["x"] = "10"
        status = mission_status(fresh(wrong, 6), mission)
        self.assertIn("unexpected_placed_pose", codes(status))
        self.assertEqual(status["placement"]["verified_placed_count"], 0)
        rollback = fresh(board, 7)
        self.assertEqual(next_candidate(rollback, mission)["refdes"], "U1")

    def test_out_of_order_exact_native_placement_counts_but_is_not_replayed(self):
        board = snapshot()
        mission = plan_mission(board, requirements(board))
        board = fake_apply(board, mission["targets"][-1], 2)
        status = mission_status(board, mission)
        self.assertEqual(status["placement"]["verified_placed_count"], 1)
        self.assertEqual(next_candidate(board, mission)["refdes"], mission["targets"][0]["refdes"])

    def test_budget_evidence_is_screening_not_routing_or_persistence_proof(self):
        board = snapshot([component("U1"), component("U2")])
        req = requirements(board, routing={
            "stackup": {"signal_layers": ["TOP", "BOTTOM"], "evidence": "Operator stackup revision A"},
            "budget": {"max_total_hpwl_mm": "20", "max_net_hpwl_mm": {"SIGNAL": "20"},
                       "evidence": "Operator pre-route length allowance"},
        })
        mission = plan_mission(board, req)
        routing = mission["evidence"]["routing"]
        self.assertEqual(routing["screening"], "within_supplied_proxy_budget")
        self.assertIn("pad_and_drill_geometry", routing["missing_inputs"])
        self.assertIn("routed_connectivity_and_native_drc", routing["missing_inputs"])
        self.assertFalse(routing["feasibility_proven"])
        self.assertEqual(routing["verification"], "unverified")
        self.assertEqual(routing["scope"], "intended_poses")
        self.assertEqual(mission_status(board, mission)["routing"]["screening"], "placement_incomplete")
        self.assertEqual(mission["evidence"]["persistence"], "unverified")
        self.assertEqual(plan_mission(board, requirements(board))["evidence"]["routing"]["screening"],
                         "insufficient_design_evidence")

    def test_incompatible_proxy_budget_blocks_complete_plan(self):
        board = snapshot([
            component("J1", x="2", y="2", placed=True),
            component("J2", x="8", y="2", placed=True),
        ])
        req = requirements(board, routing={"budget": {
            "max_total_hpwl_mm": "1", "evidence": "Explicit operator limit",
        }})
        mission = plan_mission(board, req)
        self.assertEqual(mission["status"], "blocked")
        self.assertIn("total_hpwl_budget", codes(mission_status(board, mission)))

    def test_unknown_nets_and_stackup_layers_are_explicit(self):
        board = snapshot()
        req = requirements(board, critical_nets=["NOT-A-NATIVE-NET"])
        self.assertIn("unknown_nets", codes(plan_mission(board, req)))
        req = requirements(board, routing={"stackup": {
            "signal_layers": ["INNER99"], "evidence": "Operator declaration",
        }})
        self.assertIn("stackup_mismatch", codes(plan_mission(board, req)))

    def test_empty_expected_and_all_dnp_cannot_be_zero_over_zero_complete(self):
        board = snapshot([component("U1")])
        for req in (
            requirements(board, expected_refdes=[]),
            requirements(board, expected_refdes=[], excluded_refdes=["U1"]),
        ):
            with self.assertRaises(MissionError):
                plan_mission(board, req)
        missing = snapshot([])
        mission = plan_mission(missing, requirements(missing, expected_refdes=["U1"]))
        self.assertFalse(mission_status(missing, mission)["placement"]["complete"])
        self.assertEqual(next_candidate(missing, mission)["status"], "blocked")

    def test_invalid_board_types_values_and_geometry_are_rejected(self):
        board = snapshot()
        req = requirements(board)
        mutations = [
            lambda value: value.update(components="not inventory"),
            lambda value: value["components"][0].update(x=1),
            lambda value: value["components"][0].update(x="NaN"),
            lambda value: value["components"][0].update(x="1e2"),
            lambda value: value["components"][0].update(x="1" * 10000),
            lambda value: value["components"][0].update(x="1000000000"),
            lambda value: value["components"][0].update(angle=90),
            lambda value: value["components"][0].update(angle="45"),
            lambda value: value["components"][0].update(placed=1),
            lambda value: value["components"][0].update(bounds=["0", "0", "0", "1"]),
            lambda value: value["components"][0].update(refdes="bad ref"),
            lambda value: value["components"].append(deepcopy(value["components"][0])),
            lambda value: value["components"][0]["pins"].append(deepcopy(value["components"][0]["pins"][0])),
            lambda value: value.update(keepin=["-1", "0", "16", "12"]),
            lambda value: value.update(outline=["0", "0", "1"]),
            lambda value: value.update(board="relative.brd"),
            lambda value: value.update(snapshot_id="bad"),
            lambda value: value.update(scene_digest="3" * 63),
            lambda value: value.update(unknown=True),
            lambda value: value.update(layers=["TOP", "TOP"]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                invalid = deepcopy(board)
                mutate(invalid)
                with self.assertRaises(MissionError):
                    plan_mission(invalid, req)
        for invalid in ([], None, "native"):
            with self.assertRaises(MissionError):
                plan_mission(invalid, req)

    def test_invalid_requirements_are_rejected_without_implicit_defaults(self):
        board = snapshot()
        req = requirements(board)
        mutations = [
            lambda value: value.pop("grid_mm"),
            lambda value: value.pop("clearance_mm"),
            lambda value: value.update(grid_mm="0"),
            lambda value: value.update(grid_mm="1e-3"),
            lambda value: value.update(clearance_mm="-1"),
            lambda value: value.update(clearance_mm=0.1),
            lambda value: value.update(expected_refdes="U1"),
            lambda value: value.update(expected_refdes=["U1", "U1"]),
            lambda value: value.update(excluded_refdes=["U1"]),
            lambda value: value.update(limits={"max_seconds": True}),
            lambda value: value.update(limits={"max_candidates": 1000001}),
            lambda value: value.update(routing={"budget": {"evidence": "No limit"}}),
            lambda value: value.update(routing={"budget": {"evidence": "Limit", "max_total_hpwl_mm": "-1"}}),
            lambda value: value.update(anchors=[{
                "refdes": "U1", "kind": "mechanical-interface", "x": "0.25", "y": "2", "angle": "0",
            }]),
            lambda value: value.update(anchors=[{
                "refdes": "U1", "kind": "inferred-power-supply", "x": "2", "y": "2", "angle": "0",
            }]),
            lambda value: value.update(functional_groups=[
                {"name": "one", "refdes": ["U1"], "critical": False},
                {"name": "two", "refdes": ["U1"], "critical": False},
            ]),
            lambda value: value.update(reserved_regions=[
                {"name": "bad", "kind": "routing", "bounds": ["2", "0", "1", "2"]},
            ]),
            lambda value: value.update(auto_approve=True),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                invalid = deepcopy(req)
                mutate(invalid)
                with self.assertRaises(MissionError):
                    plan_mission(board, invalid)

    def test_huge_inventory_and_search_domains_are_bounded(self):
        board = snapshot([component(f"U{index}") for index in range(257)])
        with self.assertRaises(MissionError):
            plan_mission(board, requirements(board))
        board = snapshot([component("U1")], outline=("0", "0", "999999999", "999999999"))
        mission = plan_mission(board, requirements(board, grid_mm="0.000000001"))
        self.assertIn("search_limit", codes(mission))
        self.assertEqual(mission["targets"], [])
        self.assertEqual(mission["evidence"]["search"]["candidate_evaluations"], 0)
        self.assertEqual(next_candidate(board, mission)["status"], "blocked")
        board = snapshot([component("U1", pins=[
            {"number": str(index), "net": "", "x": "0", "y": "0"} for index in range(8193)
        ])])
        with self.assertRaises(MissionError):
            plan_mission(board, requirements(board))

    def test_many_collisions_have_bounded_diagnoses_and_remain_reconcilable(self):
        board = snapshot([component(f"U{index}", x="3", y="3", placed=True) for index in range(80)])
        mission = plan_mission(board, requirements(board))
        self.assertIn("additional_geometry_violations", codes(mission))
        self.assertLessEqual(len(mission["blockers"]), 513)
        status = mission_status(board, mission)
        self.assertEqual(status["status"], "blocked")
        self.assertFalse(status["placement"]["complete"])

    def test_candidate_node_and_time_limits_fail_closed(self):
        board = snapshot([component("U1")])
        for limits in ({"max_candidates": 1}, {"max_search_nodes": 1}):
            with self.subTest(limits=limits):
                mission = plan_mission(board, requirements(board, limits=limits))
                self.assertIn("search_limit", codes(mission))
                self.assertFalse(mission_status(board, mission)["placement"]["complete"])
        with patch("orcad_placement_agent.missions.time.monotonic", side_effect=[0, 20]):
            mission = plan_mission(board, requirements(board))
        self.assertIn("search_limit", codes(mission))
        self.assertEqual(mission["blockers"][0]["limit"], "max_seconds")

    def test_mission_binds_exact_requirements_and_poses_and_rejects_tampering(self):
        board = snapshot([component("U1")])
        mission = plan_mission(board, requirements(board))
        self.assertEqual(mission["mission_id"], canonical_digest({
            key: value for key, value in mission.items() if key != "mission_id"
        }))
        for mutate in (
            lambda value: value["targets"][0].update(x="10"),
            lambda value: value["requirements"].update(clearance_mm="0"),
            lambda value: value["baseline"]["components"][0].update(package="forged"),
            lambda value: value.update(status="placement_complete"),
        ):
            altered = deepcopy(mission)
            mutate(altered)
            with self.assertRaises(MissionError):
                mission_status(board, altered)

    def test_rehashed_malformed_or_illegal_targets_still_fail_closed(self):
        board = snapshot([component("U1")])
        mission = plan_mission(board, requirements(board))
        for mutate in (
            lambda value: value["targets"][0].update(x="100"),
            lambda value: value["targets"][0].update(x="0.25"),
            lambda value: value["targets"].clear(),
            lambda value: value.update(status="placement_complete"),
            lambda value: value.update(blockers=["not a diagnosis"]),
        ):
            altered = deepcopy(mission)
            mutate(altered)
            altered["mission_id"] = canonical_digest({
                key: value for key, value in altered.items() if key != "mission_id"
            })
            with self.assertRaises(MissionError):
                next_candidate(board, altered)


if __name__ == "__main__":
    unittest.main()

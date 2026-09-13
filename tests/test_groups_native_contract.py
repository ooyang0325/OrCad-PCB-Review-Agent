"""Static native contracts supplement, but do not replace, read-only/live acceptance."""

from pathlib import Path
import unittest

from tests.test_managed_board_contract import _code_only, _procedures


ROOT = Path(__file__).resolve().parents[1]


class GroupNativeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "skill" / "managed_board.il").read_text(encoding="ascii")
        cls.procedures = _procedures(cls.source)

    def test_flat_group_memberships_are_validated_in_both_directions(self):
        guard = self.procedures["opaManagedObjectGuard"]
        self.assertIn("member(group axlDBGetDesign()->groups)", guard)
        self.assertIn("member(object group->groupMembers)", guard)
        self.assertIn("!group->parentGroups", guard)
        groups = self.procedures["opaManagedGroups"]
        self.assertIn("member(net design->nets)", groups)
        self.assertIn("member(group net->parentGroups)", groups)
        self.assertIn("equal(shape->parentGroups list(group))", groups)
        self.assertIn("total <= 4096", groups)
        self.assertIn("!group->groupMembers && !properties", groups)
        self.assertIn("member(group->name axlSubclassRoute())", groups)
        self.assertIn('"@ungrouped:"', groups)
        self.assertIn("!shape->parentGroups", groups)

    def test_rooms_keep_geometry_attached_labels_and_text_block_settings(self):
        labels = self.procedures["opaManagedRoomLabels"]
        for token in ("text->parent == shape", "length(labels) == 1",
                      'axlGetParam(strcat("paramTextBlock:"', "block->charSpace", "block->lineSpace",
                      "text->rotation", "text->isMirrored", "text->justify"):
            self.assertIn(token, labels)
        groups = self.procedures["opaManagedGroups"]
        self.assertIn("geometry = opaManagedGeometry(shape)", groups)
        self.assertIn("label = opaManagedRoomLabels(shape)", groups)
        self.assertIn("member(text axlDBGetAttachedText(shape))", groups)
        figures = self.procedures["opaManagedAllFigures"]
        self.assertIn("copy(design->groups)", figures)
        self.assertIn("copy(axlDBGetAttachedText(shape))", figures)

    def test_all_named_csets_are_read_on_every_layer_without_setting_them(self):
        csets = self.procedures["opaManagedCsets"]
        self.assertIn("foreach(domain '(physical spacing sameNet)", csets)
        self.assertIn('member("DEFAULT" names)', csets)
        self.assertIn("length(names) <= 32", csets)
        self.assertIn("foreach(layer layers", csets)
        for name in ("Physical", "Spacing", "SameNet"):
            self.assertIn(f"axlCNSGet{name}(name layer nil)", csets)
        self.assertIn("opaRequire(values", csets)
        assignments = self.procedures["opaManagedCsetReference"]
        self.assertIn("member(value axlCnsList(domain))", assignments)
        self.assertIn('("CONDUCTOR" "PLANE")', self.procedures["opaManagedStackup"])
        self.assertIn('list("named-csets" opaManagedCsets(layers))', self.procedures["opaManagedConstraints"])
        combined = "\n".join(self.procedures[name] for name in (
            "opaManagedGroups", "opaManagedCsets", "opaManagedCsetReference",
            "opaManagedRoomLabels", "opaManagedRoomAssignments", "opaManagedPolicyRecords",
        ))
        self.assertNotRegex(_code_only(combined),
                            r"\b(?:axlDB(?:Create|Delete|AddProp|DeleteProp)|axlCNSSet|axlSetVariable)\w*\(")

    def test_policy_records_bind_common_and_component_invariants_and_exact_counts(self):
        policy = self.procedures["opaManagedPolicyRecords"]
        self.assertIn('list("common" common)', policy)
        self.assertIn('list("component-invariants"', policy)
        self.assertIn("nth(7 data) nth(10 data) nth(11 data) nth(12 data)", policy)
        self.assertIn('list("policy-model" "grouped-constraints-v1")', policy)
        for record in ("policy-part", "room", "room-assignment", "net-group",
                       "net-group-member", "constraint-set", "policy-net"):
            self.assertIn('"' + record + '"', policy)
        self.assertIn("index <= 64", policy)
        read = self.procedures["opaManagedReadFrame"]
        self.assertLess(read.index("constraints = opaManagedConstraints()"), read.index("opaManagedGroups(design)"))
        for field in ("groups", "rooms", "room-assignments", "routing-keepin"):
            self.assertIn('list("' + field + '"', read)

    def test_room_constraints_are_additional_and_native_drc_cannot_be_disabled(self):
        room = self.procedures["opaManagedRoomCheck"]
        self.assertIn("cadr(room) == car(labels)", room)
        self.assertIn("length(labels) <= 1", room)
        self.assertIn("length(matches) <= 1", room)
        self.assertIn("opaManagedInside(bounds nth(2 car(matches)))", room)
        policy = self.procedures["opaManagedPlacementPolicy"]
        self.assertIn("opaManagedRoomCheck(car(data) bounds rooms assignments)", policy)
        self.assertIn("opaManagedContourContains(bounds outline)", policy)
        writes = self.procedures["opaManagedWritesAllowed"]
        self.assertIn("cadr(assoc(\"room-assignments\" frame->common))", writes)
        self.assertIn("axlCNSDesignModeGet('Package_to_Room_Spacing) == 'on", writes)

    def test_missing_footprints_are_an_explicit_input_blocker_not_permission_to_load(self):
        method = self.procedures["opaManagedRequireFootprints"]
        self.assertIn('definition->type == "PACKAGE"', method)
        self.assertIn("definition->name == component->package", method)
        self.assertIn("nothing was loaded", method)
        self.assertNotRegex(_code_only(self.source), r"\baxlLoadSymbol\(")
        read = self.procedures["opaManagedReadFrame"]
        self.assertLess(read.index("opaManagedRequireFootprints(design)"), read.index("opaManagedPadstacks(design)"))

    def test_diagnostic_scripts_never_mutate_the_design_or_pretend_to_be_snapshots(self):
        for name in ("groups_readonly.il", "room_constraints_readonly.il", "group_policy_readonly.il"):
            source = (ROOT / "tests" / "native" / name).read_text(encoding="ascii")
            self.assertEqual(len(_procedures(source)), 1)
            self.assertIn("opaBoardGuard()", source)
            self.assertNotIn('list("OPA" "1"', source)
            self.assertNotRegex(_code_only(source),
                                r"\baxl(?:DBCreate\w*|DBDelete\w*|DBTransaction\w*|TransformObject|DRCUpdate|SaveDesign|OpenDesign|CNSSet\w*)\(")


if __name__ == "__main__":
    unittest.main()

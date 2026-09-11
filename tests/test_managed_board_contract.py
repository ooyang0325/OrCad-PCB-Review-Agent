"""Static managed-SKILL contracts, not a substitute for native fixture acceptance."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skill" / "managed_board.il"


def _code_only(source: str) -> str:
    """Retain positions while masking SKILL strings and line comments."""
    result = list(source)
    string = comment = escaped = False
    for index, character in enumerate(source):
        if comment:
            if character == "\n":
                comment = False
            else:
                result[index] = " "
        elif string:
            result[index] = "\n" if character == "\n" else " "
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                string = False
        elif character == ";":
            comment = True
            result[index] = " "
        elif character == '"':
            string = True
            result[index] = " "
    if string:
        raise AssertionError("Unterminated SKILL string")
    return "".join(result)


def _procedures(source: str) -> dict[str, str]:
    code = _code_only(source)
    stack: list[tuple[str, int]] = []
    ends: dict[int, int] = {}
    parents: dict[int, int | None] = {}
    pairs = {")": "(", "]": "["}
    for index, character in enumerate(code):
        if character in "([":
            parents[index] = stack[-1][1] if stack else None
            stack.append((character, index))
        elif character in ")]":
            if not stack or stack[-1][0] != pairs[character]:
                raise AssertionError(f"Unmatched delimiter at line {code.count(chr(10), 0, index) + 1}")
            _, start = stack.pop()
            ends[start] = index + 1
    if stack:
        raise AssertionError("Unclosed SKILL delimiters")
    procedures = {}
    covered = list(code)
    for match in re.finditer(r"\bprocedure\((\w+)\(", code):
        start = code.index("(", match.start())
        end = ends[start]
        name = match[1]
        if parents[start] is not None:
            raise AssertionError(f"Nested procedure {name}")
        if name in procedures:
            raise AssertionError(f"Duplicate procedure {name}")
        procedures[name] = source[match.start():end]
        covered[match.start():end] = " " * (end - match.start())
    if "".join(covered).strip():
        raise AssertionError("Unexpected executable top-level SKILL")
    return procedures


class ManagedBoardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="ascii")
        cls.procedures = _procedures(cls.source)

    def reachable(self, name: str) -> str:
        pending = [name]
        visited = set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            pending.extend(
                call for call in re.findall(r"\b(opaManaged\w+)\(", _code_only(self.procedures[name]))
                if call != name and call not in visited
            )
        return "\n".join(self.procedures[name] for name in sorted(visited))

    def test_exports_and_all_managed_references_are_defined(self):
        expected = {
            "opaManagedReadFrame", "opaManagedWritesAllowed", "opaManagedPlacementPolicy",
            "opaManagedOnlyTargetChanged", "opaManagedApplyTransaction",
        }
        self.assertTrue(expected <= self.procedures.keys())
        calls = set(re.findall(r"\b(opaManaged\w+)\(", _code_only(self.source)))
        self.assertEqual(calls, set(self.procedures))

    def test_parent_dispatch_wrappers_are_top_level_and_fixture_default_is_preserved(self):
        parent = (ROOT / "skill" / "placement.il").read_text(encoding="ascii")
        parent = re.sub(r"(?m)^defstruct\([^\n]+\)\s*$", "", parent)
        procedures = _procedures(parent)
        self.assertIn("boundp('opaBoardModel)", procedures["opaManagedMode"])
        for name in ("ReadFrame", "WritesAllowed", "PlacementPolicy", "OnlyTargetChanged", "ApplyTransaction"):
            dispatch = procedures["opa" + name]
            self.assertIn("opaManaged" + name + "(", dispatch)
            self.assertIn("opaFixture" + name + "(", dispatch)
            self.assertIn("opaManagedMode()", dispatch)
        properties = procedures["opaProps"]
        self.assertIn("when(object->prop", properties)
        self.assertIn("values = axlDBGetProperties(object)", properties)
        self.assertIn('opaRequire(values "Attached native properties could not be read.")', properties)

    def test_optional_native_reader_suite_contains_no_board_mutations(self):
        native = (ROOT / "tests" / "native" / "managed_readonly.il").read_text(encoding="ascii")
        procedures = _procedures(native)
        self.assertEqual(set(procedures), {"opaManagedReadOnlyAcceptance"})
        code = _code_only(native)
        self.assertNotRegex(code, r"\baxl(?:DBCreate\w*|DBTransaction\w*|TransformObject|DRCUpdate|SaveDesign|OpenDesign|DBDelete\w*)\(")
        self.assertIn("opaBoardGuard()", code)
        self.assertIn("mod(index 256)", code)
        self.assertIn('opaManagedReadBytes(strcat(opaRoot "\\\\native-byte-fixture.bin") 511)', native)

    def test_no_registration_import_library_loading_or_settings_writes(self):
        code = _code_only(self.source)
        forbidden = (
            "axlCmdRegister", "axlShell", "axlOpenDesign", "axlSaveDesign",
            "axlLoadSymbol", "axlLoadPadstack", "axlRunBatchDBProgram",
            "axlNetlistTextIn", "axlDBCreateComponent", "axlDBAssignNet",
            "axlDBChangeDesignUnits", "axlSetVariable", "axlDBIgnoreFixed",
            "axlRefreshSymbol", "axlCNSDesignModeSet", "axlCNSDesignValueSet",
            "eval", "evalstring", "load", "system", "outfile",
        )
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotRegex(code, rf"\b{re.escape(name)}\s*\(")
        self.assertNotRegex(code, r"\baxlDBControl\([^)]*,")
        self.assertNotRegex(code, r"\baxlDBControl\('[A-Za-z]+\s+[^\s)]")

    def test_read_closure_contains_no_database_mutations(self):
        code = _code_only(self.reachable("opaManagedReadFrame"))
        self.assertNotRegex(code, r"\baxl(?:DBCreate\w*|DBTransaction\w*|TransformObject|DRCUpdate)\(")
        self.assertIn("axlDBRefreshId(nil)", code)
        self.assertIn("unwindProtect(", code)
        self.assertIn("when(saved axlAddSelectObject(saved))", code)

    def test_bounded_full_scene_and_numbered_chunk_contract(self):
        canonical = self.procedures["opaManagedCanonical"]
        self.assertIn('"OPA-BOARD-1;"', canonical)
        self.assertIn("strlen(result) <= 524288", canonical)
        self.assertIn("opaCollectAtoms(rows nil)", canonical)
        self.assertIn("opaEncodeTree(rows table nodes)", canonical)
        chunks = self.procedures["opaManagedSceneRecords"]
        self.assertIn('"OPA-BOARD-1;chunks=%d"', chunks)
        self.assertIn('"scene-part" sprintf(nil "%d" index) part', chunks)
        self.assertIn("count >= 1 && count <= 128", chunks)
        self.assertIn("size = min(8192", chunks)
        budget = self.procedures["opaManagedRecordBudget"]
        self.assertIn("length(records) <= 4088", budget)
        self.assertIn("length(row) <= 16", budget)
        self.assertIn("total <= 1032192", budget)
        read = self.procedures["opaManagedReadFrame"]
        self.assertIn('list("derived-connectivity" cadr(nets))', read)
        self.assertIn('list("drc" design->drcState drcs)', read)
        self.assertIn("opaManagedRecordBudget(records)", read)

    def test_boundary_reader_keeps_native_arcs_and_emits_explicit_complete_contours(self):
        boundary = self.procedures["opaManagedBoundary"]
        self.assertIn("center = opaPoint(segment->xy)", boundary)
        self.assertNotIn("segment->radius", boundary)
        self.assertIn("segment->isClockwise", boundary)
        self.assertIn("!segment->isCircle", boundary)
        self.assertIn("!object->voids", boundary)
        self.assertIn("opaManagedBoundaryPoly(object)", boundary)
        self.assertIn("opaManagedContourFromEdges(edges)", boundary)
        self.assertIn("car(data) opaProps(object)", boundary)
        read = self.procedures["opaManagedReadFrame"]
        self.assertIn('list("boundary-model" "polygon-v1")', read)
        self.assertIn('opaManagedContourRecords("outline"', read)
        self.assertIn('opaManagedContourRecords("keepin"', read)
        self.assertNotIn("opaManagedInside(keepin outline)", read)
        policy = self.procedures["opaManagedPlacementPolicy"]
        self.assertIn("opaManagedContourContains(bounds outline)", policy)
        self.assertIn("opaManagedContourContains(bounds keepin)", policy)
        self.assertIn("opaManagedPolygonContains(bounds outlinePoly)", policy)
        self.assertIn("opaManagedPolygonContains(bounds keepinPoly)", policy)
        self.assertNotIn("opaManagedInside(bounds outline)", policy)

    def test_native_polygon_intersection_never_equates_failure_or_area_to_containment(self):
        check = self.procedures["opaManagedPolygonContains"]
        self.assertIn("axlPathStart(", check)
        self.assertIn("axlPolyOperation(car(rectangles) polygon 'AND)", check)
        self.assertIn('opaRequire(intersection "Native boundary intersection failed;', check)
        self.assertIn("equal(car(rectangles) car(intersection))", check)
        self.assertNotIn("->area", check)
        self.assertNotIn("->bBox", check)

    def test_legacy_outline_must_match_complete_line_and_arc_geometry(self):
        read = self.procedures["opaManagedReadFrame"]
        self.assertIn('opaManagedBoundaryIdentity(caddr(assoc("legacy-outline" common)))', read)
        self.assertIn('opaManagedBoundaryIdentity(caddr(assoc("outline" common)))', read)
        identity = self.procedures["opaManagedBoundaryIdentity"]
        self.assertIn("opaSortedData(list(nth(1 edge) nth(2 edge)))", identity)
        self.assertIn("then nth(4 edge) else !nth(4 edge)", identity)
        self.assertIn('list("arc" endpoints nth(3 edge) clockwise nth(5 edge))', identity)
        self.assertNotIn("nth(3 geometry)", identity)
        self.assertNotIn("nth(6 geometry)", identity)

    def test_arc_sampling_is_bounded_and_does_not_treat_chords_as_exact(self):
        arc = self.procedures["opaManagedArcPoints"]
        self.assertIn("theta = abs(atan2(cross dot))", arc)
        self.assertNotIn("acos(", arc)
        self.assertIn("divisions <= 512", arc)
        self.assertIn("theta / 1.5707963267948966", arc)
        self.assertIn("radius * theta * theta / (8.0 * divisions * divisions) <= 8.0", arc)
        self.assertIn("list(round(x) round(y))", arc)
        contour = self.procedures["opaManagedContourFromEdges"]
        self.assertIn("margin = 12", contour)
        self.assertIn("length(vertices) + length(points) <= 512", contour)
        contains = self.procedures["opaManagedContourContains"]
        self.assertIn("caar(box) - margin", contains)
        self.assertIn("caadr(box) + margin", contains)
        self.assertIn("opaManagedContourCutsBox(", contains)

    def test_native_nonrectangular_tests_are_read_only_and_check_more_than_corners(self):
        for filename in ("nonrectangular_readonly.il", "outline_readonly.il"):
            source = (ROOT / "tests" / "native" / filename).read_text(encoding="ascii")
            procedures = _procedures(source)
            self.assertEqual(len(procedures), 1)
            self.assertIn("opaBoardGuard()", source)
            self.assertNotRegex(_code_only(source),
                                r"\baxl(?:DBCreate\w*|DBTransaction\w*|TransformObject|DRCUpdate|SaveDesign|OpenDesign)\(")
        source = (ROOT / "tests" / "native" / "nonrectangular_readonly.il").read_text(encoding="ascii")
        self.assertIn("notch-between-inside-corners", source)
        self.assertIn("Signed-zero semicircle", source)

    def test_inventory_and_definition_geometry_are_not_fixture_hardcoded(self):
        self.assertNotRegex(self.source, r'OPA_FIXTURE_|"R[123]"|TEST_NET|TEST_RETURN')
        code = self.reachable("opaManagedReadFrame")
        self.assertIn("length(design->components) >= 1", code)
        self.assertIn("length(design->components) <= 256", code)
        self.assertIn("component->package definitions", code)
        self.assertIn("opaManagedFunctions(component)", code)
        self.assertNotIn("length(design->symbols) > 0", code)
        definitions = self.procedures["opaManagedDefinitions"]
        self.assertNotIn("definition->instances", _code_only(definitions))
        self.assertNotIn("component->symbol", definitions)
        self.assertIn("position = opaPoint(pin->xy)", definitions)
        self.assertIn("opaWorldBox(nth(1 stack) position rotation)", definitions)
        read = self.procedures["opaManagedReadFrame"]
        self.assertIn('opaManagedBoxRecord("bounds" nth(11 data) car(data))', read)
        self.assertIn('list("pin" car(data) car(pin) cadr(pin)', read)

    def test_moved_geometry_keeps_origin_relative_properties_and_native_pin_proof(self):
        component = self.procedures["opaManagedComponent"]
        self.assertIn("opaManagedLocalGeometry(item origin angle)", component)
        self.assertIn("opaManagedGeometryPose(item origin angle)", component)
        self.assertIn("equal(opaPoint(pin->xy) opaWorld(nth(2 pinDef) origin angle))", component)
        self.assertIn("mod(angle + nth(3 pinDef) 360)", component)
        self.assertIn("equal(physicalPads expectedPads)", component)
        self.assertIn("axlDBIsReadOnly(pin)", component)
        inverse = self.procedures["opaManagedLocalGeometry"]
        self.assertIn("opaRotate(list(-car(origin) -cadr(origin)) inverse)", inverse)
        self.assertIn("list(nth(5 data))", inverse)

    def test_every_geometry_family_is_closed_and_unaccounted_figures_are_rejected(self):
        geometry = self.procedures["opaManagedGeometry"]
        self.assertIn('member(kind \'("shape" "polygon"))', geometry)
        self.assertIn('kind == "path"', geometry)
        self.assertIn('kind == "line"', geometry)
        for guard in (
            "!object->voids", "!object->shapeBoundary", "!object->shapeIsBoundary",
            "!object->shapeAuto", "!object->hasArcs", "!object->isEtch",
        ):
            self.assertIn(guard, geometry)
        self.assertIn('(t opaRequire(nil "Unsupported text, figure, arc or package shape type."))', geometry)
        self.assertIn("member(object allowed)", self.procedures["opaManagedAllFigures"])
        read = self.procedures["opaManagedReadFrame"]
        self.assertIn("member(shape packageShapes)", read)
        self.assertIn("member(component->symbol design->symbols)", read)

    def test_initial_placement_and_move_have_one_guarded_transaction(self):
        apply = self.procedures["opaManagedApplyTransaction"]
        self.assertLess(apply.index("opaExpected("), apply.index("axlDBTransactionStart("))
        self.assertLess(apply.index("opaManagedWritesAllowed(before)"), apply.index("axlDBTransactionStart("))
        self.assertIn("when(nth(5 old)", apply)
        self.assertIn("if(symbol then", apply)
        self.assertEqual(apply.count("axlDBCreateSymbol("), 1)
        self.assertEqual(apply.count("axlTransformObject("), 1)
        self.assertIn("?allOrNone t", apply)
        self.assertIn("!axlDBIsReadOnly(component)", apply)
        self.assertIn("!axlDBIsFixed(component)", apply)
        self.assertLess(apply.index("opaManagedOnlyTargetChanged("), apply.index("axlDBTransactionCommit("))
        self.assertLess(apply.index("opaManagedPlacementPolicy("), apply.index("axlDBTransactionCommit("))
        self.assertIn("equal(before->scene after->scene)", apply)
        self.assertIn("axlDBTransactionRollback(mark)", apply)
        self.assertIn('list("indeterminate"', apply)
        self.assertIn("opaHalted = t", apply)

    def test_no_automatic_drc_enable_and_no_new_identity_policy(self):
        allowed = self.procedures["opaManagedWritesAllowed"]
        self.assertIn("axlDBControl('drcEnable)", allowed)
        self.assertIn("axlDBGetDesign()->drcState == t", allowed)
        self.assertIn("axlCNSDesignModeGet(rule) == 'on", allowed)
        changed = self.procedures["opaManagedOnlyTargetChanged"]
        self.assertIn("equal(before->common after->common)", changed)
        self.assertIn("length(before->components) == length(after->components)", changed)
        self.assertIn("equal(opaManagedStaticComponent(old) opaManagedStaticComponent(current))", changed)
        self.assertIn("equal(previousNet net)", changed)
        self.assertIn("unless(member(car(net) touched)", changed)
        self.assertIn("member(identity before->drcs)", changed)
        read = self.procedures["opaManagedReadFrame"]
        for guard in (
            "!design->region", "!design->module", "!design->zone",
            "!design->ecsets", "!axlDBGetLonelyBranches()",
        ):
            self.assertIn(guard, read)
        self.assertIn("!axlCnsClassTableFind('netclass)", self.source)

    def test_attachments_preserve_expanded_binary_data_without_changing_database(self):
        read = self.procedures["opaManagedReadBytes"]
        self.assertIn('axlDMOpenFile("TEMP" path "rb")', read)
        self.assertIn("getc(port)", read)
        self.assertIn("charToInt(value)", read)
        self.assertIn('sprintf(nil "%02x" value)', read)
        self.assertIn("count < maximum", read)
        self.assertIn("axlDMClose(port)", read)
        attachment = self.procedures["opaManagedAttachments"]
        self.assertIn("axlGetAttachment(name 'file)", attachment)
        self.assertNotIn("axlGetAttachment(name 'string)", attachment)
        self.assertIn("metadata->size <= 65536", attachment)
        self.assertIn("131072 - expanded", attachment)
        self.assertIn("deleteFile(path)", attachment)
        self.assertIn('list("attachments" opaManagedAttachments())', self.procedures["opaManagedReadFrame"])

    def test_native_default_flags_are_modeled_not_confused_with_fixed_topology(self):
        stacks = self.procedures["opaManagedPadstacks"]
        self.assertIn("member(stack->padSuppresion '(nil t))", stacks)
        self.assertIn("stack->padSuppresion opaProps(stack)", stacks)
        component = self.procedures["opaManagedComponent"]
        self.assertIn("fixed = if(fixed || axlDBIsFixed(symbol)", component)
        self.assertNotIn("fixed = if(fixed || axlDBIsFixed(pin)", component)
        nets = self.procedures["opaManagedNetData"]
        self.assertIn("!rat->userDefined", nets)
        self.assertIn("rat->pwrAndGnd rat->ratsPlaced", nets)
        stackup = self.procedures["opaManagedStackup"]
        self.assertIn('!entry->layerType && entry->layerFunction == "SURFACE" && !entry->conductor', stackup)

    def test_logical_function_mapping_checks_both_forward_and_reverse_ownership(self):
        functions = self.procedures["opaManagedFunctions"]
        for check in (
            "function->parent == component",
            "member(localPin component->pins)",
            "member(pin localPin->functionPins)",
            "expected->parent->number == localPin->number",
            "expected->swapCode == pin->swapCode",
            "expected->use == pin->use",
            "member(functionPin seen) && functionPin->pin == pin",
        ):
            self.assertIn(check, functions)
        self.assertIn('list("functions" opaManagedFunctions(component))', self.procedures["opaManagedComponent"])

    def test_complete_stackup_includes_nonconductors_and_unrounded_material_values(self):
        stackup = self.procedures["opaManagedStackup"]
        self.assertIn("axlXSectionGet(nil 'all)", stackup)
        self.assertIn("axlXSectionGet(nil 'count)", stackup)
        self.assertIn("entry->position", stackup)
        self.assertIn("entry->thickness entry->tolMinus entry->tolPlus", stackup)
        self.assertIn("entry->dielectricConst", stackup)
        self.assertIn("entry->lossTangent", stackup)
        self.assertIn("opaProps(entry)", stackup)
        self.assertNotIn("opaDbu(", stackup)
        self.assertIn("opaManagedStackup(layers)", self.procedures["opaManagedConstraints"])


if __name__ == "__main__":
    unittest.main()

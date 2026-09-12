"""Static setup-SKILL contracts; no native execution or rollback acceptance."""

from pathlib import Path
import re
import unittest

from tests.test_managed_board_contract import _code_only, _procedures


ROOT = Path(__file__).resolve().parents[1]


class LibraryNativeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "skill" / "library_setup.il").read_text(encoding="ascii")
        cls.procedures = _procedures(cls.source)

    def closure(self, name):
        pending, visited = [name], set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            pending.extend(
                call for call in re.findall(r"\b(opaLibrary\w+)\(", _code_only(self.procedures[name]))
                if call in self.procedures and call not in visited
            )
        return "\n".join(self.procedures[name] for name in sorted(visited))

    def test_exports_and_helper_closure_are_complete_and_top_level(self):
        self.assertTrue({
            "opaLibraryPadstacks", "opaLibraryDefinitions",
            "opaLibraryComponent", "opaLoadLibraries",
        } <= self.procedures.keys())
        calls = set(re.findall(r"\b(opaLibrary\w+)\(", _code_only(self.source)))
        self.assertEqual(calls, set(self.procedures) - {"opaLoadLibraries"})

    def test_only_approved_load_and_temporary_paths_can_mutate(self):
        code = _code_only(self.source)
        forbidden = (
            r"axlDB(?:Create|Delete|Assign|Transaction|Change|AddProp)\w*",
            r"axl(?:DRCUpdate|SaveDesign|OpenDesign|LoadPadstack|RefreshSymbol)",
            r"axl(?:CmdRegister|Shell|RunBatchDBProgram|NetlistTextIn)",
            r"axl(?:SetVariableFile|UnsetVariableFile|PadstackEdit|TransformObject)",
            r"(?:eval|evalstring|load|system|outfile|deleteFile|renameFile)",
        )
        for pattern in forbidden:
            self.assertNotRegex(code, rf"\b(?:{pattern})\s*\(")
        self.assertEqual(len(re.findall(r"\baxlLoadSymbol\(", code)), 1)
        self.assertIn('axlLoadSymbol("PACKAGE" lowerCase(name))', self.procedures["opaLoadLibraries"])
        self.assertNotRegex(code, r"\baxlReadOnlyVariable\([^)]*[\s,](?:t|nil)\)")

    def test_read_collectors_never_load_or_change_paths(self):
        for name in ("opaLibraryPadstacks", "opaLibraryDefinitions", "opaLibraryComponent"):
            with self.subTest(name=name):
                code = _code_only(self.closure(name))
                self.assertNotRegex(code, r"\baxl(?:Load\w*|SetVariable|UnsetVariable|DBCreate\w*)\(")

    def test_signatures_capture_all_readable_attributes_and_reject_unknown_handles(self):
        method = self.procedures["opaLibraryObject"]
        self.assertIn("attributes = object->??", method)
        self.assertIn("attributes = cddr(attributes)", method)
        self.assertIn("!assoc(name rows)", method)
        self.assertIn("opaLibraryValue(value depth + 1 budget)", method)
        self.assertIn("!member(object ancestors)", method)
        self.assertIn("axlDBGetProperties(object)", method)
        self.assertIn('list("padstack" opaLibraryName(value->name))', method)
        self.assertIn("!value || value == owner", method)
        self.assertIn('"drillSizeWidth" "drillSizeHeight" "holeType" "startEnd" "isThrough"', method)
        self.assertIn('foreach(name required', method)
        self.assertIn('opaRequire(assoc(name rows)', method)
        self.assertIn('member(kind \'("padstack" "pin")) && key == \'pads', method)
        self.assertIn("then object->definition else object", method)
        values = self.procedures["opaLibraryValue"]
        self.assertIn("!axlIsDBIDType(value)", values)
        self.assertIn("Unmodeled native library structure or geometry.", values)
        self.assertNotIn("sprintf", values)
        budget = self.procedures["opaLibraryBudget"]
        self.assertIn("depth <= 24", budget)
        self.assertIn('budget["nodes"] <= 131072', budget)

    def test_through_slots_and_flash_are_not_filtered_as_placement_shapes(self):
        code = _code_only(self.closure("opaLibraryPadstacks") + self.closure("opaLibraryDefinitions"))
        self.assertNotRegex(code, r"(?:isThrough|drillDiameter|holeType|figureName)\s*==")
        self.assertNotIn("opaManagedGeometry(", code)
        self.assertNotIn("opaManagedPad(", code)
        self.assertIn('"FLASH" "SHAPE" "MECHANICAL" "FORMAT"', self.procedures["opaLibraryDefinitions"])
        self.assertIn("!definition->instances", self.procedures["opaLibraryDefinitions"])

    def test_pad_path_signatures_preserve_arcs_widths_and_order_without_approximation(self):
        path = self.procedures["opaLibraryPath"]
        for name in ("axlPathGetWidth", "axlPathGetPathSegs", "axlPathSegGetWidth",
                     "axlPathSegGetEndPoint", "axlPathSegGetArcCenter", "axlPathSegGetArcClockwise"):
            self.assertIn(name + "(", path)
        self.assertIn("reverse(rows)", path)
        self.assertNotIn("opaSortedData(rows)", path)
        self.assertNotIn("opaDbu(", path)
        self.assertNotIn("axlPolyFromDB(", self.source)
        self.assertIn("opaLibraryPlainAttributes(block", self.procedures["opaLibraryObject"])
        self.assertIn('axlGetParam(strcat("paramTextBlock:" value))', self.procedures["opaLibraryObject"])
        self.assertIn("stringp(value) && strlen(value)", self.procedures["opaLibraryObject"])

    def test_library_attached_text_is_owned_bounded_complete_and_not_a_placement_guard_change(self):
        method = self.procedures["opaLibraryObject"]
        self.assertIn('!object->parentGroups "Grouped library geometry is unsupported."', method)
        self.assertNotIn("opaManagedObjectGuard(", method)
        self.assertIn('unless(kind == "pad"', method)
        self.assertIn("attached = axlDBGetAttachedText(object)", method)
        self.assertIn("listp(attached) && length(attached) <= 256", method)
        self.assertIn('text->objType == "text" && text->parent == object', method)
        self.assertIn("!member(text seen)", method)
        self.assertIn("when(key == 'children nativeChildren = value)", method)
        self.assertIn("if(member(text nativeChildren) then t else nil)", method)
        self.assertIn("opaLibraryObject(text object ancestors depth + 1 budget)", method)
        self.assertIn('list("attached-text" opaSortedData(textRows))', method)
        self.assertIn("when(attached", method)
        self.assertNotIn("procedure(opaManagedObjectGuard", self.source)

    def test_logical_component_has_exact_fourteen_slot_shape_without_coordinates(self):
        component = self.procedures["opaLibraryComponent"]
        self.assertIn(
            "list(component->name '(0 0) 0 nil fixed nil nil opaSortedData(intrinsic)\n"
            "            nil nil component->package nil opaSortedData(pins) nil)", component)
        self.assertIn("list(pin->number netName nil)", component)
        self.assertIn("!component->symbol", component)
        self.assertIn("(!pin->parent || pin->parent == component)", component)
        self.assertIn("!pin->definition && !pin->pads && !pin->name", component)
        self.assertIn('list("logical-parent" if(pin->parent then component->name else nil))', component)
        self.assertIn("opaManagedCompdef(component->compdef)", component)
        self.assertIn("opaManagedFunctions(component)", component)
        self.assertNotRegex(component, r"pin->(?:xy|relxy|rotation)|opaPoint\(")

    def test_native_unnamed_single_pin_nets_keep_complete_data_and_stable_links(self):
        net = self.procedures["opaLibraryLogicalNet"]
        self.assertIn("name = opaField(net->name)", net)
        self.assertIn("equal(net->branches list(branch))", net)
        self.assertIn("equal(branch->children list(pin))", net)
        self.assertIn("!member(net axlDBGetDesign()->nets)", net)
        self.assertIn("net->xnet == net", net)
        self.assertIn('list(name list("anonymous-net"', net)
        attributes = self.procedures["opaLibraryIsolatedNetObject"]
        self.assertIn("attributes = object->??", attributes)
        self.assertIn("opaLibraryValue(value 0 budget)", attributes)
        self.assertIn('list("logical-pin" pin->component->name pin->number)', attributes)
        self.assertIn('data = "isolated-net"', attributes)
        component = self.procedures["opaLibraryComponent"]
        self.assertIn("netData = opaLibraryLogicalNet(pin)", component)
        self.assertIn("cadr(netData)) intrinsic)", component)

    def test_plan_parser_is_rooted_bounded_complete_and_snapshot_bound(self):
        plan = self.procedures["opaLibraryPlan"]
        for token in (
            'strcat(opaRoot "\\\\" filename)', 'strlen(filename) == 44',
            "opaID(substring(filename 9 32))", "total <= 65536", "strlen(line) <= 1024",
            "length(rows) < 258", 'substring(line strlen(line) 1) == "\\n"',
            'list("OPA_LIBRARIES" "1" opaNonce cacheid nth(1 params))',
            'equal(car(last(rows)) list("end" cacheid))',
            "equal(buildString(row \",\") line)", 'car(row) == "package"',
            "!member(folded seen)", "length(names) <= 256", "names = cons(root names)",
        ):
            self.assertIn(token, plan)
        self.assertIn('infile(strcat(opaRoot', plan)
        self.assertEqual(plan.count("infile("), 1)
        self.assertIn("unwindProtect(", plan)
        self.assertIn("close(port)", plan)
        self.assertIn('".psm" ".pad" ".fsm" ".ssm"', plan)

    def test_package_root_rules_allow_internal_periods_but_not_extensions_or_final_dot(self):
        name = self.procedures["opaLibraryName"]
        self.assertIn("strlen(value) >= 1 && strlen(value) <= 128", name)
        self.assertIn('rexMatchp("^[A-Za-z0-9]" value)', name)
        self.assertIn('!rexMatchp("[^A-Za-z0-9_.+-]" value)', name)
        self.assertIn('substring(value strlen(value) 1) != "."', name)
        plan = self.procedures["opaLibraryPlan"]
        self.assertIn('foreach(extension \'(".psm" ".pad" ".fsm" ".ssm" ".bsm" ".osm" ".dra")', plan)
        self.assertIn("folded = lowerCase(root)", plan)
        self.assertIn("!member(folded seen)", plan)

    def test_load_checks_fresh_missing_requirements_and_exact_cache_resolution(self):
        load = self.procedures["opaLoadLibraries"]
        for token in ("before = opaManagedReadFrame(t)", "opaExpected(nth(1 params) before)",
                      "!opaLibraryPresent(name definitions)", "lowerCase(nth(10 component)) == lowerCase(name)",
                      "opaDispatchActive && !opaHalted", "axlOKToProceed()"):
            self.assertIn(token, load)
        self.assertLess(load.index("opaExpected("), load.index('axlSetVariable("psmpath"'))
        self.assertLess(load.index("opaInvalidate(nil)"), load.index("opaMutationBegan = t"))
        self.assertLess(load.index("opaMutationBegan = t"), load.index("axlSetVariable("))
        resolve = self.procedures["opaLibraryCacheFile"]
        self.assertIn('axlDMFindFile("ALLEGRO_PACKAGE_DB" name "r")', resolve)
        self.assertIn('strcat(cache "\\\\" name ".psm")', resolve)
        self.assertIn('parseString(lowerCase(resolved) "\\\\/")', resolve)
        self.assertIn("isFile(expected)", resolve)

    def test_exclusive_paths_are_restored_independently_even_after_failure(self):
        load = self.procedures["opaLoadLibraries"]
        for path in ("psmpath", "padpath"):
            self.assertIn(f'axlSetVariable("{path}" list(cache))', load)
            self.assertIn(f'opaLibraryExclusivePath("{path}" cache)', load)
            self.assertIn(f"errset(opaLibraryRestorePath({path}) t)", load)
        self.assertIn("!nth(3 psmpath) && !nth(3 padpath)", load)
        self.assertIn("unwindProtect(", load)
        restore = self.procedures["opaLibraryRestorePath"]
        self.assertIn("axlUnsetVariable(car(state))", restore)
        self.assertIn("axlSetVariable(car(state) nth(2 state))", restore)
        self.assertIn("equal(opaLibraryPathState(car(state)) state)", restore)
        self.assertLess(load.index("restoredPad = errset"), load.index("after = opaManagedReadFrame(t)"))
        exclusive = self.procedures["opaLibraryExclusivePath"]
        self.assertIn("equal(value list(cache)) || equal(value cache)", exclusive)
        dependencies = self.procedures["opaLibraryDependencyPaths"]
        self.assertIn("axlDMLibraryFileNames(kind)", dependencies)
        self.assertIn("equal(reverse(cdr(reverse(parts))) expected)", dependencies)
        for kind in ("PACKAGE", "PADSTACK", "FLASH", "SHAPE"):
            self.assertIn(f'"ALLEGRO_{kind}_DB"', dependencies)
        self.assertLess(load.index("opaLibraryDependencyPaths(cache)"), load.index("axlLoadSymbol("))
        each_load = load[load.index("unless(failed"):load.index("returned = axlLoadSymbol(")]
        self.assertIn("opaLibraryDependencyPaths(cache)", each_load)
        self.assertIn("opaLibraryCacheFile(cache lowerCase(name))", each_load)

    def test_readback_protects_existing_libraries_logical_data_and_property_schema(self):
        protected = self.procedures["opaLibraryProtected"]
        self.assertIn('exceptions = \'("padstacks" "definitions" "property-dictionary")', protected)
        self.assertIn("equal(before->components after->components)", protected)
        self.assertIn("equal(before->drcs after->drcs)", protected)
        self.assertIn("opaLibrarySubset(", protected)
        self.assertIn('member(cadr(row) \'("FLASH" "SHAPE"))', protected)
        self.assertIn("lowerCase(name) == lowerCase(car(row))", protected)
        self.assertIn("equal(row assoc(car(row) current))", self.procedures["opaLibrarySubset"])

    def test_partial_and_indeterminate_do_not_claim_rollback_or_replay(self):
        load = self.procedures["opaLoadLibraries"]
        self.assertIn("!readback || (!result && attempted)", load)
        self.assertIn("opaHalted = t", load)
        self.assertIn('list("indeterminate"', load)
        self.assertIn('list("library_partial"', load)
        self.assertIn('list("libraries_loaded"', load)
        self.assertIn('list("library-loaded" name)', load)
        self.assertIn('list("library-missing" name)', load)
        self.assertIn("unless(failed", load)
        self.assertIn("else failed = t", load)
        self.assertIn("!loaded && equal(before->scene after->scene)", load)
        self.assertNotIn('"rolled_back"', self.source)
        self.assertNotIn("opaCache(", load)

    def test_preload_scene_mismatch_is_caught_before_terminal_halt_classification(self):
        load = self.procedures["opaLoadLibraries"]
        check = load.index("when(!result && !attempted")
        self.assertLess(load.index("readback = errset("), check)
        self.assertLess(check, load.index("!readback || (!result && attempted)"))
        rejection = load[load.index("(!result\n"):]
        self.assertNotIn("opaRequire(", rejection)
        self.assertIn("opaHalted = t", load)

    def test_indeterminate_receipts_keep_bounded_specific_readback_and_restoration_errors(self):
        error = self.procedures["opaLibraryErrorText"]
        self.assertIn("stringp(value) && strlen(value) > 0", error)
        self.assertIn("limit = min(strlen(value) 1024)", error)
        self.assertIn('rexMatchp("^[ -~]$" character)', error)
        self.assertIn('else "?"', error)
        self.assertIn('when(strlen(value) > limit text = strcat(text "..."))', error)
        load = self.procedures["opaLoadLibraries"]
        self.assertLess(load.index("message = opaError"), load.index("restoredPsm = errset"))
        self.assertIn('restoreError = strcat("psmpath: " opaLibraryErrorText(opaError))', load)
        self.assertIn('restoreError = strcat("padpath: " opaLibraryErrorText(opaError))', load)
        self.assertIn("if(restoreError then restoreError", load)
        self.assertIn("opaLibraryErrorText(if(!readback then opaError else message))", load)
        self.assertIn('"Native library setup readback did not complete."', load)
        self.assertIn('list("rejected" opaLibraryErrorText(message) after->records)', load)
        self.assertLess(load.index("opaHalted = t"), load.index("Cause: "))


if __name__ == "__main__":
    unittest.main()

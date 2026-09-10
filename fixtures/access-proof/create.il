; Original, fixed synthetic M0 recipe. Not a board-edit request interface.
procedure(opaFixtureRequire(value message)
    unless(value
        error("OPA FIXTURE: %s\n" message)
    )
    value
)

procedure(opaFixturePath(name)
    let((root leaf)
        opaFixtureRequire(boundp('opaFixtureDirectory)
            "load the trusted fixture bootstrap first")
        root = strcat(getShellEnvVar("LOCALAPPDATA")
                      "\\OrCadPlacementAgent\\sessions\\")
        leaf = car(last(parseString(opaFixtureDirectory "\\/")))
        opaFixtureRequire(
            equal(opaFixtureDirectory strcat(root leaf)) &&
            rexMatchp("^fixture-[A-Za-z0-9_-]+$" leaf) &&
            isDir(opaFixtureDirectory)
            "target must be one fresh ASCII fixture-* directory under the local session root")
        strcat(opaFixtureDirectory "\\" name)
    )
)

procedure(opaFixtureEmpty()
    let((design objects enabled buttons)
        axlDBRefreshId(nil)
        design = opaFixtureRequire(axlDBGetDesign() "no board is open")
        ; Root readOnly and saveEnable do not describe a fresh editor's access mode.
        opaFixtureRequire(equal(axlDesignType(t) "BOARD")
            "only a PCB board database is accepted")
        opaFixtureRequire(
            !design->components && !design->symbols && !design->nets &&
            !design->symdefs && !design->compdefs && !design->padstacks &&
            !design->pins && !design->text && !design->groups &&
            !design->designOutline && !design->keepinPlace &&
            !design->keepinRoute && !axlDBGetShapes(nil)
            "refusing a nonempty board")
        enabled = axlGetFindFilter(nil)
        buttons = axlGetFindFilter(t)
        unwindProtect(
            progn(
                axlClearSelSet()
                axlSetFindFilter(?enabled '("all" "invisible")
                                 ?onButtons '("all"))
                axlAddSelectAll()
                objects = axlGetSelSet()
            )
            progn(
                axlClearSelSet()
                axlSetFindFilter(?enabled enabled ?onButtons buttons)
            )
        )
        ; A new board exposes its immutable origin cross through Select All.
        objects = setof(item objects
            !(equal(item->objType "figure") &&
              equal(item->layer "DRAWING FORMAT/DRAWING_ORIGIN") &&
              item->readOnly))
        opaFixtureRequire(!objects "refusing existing board figures")
        opaFixtureRequire(
            equal(parseString(axlGetDrawingName() "\\/")
                  parseString(opaFixturePath("unnamed.brd") "\\/")) &&
            !isFile(opaFixturePath("unnamed.brd"))
            "only a new unnamed board in the fixture directory is accepted")
        t
    )
)

procedure(opaFixtureRectangle(box fill layer parent)
    car(opaFixtureRequire(
        axlDBCreateRectangle(box fill layer nil parent)
        strcat("rectangle creation failed on " layer)))
)

procedure(opaFixtureCheckBox(object box)
    let((actual)
        opaFixtureRequire(object "required rectangular geometry is missing")
        opaFixtureRequire(object->isRect && object->nSegs == 4
            "required geometry is not a native four-edge rectangle")
        actual = object->bBox
        opaFixtureRequire(
            abs(xCoord(car(actual)) - xCoord(car(box))) < 0.00001 &&
            abs(yCoord(car(actual)) - yCoord(car(box))) < 0.00001 &&
            abs(xCoord(cadr(actual)) - xCoord(cadr(box))) < 0.00001 &&
            abs(yCoord(cadr(actual)) - yCoord(cadr(box))) < 0.00001
            "explicit rectangular geometry differs from recipe")
        t
    )
)

procedure(opaFixtureVerify()
    let((design component symbol pin expected position child count
         shapes shape net branch object rule)
        ; Construction changes cached root, component, symbol and pin attributes.
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        opaFixtureRequire(length(design->components) == 3
            "expected exactly three logical components")
        opaFixtureRequire(length(design->symbols) == 3
            "expected exactly three physical symbols")
        opaFixtureRequire(length(design->nets) == 2 "expected exactly two nets")
        opaFixtureRequire(equal(car(axlDBGetDesignUnits()) "millimeters")
            "database is not in millimeters")
        opaFixtureRequire(design->designOutline && design->keepinPlace
            "native design outline or package keepin is missing")
        opaFixtureCheckBox(design->designOutline list(0:0 40:30))
        opaFixtureCheckBox(design->keepinPlace list(1:1 39:29))
        shapes = axlDBGetShapes("PACKAGE KEEPOUT/TOP")
        opaFixtureRequire(length(shapes) == 1 "expected one top package keepout")
        opaFixtureCheckBox(car(shapes) list(24:18 30:24))
        foreach(shape axlDBGetShapes(nil)
            opaFixtureRequire(!rexMatchp("^ETCH/" shape->layer)
                "unexpected routed copper shape")
        )
        foreach(net design->nets
            foreach(branch net->branches
                foreach(object branch->children
                    opaFixtureRequire(equal(object->objType "pin")
                        "unexpected trace, via, or other routed object")
                )
            )
        )
        opaFixtureRequire(axlDBControl('drcEnable) "native DRC is disabled")
        foreach(rule '(Package_to_Package_Spacing
                       Package_to_Place_Keepin_Spacing
                       Package_to_Place_Keepout_Spacing)
            opaFixtureRequire(equal(axlCNSDesignModeGet(rule) 'on)
                "required native placement check is not enabled")
        )
        foreach(component design->components
            expected = assoc(component->name
                '(("R1" 10.0 10.0) ("R2" 20.0 10.0) ("R3" 30.0 10.0)))
            opaFixtureRequire(expected "unexpected component identifier")
            symbol = opaFixtureRequire(component->symbol "component is unplaced")
            opaFixtureRequire(!axlDBIsReadOnly(symbol)
                "native physical symbol is read-only")
            opaFixtureRequire(!symbol->etchChildren "unexpected package copper")
            position = symbol->xy
            opaFixtureRequire(
                abs(xCoord(position) - cadr(expected)) < 0.00001 &&
                abs(yCoord(position) - caddr(expected)) < 0.00001 &&
                !symbol->isMirrored && abs(symbol->rotation) < 0.00001
                "component origin, side, or rotation differs from the recipe")
            opaFixtureRequire(length(component->pins) == 2 "expected two pins")
            foreach(pin component->pins
                opaFixtureRequire(pin->definition && pin->xy
                    "pin is not physically instantiated")
                opaFixtureRequire(
                    (equal(pin->number "1") && equal(pin->net->name "TEST_NET")) ||
                    (equal(pin->number "2") && equal(pin->net->name "TEST_RETURN"))
                    "pin connectivity differs from recipe")
            )
            opaFixtureRequire(
                if(equal(component->name "R3")
                    then axlDBIsFixed(symbol)
                    else !axlDBIsFixed(symbol))
                "native fixed status differs from recipe")
            count = 0
            foreach(child symbol->children
                when(equal(child->layer "PACKAGE GEOMETRY/PLACE_BOUND_TOP")
                    opaFixtureCheckBox(child
                        list(list(cadr(expected) - 2.0 9.0)
                             list(cadr(expected) + 2.0 11.0)))
                    count = count + 1
                )
            )
            opaFixtureRequire(count == 1 "expected one explicit top place bound")
        )
        t
    )
)

procedure(opaFixtureReceipt()
    let((output design component symbol pin child shape rule drc)
        opaFixtureVerify()
        opaFixtureRequire(
            equal(parseString(axlGetDrawingName() "\\/")
                  parseString(opaFixturePath("working.brd") "\\/"))
            "receipt requires the reopened working board")
        opaFixtureRequire(!isFile(opaFixturePath("fixture-receipt.txt"))
            "receipt already exists")
        output = opaFixtureRequire(outfile(opaFixturePath("fixture-receipt.txt"))
            "cannot create receipt")
        unwindProtect(
            progn(
                design = axlDBGetDesign()
                fprintf(output "fixture_schema 1\n")
                fprintf(output "drawing %L\n" axlGetDrawingName())
                fprintf(output "editor_version %L\n" axlVersion('fullVersion))
                fprintf(output "product %L\n" axlVersion('formalName))
                fprintf(output "units %L\n" axlDBGetDesignUnits())
                fprintf(output "statistics %L\n" axlDBGetDesignStats())
                fprintf(output "design_attributes %L\n" design->?)
                foreach(component design->components
                    symbol = component->symbol
                    fprintf(output "component %L package %L xy %L rotation %L mirrored %L fixed %L\n"
                        component->name component->package symbol->xy
                        symbol->rotation symbol->isMirrored
                        if(axlDBIsFixed(symbol) then t else nil))
                    fprintf(output "component_attributes %L\n" component->?)
                    fprintf(output "symbol_attributes %L\n" symbol->?)
                    fprintf(output "symbol_read_only %L\n" axlDBIsReadOnly(symbol))
                    foreach(pin component->pins
                        fprintf(output "pin %L %L net %L xy %L padstack %L\n"
                            component->name pin->number pin->net->name pin->xy pin->name)
                    )
                    foreach(child symbol->children
                        fprintf(output "symbol_child %L type %L layer %L bbox %L\n"
                            component->name child->objType child->layer child->bBox)
                    )
                )
                foreach(shape axlDBGetShapes(nil)
                    fprintf(output "shape type %L layer %L bbox %L parent %L\n"
                        shape->objType shape->layer shape->bBox shape->parent)
                )
                fprintf(output "drc_enabled %L\n" axlDBControl('drcEnable))
                fprintf(output "drc_state %L\n" design->drcState)
                foreach(rule axlCNSDesignModeGet('all)
                    fprintf(output "design_rule %L\n" rule)
                )
                fprintf(output "baseline_drc_count %d\n" length(design->drcs))
                foreach(drc design->drcs
                    fprintf(output "drc name %L type %L xy %L actual %L expected %L\n"
                        drc->name drc->type drc->xy drc->actual drc->expected)
                )
                fprintf(output "fixture_verified t\n")
                fprintf(output "routed_copper_traces_vias nil\n")
                fprintf(output "move_cases_executed nil\n")
            )
            close(output)
        )
        axlMsgPut("OPA FIXTURE: saved working-copy geometry verified; receipt written.")
        t
    )
)

procedure(opaFixtureCreate()
    let((source working receipt device mark committed pad definition bounds
         entry component symbol pin rule oldDevpath)
        source = opaFixturePath("source.brd")
        working = opaFixturePath("working.brd")
        receipt = opaFixturePath("fixture-receipt.txt")
        device = opaFixturePath("opa_fixture_device.txt")
        foreach(entry list(source working receipt)
            opaFixtureRequire(!isFile(entry) strcat("destination already exists: " entry))
        )
        opaFixtureRequire(isFile(device) "original device declaration is missing")
        opaFixtureEmpty()
        opaFixtureRequire(axlDBChangeDesignUnits("millimeters" 4)
            "cannot set millimeters with four decimal places")
        oldDevpath = axlGetVariable("devpath")
        axlSetVariable("devpath" list(opaFixtureDirectory))
        unwindProtect(
            progn(
                mark = opaFixtureRequire(axlDBTransactionStart()
                    "cannot start fixture transaction")
                opaFixtureRectangle(list(0:0 40:30) nil
                    "BOARD GEOMETRY/DESIGN_OUTLINE" nil)
                opaFixtureRectangle(list(0:0 40:30) nil
                    "BOARD GEOMETRY/OUTLINE" nil)
                opaFixtureRectangle(list(1:1 39:29) nil "PACKAGE KEEPIN/ALL" nil)
                opaFixtureRectangle(list(24:18 30:24) t "PACKAGE KEEPOUT/TOP" nil)
                pad = opaFixtureRequire(axlDBCreatePadStack("OPA_FIXTURE_SMD" nil
                    list(make_axlPadStackPad(?layer "TOP" ?type 'REGULAR
                        ?figure 'RECTANGLE ?figureSize 0.8:1.0)))
                    "cannot create original embedded SMT padstack")
                definition = opaFixtureRequire(axlDBCreateSymDefSkeleton(
                    '("OPA_FIXTURE_TWO_PIN" "PACKAGE") list(-2:-1 2:1)
                    list(
                        make_axlPinData(?number "1" ?padstack "OPA_FIXTURE_SMD"
                            ?origin -1.2:0 ?rotation 0.0)
                        make_axlPinData(?number "2" ?padstack "OPA_FIXTURE_SMD"
                            ?origin 1.2:0 ?rotation 0.0)))
                    "cannot create original embedded two-pin definition")
                bounds = opaFixtureRectangle(list(-2:-1 2:1) t
                    "PACKAGE GEOMETRY/PLACE_BOUND_TOP" definition)
                opaFixtureRequire(axlDBAddProp(list(bounds)
                    list("PACKAGE_HEIGHT_MAX" "1.0 mm")) "cannot set package height")
                opaFixtureRectangle(list(-1.7:-0.7 1.7:0.7) nil
                    "PACKAGE GEOMETRY/SILKSCREEN_TOP" definition)
                opaFixtureRequire(axlDBCreateNet("TEST_NET") "cannot create TEST_NET")
                opaFixtureRequire(axlDBCreateNet("TEST_RETURN") "cannot create TEST_RETURN")
                foreach(entry '(("R1" 10 10) ("R2" 20 10) ("R3" 30 10))
                    component = opaFixtureRequire(axlDBCreateComponent(
                        car(entry) "opa_fixture_device" "OPA_FIXTURE_TWO_PIN")
                        "cannot create logical component")
                    symbol = car(opaFixtureRequire(axlDBCreateSymbol(
                        car(entry) list(cadr(entry) caddr(entry)) nil 0.0)
                        "cannot place physical symbol"))
                    foreach(pin component->pins
                        opaFixtureRequire(axlDBAssignNet(pin
                            if(equal(pin->number "1")
                                then "TEST_NET" else "TEST_RETURN"))
                            "cannot assign fixture pin net")
                    )
                    when(equal(car(entry) "R3")
                        opaFixtureRequire(axlDBAddProp(list(symbol) list("FIXED"))
                            "cannot apply native FIXED property")
                    )
                )
                axlDBControl('drcEnable t)
                foreach(rule '(Package_to_Package_Spacing
                               Package_to_Place_Keepin_Spacing
                               Package_to_Place_Keepout_Spacing)
                    opaFixtureRequire(member(rule axlCNSDesignModeGet(nil))
                        "required placement DRC rule is unavailable")
                    opaFixtureRequire(axlCNSDesignModeSet(rule 'on)
                        "cannot enable required placement DRC rule")
                )
                opaFixtureVerify()
                opaFixtureRequire(axlDBTransactionCommit(mark)
                    "fixture transaction commit failed")
                committed = t
            )
            progn(
                when(mark && !committed axlDBTransactionRollback(mark))
                if(oldDevpath then axlSetVariable("devpath" oldDevpath)
                    else axlUnsetVariable("devpath"))
            )
        )
        ; Saving invalidates DBIDs and transactions; never save inside the transaction.
        opaFixtureRequire(axlDRCUpdate(nil) "native baseline DRC update failed")
        opaFixtureRequire(!isFile(source) && !isFile(working)
            "a destination appeared during construction")
        opaFixtureRequire(axlSaveDesign(?design source ?noMru t)
            "native source save failed")
        opaFixtureRequire(isFile(source) "native source save produced no file")
        opaFixtureRequire(!isFile(working) "working destination appeared during save")
        opaFixtureRequire(axlOSFileCopy(source working nil)
            "cannot copy source to working board")
        ; Only the just-saved synthetic source is replaced; no unsaved work exists.
        opaFixtureRequire(axlOpenDesign(?design working ?mode "wf" ?noMru t)
            "cannot reopen disposable working copy")
        opaFixtureReceipt()
        t
    )
)

axlCmdRegister("opa_fixture_create" 'opaFixtureCreate ?cmdType "general")
axlCmdRegister("opa_fixture_receipt" 'opaFixtureReceipt ?cmdType "general")

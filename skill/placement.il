; Original, deliberately narrow native model for the self-contained OPA fixture.
defstruct(opaNativeFrame scene records common components drcs)

procedure(opaSort(values)
    sort(copy(values) 'alphalessp)
)

procedure(opaStable(value)
    let((text)
        ; %L rounds floating-point atoms using ambient print settings. Format
        ; each float explicitly, including inside list/dictionary keys.
        cond(
            (floatp(value)
                text = sprintf(nil "%.17g" value)
                opaRequire(!rexMatchp("[^0-9eE+.-]" text)
                    "Nonfinite native numeric value.")
                unless(rexMatchp("[.eE]" text) text = strcat(text ".0")))
            (null(value) text = "nil")
            (listp(value)
                text = strcat("(" buildString(foreach(mapcar item value
                    opaStable(item)) " ") ")"))
            (t
                opaRequire(stringp(value) || symbolp(value) || fixp(value)
                    "Unsupported stable scene value.")
                text = sprintf(nil "%L" value))
        )
        opaRequire(!rexMatchp("dbid:" text) && !rexMatchp("pad:" text) &&
            !rexMatchp("_axlPath@" text)
            "Transient native handles cannot be scene identities.")
        text
    )
)

procedure(opaSortedData(values)
    sort(copy(values) lambda((a b) alphalessp(opaStable(a) opaStable(b))))
)

procedure(opaPairs(values)
    opaSortedData(values)
)

procedure(opaProps(object)
    let((values)
        values = axlDBGetProperties(object)
        ; Audit metadata changes on a save or with elapsed time, not with placement.
        values = setof(value values
            !member(car(value) '(VERSION_ID LAST_SAVED_NAME EDIT_TIME)))
        opaPairs(values)
    )
)

procedure(opaDbu(value)
    let((scaled)
        opaRequire(numberp(value) && abs(value) <= 10000.0
            "Native coordinate is outside the bounded millimeter model.")
        scaled = value * 10000.0
        opaRequire(abs(scaled - round(scaled)) < 0.00001
            "Coordinate is not canonical at the native DBU scale.")
        round(scaled)
    )
)

procedure(opaPoint(point)
    opaRequire(listp(point) && length(point) == 2 "Missing native point.")
    list(opaDbu(xCoord(point)) opaDbu(yCoord(point)))
)

procedure(opaBox(box)
    when(box
        opaRequire(length(box) == 2 "Invalid native bounding rectangle.")
        list(opaPoint(car(box)) opaPoint(cadr(box)))
    )
)

procedure(opaFlag(value)
    if(value then "1" else "0")
)

procedure(opaCoordinate(value)
    sprintf(nil "%.4f" value / 10000.0)
)

procedure(opaOrthogonal(value)
    opaRequire(numberp(value) && member(round(value) '(0 90 180 270)) &&
        abs(value - round(value)) < 0.000001
        "Only canonical orthogonal top-side poses are modeled.")
    round(value)
)

procedure(opaTargetDbu(text)
    let((value parts fraction)
        value = opaNumber(text)
        parts = parseString(text ".")
        when(length(parts) == 2
            fraction = cadr(parts)
            when(strlen(fraction) > 4
                opaRequire(!rexMatchp("[1-9]" substring(fraction 5))
                    "Requested position contains a fractional DBU.")))
        opaDbu(value)
    )
)

procedure(opaTargetAngle(text)
    let((value parts)
        value = opaNumber(text)
        parts = parseString(text ".")
        when(length(parts) == 2
            opaRequire(!rexMatchp("[1-9]" cadr(parts))
                "Requested angle is not exactly orthogonal."))
        opaOrthogonal(value)
    )
)

procedure(opaRotate(point angle)
    case(angle
        (0 point)
        (90 list(-cadr(point) car(point)))
        (180 list(-car(point) -cadr(point)))
        (270 list(cadr(point) -car(point)))
        (t opaRequire(nil "Unsupported native rotation."))
    )
)

procedure(opaWorld(point origin angle)
    let((rotated)
        rotated = opaRotate(point angle)
        list(car(origin) + car(rotated) cadr(origin) + cadr(rotated))
    )
)

procedure(opaWorldBox(box origin angle)
    let((points xs ys)
        points = list(car(box) cadr(box)
            list(caar(box) cadadr(box)) list(caadr(box) cadar(box)))
        points = foreach(mapcar point points opaWorld(point origin angle))
        xs = foreach(mapcar point points car(point))
        ys = foreach(mapcar point points cadr(point))
        list(list(apply('min xs) apply('min ys))
             list(apply('max xs) apply('max ys)))
    )
)

procedure(opaRectangleFill(layer fill)
    let((expected)
        opaRequire(member(layer '("BOARD GEOMETRY/DESIGN_OUTLINE"
            "BOARD GEOMETRY/OUTLINE" "PACKAGE KEEPIN/ALL"
            "PACKAGE KEEPOUT/TOP" "PACKAGE GEOMETRY/PLACE_BOUND_TOP"
            "PACKAGE GEOMETRY/SILKSCREEN_TOP"))
            "Unsupported rectangle layer.")
        expected = if(member(layer '("PACKAGE KEEPOUT/TOP"
            "PACKAGE GEOMETRY/PLACE_BOUND_TOP")) then t else nil)
        opaRequire(equal(fill expected)
            "Rectangle fill differs from the original fixture.")
        fill
    )
)

procedure(opaRectangle(object expected)
    let((segments pair fill)
        opaRequire(object && object->isRect && object->nSegs == 4 &&
            length(object->segments) == 4 "Unsupported nonrectangular geometry.")
        opaRequire(member(object->objType '("polygon" "shape"))
            "Unsupported rectangle object type.")
        ; Native polygon figures are unfilled; shape figures carry a fill
        ; attribute which must agree with the exact fixture layer.
        fill = if(object->objType == "polygon" then nil else object->fill)
        opaRectangleFill(object->layer fill)
        opaRequire(equal(opaBox(object->bBox) expected)
            "Actual rectangular geometry differs from the supported footprint.")
        foreach(segment object->segments
            opaRequire(segment->objType == "line" && segment->width == 0.0
                "Unsupported curved or stroked rectangle boundary.")
            pair = foreach(mapcar point segment->startEnd opaPoint(point))
            opaRequire(length(pair) == 2 &&
                (caar(pair) == caadr(pair) || cadar(pair) == cadadr(pair))
                "Rectangle has a non-axis-aligned edge.")
            segments = cons(opaSortedData(pair) segments)
        )
        list(object->objType object->layer fill expected
            opaSortedData(segments) opaProps(object))
    )
)

procedure(opaOnlyShape(layer expected)
    let((shapes)
        shapes = axlDBGetShapes(layer)
        opaRequire(length(shapes) == 1 "Missing or additional fixture boundary.")
        opaRectangle(car(shapes) expected)
    )
)

procedure(opaPadData(pad)
    list(pad->layer pad->type pad->figureName opaBox(pad->bBox)
         opaPoint(pad->offset) pad->flash pad->name pad->corners
         pad->radius pad->inside pad->sides)
)

procedure(opaDefinitions(design)
    let((definition padstack pad rows child pins compdef)
        opaRequire(length(design->symdefs) == 1 && length(design->padstacks) == 1 &&
            length(design->compdefs) == 1 "Unexpected native library definitions.")
        definition = car(design->symdefs)
        padstack = car(design->padstacks)
        compdef = car(design->compdefs)
        opaRequire(definition->name == "OPA_FIXTURE_TWO_PIN" &&
            definition->type == "PACKAGE" && length(definition->children) == 2 &&
            length(definition->pins) == 2 "Unsupported embedded package definition.")
        opaRequire(compdef->package == "OPA_FIXTURE_TWO_PIN" &&
            compdef->deviceType == "OPA_FIXTURE_DEVICE" &&
            compdef->class == "DISCRETE" && length(compdef->pins) == 2
            "Unsupported logical device definition.")
        opaRequire(padstack->name == "OPA_FIXTURE_SMD" && !padstack->isThrough &&
            padstack->holeType == "none" && padstack->drillDiameter == 0.0 &&
            equal(padstack->startEnd '("ETCH/TOP" "ETCH/TOP")) &&
            !padstack->pluralVia && !padstack->uvia &&
            !padstack->holeCounterType && !padstack->backdrillDiameter
            "Unsupported padstack, drill, or layer span.")
        pad = axlDBGetPad(padstack "TOP" "REGULAR")
        opaRequire(pad && pad->figureName == "RECTANGLE" &&
            equal(opaBox(pad->bBox) '((-4000 -5000) (4000 5000))) &&
            equal(opaPoint(pad->offset) '(0 0))
            "The actual top pad is not the original rectangular SMT pad.")
        foreach(pad padstack->pads
            opaRequire(
                (pad->layer == "ETCH/TOP" && pad->type == "REGULAR" &&
                    pad->figureName == "RECTANGLE") ||
                member(pad->figureName '(nil "NULL"))
                "An additional active pad or mask geometry is unsupported.")
            rows = cons(list("pad" opaPadData(pad)) rows)
        )
        rows = cons(list("padstack" padstack->name padstack->type padstack->usage
            padstack->plating padstack->holeType padstack->drillDiameter
            padstack->spanLockCount padstack->padSuppresion opaProps(padstack)) rows)
        foreach(pin definition->pins
            opaRequire(member(pin->number '("1" "2")) &&
                pin->name == "OPA_FIXTURE_SMD" && pin->rotation == 0.0 &&
                !pin->isMirrored && !pin->isMech
                "Unsupported footprint pin definition.")
            opaRequire(equal(opaPoint(pin->xy)
                if(pin->number == "1" then '(-12000 0) else '(12000 0)))
                "Footprint pin origin changed.")
            pins = cons(list(pin->number pin->name opaPoint(pin->xy) opaProps(pin)) pins)
        )
        foreach(child definition->children
            cond(
                (child->layer == "PACKAGE GEOMETRY/PLACE_BOUND_TOP"
                    rows = cons(list("definition-bound"
                        opaRectangle(child '((-20000 -10000) (20000 10000)))) rows))
                (child->layer == "PACKAGE GEOMETRY/SILKSCREEN_TOP"
                    rows = cons(list("definition-silk"
                        opaRectangle(child '((-17000 -7000) (17000 7000)))) rows))
                (t opaRequire(nil "Unknown footprint geometry."))
            )
        )
        rows = cons(list("definition" definition->name opaPairs(pins)
            opaProps(definition) opaProps(compdef)) rows)
        rows
    )
)

procedure(opaComponentData(component)
    let((symbol origin angle fixed mirrored placed bounds geometry intrinsic pins
         expected pad boundCount silkCount)
        opaRequire(member(component->name '("R1" "R2" "R3")) &&
            component->package == "OPA_FIXTURE_TWO_PIN" &&
            component->deviceType == "OPA_FIXTURE_DEVICE" &&
            component->class == "DISCRETE" && length(component->pins) == 2
            "Unsupported logical component.")
        symbol = component->symbol
        placed = if(symbol then t else nil)
        origin = '(0 0)
        angle = 0
        when(symbol
            opaRequire(symbol->name == "OPA_FIXTURE_TWO_PIN" &&
                !symbol->embedded && !symbol->etchChildren &&
                length(symbol->children) == 2 && length(symbol->pins) == 2
                "Unsupported symbol instance or attached copper.")
            origin = opaPoint(symbol->xy)
            angle = opaOrthogonal(symbol->rotation)
            mirrored = symbol->isMirrored
            opaRequire(!mirrored "Bottom-side or mirrored fixtures are unsupported.")
            fixed = if(axlDBIsFixed(symbol) then t else nil)
            bounds = opaWorldBox('((-20000 -10000) (20000 10000)) origin angle)
            boundCount = 0
            silkCount = 0
            foreach(child symbol->children
                cond(
                    (child->layer == "PACKAGE GEOMETRY/PLACE_BOUND_TOP"
                        boundCount = boundCount + 1
                        opaRequire(child->fill && !child->voids
                            "Place bounds must be a filled rectangle without voids.")
                        geometry = cons(opaRectangle(child bounds) geometry))
                    (child->layer == "PACKAGE GEOMETRY/SILKSCREEN_TOP"
                        silkCount = silkCount + 1
                        geometry = cons(opaRectangle(child
                            opaWorldBox('((-17000 -7000) (17000 7000)) origin angle))
                            geometry))
                    (t opaRequire(nil "Unexpected instance geometry."))
                )
                intrinsic = cons(list(child->layer opaProps(child)) intrinsic)
            )
            opaRequire(boundCount == 1 && silkCount == 1
                "Explicit place bounds or original silkscreen is missing.")
            intrinsic = cons(list("symbol" opaProps(symbol)
                axlDBIsReadOnly(symbol) fixed mirrored) intrinsic)
        )
        foreach(pin component->pins
            opaRequire(member(pin->number '("1" "2")) && pin->net &&
                pin->net->name == if(pin->number == "1" then "TEST_NET" else "TEST_RETURN")
                "Unexpected fixture pin or net association.")
            when(placed
                opaRequire(pin->name == "OPA_FIXTURE_SMD" && pin->definition &&
                    pin->definition->name == "OPA_FIXTURE_SMD" && !pin->isExploded &&
                    !pin->isThrough && !pin->isMech && !pin->isMirrored &&
                    opaOrthogonal(pin->rotation) == angle
                    "A physical pin differs from the embedded SMT definition.")
                expected = opaWorld(
                    if(pin->number == "1" then '(-12000 0) else '(12000 0))
                    origin angle)
                opaRequire(equal(opaPoint(pin->xy) expected)
                    "Physical pin coordinates disagree with the symbol pose.")
                pad = axlDBGetPad(pin "TOP" "REGULAR")
                opaRequire(pad && pad->figureName == "RECTANGLE"
                    "Physical pin lacks the supported rectangular top pad.")
            )
            pins = cons(list(pin->number pin->net->name
                if(placed then opaPoint(pin->xy) else nil)
                if(placed then opaPadData(pad) else nil)) pins)
            intrinsic = cons(list("pin" pin->number pin->net->name opaProps(pin)) intrinsic)
        )
        intrinsic = cons(list("component" component->package opaProps(component)) intrinsic)
        ; Only data escapes this command; no native DBIDs are cached.
        list(component->name origin angle mirrored fixed placed bounds
             opaPairs(intrinsic) opaPairs(geometry) opaPairs(pins))
    )
)

procedure(opaObjectIdentity(object)
    cond(
        (object->objType == "symbol" list("symbol" object->refdes))
        (object->objType == "component" list("component" object->name))
        (object->objType == "pin"
            opaRequire(object->component "Unowned pin in DRC marker.")
            list("pin" object->component->name object->number))
        (member(object->objType '("shape" "polygon"))
            list("geometry"
                if(object->parent && object->parent->objType == "symbol"
                    then object->parent->refdes else "board")
                object->layer opaBox(object->bBox)))
        (object->objType == "line"
            list("edge" opaObjectIdentity(object->parent)
                foreach(mapcar point object->startEnd opaPoint(point))))
        (t opaRequire(nil "Unmodeled object in a native DRC identity."))
    )
)

procedure(opaDrcIdentities(design)
    let((identities affected)
        opaRequire(!design->waived "Waived DRCs are outside this fixture model.")
        foreach(marker design->drcs
            opaRequire(marker->objType == "drc" && !marker->waived
                "Unsupported DRC marker.")
            affected = foreach(mapcar object marker->violations opaObjectIdentity(object))
            identities = cons(opaStable(list(marker->name marker->type marker->source
                opaPoint(marker->xy) marker->actual marker->expected
                opaPairs(affected))) identities)
        )
        opaSort(identities)
    )
)

procedure(opaAllFigures(design shapes)
    let((saved enabled buttons allowed selected)
        ; Invoked only by a private interactive callback, never by a general gate.
        saved = axlGetSelSet()
        enabled = axlGetFindFilter(nil)
        buttons = axlGetFindFilter(t)
        allowed = append(copy(shapes) append(copy(design->symbols) copy(design->drcs)))
        foreach(component design->components
            allowed = append(allowed copy(component->pins))
        )
        foreach(shape shapes allowed = append(allowed copy(shape->segments)))
        unwindProtect(
            progn(
                axlClearSelSet()
                axlSetFindFilter(
                    ?enabled '("noall" "symbols" "pins" "vias" "clines" "lines"
                               "shapes" "text" "figures" "drcs" "invisible")
                    ?onButtons '("noall" "symbols" "pins" "vias" "clines" "lines"
                                 "shapes" "text" "figures" "drcs"))
                axlAddSelectAll()
                selected = axlGetSelSet()
                foreach(object selected
                    opaRequire(member(object allowed) ||
                        (object->objType == "figure" &&
                         object->layer == "DRAWING FORMAT/DRAWING_ORIGIN" &&
                         object->readOnly)
                        "Unexpected free geometry, text, routing, via, or figure.")
                )
            )
            progn(
                axlClearSelSet()
                axlSetFindFilter(?enabled enabled ?onButtons buttons)
                when(saved axlAddSelectObject(saved))
            )
        )
        t
    )
)

procedure(opaLayerValues(tag top bottom)
    top = opaPairs(top)
    bottom = opaPairs(bottom)
    if(equal(top bottom) then list(list(tag '("BOTTOM" "TOP") top))
        else list(list(tag '("BOTTOM") bottom) list(tag '("TOP") top)))
)

procedure(opaConstraintData()
    let((rows layers layerInfo assembly options)
        layers = axlSubclassRoute()
        opaRequire(equal(opaSort(layers) '("BOTTOM" "TOP"))
            "Only the original two-layer stackup is supported.")
        foreach(domain '(spacing physical sameNet)
            opaRequire(equal(axlCnsList(domain) '("DEFAULT"))
                "Additional constraint sets require a new native board model.")
        )
        opaRequire(!axlCNSDFAMode('table) && axlCNSDFAMode('mode) == 'off
            "DFA tables need a separate modeled constraint envelope.")
        assembly = axlCNSAssemblyModeGet('all)
        foreach(mode assembly
            opaRequire(cadr(mode) == 'off
                "Enabled IC assembly checks are outside this PCB fixture model."))
        options = foreach(mapcar option axlCNSOptions(nil)
            list(option axlCNSOptions(option)))
        rows = list(
            list("dfa" nil axlCNSDFAMode('mode))
            list("assembly-modes" opaPairs(assembly))
            list("constraint-options" opaPairs(options))
            list("design-modes" opaPairs(axlCNSDesignModeGet('all)))
            list("design-values" opaPairs(axlCNSDesignValueGet('all)))
            list("physical-modes" opaPairs(axlCNSPhysicalModeGet('all)))
            list("spacing-modes" opaPairs(axlCNSSpacingModeGet('all)))
            list("same-net-modes" opaPairs(axlCNSSameNetModeGet('all)))
            list("controls" axlDBControl('drcEnable) axlDBControl('defaultSymbolHeight)
                 axlDBControl('testPointFixed) axlGetVariable("dbg_noskilltriggers")))
        foreach(layer layers
            layerInfo = axlLayerGet(strcat("ETCH/" layer))
            opaRequire(layerInfo && layerInfo->isEtch &&
                layerInfo->type == "CONDUCTOR" && layerInfo->drcPhotoType == "positive"
                "Unexpected layer type or polarity.")
            rows = cons(list("layer" layer layerInfo->type layerInfo->drcPhotoType
                layerInfo->material layerInfo->fillinMaterial layerInfo->thickness) rows)
        )
        rows = append(opaLayerValues("spacing" axlCNSGetSpacing("" "TOP" nil)
            axlCNSGetSpacing("" "BOTTOM" nil)) rows)
        rows = append(opaLayerValues("physical" axlCNSGetPhysical("" "TOP" nil)
            axlCNSGetPhysical("" "BOTTOM" nil)) rows)
        rows = append(opaLayerValues("same-net" axlCNSGetSameNet("" "TOP" nil)
            axlCNSGetSameNet("" "BOTTOM" nil)) rows)
        rows
    )
)

procedure(opaCollectAtoms(value atoms)
    if(listp(value) then
        foreach(item value atoms = opaCollectAtoms(item atoms))
    else
        opaRequire(stringp(value) || symbolp(value) || numberp(value)
            "Unsupported native scene value.")
        value = opaStable(value)
        opaField(value)
        unless(member(value atoms) atoms = cons(value atoms))
    )
    atoms
)

procedure(opaIndexCode(index)
    let((digits)
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        if(index < 62 then substring(digits index + 1 1)
            else strcat(opaIndexCode(fix(index / 62.0))
                substring(digits mod(index 62) + 1 1)))
    )
)

procedure(opaCountCode(count)
    if(count < 62 then opaIndexCode(count) else sprintf(nil "~%d;" count))
)

procedure(opaJoinTree(parts)
    let((result previous)
        result = ""
        previous = ""
        foreach(part parts
            when(previous != "" &&
                 rexMatchp("[0-9A-Za-z]" previous) &&
                 rexMatchp("^[0-9A-Za-z]" part)
                result = strcat(result "."))
            result = strcat(result part)
            previous = substring(part strlen(part) 1)
        )
        result
    )
)

procedure(opaEncodeTree(value table nodes)
    let((key code)
        if(listp(value) then
            key = opaStable(value)
            code = nodes[key]
            if(code then strcat("~" code) else
                nodes[key] = opaIndexCode(nodes["next"])
                nodes["next"] = nodes["next"] + 1
                strcat("(" opaJoinTree(
                    foreach(mapcar item value opaEncodeTree(item table nodes))) ")"))
        else table[opaStable(value)])
    )
)

procedure(opaCanonical(rows)
    let((atoms table nodes dictionary previous prefix index entry tree result)
        ; Lossless front-coded atom dictionary keeps the complete scene below
        ; the wire limit. Sorted rows/atoms make this independent of DBID order.
        rows = opaSortedData(rows)
        atoms = opaSort(opaCollectAtoms(rows nil))
        table = makeTable('opaSceneAtoms nil)
        dictionary = ""
        previous = ""
        index = 0
        foreach(atom atoms
            table[atom] = opaIndexCode(index)
            index = index + 1
            prefix = 0
            while(prefix < strlen(previous) && prefix < strlen(atom) &&
                  substring(previous prefix + 1 1) == substring(atom prefix + 1 1)
                prefix = prefix + 1)
            entry = if(prefix < strlen(atom) then substring(atom prefix + 1) else "")
            dictionary = strcat(dictionary opaCountCode(prefix)
                opaCountCode(strlen(entry)) entry)
            previous = atom
        )
        ; Dictionary entries preserve complete values rather than hashing them.
        nodes = makeTable('opaSceneLists nil)
        nodes["next"] = 0
        tree = opaEncodeTree(rows table nodes)
        result = strcat("OPA-FIXTURE-1;" sprintf(nil "%d;" length(atoms))
                        dictionary ";" tree)
        opaRequire(strlen(result) <= 8192 sprintf(nil
            "Complete scene needs %d characters (dictionary %d tree %d); maximum 8192."
            strlen(result) strlen(dictionary) strlen(tree)))
        opaField(result)
        result
    )
)

procedure(opaFixtureReadFrame()
    let((design units common components records shapes placedCount rows component
         data symbol drcs scene frame)
        opaBoardGuard()
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        units = axlDBGetDesignUnits()
        opaRequire(equal(units '("millimeters" 4 10000))
            "Expected the synthetic fixture's millimeter/4/10000 database.")
        opaRequire(!design->groups && !design->module && !design->zone &&
            !design->netclass && !design->netGroup &&
            !design->bus && !design->diffpair && !design->matchgroup &&
            !design->ecsets && !design->text && !design->pins && !design->keepinRoute &&
            !design->koGroup && !axlDBGetLonelyBranches()
            "Additional topology, routing, groups, or regions are unsupported.")
        opaRequire(length(design->components) <= 3 &&
            equal(opaSort(design->nets~>name) '("TEST_NET" "TEST_RETURN"))
            "Unexpected fixture components or nets.")
        ; In 25.1 the xnet view also returns ordinary unextended net DBIDs.
        foreach(xnet design->xnet
            opaRequire(xnet->objType == "net" && member(xnet design->nets)
                "An extended net group is outside the supported fixture."))
        common = append(opaDefinitions(design) opaConstraintData())
        common = cons(list("board" opaBoardPath units axlVersion('fullVersion)
            opaProps(design) opaBox(axlGetParam("paramDesign")->bBox)) common)
        common = cons(list("outline" opaOnlyShape("BOARD GEOMETRY/DESIGN_OUTLINE"
            '((0 0) (400000 300000)))) common)
        common = cons(list("legacy-outline" opaOnlyShape("BOARD GEOMETRY/OUTLINE"
            '((0 0) (400000 300000)))) common)
        common = cons(list("keepin" opaOnlyShape("PACKAGE KEEPIN/ALL"
            '((10000 10000) (390000 290000)))) common)
        common = cons(list("keepout" opaOnlyShape("PACKAGE KEEPOUT/TOP"
            '((240000 180000) (300000 240000)))) common)
        opaRequire(design->designOutline && design->keepinPlace
            "Native outline/keepin identity is missing.")
        foreach(net design->nets
            common = cons(list("net" net->name opaProps(net)) common)
            foreach(branch net->branches
                foreach(object branch->children
                    opaRequire(object->objType == "pin" "Routed connectivity is unsupported.")
                )
            )
        )
        placedCount = 0
        foreach(component design->components
            data = opaComponentData(component)
            opaRequire(!assoc(car(data) components) "Duplicate native reference designator.")
            components = cons(data components)
            when(nth(5 data) placedCount = placedCount + 1)
        )
        shapes = axlDBGetShapes(nil)
        opaRequire(length(design->symbols) == placedCount &&
            length(shapes) == 4 + 2 * placedCount
            "Additional symbols or shapes are outside the supported fixture.")
        opaAllFigures(design shapes)
        drcs = opaDrcIdentities(design)
        common = opaSortedData(common)
        components = sort(components lambda((a b) alphalessp(car(a) car(b))))
        rows = list(list("common" common) list("components" components)
                    list("drc" design->drcState drcs))
        scene = opaCanonical(rows)
        records = list(list("board" opaBoardPath)
            list("units" car(units) sprintf(nil "%d" cadr(units))
                 sprintf(nil "%d" caddr(units)))
            list("version" axlVersion('fullVersion)))
        foreach(data components
            records = append(records list(list("component" car(data) "OPA_FIXTURE_TWO_PIN"
                opaCoordinate(caadr(data)) opaCoordinate(cadadr(data))
                sprintf(nil "%d" nth(2 data))
                opaFlag(nth(3 data)) opaFlag(nth(4 data)) opaFlag(nth(5 data)))))
        )
        records = append(records list(list("scene" scene)))
        frame = make_opaNativeFrame(?scene scene ?records records ?common common
            ?components components ?drcs drcs)
        frame
    )
)

procedure(opaFixtureWritesAllowed(frame)
    let((r3)
        opaRequire(length(frame->components) == 3 "Writes require all three fixture components.")
        foreach(data frame->components
            opaRequire(nth(5 data) && !nth(3 data) "Writes require every part placed on top.")
        )
        r3 = assoc("R3" frame->components)
        opaRequire(r3 && nth(4 r3) "The fixture's R3 fixed precondition is missing.")
        opaRequire(axlDBControl('drcEnable) && axlDBGetDesign()->drcState == t
            "Native baseline DRC is disabled or out of date.")
        foreach(rule '(Package_to_Package_Spacing Package_to_Place_Keepin_Spacing
                       Package_to_Place_Keepout_Spacing)
            opaRequire(axlCNSDesignModeGet(rule) == 'on
                "Required native placement DRC coverage is not enabled.")
        )
        opaRequire(!axlGetVariable("dbg_noskilltriggers")
            "Native lifecycle triggers have been disabled.")
        t
    )
)

procedure(opaOverlap(first second)
    caar(first) < caadr(second) && caadr(first) > caar(second) &&
    cadar(first) < cadadr(second) && cadadr(first) > cadar(second)
)

procedure(opaFixturePlacementPolicy(frame)
    let((bounds others)
        foreach(data frame->components
            bounds = nth(6 data)
            opaRequire(bounds && caar(bounds) >= 10000 && cadar(bounds) >= 10000 &&
                caadr(bounds) <= 390000 && cadadr(bounds) <= 290000
                "Place bounds leave the board/placement keepin.")
            opaRequire(!opaOverlap(bounds '((240000 180000) (300000 240000)))
                "Place bounds overlap the controlled package keepout.")
            foreach(other others
                opaRequire(!opaOverlap(bounds nth(6 other))
                    "Two explicit package place bounds overlap.")
            )
            others = cons(data others)
        )
        t
    )
)

procedure(opaFixtureOnlyTargetChanged(before after refdes target angle)
    let((old current)
        opaRequire(equal(before->common after->common)
            "Non-component scene changed during the transaction.")
        foreach(old before->components
            current = assoc(car(old) after->components)
            opaRequire(current "A component disappeared during the transaction.")
            if(car(old) == refdes then
                opaRequire(equal(nth(1 current) target) && nth(2 current) == angle &&
                    equal(nth(7 old) nth(7 current))
                    "Target pose or intrinsic component state was not preserved.")
            else
                opaRequire(equal(old current) "A non-target component changed.")
            )
        )
        foreach(identity after->drcs
            opaRequire(member(identity before->drcs) "Native DRC reported a new violation.")
        )
        t
    )
)

procedure(opaFixtureApplyTransaction(context)
    let((params identifier expected before after restored target angle refdes symbol
         old mark committed rollbackOK outcome result message)
        identifier = nth(1 context)
        params = nth(3 context)
        refdes = nth(2 params)
        target = list(opaTargetDbu(nth(3 params)) opaTargetDbu(nth(4 params)))
        angle = opaTargetAngle(nth(5 params))
        before = opaReadFrame()
        opaExpected(nth(1 params) before)
        opaWritesAllowed(before)
        old = assoc(refdes before->components)
        opaRequire(old && nth(5 old) && !nth(4 old) && !nth(3 old)
            "Target is missing, unplaced, fixed, or mirrored.")
        opaRequire(!equal(nth(1 old) target) || nth(2 old) != angle "No-op apply is rejected.")
        ; Resolve through the logical component without retaining handles across commands.
        symbol = nil
        foreach(component axlDBGetDesign()->components
            when(component->name == refdes symbol = component->symbol))
        opaRequire(symbol && !axlDBIsFixed(symbol) && !axlDBIsReadOnly(symbol)
            "Native target is fixed or read-only.")
        opaInvalidate(nil)
        result = errset(
            progn(
                mark = axlDBTransactionStart()
                opaRequire(mark "Cannot start a native placement transaction.")
                opaMutationBegan = t
                ; Transform order is move then rotate: pivot at the new component origin.
                opaRequire(axlTransformObject(symbol
                    ?move list((car(target) - caadr(old)) / 10000.0
                               (cadr(target) - cadadr(old)) / 10000.0)
                    ?angle angle - nth(2 old)
                    ?origin list(car(target) / 10000.0 cadr(target) / 10000.0)
                    ?allOrNone t)
                    "Native transform did not succeed.")
                opaRequire(axlDRCUpdate(nil) "Native placement DRC update failed.")
                after = opaReadFrame()
                opaWritesAllowed(after)
                opaOnlyTargetChanged(before after refdes target angle)
                opaPlacementPolicy(after)
                opaRequire(axlDBTransactionCommit(mark) "Native transaction commit failed.")
                committed = t
                after = opaReadFrame()
                opaOnlyTargetChanged(before after refdes target angle)
                opaPlacementPolicy(after)
                t
            )

            t
        )
        message = opaError
        if(result && committed then
            opaMutationBegan = nil
            list("applied" "Exact pose applied in memory; not saved." after->records)
        else
            if(mark && !committed then
                rollbackOK = errset(axlDBTransactionRollback(mark) t)
                restored = errset(
                    progn(
                        opaRequire(axlDRCUpdate(nil) "Post-rollback DRC update failed.")
                        after = opaReadFrame()
                        opaRequire(equal(before->scene after->scene)
                            "Complete pre-transaction scene was not restored.")
                        t
                    ) t)
                if(rollbackOK && car(rollbackOK) && restored then
                    opaMutationBegan = nil
                    list("rolled_back" message after->records)
                else
                    opaHalted = t
                    list("indeterminate" "Rollback restoration could not be established." nil))
            else
                if(committed then
                    opaHalted = t
                    list("indeterminate" "Post-commit verification failed; stop writes." nil)
                else
                    list("rejected" message nil))
            )
        )
    )
)

procedure(opaManagedMode()
    boundp('opaBoardModel) && opaBoardModel == "managed-board-v1"
)

procedure(opaReadFrame()
    if(opaManagedMode() then opaManagedReadFrame() else opaFixtureReadFrame())
)

procedure(opaWritesAllowed(frame)
    if(opaManagedMode() then opaManagedWritesAllowed(frame)
        else opaFixtureWritesAllowed(frame))
)

procedure(opaPlacementPolicy(frame)
    if(opaManagedMode() then opaManagedPlacementPolicy(frame)
        else opaFixturePlacementPolicy(frame))
)

procedure(opaOnlyTargetChanged(before after refdes target angle)
    if(opaManagedMode() then opaManagedOnlyTargetChanged(before after refdes target angle)
        else opaFixtureOnlyTargetChanged(before after refdes target angle))
)

procedure(opaApplyTransaction(context)
    if(opaManagedMode() then opaManagedApplyTransaction(context)
        else opaFixtureApplyTransaction(context))
)

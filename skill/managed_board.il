; Bounded imported-board model, not an import or library-loading interface.
; Requires placement.il primitives and the adapter's exact approval/state gate.
; Scope: embedded simple top SMT packages, rectangles/straight package linework,
; mapped logical functions, bounded attachments, default constraints, no routed copper.
; Native acceptance is still required. Installed API evidence:
; DOC/FUNCS/axlDBCreateSymbol.txt, axlLoadSymbol.txt, axlDBRefreshId.txt,
; axlDbidDoc.txt, axlPadDbidDoc.txt and DOC/QIR/CHANGE/axlCmdRegister.txt.

procedure(opaManagedName(value)
    opaField(value)
    opaRequire(strlen(value) > 0 "An inventory name is empty.")
    value
)

procedure(opaManagedReadBytes(path maximum)
    let((port value count chunks chunk)
        opaRequire(fixp(maximum) && maximum >= 0 && maximum <= 65536
            "Invalid native attachment byte limit.")
        port = axlDMOpenFile("TEMP" path "rb")
        opaRequire(port "Cannot read the extracted native attachment.")
        count = 0
        chunks = nil
        chunk = ""
        unwindProtect(
            progn(
                while(value = getc(port)
                    value = charToInt(value)
                    opaRequire(value >= 0 && value <= 255 && count < maximum
                        "Expanded attachment bytes exceed the bounded native model.")
                    chunk = strcat(chunk sprintf(nil "%02x" value))
                    count = count + 1
                    when(strlen(chunk) == 1024
                        chunks = cons(chunk chunks)
                        chunk = ""))
                unless(chunk == "" chunks = cons(chunk chunks))
                list(count reverse(chunks))
            )
            axlDMClose(port)
        )
    )
)

procedure(opaManagedAttachments()
    let((names rows metadata attachment total expanded bytes path)
        names = axlGetAllAttachmentNames()
        opaRequire(length(names) <= 128 "Too many native board attachments.")
        total = 0
        expanded = 0
        foreach(name opaSort(names)
            opaManagedName(name)
            opaRequire(!assoc(name rows) "Duplicate native attachment identifier.")
            metadata = axlGetAttachment(name)
            opaRequire(metadata && metadata->objType == "attachment" &&
                metadata->id == name && fixp(metadata->size) &&
                metadata->size >= 0 && metadata->size <= 65536
                "Native attachment is missing or exceeds the 64 KiB bound.")
            total = total + metadata->size
            opaRequire(total <= 131072 "Native attachments exceed the 128 KiB total bound.")
            ; String retrieval truncates binary attachments at NUL. Export to a
            ; temporary file and preserve every byte, without changing the DB.
            attachment = axlGetAttachment(name 'file)
            opaRequire(attachment && attachment->id == name &&
                attachment->dataFormat == 'file && stringp(attachment->data) &&
                attachment->size == metadata->size && attachment->revision == metadata->revision
                "Cannot extract the complete native attachment.")
            path = attachment->data
            unwindProtect(
                progn(
                    bytes = opaManagedReadBytes(path min(65536 131072 - expanded))
                    expanded = expanded + car(bytes)
                    ; 'file expands compressed attachments and omits text
                    ; terminators. Preserve both native size and full exported
                    ; bytes; the two lengths are not generally equal.
                    rows = cons(list(name metadata->revision metadata->password metadata->size
                        car(bytes) cadr(bytes)) rows)
                )
                opaRequire(deleteFile(path) "Cannot remove the extracted attachment temporary file.")
            )
        )
        opaSortedData(rows)
    )
)

procedure(opaManagedBox(box)
    let((result)
        result = opaBox(box)
        opaRequire(result && caar(result) < caadr(result) &&
            cadar(result) < cadadr(result) "Missing or degenerate managed rectangle.")
        result
    )
)

procedure(opaManagedUnion(first second)
    if(!first then second else
        if(!second then first else
            list(list(min(caar(first) caar(second)) min(cadar(first) cadar(second)))
                 list(max(caadr(first) caadr(second)) max(cadadr(first) cadadr(second))))))
)

procedure(opaManagedInside(inner outer)
    inner && outer && caar(inner) >= caar(outer) && cadar(inner) >= cadar(outer) &&
        caadr(inner) <= caadr(outer) && cadadr(inner) <= cadadr(outer)
)

procedure(opaManagedObjectGuard(object)
    opaRequire(object && !object->parentGroups && !axlDBGetAttachedText(object)
        "Groups or attached text require an additional native scene model.")
    t
)

procedure(opaManagedEdge(object)
    let((points width)
        opaManagedObjectGuard(object)
        opaRequire(object->objType == "line" && !object->isEtch
            "Only straight non-copper package edges are supported.")
        points = foreach(mapcar point object->startEnd opaPoint(point))
        width = opaDbu(object->width)
        opaRequire(length(points) == 2 && !equal(car(points) cadr(points)) && width >= 0
            "Invalid straight package edge.")
        list(opaSortedData(points) width object->font opaProps(object))
    )
)

procedure(opaManagedGeometry(object)
    let((kind box edges fill points)
        opaManagedObjectGuard(object)
        kind = object->objType
        opaRequire(member(object->layer
            '("BOARD GEOMETRY/DESIGN_OUTLINE" "BOARD GEOMETRY/OUTLINE"
              "PACKAGE KEEPIN/ALL" "PACKAGE KEEPOUT/TOP"
              "PACKAGE GEOMETRY/PLACE_BOUND_TOP" "PACKAGE GEOMETRY/DFA_BOUND_TOP"
              "PACKAGE GEOMETRY/SILKSCREEN_TOP" "PACKAGE GEOMETRY/ASSEMBLY_TOP"))
            "Unsupported board or package geometry layer.")
        box = opaBox(object->bBox)
        opaRequire(box "Package geometry has no bounding box.")
        cond(
            (member(kind '("shape" "polygon"))
                opaRequire(object->isRect && object->nSegs == 4 &&
                    length(object->segments) == 4 && !object->voids &&
                    !object->shapeBoundary && !object->shapeIsBoundary &&
                    !object->shapeAuto && !object->cavity && !object->isHole &&
                    !object->fillet && !object->taper && !object->dynamicGroup
                    "Only static rectangular shapes without voids are supported.")
                fill = if(kind == "polygon" then nil else object->fill)
                opaRequire(fill == nil || fill == t "Hatched shapes are unsupported.")
                foreach(segment object->segments
                    edges = cons(opaManagedEdge(segment) edges))
                foreach(edge edges
                    points = car(edge)
                    opaRequire(cadr(edge) == 0 &&
                        (caar(points) == caadr(points) || cadar(points) == cadadr(points))
                        "Rectangle edges must be zero-width and axis-aligned.")))
            (kind == "path"
                opaRequire(!object->isEtch && !object->hasArcs && !object->branch &&
                    !object->symbolEtch && !object->startEnd &&
                    object->nSegs == length(object->segments) &&
                    length(object->segments) > 0 && length(object->segments) <= 256
                    "Unsupported routed, curved, empty or oversized package path.")
                foreach(segment object->segments
                    edges = cons(opaManagedEdge(segment) edges)))
            (kind == "line" edges = list(opaManagedEdge(object)))
            (t opaRequire(nil "Unsupported text, figure, arc or package shape type."))
        )
        list(kind object->layer fill box opaSortedData(edges) opaProps(object))
    )
)

procedure(opaManagedGeometryBounds(data)
    let((box points width margin edgeBox)
        box = nth(3 data)
        foreach(edge nth(4 data)
            points = car(edge)
            width = cadr(edge)
            ; Round an odd half-DBU stroke outward rather than underestimating it.
            margin = fix((width + 1) / 2.0)
            edgeBox = list(
                list(min(caar(points) caadr(points)) - margin
                     min(cadar(points) cadadr(points)) - margin)
                list(max(caar(points) caadr(points)) + margin
                     max(cadar(points) cadadr(points)) + margin))
            box = opaManagedUnion(box edgeBox))
        box
    )
)

procedure(opaManagedGeometryPose(data origin angle)
    list(car(data) cadr(data) nth(2 data)
        opaWorldBox(nth(3 data) origin angle)
        opaSortedData(foreach(mapcar edge nth(4 data)
            list(opaSortedData(foreach(mapcar point car(edge) opaWorld(point origin angle)))
                 cadr(edge) nth(2 edge) nth(3 edge)))))
)

procedure(opaManagedGeometryShape(data)
    list(car(data) cadr(data) nth(2 data) nth(3 data) nth(4 data))
)

procedure(opaManagedLocalGeometry(data origin angle)
    let((inverse inverseOrigin)
        inverse = mod(360 - angle 360)
        inverseOrigin = opaRotate(list(-car(origin) -cadr(origin)) inverse)
        append(opaManagedGeometryPose(data inverseOrigin inverse) list(nth(5 data)))
    )
)

procedure(opaManagedPad(pad)
    let((active box offset)
        opaRequire(pad "Missing native pad data.")
        active = !member(pad->figureName '(nil "NULL"))
        when(active
            opaRequire(member(pad->figureName '("RECTANGLE" "SQUARE" "CIRCLE")) &&
                member(pad->layer '("ETCH/TOP" "PIN/SOLDERMASK_TOP"
                    "PIN/PASTEMASK_TOP")) &&
                pad->type == "REGULAR" && member(pad->name '(nil "")) &&
                member(pad->flash '(nil "")) && !pad->corners &&
                member(pad->radius '(nil 0 0.0)) &&
                member(pad->inside '(nil 0 0.0)) &&
                member(pad->sides '(nil 0))
                "Only simple top-side regular SMT and mask pads are supported.")
            box = opaManagedBox(pad->bBox)
            offset = opaPoint(pad->offset))
        list(pad->layer pad->type pad->figureName
            if(active then box else opaBox(pad->bBox))
            if(pad->offset then opaPoint(pad->offset) else nil)
            pad->flash pad->name pad->corners pad->radius pad->inside pad->sides)
    )
)

procedure(opaManagedPadstacks(design)
    let((rows pads bounds box offset top)
        opaRequire(length(design->padstacks) > 0 && length(design->padstacks) <= 1024
            "Embedded padstack inventory is missing or oversized.")
        foreach(stack design->padstacks
            opaManagedObjectGuard(stack)
            opaManagedName(stack->name)
            opaRequire(!assoc(stack->name rows) && !stack->isThrough &&
                stack->holeType == "none" && stack->drillDiameter == 0.0 &&
                equal(stack->startEnd '("ETCH/TOP" "ETCH/TOP")) &&
                !stack->pluralVia && !stack->uvia && !stack->isPadRef &&
                !stack->derived && !stack->multiDrillData &&
                !stack->holeCounterType && !stack->backdrillDiameter &&
                member(stack->padSuppresion '(nil t))
                "Duplicate, drilled, derived or advanced padstack.")
            pads = nil
            bounds = nil
            opaRequire(length(stack->pads) <= 128 "Oversized padstack.")
            foreach(pad stack->pads
                pads = cons(opaManagedPad(pad) pads))
            foreach(pad pads
                unless(member(nth(2 pad) '(nil "NULL"))
                    box = nth(3 pad)
                    offset = nth(4 pad)
                    ; Include both relative-box conventions conservatively; the
                    ; exact native pad and its offset remain in the scene.
                    bounds = opaManagedUnion(bounds box)
                    bounds = opaManagedUnion(bounds opaWorldBox(box offset 0))))
            top = opaManagedPad(axlDBGetPad(stack "TOP" "REGULAR"))
            opaRequire(!member(nth(2 top) '(nil "NULL")) && member(top pads) && bounds
                "Padstack has no accounted-for regular top pad.")
            rows = cons(list(stack->name bounds opaSortedData(pads)
                list(stack->type stack->usage stack->plating stack->holeType
                     stack->drillDiameter stack->drillSizeWidth stack->drillSizeHeight
                     stack->drillOffset stack->spanLockCount stack->startEnd
                     stack->padSuppresion opaProps(stack))) rows))
        opaSortedData(rows)
    )
)

procedure(opaManagedDefinitions(design padstacks)
    let((rows pins geometry bounds stack position rotation item bodyCount)
        opaRequire(length(design->symdefs) > 0 && length(design->symdefs) <= 256
            "Missing or oversized embedded footprint inventory.")
        foreach(definition design->symdefs
            opaManagedObjectGuard(definition)
            opaManagedName(definition->name)
            opaRequire(definition->type == "PACKAGE" && !assoc(definition->name rows) &&
                length(definition->pins) > 0 && length(definition->pins) <= 256 &&
                length(definition->children) > 0 && length(definition->children) <= 256
                "Only unique, bounded embedded PACKAGE definitions are supported.")
            pins = nil
            geometry = nil
            bounds = nil
            bodyCount = 0
            foreach(child definition->children
                opaRequire(child->parent == definition &&
                    rexMatchp("^PACKAGE GEOMETRY/" child->layer)
                    "Definition contains unowned or non-package geometry.")
                item = opaManagedGeometry(child)
                geometry = cons(item geometry)
                bounds = opaManagedUnion(bounds opaManagedGeometryBounds(item))
                when(child->layer == "PACKAGE GEOMETRY/PLACE_BOUND_TOP"
                    opaRequire(member(child->objType '("shape" "polygon")) && child->fill
                        "Explicit top place bounds must be filled rectangles.")
                    bodyCount = bodyCount + 1))
            opaRequire(bodyCount > 0 "Footprint has no explicit top placement bounds.")
            foreach(pin definition->pins
                opaManagedObjectGuard(pin)
                opaManagedName(pin->number)
                stack = assoc(pin->name padstacks)
                opaRequire(stack && !assoc(pin->number pins) && pin->definition &&
                    pin->definition->name == pin->name && !pin->isMech &&
                    !pin->isMirrored && !pin->isThrough && !pin->isExploded &&
                    !pin->testPoint && !pin->bondpad
                    "Unsupported, duplicate or unresolved physical definition pin.")
                position = opaPoint(pin->xy)
                rotation = opaOrthogonal(pin->rotation)
                bounds = opaManagedUnion(bounds opaWorldBox(nth(1 stack) position rotation))
                pins = cons(list(pin->number pin->name position rotation
                    opaProps(pin) pin->use pin->startEnd) pins))
            opaRequire(bounds "Footprint bounds cannot be established.")
            ; Never use definition->instances: immutable data must survive an
            ; unplaced-to-placed transition without changing its fingerprint.
            rows = cons(list(definition->name bounds opaSortedData(pins)
                opaSortedData(geometry) opaProps(definition) opaBox(definition->bBox)) rows))
        opaSortedData(rows)
    )
)

procedure(opaManagedCompdef(definition)
    let((pins functions functionPins)
        opaManagedObjectGuard(definition)
        opaRequire(definition->objType == "compdef" &&
            length(definition->pins) > 0 && length(definition->pins) <= 256 &&
            length(definition->functions) <= 256 "Unsupported logical definition.")
        foreach(pin definition->pins
            opaManagedObjectGuard(pin)
            opaManagedName(pin->number)
            opaRequire(!assoc(pin->number pins) "Duplicate logical definition pin.")
            pins = cons(list(pin->number pin->use opaProps(pin)) pins))
        foreach(function definition->functions
            opaManagedObjectGuard(function)
            opaRequire(function->objType == "funcdef" && function->parent == definition &&
                length(function->pins) <= 256 "Unsupported logical function definition.")
            functionPins = nil
            foreach(pin function->pins
                opaManagedObjectGuard(pin)
                opaRequire(pin->objType == "funcdefPin" &&
                    member(pin->parent definition->pins) "Unresolved logical function pin.")
                functionPins = cons(list(pin->name pin->parent->number pin->swapCode
                    pin->use opaProps(pin)) functionPins))
            functions = cons(list(function->slot function->type
                opaSortedData(functionPins) opaProps(function)) functions))
        list(definition->deviceType definition->class definition->package
            opaSortedData(pins) opaSortedData(functions) opaProps(definition))
    )
)

procedure(opaManagedFunctions(component)
    let((rows pins definitions definition matches expected seen localPin)
        opaRequire(length(component->functions) <= 256 "Too many logical function instances.")
        definitions = component->compdef->functions
        foreach(function component->functions
            opaManagedObjectGuard(function)
            opaManagedName(function->name)
            matches = setof(item definitions
                item->slot == function->slot && item->type == function->type)
            opaRequire(function->objType == "function" && function->parent == component &&
                length(matches) == 1 && !assoc(function->name rows)
                "Invalid, duplicate or unresolved logical function instance.")
            definition = car(matches)
            opaRequire(length(function->pins) == length(definition->pins)
                "Logical function instance has an incomplete pin map.")
            pins = nil
            foreach(pin function->pins
                opaManagedObjectGuard(pin)
                localPin = pin->pin
                opaRequire(pin->objType == "functionPin" && pin->parent == function &&
                    member(localPin component->pins) && member(pin localPin->functionPins) &&
                    !member(pin seen) && !assoc(pin->name pins)
                    "Function pin has invalid component ownership or reverse association.")
                matches = setof(item definition->pins item->name == pin->name)
                opaRequire(length(matches) == 1 "Function pin definition is ambiguous.")
                expected = car(matches)
                opaRequire(expected->parent->number == localPin->number &&
                    expected->swapCode == pin->swapCode && expected->use == pin->use
                    "Function pin mapping differs from its protected logical definition.")
                pins = cons(list(pin->name localPin->number pin->use pin->swapCode
                    opaProps(pin) axlDBIsReadOnly(pin)) pins)
                seen = cons(pin seen))
            rows = cons(list(function->name function->slot function->type
                opaSortedData(pins) opaProps(function) axlDBIsReadOnly(function)) rows))
        foreach(pin component->pins
            foreach(functionPin pin->functionPins
                opaRequire(member(functionPin seen) && functionPin->pin == pin
                    "A logical pin references an unaccounted function pin.")))
        opaSortedData(rows)
    )
)

procedure(opaManagedComponent(component definitions padstacks)
    let((definition symbol placed origin angle fixed bounds intrinsic geometry pins localPins
         nativePins pinDef netName padstack physicalPads expectedPads symbolState localGeometry
         item pinState)
        opaManagedObjectGuard(component)
        opaManagedName(component->name)
        opaRequire(strlen(component->name) <= 31 &&
            rexMatchp("^[A-Za-z]" component->name) &&
            !rexMatchp("[^A-Za-z0-9_]" component->name)
            "Refdes is outside the exact-placement protocol.")
        definition = assoc(component->package definitions)
        opaRequire(definition && component->compdef &&
            length(component->pins) == length(nth(2 definition))
            "Missing embedded footprint or logical-to-physical pin mismatch.")
        symbol = component->symbol
        placed = if(symbol then t else nil)
        origin = '(0 0)
        angle = 0
        fixed = if(axlDBIsFixed(component) then t else nil)
        intrinsic = list(list("logical" component->package component->deviceType component->class
            opaManagedCompdef(component->compdef) opaProps(component)
            axlDBIsReadOnly(component))
            list("functions" opaManagedFunctions(component)))
        when(placed
            opaManagedObjectGuard(symbol)
            opaRequire(symbol->objType == "symbol" && symbol->component == component &&
                symbol->refdes == component->name && symbol->name == component->package &&
                symbol->definition && symbol->definition->name == component->package &&
                !symbol->isMirrored && !symbol->embedded && !symbol->embeddedLayer &&
                !symbol->zone && !symbol->etchChildren &&
                length(symbol->children) == length(nth(3 definition)) &&
                length(symbol->pins) == length(component->pins)
                "Unsupported physical symbol, instance geometry, side or attached copper.")
            origin = opaPoint(symbol->xy)
            angle = opaOrthogonal(symbol->rotation)
            fixed = if(fixed || axlDBIsFixed(symbol) then t else nil)
            bounds = opaWorldBox(nth(1 definition) origin angle)
            foreach(child symbol->children
                opaRequire(child->parent == symbol "Unowned symbol geometry.")
                item = opaManagedGeometry(child)
                geometry = cons(item geometry)
                localGeometry = cons(list(opaManagedLocalGeometry(item origin angle)
                    axlDBIsReadOnly(child) if(axlDBIsFixed(child) then t else nil)) localGeometry))
            opaRequire(equal(
                opaSortedData(foreach(mapcar item geometry opaManagedGeometryShape(item)))
                opaSortedData(foreach(mapcar item nth(3 definition)
                    opaManagedGeometryPose(item origin angle))))
                "Actual instance geometry is not the embedded definition at its pose.")
            symbolState = list(list("symbol" opaProps(symbol) axlDBIsReadOnly(symbol))
                list("geometry" opaSortedData(localGeometry)))
            nativePins = symbol->pins)
        foreach(pin component->pins
            opaManagedObjectGuard(pin)
            opaRequire(!assoc(pin->number localPins) "Duplicate logical pin.")
            pinDef = assoc(pin->number nth(2 definition))
            opaRequire(pinDef "Logical pin has no physical definition.")
            netName = if(pin->net then opaManagedName(pin->net->name) else "")
            ; A physical pin is fixed against independent motion within its
            ; package. The symbol query already checks fixed children and test
            ; points; do not turn every ordinary package into a fixed component.
            localPins = cons(list(pin->number netName nth(2 pinDef)) localPins)
            intrinsic = cons(list("pin" pin->number netName pin->use opaProps(pin)
                axlDBIsReadOnly(pin)) intrinsic)
            when(placed
                opaRequire(member(pin nativePins) && pin->component == component &&
                    pin->parent == symbol && pin->name == nth(1 pinDef) &&
                    pin->definition && pin->definition->name == nth(1 pinDef) &&
                    !pin->isExploded && !pin->isThrough && !pin->isMech &&
                    !pin->isMirrored && !pin->testPoint && !pin->bondpad &&
                    opaOrthogonal(pin->rotation) == mod(angle + nth(3 pinDef) 360) &&
                    equal(opaPoint(pin->xy) opaWorld(nth(2 pinDef) origin angle)) &&
                    equal(pin->startEnd nth(6 pinDef))
                    "Native physical pin is not the intended definition/pose.")
                padstack = assoc(nth(1 pinDef) padstacks)
                expectedPads = nth(2 padstack)
                physicalPads = opaSortedData(foreach(mapcar pad pin->pads opaManagedPad(pad)))
                opaRequire(equal(physicalPads expectedPads) &&
                    member(opaManagedPad(axlDBGetPad(pin "TOP" "REGULAR")) expectedPads)
                    "Native pin pad geometry differs from its protected padstack.")
                pins = cons(list(pin->number opaPoint(pin->xy) pin->rotation
                    physicalPads opaProps(pin) axlDBIsReadOnly(pin)
                    if(axlDBIsFixed(pin) then t else nil)) pins)
                pinState = cons(list(pin->number axlDBIsReadOnly(pin)
                    if(axlDBIsFixed(pin) then t else nil)) pinState)))
        opaRequire(length(localPins) == length(nth(2 definition))
            "Incomplete logical-to-physical pin mapping.")
        ; 0..9 preserve the fixture frame conventions; 10..13 are managed data.
        list(component->name origin angle nil fixed placed bounds
            opaSortedData(intrinsic) opaSortedData(geometry) opaSortedData(pins)
            component->package nth(1 definition) opaSortedData(localPins)
            opaSortedData(cons(list("pins" opaSortedData(pinState)) symbolState)))
    )
)

procedure(opaManagedStackup(layers)
    let((entries rows conductors seen)
        opaRequire(equal(axlXSectionGet(nil 'stackups) '("PRIMARY"))
            "Multiple or non-primary stackups are unsupported.")
        entries = axlXSectionGet(nil 'all)
        opaRequire(entries && length(entries) <= 128 &&
            length(entries) == axlXSectionGet(nil 'count)
            "Complete cross-section inventory could not be read.")
        foreach(entry entries
            opaRequire(entry->objType == "xsection" && !member(entry->position seen) &&
                !entry->negativeArtwork &&
                (member(entry->layerType '("SURFACE" "CONDUCTOR" "DIELECTRIC" "MASK")) ||
                    (!entry->layerType && entry->layerFunction == "SURFACE" && !entry->conductor)) &&
                member(entry->embedded '(nil "NOT_EMBEDDED")) &&
                member(entry->embeddedAttach '(nil "" "DIRECT_ATTACH" "INDIRECT_ATTACH")) &&
                member(entry->freqDepFile '(nil ""))
                "Unsupported cross-section polarity, embedding, type or external model.")
            seen = cons(entry->position seen)
            when(entry->conductor
                opaRequire(entry->layerType == "CONDUCTOR" && member(entry->name layers)
                    "Cross-section conductor inventory disagrees with the native layers.")
                conductors = cons(entry->name conductors))
            ; These values can have finer precision than placement coordinates.
            rows = cons(list(entry->position entry->name entry->layerType entry->layerFunction
                entry->conductor entry->constraint entry->layerId entry->material entry->maskLayer
                entry->mfg entry->negativeArtwork entry->thickness entry->tolMinus entry->tolPlus
                entry->unusedPin entry->unusedVia entry->embedded entry->embeddedAttach
                entry->diffCouplingType entry->diffSpacing entry->conductivity
                entry->dielectricConst entry->etchFactor entry->freqDepFile entry->lossTangent
                entry->shield entry->width entry->siIgnore opaProps(entry)) rows))
        opaRequire(equal(opaSort(conductors) opaSort(layers))
            "Missing or duplicate cross-section conductor.")
        list(axlXSectionGet(nil 'thickness) axlXSectionGet(nil 'locked) opaSortedData(rows))
    )
)

procedure(opaManagedConstraints()
    let((rows layers layerInfo assembly options seen spacing physical sameNet)
        layers = axlSubclassRoute()
        opaRequire(length(layers) >= 2 && length(layers) <= 32 &&
            member("TOP" layers) && member("BOTTOM" layers)
            "Missing or oversized conductor stackup.")
        foreach(domain '(spacing physical sameNet)
            opaRequire(equal(axlCnsList(domain) '("DEFAULT"))
                "Nondefault constraint sets require a larger constraint model."))
        opaRequire(!axlCnsList('electrical) &&
            !axlCnsClassTableFind('netclass) && !axlCnsClassTableFind('component) &&
            !axlCnsClassTableFind('wireProf) &&
            !axlCNSDFAMode('table) && axlCNSDFAMode('mode) == 'off
            "Electrical, class/region, assembly or DFA constraint topology is unsupported.")
        assembly = axlCNSAssemblyModeGet('all)
        foreach(mode assembly
            opaRequire(cadr(mode) == 'off "Enabled IC assembly checks are unsupported."))
        options = foreach(mapcar option axlCNSOptions(nil) list(option axlCNSOptions(option)))
        rows = list(list("stackup" opaManagedStackup(layers))
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
            opaManagedName(layer)
            opaRequire(!member(layer seen) "Duplicate conductor layer.")
            seen = cons(layer seen)
            layerInfo = axlLayerGet(strcat("ETCH/" layer))
            opaRequire(layerInfo && layerInfo->isEtch && layerInfo->type == "CONDUCTOR" &&
                layerInfo->drcPhotoType == "positive"
                "Only positive conductor layers are supported.")
            spacing = axlCNSGetSpacing("" layer nil)
            physical = axlCNSGetPhysical("" layer nil)
            sameNet = axlCNSGetSameNet("" layer nil)
            opaRequire(spacing && physical && sameNet
                "Complete per-layer constraint values could not be read.")
            rows = cons(list("layer" layer layerInfo->type layerInfo->drcPhotoType
                opaPairs(spacing) opaPairs(physical) opaPairs(sameNet)) rows))
        opaSortedData(rows)
    )
)

procedure(opaManagedPropertyDictionary()
    let((names rows entry)
        names = append(copy(axlDBGetPropDict(nil)) copy(axlDBGetPropDict('invisible)))
        opaRequire(length(names) <= 8192 "Oversized property dictionary.")
        foreach(name opaSort(names)
            unless(assoc(name rows)
                entry = axlDBGetPropDictEntry(name)
                opaRequire(entry "Property dictionary entry disappeared.")
                ; useCount changes when a symbol is instantiated, not its schema.
                rows = cons(list(name entry->dataType entry->units entry->range
                    entry->objects entry->write entry->readOnly) rows)))
        opaSortedData(rows)
    )
)

procedure(opaManagedNetData(design components)
    let((rows nets branches rats logical identities pins data)
        foreach(net design->nets
            opaManagedObjectGuard(net)
            opaManagedName(net->name)
            opaRequire(!assoc(net->name nets) && !net->pinpair && !net->ratT &&
                !net->scheduleLocked && !net->isBundled
                "Duplicate net or unsupported pin-pair/locked scheduling topology.")
            logical = nil
            foreach(data components
                foreach(pin nth(12 data)
                    when(cadr(pin) == net->name
                        logical = cons(list(car(data) car(pin)) logical))))
            nets = cons(list(net->name opaProps(net) opaSortedData(logical)
                net->ratsnestOn) nets)
            branches = nil
            foreach(branch net->branches
                opaManagedObjectGuard(branch)
                opaRequire(!opaProps(branch) "Branch-level properties are unsupported.")
                identities = nil
                foreach(pin branch->children
                    opaRequire(pin->objType == "pin" && pin->component &&
                        pin->net == net && assoc(pin->component->name components) &&
                        member(pin pin->component->pins) &&
                        member(list(pin->component->name pin->number) logical)
                        "Routed copper, vias, shapes or unowned branch objects are unsupported.")
                    identities = cons(list(pin->component->name pin->number) identities))
                branches = cons(opaSortedData(identities) branches))
            rats = nil
            foreach(rat net->ratsnest
                opaManagedObjectGuard(rat)
                opaRequire(rat->objType == "ratsnest" && !rat->userDefined &&
                    member(rat->ratsPlaced '(nil t)) && !opaProps(rat) sprintf(nil
                        "Unsupported ratsnest: type=%L userDefined=%L ratsPlaced=%L properties=%L"
                        rat->objType rat->userDefined rat->ratsPlaced opaProps(rat)))
                pins = nil
                foreach(pin rat->pins
                    opaRequire(pin->objType == "pin" && pin->component && pin->net == net &&
                        assoc(pin->component->name components) &&
                        member(pin pin->component->pins) &&
                        member(list(pin->component->name pin->number) logical)
                        "Unmodeled ratsnest endpoint.")
                    pins = cons(list(pin->component->name pin->number) pins))
                opaRequire(length(pins) == 2 "Ratsnest does not have two logical pins.")
                rats = cons(list(opaSortedData(pins) rat->pinsConnected rat->bus
                    rat->pwrAndGnd rat->ratsPlaced) rats))
            rows = cons(list(net->name opaSortedData(branches) opaSortedData(rats)
                net->nBranches net->unconnected net->unplaced) rows))
        foreach(data components
            foreach(pin nth(12 data)
                opaRequire(cadr(pin) == "" || assoc(cadr(pin) nets)
                    "Logical pin net is absent from the native net inventory.")))
        list(opaSortedData(nets) opaSortedData(rows))
    )
)

procedure(opaManagedDrcs(design)
    let((rows affected)
        opaRequire(!design->waived "Waived DRC identities are unsupported.")
        foreach(marker design->drcs
            opaManagedObjectGuard(marker)
            opaRequire(marker->objType == "drc" && !marker->waived "Unsupported native DRC.")
            affected = foreach(mapcar object marker->violations opaObjectIdentity(object))
            rows = cons(opaStable(list(marker->name marker->type marker->source
                opaPoint(marker->xy) marker->actual marker->expected marker->fixed
                opaPairs(affected) opaProps(marker))) rows))
        opaSort(rows)
    )
)

procedure(opaManagedAllFigures(design boardShapes)
    let((saved enabled buttons allowed selected)
        saved = axlGetSelSet()
        enabled = axlGetFindFilter(nil)
        buttons = axlGetFindFilter(t)
        allowed = append(copy(boardShapes) append(copy(design->symbols) copy(design->drcs)))
        foreach(component design->components
            when(component->symbol
                allowed = append(allowed copy(component->symbol->children))
                allowed = append(allowed copy(component->pins))
                foreach(child component->symbol->children
                    unless(child->objType == "line"
                        allowed = append(allowed copy(child->segments))))))
        foreach(shape boardShapes allowed = append(allowed copy(shape->segments)))
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
                         object->layer == "DRAWING FORMAT/DRAWING_ORIGIN" && object->readOnly)
                        "Unaccounted free geometry, routing, text, symbol or figure.")))
            progn(
                axlClearSelSet()
                axlSetFindFilter(?enabled enabled ?onButtons buttons)
                when(saved axlAddSelectObject(saved))))
        t
    )
)

procedure(opaManagedCanonical(rows)
    let((atoms table nodes dictionary previous prefix index entry tree result)
        rows = opaSortedData(rows)
        atoms = opaSort(opaCollectAtoms(rows nil))
        table = makeTable('opaManagedAtoms nil)
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
            dictionary = strcat(dictionary opaCountCode(prefix) opaCountCode(strlen(entry)) entry)
            previous = atom)
        nodes = makeTable('opaManagedLists nil)
        nodes["next"] = 0
        tree = opaEncodeTree(rows table nodes)
        result = strcat("OPA-BOARD-1;" sprintf(nil "%d;" length(atoms)) dictionary ";" tree)
        opaRequire(strlen(result) <= 524288 "Complete managed scene exceeds 524288 characters.")
        result
    )
)

procedure(opaManagedSceneRecords(scene)
    let((records count index offset size part)
        count = fix((strlen(scene) + 8191) / 8192.0)
        opaRequire(count >= 1 && count <= 128 "Invalid managed scene chunk count.")
        records = list(list("scene" sprintf(nil "OPA-BOARD-1;chunks=%d" count)))
        for(index 0 count - 1
            offset = index * 8192
            size = min(8192 strlen(scene) - offset)
            part = substring(scene offset + 1 size)
            opaField(part)
            records = append(records list(list("scene-part" sprintf(nil "%d" index) part))))
        records
    )
)

procedure(opaManagedBoxRecord(tag box @optional refdes)
    append(if(refdes then list(tag refdes) else list(tag))
        list(opaCoordinate(caar(box)) opaCoordinate(cadar(box))
             opaCoordinate(caadr(box)) opaCoordinate(cadadr(box))))
)

procedure(opaManagedRecordBudget(records)
    let((total)
        opaRequire(length(records) <= 4088 "Managed inventory exceeds the wire record budget.")
        total = 0
        foreach(row records
            opaRequire(length(row) > 0 && length(row) <= 16 "Invalid managed wire record.")
            total = total + strlen(buildString(mapcar('opaCsv row) ",")) + 1)
        opaRequire(total <= 1032192 "Managed inventory leaves insufficient receipt space.")
        t
    )
)

procedure(opaManagedBoundaryPoly(object)
    let((path polygons)
        opaRequire(!object->voids && !object->isHole
            "Boundary holes must not be discarded by path conversion.")
        path = axlDB2Path(object)
        opaRequire(path "Native boundary could not be converted to a closed path.")
        polygons = axlPolyFromDB(path)
        opaRequire(polygons && length(polygons) == 1 && car(polygons) &&
            !car(polygons)->isHole && !car(polygons)->holes &&
            abs(car(polygons)->area) > 0.0
            "Native boundary is not one valid simple closed interior.")
        car(polygons)
    )
)

procedure(opaManagedBoundary(object)
    let((edges endpoints center sx sy ex ey radius data box fill)
        opaManagedObjectGuard(object)
        opaRequire(member(object->objType '("shape" "polygon")) &&
            member(object->layer '("BOARD GEOMETRY/DESIGN_OUTLINE"
                "BOARD GEOMETRY/OUTLINE" "PACKAGE KEEPIN/ALL")) &&
            object->nSegs == length(object->segments) &&
            length(object->segments) >= 2 && length(object->segments) <= 512 &&
            !object->voids && !object->net && !object->branch && !object->symbolEtch &&
            !object->shapeBoundary && !object->shapeIsBoundary && !object->shapeAuto &&
            !object->cavity && !object->isHole && !object->fillet &&
            !object->taper && !object->dynamicGroup
            "Outline/keepin must be one static simple closed contour without holes.")
        box = opaManagedBox(object->bBox)
        fill = if(object->objType == "polygon" then nil else object->fill)
        opaRequire(member(fill '(nil t)) "Hatched board boundaries are unsupported.")
        foreach(segment object->segments
            opaManagedObjectGuard(segment)
            opaRequire(member(segment->objType '("line" "arc")) &&
                segment->width == 0.0 && !segment->isEtch &&
                segment->parent == object
                "Boundary edges must be owned zero-width lines or circular arcs.")
            endpoints = foreach(mapcar point segment->startEnd opaPoint(point))
            opaRequire(length(endpoints) == 2 && !equal(car(endpoints) cadr(endpoints))
                "Boundary edge is degenerate or a full circle.")
            if(segment->objType == "arc" then
                opaRequire(!segment->isCircle && member(segment->isClockwise '(nil t))
                    "Unsupported full circle or ambiguous arc direction.")
                center = opaPoint(segment->xy)
                sx = 1.0 * (caar(endpoints) - car(center))
                sy = 1.0 * (cadar(endpoints) - cadr(center))
                ex = 1.0 * (caadr(endpoints) - car(center))
                ey = 1.0 * (cadadr(endpoints) - cadr(center))
                radius = max(sqrt(sx * sx + sy * sy) sqrt(ex * ex + ey * ey))
                edges = cons(list("arc" car(endpoints) cadr(endpoints) center
                    segment->isClockwise radius
                    list(segment->font segment->isCircle opaProps(segment))) edges)
            else
                edges = cons(list("line" car(endpoints) cadr(endpoints) nil nil nil
                    list(segment->font nil opaProps(segment))) edges)))
        opaManagedBoundaryPoly(object)
        data = opaManagedContourFromEdges(edges)
        foreach(point cadr(data)
            opaRequire(car(point) >= caar(box) - caddr(data) &&
                car(point) <= caadr(box) + caddr(data) &&
                cadr(point) >= cadar(box) - caddr(data) &&
                cadr(point) <= cadadr(box) + caddr(data)
                "Boundary sampling disagrees with native extents."))
        list(object->objType object->layer fill box car(data) opaProps(object)
            cadr(data) caddr(data))
    )
)

procedure(opaManagedArcPoints(edge)
    let((start finish center clockwise radius sx sy ex ey startRadius endRadius
         dot cross theta divisions points angle x y count)
        start = nth(1 edge)
        finish = nth(2 edge)
        center = nth(3 edge)
        clockwise = nth(4 edge)
        radius = nth(5 edge)
        opaRequire(numberp(radius) && radius > 0.0 && radius <= 200000000.0 &&
            !equal(start finish) "Degenerate or full-circle boundary arc is unsupported.")
        sx = 1.0 * (car(start) - car(center))
        sy = 1.0 * (cadr(start) - cadr(center))
        ex = 1.0 * (car(finish) - car(center))
        ey = 1.0 * (cadr(finish) - cadr(center))
        startRadius = sqrt(sx * sx + sy * sy)
        endRadius = sqrt(ex * ex + ey * ey)
        opaRequire(startRadius > 0.0 && endRadius > 0.0 &&
            abs(startRadius - radius) <= 1.0 && abs(endRadius - radius) <= 1.0
            "Arc endpoints disagree with the native radius.")
        dot = sx * ex + sy * ey
        cross = sx * ey - sy * ex
        ; atan2 avoids acos cancellation for very short, large-radius arcs.
        theta = abs(atan2(cross dot))
        when((clockwise && cross > 0.0) || (!clockwise && cross < 0.0)
            theta = 6.283185307179586 - theta)
        opaRequire(theta > 0.0 && theta < 6.283185307179586 sprintf(nil
            "Ambiguous boundary arc sweep: start=%L end=%L center=%L clockwise=%L angle=%L"
            start finish center clockwise theta))
        ; r*(sweep/n)^2/8 bounds sagitta. Reserve 8 DBUs for sagitta
        ; and 4 more for endpoint tolerance, DBU rounding and numeric error.
        divisions = max(1 fix(sqrt(radius * theta * theta / 64.0)) + 1
            fix(theta / 1.5707963267948966) + 1)
        opaRequire(divisions <= 512 "Boundary arc exceeds the vertex budget.")
        opaRequire(radius * theta * theta / (8.0 * divisions * divisions) <= 8.0
            "Boundary arc subdivision did not establish the error bound.")
        points = list(start)
        for(index 1 divisions - 1
            angle = theta * index / divisions
            when(clockwise angle = -angle)
            x = car(center) + sx * cos(angle) - sy * sin(angle)
            y = cadr(center) + sx * sin(angle) + sy * cos(angle)
            points = append(points list(list(round(x) round(y)))))
        points
    )
)

procedure(opaManagedContourFromEdges(edges)
    let((remaining first current ordered matches edge reversed vertices points margin)
        opaRequire(length(edges) >= 2 && length(edges) <= 512
            "Boundary needs 2-512 native edges.")
        remaining = opaSortedData(edges)
        first = nth(1 car(remaining))
        current = first
        while(remaining
            matches = setof(item remaining
                equal(nth(1 item) current) || equal(nth(2 item) current))
            opaRequire(length(matches) == if(ordered then 1 else 2)
                "Boundary has gaps, branches or multiple disconnected contours.")
            edge = car(matches)
            when(!equal(nth(1 edge) current)
                edge = list(car(edge) nth(2 edge) nth(1 edge) nth(3 edge)
                    if(car(edge) == "arc" then !nth(4 edge) else nil)
                    nth(5 edge) nth(6 edge)))
            remaining = remove(car(matches) remaining)
            ordered = append(ordered list(edge))
            current = nth(2 edge)
            when(equal(current first)
                opaRequire(!remaining "Boundary closes before accounting for all edges.")))
        opaRequire(equal(current first) "Boundary is not closed.")
        margin = 0
        foreach(edge ordered
            if(car(edge) == "arc" then
                points = opaManagedArcPoints(edge)
                margin = 12
            else
                opaRequire(car(edge) == "line" "Unknown boundary edge kind.")
                points = list(nth(1 edge)))
            opaRequire(length(vertices) + length(points) <= 512
                "Complete boundary exceeds 512 vertices; no truncation is permitted.")
            vertices = append(vertices points))
        opaManagedContourValidate(vertices)
        list(ordered vertices margin)
    )
)

procedure(opaManagedContourCross(a b c)
    ; Coordinates are integral DBUs; bounded spans keep these products exact
    ; in binary64 without depending on SKILL fixnum multiplication overflow.
    (1.0 * (car(b) - car(a))) * (cadr(c) - cadr(a)) -
        (1.0 * (cadr(b) - cadr(a))) * (car(c) - car(a))
)

procedure(opaManagedContourOnSegment(a b point)
    opaManagedContourCross(a b point) == 0.0 &&
        car(point) >= min(car(a) car(b)) && car(point) <= max(car(a) car(b)) &&
        cadr(point) >= min(cadr(a) cadr(b)) && cadr(point) <= max(cadr(a) cadr(b))
)

procedure(opaManagedContourIntersects(a b c d)
    let((ac ad ca cb)
        ac = opaManagedContourCross(a b c)
        ad = opaManagedContourCross(a b d)
        ca = opaManagedContourCross(c d a)
        cb = opaManagedContourCross(c d b)
        ((ac < 0.0 && ad > 0.0 || ac > 0.0 && ad < 0.0) &&
         (ca < 0.0 && cb > 0.0 || ca > 0.0 && cb < 0.0)) ||
        opaManagedContourOnSegment(a b c) || opaManagedContourOnSegment(a b d) ||
        opaManagedContourOnSegment(c d a) || opaManagedContourOnSegment(c d b)
    )
)

procedure(opaManagedContourValidate(vertices)
    let((count a b c d area xs ys)
        count = length(vertices)
        opaRequire(count >= 3 && count <= 512 "Boundary needs 3-512 vertices.")
        xs = foreach(mapcar point vertices car(point))
        ys = foreach(mapcar point vertices cadr(point))
        opaRequire(apply('max xs) - apply('min xs) <= 67108863 &&
            apply('max ys) - apply('min ys) <= 67108863
            "Boundary span exceeds exact native containment arithmetic.")
        area = 0.0
        for(i 0 count - 1
            a = nth(i vertices)
            b = nth(mod(i + 1 count) vertices)
            c = nth(mod(i + 2 count) vertices)
            opaRequire(!equal(a b) "Boundary has a zero-length edge.")
            opaRequire(opaManagedContourCross(a b c) != 0.0 ||
                (1.0 * (car(b) - car(a))) * (car(c) - car(b)) +
                (1.0 * (cadr(b) - cadr(a))) * (cadr(c) - cadr(b)) > 0.0
                "Boundary doubles back along an adjacent edge.")
            area = area + opaManagedContourCross(car(vertices) a b)
            for(j i + 1 count - 1
                unless(j == i + 1 || (i == 0 && j == count - 1)
                    c = nth(j vertices)
                    d = nth(mod(j + 1 count) vertices)
                    opaRequire(!opaManagedContourIntersects(a b c d)
                        "Boundary is self-intersecting or self-touching."))))
        opaRequire(abs(area) >= 1.0 "Boundary area is degenerate.")
        vertices
    )
)

procedure(opaManagedContourPoint(vertices point)
    let((inside touching a b cross)
        for(i 0 length(vertices) - 1
            a = nth(i vertices)
            b = nth(mod(i + 1 length(vertices)) vertices)
            cross = opaManagedContourCross(a b point)
            when(opaManagedContourOnSegment(a b point) touching = t)
            when((cadr(a) > cadr(point)) != (cadr(b) > cadr(point))
                when((cross > 0.0) == (cadr(b) > cadr(a)) inside = !inside)))
        inside || touching
    )
)

procedure(opaManagedContourCutsBox(a b box)
    let((corners sides)
        when(max(car(a) car(b)) > caar(box) && min(car(a) car(b)) < caadr(box) &&
             max(cadr(a) cadr(b)) > cadar(box) && min(cadr(a) cadr(b)) < cadadr(box)
            corners = list(car(box) cadr(box) list(caar(box) cadadr(box))
                list(caadr(box) cadar(box)))
            sides = foreach(mapcar point corners opaManagedContourCross(a b point))
            apply('min sides) < 0.0 && apply('max sides) > 0.0)
    )
)

procedure(opaManagedContourContains(box geometry)
    let((vertices margin expanded corners inside)
        vertices = nth(6 geometry)
        margin = nth(7 geometry)
        expanded = list(list(caar(box) - margin cadar(box) - margin)
            list(caadr(box) + margin cadadr(box) + margin))
        inside = opaManagedInside(expanded nth(3 geometry))
        when(inside
            corners = list(car(expanded) cadr(expanded)
                list(caar(expanded) cadadr(expanded)) list(caadr(expanded) cadar(expanded)))
            foreach(point corners
                unless(opaManagedContourPoint(vertices point) inside = nil))
            for(i 0 length(vertices) - 1
                when(opaManagedContourCutsBox(nth(i vertices)
                    nth(mod(i + 1 length(vertices)) vertices) expanded) inside = nil)))
        inside
    )
)

procedure(opaManagedPolygonContains(box polygon)
    let((path rectangles intersection xmin ymin xmax ymax)
        xmin = caar(box) / 10000.0
        ymin = cadar(box) / 10000.0
        xmax = caadr(box) / 10000.0
        ymax = cadadr(box) / 10000.0
        path = axlPathStart(list(list(xmin ymin) list(xmax ymin)
            list(xmax ymax) list(xmin ymax) list(xmin ymin)) 0.0)
        opaRequire(path "Cannot construct an in-memory footprint boundary.")
        rectangles = axlPolyFromDB(path)
        opaRequire(rectangles && length(rectangles) == 1 && car(rectangles)
            "Cannot convert the complete footprint rectangle to native polygon data.")
        intersection = axlPolyOperation(car(rectangles) polygon 'AND)
        ; Bare nil is an operation failure, whereas (nil) is an empty result.
        opaRequire(intersection "Native boundary intersection failed; containment is unknown.")
        length(intersection) == 1 && car(intersection) &&
            !car(intersection)->holes && !car(intersection)->isHole &&
            equal(car(rectangles) car(intersection))
    )
)

procedure(opaManagedContourRecords(role geometry)
    let((rows vertices index)
        vertices = nth(6 geometry)
        rows = list(list("boundary" role sprintf(nil "%d" length(vertices))
            opaCoordinate(nth(7 geometry)) sprintf(nil "%d" length(nth(4 geometry)))))
        index = 0
        foreach(point vertices
            rows = append(rows list(list("boundary-point" role sprintf(nil "%d" index)
                opaCoordinate(car(point)) opaCoordinate(cadr(point)))))
            index = index + 1)
        index = 0
        foreach(edge nth(4 geometry)
            rows = append(rows list(list("boundary-source" role sprintf(nil "%d" index) opaStable(edge))))
            index = index + 1)
        rows
    )
)

procedure(opaManagedReadFrame()
    let((design units padstacks definitions compdefs common components records shapes boardShapes
         outline keepin keepouts legacy geometry placedCount shapeCount data nets drcs scene
         packageShapes)
        opaBoardGuard()
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        units = axlDBGetDesignUnits()
        opaRequire(design && equal(units '("millimeters" 4 10000))
            "Managed boards require millimeters/4/10000.")
        opaManagedObjectGuard(design)
        foreach(check list(
            list("groups" !design->groups) list("module" !design->module)
            list("zone" !design->zone) list("region" !design->region)
            list("netclass" !design->netclass) list("netgroup" !design->netgroup)
            list("netGroup" !design->netGroup) list("bus" !design->bus)
            list("diffpair" !design->diffpair) list("matchgroup" !design->matchgroup)
            list("ecsets" !design->ecsets) list("text" !design->text)
            list("pins" !design->pins) list("keepinRoute" !design->keepinRoute)
            list("koGroup" !design->koGroup) list("lonely branches" !axlDBGetLonelyBranches()))
            opaRequire(cadr(check) strcat("Unsupported managed-board feature: " car(check))))
        opaRequire(length(design->components) >= 1 && length(design->components) <= 256 &&
            length(design->compdefs) >= 1 && length(design->compdefs) <= 256 &&
            length(design->nets) <= 4096
            "Managed placement needs a bounded nonempty imported logical inventory.")
        foreach(xnet design->xnet
            opaRequire(xnet->objType == "net" && member(xnet design->nets)
                "Extended net topology is unsupported."))
        padstacks = opaManagedPadstacks(design)
        definitions = opaManagedDefinitions(design padstacks)
        compdefs = opaSortedData(foreach(mapcar definition design->compdefs
            opaManagedCompdef(definition)))
        common = list(list("attachments" opaManagedAttachments())
            list("padstacks" padstacks) list("definitions" definitions)
            list("compdefs" compdefs) list("rules" opaManagedConstraints())
            list("property-dictionary" opaManagedPropertyDictionary())
            list("board" opaBoardPath units axlVersion('fullVersion) opaProps(design)
                opaManagedBox(axlGetParam("paramDesign")->bBox)))
        placedCount = 0
        shapeCount = 0
        foreach(component design->components
            opaRequire(member(component->compdef design->compdefs)
                "Component has an unaccounted logical definition.")
            data = opaManagedComponent(component definitions padstacks)
            opaRequire(!assoc(car(data) components) "Duplicate native reference designator.")
            components = cons(data components)
            when(nth(5 data)
                opaRequire(member(component->symbol design->symbols)
                    "Logical symbol is absent from the physical inventory.")
                placedCount = placedCount + 1
                foreach(child component->symbol->children
                    when(member(child->objType '("shape" "polygon"))
                        packageShapes = cons(child packageShapes)
                        shapeCount = shapeCount + 1))))
        opaRequire(length(design->symbols) == placedCount
            "Unowned mechanical or non-logical physical symbols are unsupported.")
        shapes = axlDBGetShapes(nil)
        foreach(shape shapes
            if(shape->parent && shape->parent->objType == "symbol" then
                opaRequire(member(shape packageShapes) "Unaccounted symbol-owned shape.")
            else
                opaRequire(!shape->parent || shape->parent == design
                    "Unaccounted copper or nested shape.")
                opaRequire(member(shape->layer '("BOARD GEOMETRY/DESIGN_OUTLINE"
                    "BOARD GEOMETRY/OUTLINE" "PACKAGE KEEPIN/ALL" "PACKAGE KEEPOUT/TOP"))
                    "Unsupported board-level shape layer.")
                geometry = if(shape->layer == "PACKAGE KEEPOUT/TOP"
                    then opaManagedGeometry(shape) else opaManagedBoundary(shape))
                opaManagedBox(shape->bBox)
                boardShapes = cons(shape boardShapes)
                cond(
                    (shape->layer == "BOARD GEOMETRY/DESIGN_OUTLINE"
                        opaRequire(!outline && shape == design->designOutline
                            "Missing, duplicate or ambiguous native outline.")
                        outline = nth(3 geometry)
                        common = cons(list("outline" outline geometry) common))
                    (shape->layer == "BOARD GEOMETRY/OUTLINE"
                        opaRequire(!legacy "Duplicate legacy outline.")
                        legacy = nth(3 geometry)
                        common = cons(list("legacy-outline" legacy geometry) common))
                    (shape->layer == "PACKAGE KEEPIN/ALL"
                        opaRequire(!keepin && shape == design->keepinPlace
                            "Missing, duplicate or ambiguous native keepin.")
                        keepin = nth(3 geometry)
                        common = cons(list("keepin" keepin geometry) common))
                    (shape->layer == "PACKAGE KEEPOUT/TOP"
                        opaRequire(shape->fill "Package keepouts must be filled rectangles.")
                        keepouts = cons(nth(3 geometry) keepouts)
                        common = cons(list("keepout" nth(3 geometry) geometry) common)))))
        opaRequire(outline && keepin &&
            (!legacy || equal(legacy outline)) && length(keepouts) <= 256 &&
            length(shapes) == shapeCount + length(boardShapes)
            "Outline, keepin, keepouts or native shape inventory are incomplete.")
        opaManagedAllFigures(design boardShapes)
        components = sort(components lambda((a b) alphalessp(car(a) car(b))))
        nets = opaManagedNetData(design components)
        ; Slot 14 carries shared derived-net data. It is not immutable common
        ; data: placement can change branches/rats only on the target's nets.
        components = foreach(mapcar data components append(data list(cadr(nets))))
        common = opaSortedData(cons(list("nets" car(nets)) common))
        drcs = opaManagedDrcs(design)
        scene = opaManagedCanonical(list(list("common" common) list("components" components)
            list("derived-connectivity" cadr(nets)) list("drc" design->drcState drcs)))
        records = list(list("board" opaBoardPath) list("model" "managed-board-v1")
            list("units" car(units) sprintf(nil "%d" cadr(units)) sprintf(nil "%d" caddr(units)))
            list("version" axlVersion('fullVersion))
            opaManagedBoxRecord("outline" outline) opaManagedBoxRecord("keepin" keepin)
            list("boundary-model" "polygon-v1"))
        records = append(records opaManagedContourRecords("outline" caddr(assoc("outline" common))))
        records = append(records opaManagedContourRecords("keepin" caddr(assoc("keepin" common))))
        foreach(box opaSortedData(keepouts)
            records = append(records list(opaManagedBoxRecord("keepout" box))))
        foreach(layer axlSubclassRoute()
            records = append(records list(list("layer" layer))))
        foreach(data components
            records = append(records list(list("component" car(data) nth(10 data)
                opaCoordinate(caadr(data)) opaCoordinate(cadadr(data))
                sprintf(nil "%d" nth(2 data)) opaFlag(nth(3 data))
                opaFlag(nth(4 data)) opaFlag(nth(5 data)))
                opaManagedBoxRecord("bounds" nth(11 data) car(data))))
            foreach(pin nth(12 data)
                records = append(records list(list("pin" car(data) car(pin) cadr(pin)
                    opaCoordinate(car(nth(2 pin))) opaCoordinate(cadr(nth(2 pin))))))))
        records = append(records opaManagedSceneRecords(scene))
        opaManagedRecordBudget(records)
        make_opaNativeFrame(?scene scene ?records records ?common common
            ?components components ?drcs drcs)
    )
)

procedure(opaManagedWritesAllowed(frame)
    opaRequire(length(frame->components) >= 1 && length(frame->components) <= 256 &&
        axlDBControl('drcEnable) && axlDBGetDesign()->drcState == t
        "Writes need imported inventory and enabled, current native DRC.")
    foreach(rule '(Package_to_Package_Spacing Package_to_Place_Keepin_Spacing
        Package_to_Place_Keepout_Spacing)
        opaRequire(axlCNSDesignModeGet(rule) == 'on
            "Required native placement DRC coverage is not enabled."))
    opaRequire(!axlGetVariable("dbg_noskilltriggers")
        "Native lifecycle triggers have been disabled.")
    t
)

procedure(opaManagedPlacementPolicy(frame)
    let((outline keepin keepouts bounds others outlinePoly keepinPoly design)
        outline = caddr(assoc("outline" frame->common))
        keepin = caddr(assoc("keepin" frame->common))
        keepouts = setof(row frame->common car(row) == "keepout")
        design = axlDBGetDesign()
        outlinePoly = opaManagedBoundaryPoly(design->designOutline)
        keepinPoly = opaManagedBoundaryPoly(design->keepinPlace)
        foreach(data frame->components
            when(nth(5 data)
                bounds = nth(6 data)
                opaRequire(opaManagedContourContains(bounds outline) &&
                    opaManagedContourContains(bounds keepin)
                    "Conservative package/pad bounds cross the actual outline/keepin contour.")
                opaRequire(opaManagedPolygonContains(bounds outlinePoly) &&
                    opaManagedPolygonContains(bounds keepinPoly)
                    "Native curve intersection did not confirm whole-footprint containment.")
                foreach(row keepouts
                    opaRequire(!opaOverlap(bounds cadr(row))
                        "Conservative package/pad bounds overlap a package keepout."))
                foreach(other others
                    opaRequire(!opaOverlap(bounds nth(6 other))
                        "Conservative package/pad bounds overlap another placed component."))
                others = cons(data others))))
    t
)

procedure(opaManagedOnlyTargetChanged(before after refdes target angle)
    let((old current touched previousDerived currentDerived previousNet)
        opaRequire(equal(before->common after->common) &&
            length(before->components) == length(after->components) &&
            assoc(refdes before->components) && assoc(refdes after->components)
            "Inventory, definitions, connectivity, rules or other protected common data changed.")
        foreach(old before->components
            current = assoc(car(old) after->components)
            opaRequire(current "A logical component disappeared.")
            if(car(old) == refdes then
                opaRequire(equal(nth(1 current) target) && nth(2 current) == angle &&
                    !nth(3 current) && !nth(4 current) && nth(5 current) &&
                    equal(nth(7 old) nth(7 current)) &&
                    equal(nth(10 old) nth(10 current)) &&
                    equal(nth(11 old) nth(11 current)) &&
                    equal(nth(12 old) nth(12 current))
                    "Target pose or protected logical/definition data changed.")
                when(nth(5 old)
                    opaRequire(equal(nth(13 old) nth(13 current))
                        "Existing target symbol properties or access state changed."))
            else
                opaRequire(equal(opaManagedStaticComponent(old) opaManagedStaticComponent(current))
                    "A nontarget component or fixed obstacle changed.")))
        old = assoc(refdes before->components)
        foreach(pin nth(12 old)
            unless(cadr(pin) == "" touched = cons(cadr(pin) touched)))
        previousDerived = nth(14 car(before->components))
        currentDerived = nth(14 car(after->components))
        opaRequire(length(previousDerived) == length(currentDerived)
            "Derived net inventory changed.")
        foreach(net currentDerived
            previousNet = assoc(car(net) previousDerived)
            opaRequire(previousNet "A derived net appeared.")
            unless(member(car(net) touched)
                opaRequire(equal(previousNet net)
                    "Derived connectivity changed on a nontarget net.")))
        foreach(identity after->drcs
            opaRequire(member(identity before->drcs) "Native DRC reported a new violation."))
        t
    )
)

procedure(opaManagedStaticComponent(data)
    let((result)
        for(index 0 13 result = cons(nth(index data) result))
        reverse(result)
    )
)

procedure(opaManagedApplyTransaction(context)
    let((params before after old target angle refdes component symbol mark committed
         result rollbackOK restored message created)
        params = nth(3 context)
        refdes = nth(2 params)
        target = list(opaTargetDbu(nth(3 params)) opaTargetDbu(nth(4 params)))
        angle = opaTargetAngle(nth(5 params))
        before = opaManagedReadFrame()
        opaExpected(nth(1 params) before)
        opaManagedWritesAllowed(before)
        old = assoc(refdes before->components)
        opaRequire(old && !nth(3 old) && !nth(4 old)
            "Target is missing, fixed, read-only or mirrored.")
        when(nth(5 old)
            opaRequire(!equal(nth(1 old) target) || nth(2 old) != angle
                "Already-placed no-op apply is rejected."))
        component = axlDBFindByName('refdes refdes)
        opaRequire(component && component->name == refdes &&
            !axlDBIsFixed(component) && !axlDBIsReadOnly(component)
            "Exact logical target is missing, fixed or read-only.")
        symbol = component->symbol
        opaRequire(equal(if(symbol then t else nil) nth(5 old)) &&
            (!symbol || (!axlDBIsFixed(symbol) && !axlDBIsReadOnly(symbol)))
            "Physical target placement/access state changed.")
        opaInvalidate(nil)
        result = errset(
            progn(
                mark = axlDBTransactionStart()
                opaRequire(mark "Cannot start a native managed placement transaction.")
                opaMutationBegan = t
                if(symbol then
                    opaRequire(axlTransformObject(symbol
                        ?move list((car(target) - caadr(old)) / 10000.0
                                   (cadr(target) - cadadr(old)) / 10000.0)
                        ?angle angle - nth(2 old)
                        ?origin list(car(target) / 10000.0 cadr(target) / 10000.0)
                        ?allOrNone t) "Native exact-pose transform failed.")
                else
                    ; The fresh snapshot required the definition to be embedded;
                    ; initial placement must not resolve new library content.
                    created = axlDBCreateSymbol(refdes
                        list(car(target) / 10000.0 cadr(target) / 10000.0) nil angle)
                    opaRequire(created && car(created) "Native logical initial placement failed."))
                opaRequire(axlDRCUpdate(nil) "Native placement DRC update failed.")
                after = opaManagedReadFrame()
                opaManagedWritesAllowed(after)
                opaManagedOnlyTargetChanged(before after refdes target angle)
                opaManagedPlacementPolicy(after)
                opaRequire(axlDBTransactionCommit(mark) "Native placement commit failed.")
                committed = t
                after = opaManagedReadFrame()
                opaManagedWritesAllowed(after)
                opaManagedOnlyTargetChanged(before after refdes target angle)
                opaManagedPlacementPolicy(after)
                t) t)
        message = opaError
        if(result && committed then
            opaMutationBegan = nil
            list("applied" "Exact managed pose applied in memory; not saved." after->records)
        else
            if(mark && !committed then
                rollbackOK = errset(axlDBTransactionRollback(mark) t)
                restored = errset(
                    progn(
                        opaRequire(axlDRCUpdate(nil) "Post-rollback DRC update failed.")
                        after = opaManagedReadFrame()
                        opaRequire(equal(before->scene after->scene)
                            "Complete pre-transaction managed scene was not restored.")
                        t) t)
                if(rollbackOK && car(rollbackOK) && restored then
                    opaMutationBegan = nil
                    list("rolled_back" message after->records)
                else
                    opaHalted = t
                    list("indeterminate" "Managed rollback restoration is unproven; writes halted." nil))
            else
                if(committed || opaMutationBegan then
                    opaHalted = t
                    list("indeterminate" "Managed post-commit state is unproven; writes halted." nil)
                else
                    list("rejected" message nil))))
    )
)

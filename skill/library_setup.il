; Setup-only signatures and approved in-memory definition loading, not placement.
; Native acceptance is required: axlLoadSymbol transaction rollback and dirty
; state are not established by the installed API documentation or these tests.
; Sources: DOC/FUNCS/axlLoadSymbol.txt, axlDMFindFile.txt,
; axlDMLibraryFileNames.txt, axlGetVariableList.txt, axlSetVariable.txt,
; axlReadOnlyVariable.txt, axlUnsetVariable.txt, axlDBGetPropDictEntry.txt
; (the ->?? attribute-list representation), axlPadDbidDoc.txt and axlPath*.txt.

procedure(opaLibraryName(value)
    opaField(value)
    opaRequire(strlen(value) >= 1 && strlen(value) <= 128 &&
        rexMatchp("^[A-Za-z0-9]" value) && !rexMatchp("[^A-Za-z0-9_.+-]" value) &&
        substring(value strlen(value) 1) != "."
        "Unsupported library basename.")
    value
)

procedure(opaLibraryBudget(depth budget)
    budget["nodes"] = budget["nodes"] + 1
    opaRequire(depth <= 24 && budget["nodes"] <= 131072
        "Library signature exceeds its depth or total-node limit.")
    t
)

procedure(opaLibraryValue(value depth budget)
    opaLibraryBudget(depth budget)
    opaRequire(!axlIsDBIDType(value) "Unmodeled native library reference.")
    cond(
        (null(value) nil)
        (listp(value)
            opaRequire(length(value) <= 4096 "Oversized native library value list.")
            foreach(mapcar item value opaLibraryValue(item depth + 1 budget)))
        (stringp(value) opaField(value))
        (numberp(value) opaStable(value) value)
        (symbolp(value) opaStable(value) value)
        (t opaRequire(nil "Unmodeled native library structure or geometry."))
    )
)

procedure(opaLibraryPath(path depth budget)
    let((segments rows width point center clockwise)
        opaLibraryBudget(depth budget)
        width = axlPathGetWidth(path)
        segments = axlPathGetPathSegs(path)
        opaRequire(numberp(width) && width >= 0 && segments &&
            length(segments) <= 4096 "Unreadable or oversized native pad boundary.")
        foreach(segment segments
            point = axlPathSegGetEndPoint(segment)
            opaRequire(listp(point) && length(point) == 2 &&
                numberp(car(point)) && numberp(cadr(point))
                "Unreadable native pad boundary endpoint.")
            center = axlPathSegGetArcCenter(segment)
            when(center
                opaRequire(listp(center) && length(center) == 2 &&
                    numberp(car(center)) && numberp(cadr(center))
                    "Unreadable native pad boundary arc."))
            clockwise = if(center then axlPathSegGetArcClockwise(segment) else nil)
            opaRequire(member(clockwise '(nil t)) "Invalid native pad arc direction.")
            rows = cons(opaLibraryValue(list(point axlPathSegGetWidth(segment)
                center clockwise) depth + 1 budget) rows))
        ; Path order matters; the accessor returns traversal order, unlike
        ; the reversed private _pathList. No polygon/stroke approximation.
        list(opaLibraryValue(width depth + 1 budget) reverse(rows))
    )
)

procedure(opaLibraryPlainAttributes(object depth budget)
    let((attributes name value rows)
        opaLibraryBudget(depth budget)
        attributes = object->??
        opaRequire(listp(attributes) && attributes &&
            length(attributes) <= 512 && mod(length(attributes) 2) == 0
            "Native parameter attribute inventory is unavailable.")
        while(attributes
            name = car(attributes)
            value = cadr(attributes)
            opaRequire(symbolp(name) && !assoc(symbolToString(name) rows)
                "Invalid or duplicate native parameter attribute.")
            rows = cons(list(symbolToString(name)
                opaLibraryValue(value depth + 1 budget)) rows)
            attributes = cddr(attributes))
        opaSortedData(rows)
    )
)

procedure(opaLibraryObject(object owner ancestors depth budget)
    let((kind attributes rows key name value data children paths block expected required
         attached textRows seen nativeChildren)
        opaLibraryBudget(depth budget)
        opaRequire(object && !member(object ancestors)
            "Missing or cyclic library geometry.")
        kind = object->objType
        opaRequire(member(kind '("symdef" "padstack" "pad" "pin" "path" "line"
            "arc" "shape" "polygon" "figure" "text"))
            "Unsupported native library object type.")
        unless(kind == "pad"
            opaRequire(!object->parentGroups "Grouped library geometry is unsupported."))
        ancestors = cons(object ancestors)
        attributes = object->??
        opaRequire(listp(attributes) && attributes &&
            length(attributes) <= 512 && mod(length(attributes) 2) == 0
            "Complete native library attributes are unavailable.")
        while(attributes
            key = car(attributes)
            value = cadr(attributes)
            opaRequire(symbolp(key) "Library attribute name is not a symbol.")
            name = symbolToString(key)
            opaRequire(!assoc(name rows) "Duplicate native library attribute.")
            cond(
                (key == 'parent
                    opaRequire(!value || value == owner
                        "Library object has an unaccounted owner.")
                    data = if(value then "owner" else nil))
                (key == 'prop
                    data = nil
                    when(value
                        data = axlDBGetProperties(object)
                        opaRequire(data "Library properties could not be read."))
                    data = opaSortedData(opaLibraryValue(data depth + 1 budget)))
                (key == 'definition && value
                    opaRequire(member(kind '("pin" "padstack")) &&
                        value->objType == "padstack" &&
                        member(value axlDBGetDesign()->padstacks)
                        "Unmodeled library definition reference.")
                    data = list("padstack" opaLibraryName(value->name)))
                (member(key '(children pins pads segments voids)) && value
                    opaRequire(listp(value) && length(value) <= 4096 &&
                        ((kind == "symdef" && member(key '(children pins))) ||
                         (member(kind '("padstack" "pin")) && key == 'pads) ||
                         (kind == "path" && key == 'segments) ||
                         (member(kind '("shape" "polygon")) && member(key '(segments voids))))
                        "Unmodeled native library child collection.")
                    when(key == 'children nativeChildren = value)
                    children = nil
                    foreach(child value
                        expected = child->objType
                        opaRequire(
                            (key == 'pins && expected == "pin") ||
                            (key == 'pads && expected == "pad") ||
                            (key == 'segments && member(expected '("line" "arc"))) ||
                            (key == 'voids && member(expected '("shape" "polygon"))) ||
                            (key == 'children && member(expected
                                '("path" "line" "arc" "shape" "polygon" "figure" "text")))
                            "Unexpected child type in a native library object.")
                        when(kind == "pin" && key == 'pads
                            opaRequire(object->definition &&
                                member(object->definition axlDBGetDesign()->padstacks)
                                "Physical definition-pin pads have no embedded padstack owner."))
                        children = cons(opaLibraryObject(child
                            if(kind == "pin" && key == 'pads then object->definition else object) ancestors
                            depth + 1 budget) children))
                    data = if(key == 'segments then reverse(children)
                        else opaSortedData(children)))
                (kind == "pad" && key == 'figure
                    opaRequire(listp(value) && length(value) <= 1
                        "Unmodeled multi-boundary native pad figure.")
                    paths = foreach(mapcar path value opaLibraryPath(path depth + 1 budget))
                    data = paths)
                (kind == "text" && key == 'textBlock
                    opaRequire(stringp(value) && strlen(value) >= 1 && strlen(value) <= 2 &&
                        !rexMatchp("[^0-9]" value) && atoi(value) >= 1 && atoi(value) <= 64
                        "Invalid native library text block.")
                    block = axlGetParam(strcat("paramTextBlock:" value))
                    opaRequire(block && block->objType == "paramTextBlock"
                        "Native library text parameters are unavailable.")
                    data = list(value opaLibraryPlainAttributes(block depth + 1 budget)))
                (t data = opaLibraryValue(value depth + 1 budget)))
            rows = cons(list(name data) rows)
            attributes = cddr(attributes))
        opaRequire(equal(cadr(assoc("objType" rows)) kind) && assoc("parent" rows)
            "Native library attribute inventory is incomplete.")
        required = cond(
            (kind == "symdef" '("name" "type" "bBox" "children" "pins" "instances"))
            (kind == "padstack" '("name" "pads" "definition" "drillDiameter"
                "drillSizeWidth" "drillSizeHeight" "holeType" "startEnd" "isThrough"))
            (kind == "pad" '("figure" "figureName" "layer" "type" "offset" "bBox"))
            (kind == "pin" '("number" "name" "definition" "xy" "rotation" "pads"))
            (kind == "path" '("nSegs" "segments" "layer"))
            (kind == "line" '("startEnd" "width" "layer"))
            (kind == "arc" '("startEnd" "width" "xy" "isClockwise" "isCircle" "layer"))
            (member(kind '("shape" "polygon")) '("nSegs" "segments" "voids" "layer"))
            (kind == "figure" '("figureName" "xy" "width" "height" "rotation" "fill" "layer"))
            (kind == "text" '("text" "textBlock" "xy" "rotation" "layer")))
        foreach(name required
            opaRequire(assoc(name rows) "Required native library geometry attributes are missing."))
        unless(kind == "pad"
            attached = axlDBGetAttachedText(object)
            opaRequire(listp(attached) && length(attached) <= 256
                "Unbounded library attached-text inventory.")
            foreach(text attached
                opaRequire(text->objType == "text" && text->parent == object &&
                    !member(text seen) "Unowned or duplicate library attached text.")
                seen = cons(text seen)
                textRows = cons(list(if(member(text nativeChildren) then t else nil)
                    opaLibraryObject(text object ancestors depth + 1 budget)) textRows))
            ; The API inventory is separate from ->??. Capture even text absent
            ; from children, retaining whether each attachment is also a child.
            ; Leave objects with no attached text byte-for-byte compatible.
            when(attached
                opaRequire(!assoc("attached-text" rows) "Conflicting native attached-text attribute.")
                rows = cons(list("attached-text" opaSortedData(textRows)) rows)))
        opaSortedData(rows)
    )
)

procedure(opaLibraryPadstacks(design)
    let((rows names budget)
        opaRequire(length(design->padstacks) <= 1024 "Oversized embedded padstack inventory.")
        budget = makeTable('opaLibraryPadBudget 0)
        foreach(stack design->padstacks
            opaRequire(stack->objType == "padstack" && stack->parent == design
                "Invalid native padstack ownership.")
            opaLibraryName(stack->name)
            opaRequire(!member(lowerCase(stack->name) names) "Ambiguous embedded padstack name.")
            names = cons(lowerCase(stack->name) names)
            rows = cons(list(stack->name opaLibraryObject(stack design nil 0 budget)) rows))
        opaSortedData(rows)
    )
)

procedure(opaLibraryDefinitions(design)
    let((rows names budget)
        opaRequire(length(design->symdefs) <= 256 "Oversized embedded symbol-definition inventory.")
        budget = makeTable('opaLibraryDefinitionBudget 0)
        foreach(definition design->symdefs
            opaRequire(definition->objType == "symdef" && definition->parent == design &&
                !definition->instances &&
                member(definition->type '("PACKAGE" "FLASH" "SHAPE" "MECHANICAL" "FORMAT"))
                "Instanced or unsupported embedded symbol definition.")
            opaLibraryName(definition->name)
            opaRequire(!member(lowerCase(definition->name) names)
                "Ambiguous embedded symbol-definition name.")
            names = cons(lowerCase(definition->name) names)
            rows = cons(list(definition->name definition->type
                opaLibraryObject(definition design nil 0 budget)) rows))
        opaSortedData(rows)
    )
)

procedure(opaLibraryIsolatedNetObject(object net branch pin budget)
    let((attributes rows key value data name)
        attributes = object->??
        opaRequire(listp(attributes) && attributes && length(attributes) <= 512 &&
            mod(length(attributes) 2) == 0 "Incomplete isolated logical-net attributes.")
        while(attributes
            key = car(attributes)
            value = cadr(attributes)
            opaRequire(symbolp(key) && !assoc(symbolToString(key) rows)
                "Invalid isolated logical-net attribute.")
            name = symbolToString(key)
            cond(
                (object == net && key == 'branches
                    opaRequire(equal(value list(branch)) "Isolated logical net gained another branch.")
                    data = list("isolated-branch"))
                (object == branch && key == 'children
                    opaRequire(equal(value list(pin)) "Anonymous net connects more than its one logical pin.")
                    data = list("logical-pin" pin->component->name pin->number))
                (object == net && key == 'xnet
                    opaRequire(value == net "Anonymous net has extended-net topology.")
                    data = "isolated-net")
                (object == branch && key == 'net
                    opaRequire(value == net "Isolated branch has a different net owner.")
                    data = "isolated-net")
                (t data = opaLibraryValue(value 0 budget)))
            rows = cons(list(name data) rows)
            attributes = cddr(attributes))
        opaRequire(assoc("objType" rows) &&
            if(object == net then assoc("branches" rows) && assoc("xnet" rows)
                else assoc("children" rows) && assoc("net" rows))
            "Incomplete isolated-net ownership evidence.")
        opaSortedData(rows)
    )
)

procedure(opaLibraryLogicalNet(pin)
    let((net branch name budget)
        net = pin->net
        if(!net then list("" nil) else
            opaRequire(net->objType == "net" "Logical pin has an invalid net object.")
            name = opaField(net->name)
            if(name != "" then
                opaRequire(member(net axlDBGetDesign()->nets)
                    "Named logical net is absent from the protected native inventory.")
                list(name nil)
            else
                ; 25.1 represents some NC pins by distinct unnamed, single-pin
                ; nets outside design->nets. Keep their actual data and links;
                ; neither invent names nor collapse distinct nets into a short.
                branch = pin->branch
                opaManagedObjectGuard(net)
                opaRequire(branch && branch->objType == "branch" && branch->net == net &&
                    equal(net->branches list(branch)) && equal(branch->children list(pin)) &&
                    !member(net axlDBGetDesign()->nets) && net->xnet == net &&
                    !net->ratsnest && !net->pinpair && !net->ratT &&
                    !net->parentGroups && !branch->parent
                    "Only isolated unnamed single-pin logical nets are modeled.")
                budget = makeTable('opaLibraryIsolatedNetBudget 0)
                list(name list("anonymous-net"
                    opaLibraryIsolatedNetObject(net net branch pin budget)
                    opaLibraryIsolatedNetObject(branch net branch pin budget)))))
    )
)

procedure(opaLibraryComponent(component)
    let((pins intrinsic netName fixed netData)
        opaManagedObjectGuard(component)
        opaManagedName(component->name)
        opaLibraryName(component->package)
        opaRequire(component->objType == "component" && !component->symbol &&
            component->compdef && strlen(component->name) <= 31 &&
            rexMatchp("^[A-Za-z]" component->name) &&
            !rexMatchp("[^A-Za-z0-9_]" component->name) &&
            length(component->pins) >= 1 && length(component->pins) <= 256 &&
            length(component->pins) == length(component->compdef->pins)
            "Library setup requires a bounded, entirely logical component.")
        fixed = if(axlDBIsFixed(component) then t else nil)
        intrinsic = list(list("logical" component->package component->deviceType component->class
            opaManagedCompdef(component->compdef) opaProps(component) axlDBIsReadOnly(component))
            list("functions" opaManagedFunctions(component)))
        foreach(pin component->pins
            opaManagedObjectGuard(pin)
            opaManagedName(pin->number)
            opaRequire(pin->objType == "pin" && pin->component == component &&
                (!pin->parent || pin->parent == component) &&
                !pin->definition && !pin->pads && !pin->name && !assoc(pin->number pins) &&
                length(setof(item component->compdef->pins item->number == pin->number)) == 1
                "Invalid, duplicate or physically instantiated logical pin.")
            netData = opaLibraryLogicalNet(pin)
            netName = car(netData)
            pins = cons(list(pin->number netName nil) pins)
            ; Native 25.1 unplaced pins can name their logical component as
            ; parent. Preserve that association, never a physical DBID/pose.
            intrinsic = cons(list("pin" pin->number netName pin->use opaProps(pin)
                axlDBIsReadOnly(pin)
                list("logical-parent" if(pin->parent then component->name else nil))
                cadr(netData)) intrinsic))
        list(component->name '(0 0) 0 nil fixed nil nil opaSortedData(intrinsic)
            nil nil component->package nil opaSortedData(pins) nil)
    )
)

procedure(opaLibraryPlan(params)
    let((filename cacheid port line row rows total names seen folded root)
        opaRequire(length(params) == 7 && car(params) == "params" &&
            opaID(nth(1 params)) &&
            equal(list(nth(2 params) nth(3 params) nth(4 params) nth(5 params)) '("" "" "" ""))
            "Library setup parameters cannot contain a placement.")
        filename = nth(6 params)
        opaRequire(stringp(filename) && strlen(filename) == 44 &&
            substring(filename 1 8) == "library-" && opaID(substring(filename 9 32)) &&
            substring(filename 41) == ".csv" "Invalid immutable library plan filename.")
        cacheid = substring(filename 9 32)
        port = infile(strcat(opaRoot "\\" filename))
        opaRequire(port "Immutable library plan is missing.")
        total = 0
        unwindProtect(
            while(gets(line port)
                total = total + strlen(line)
                opaRequire(total <= 65536 && strlen(line) >= 1 && strlen(line) <= 1024 &&
                    length(rows) < 258 && substring(line strlen(line) 1) == "\n"
                    "Oversized or incomplete library plan.")
                line = substring(line 1 strlen(line) - 1)
                when(strlen(line) > 0 && substring(line strlen(line) 1) == "\r"
                    line = substring(line 1 strlen(line) - 1))
                opaField(line)
                opaRequire(!rexMatchp("\"" line) "Quoted library plan fields are forbidden.")
                row = axlStringCSVParse(line)
                opaRequire(equal(buildString(row ",") line) "Noncanonical library plan CSV.")
                rows = cons(row rows))
            close(port))
        rows = reverse(rows)
        opaRequire(length(rows) >= 3 &&
            equal(car(rows) list("OPA_LIBRARIES" "1" opaNonce cacheid nth(1 params))) &&
            equal(car(last(rows)) list("end" cacheid))
            "Library plan header, snapshot or completion marker mismatch.")
        foreach(row reverse(cdr(reverse(cdr(rows))))
            opaRequire(length(row) == 2 && car(row) == "package"
                "Library plan contains an unsupported operation.")
            root = opaLibraryName(cadr(row))
            folded = lowerCase(root)
            foreach(extension '(".psm" ".pad" ".fsm" ".ssm" ".bsm" ".osm" ".dra")
                opaRequire(strlen(folded) < strlen(extension) ||
                    substring(folded strlen(folded) - strlen(extension) + 1) != extension
                    "Library plan requires roots without file extensions."))
            opaRequire(!member(folded seen) "Duplicate or case-ambiguous requested package.")
            seen = cons(folded seen)
            names = cons(root names))
        opaRequire(length(names) >= 1 && length(names) <= 256 "Empty or oversized package request.")
        list(strcat(opaRoot "\\library-" cacheid) opaSort(names))
    )
)

procedure(opaLibraryPresent(name definitions)
    setof(row definitions lowerCase(car(row)) == lowerCase(name) && cadr(row) == "PACKAGE")
)

procedure(opaLibraryPathState(name)
    let((raw paths readonly)
        raw = axlGetVariable(name)
        paths = axlGetVariableList(name)
        readonly = axlReadOnlyVariable(name)
        opaRequire((!raw || stringp(raw)) &&
            (!paths || stringp(paths) || listp(paths)) && member(readonly '(nil t))
            "Unreadable library search-path state.")
        when(listp(paths)
            opaRequire(length(paths) <= 511 "Oversized library search path.")
            foreach(path paths opaField(path)))
        when(stringp(paths) opaField(paths))
        list(name raw paths readonly)
    )
)

procedure(opaLibraryExclusivePath(name cache)
    let((value)
        value = axlGetVariableList(name)
        equal(value list(cache)) || equal(value cache)
    )
)

procedure(opaLibraryRestorePath(state)
    if(nth(1 state) then
        opaRequire(axlSetVariable(car(state) nth(2 state)) "Cannot restore library search path.")
    else
        axlUnsetVariable(car(state)))
    opaRequire(equal(opaLibraryPathState(car(state)) state)
        "Original library path value or read-only state was not restored.")
    t
)

procedure(opaLibraryCacheFile(cache name)
    let((resolved expected)
        expected = strcat(cache "\\" name ".psm")
        resolved = axlDMFindFile("ALLEGRO_PACKAGE_DB" name "r")
        opaRequire(stringp(resolved) && isFile(expected) &&
            equal(parseString(lowerCase(resolved) "\\/")
                parseString(lowerCase(expected) "\\/"))
            "Native package resolution did not select the exact approved cache file.")
        t
    )
)

procedure(opaLibraryDependencyPaths(cache)
    let((files parts expected)
        expected = parseString(lowerCase(cache) "\\/")
        ; DM reports first-resolved files, not every shadowed search location.
        ; This preflight does not freeze the directory's child namespace.
        foreach(kind '("ALLEGRO_PACKAGE_DB" "ALLEGRO_PADSTACK_DB"
            "ALLEGRO_FLASH_DB" "ALLEGRO_SHAPE_DB")
            files = axlDMLibraryFileNames(kind)
            opaRequire(listp(files) && length(files) <= 1024
                "Unbounded native dependency search inventory.")
            foreach(file files
                opaField(file)
                parts = parseString(lowerCase(file) "\\/")
                opaRequire(parts && equal(reverse(cdr(reverse(parts))) expected)
                    "Native dependency search includes an unapproved fallback location.")))
        t
    )
)

procedure(opaLibrarySubset(old current message)
    foreach(row old
        opaRequire(equal(row assoc(car(row) current)) message))
    t
)

procedure(opaLibraryProtected(before after names)
    let((exceptions oldDefinitions definitions)
        exceptions = '("padstacks" "definitions" "property-dictionary")
        opaRequire(equal(setof(row before->common !member(car(row) exceptions))
                setof(row after->common !member(car(row) exceptions))) &&
            equal(before->components after->components) && equal(before->drcs after->drcs)
            "Protected board, logical components, connectivity or DRC records changed.")
        foreach(key exceptions
            opaRequire(assoc(key before->common) && assoc(key after->common)
                "Protected library or property-dictionary inventory disappeared.")
            opaLibrarySubset(cadr(assoc(key before->common)) cadr(assoc(key after->common))
                "An existing library definition or property-dictionary entry changed."))
        oldDefinitions = cadr(assoc("definitions" before->common))
        definitions = cadr(assoc("definitions" after->common))
        foreach(row definitions
            unless(assoc(car(row) oldDefinitions)
                opaRequire(member(cadr(row) '("FLASH" "SHAPE")) ||
                    (cadr(row) == "PACKAGE" &&
                        setof(name names lowerCase(name) == lowerCase(car(row))))
                    "An unrequested nondependency symbol definition appeared.")))
        t
    )
)

procedure(opaLibraryErrorText(value)
    let((text character limit index)
        unless(stringp(value) && strlen(value) > 0
            value = "Native operation failed without additional detail.")
        text = ""
        limit = min(strlen(value) 1024)
        for(index 1 limit
            character = substring(value index 1)
            text = strcat(text if(rexMatchp("^[ -~]$" character) then character else "?")))
        when(strlen(value) > limit text = strcat(text "..."))
        text
    )
)

procedure(opaLoadLibraries(context)
    let((params plan cache names before after psmpath padpath result restoredPsm restoredPad
         readback attempted failed returned definitions loaded missing records message restoreError)
        opaRequire(length(context) == 4 && car(context) == opaNonce &&
            nth(2 context) == "load_libraries" && opaDispatchActive && !opaHalted &&
            opaManagedMode() "Library loading requires the bounded managed dispatch.")
        params = nth(3 context)
        opaBoardGuard()
        plan = opaLibraryPlan(params)
        cache = car(plan)
        names = cadr(plan)
        opaRequire(isDir(cache) "Approved library cache directory is missing.")
        before = opaManagedReadFrame(t)
        opaExpected(nth(1 params) before)
        definitions = cadr(assoc("definitions" before->common))
        foreach(name names
            opaRequire(!opaLibraryPresent(name definitions) &&
                setof(component before->components lowerCase(nth(10 component)) == lowerCase(name))
                "Requested package is not an actually missing logical requirement."))
        psmpath = opaLibraryPathState("psmpath")
        padpath = opaLibraryPathState("padpath")
        opaRequire(!nth(3 psmpath) && !nth(3 padpath)
            "Read-only library search variables cannot be overridden.")
        opaRequire(axlOKToProceed() && !axlGetVariable("dbg_noskilltriggers")
            "Editor is busy or native lifecycle invalidation is disabled.")
        opaBoardGuard()
        opaInvalidate(nil)
        opaMutationBegan = t
        opaError = "Native library loading did not complete."
        unwindProtect(
            result = errset(
                progn(
                    opaRequire(axlSetVariable("psmpath" list(cache)) &&
                        axlSetVariable("padpath" list(cache)) &&
                        opaLibraryExclusivePath("psmpath" cache) &&
                        opaLibraryExclusivePath("padpath" cache)
                        "Exclusive approved-cache library paths were not established.")
                    opaLibraryDependencyPaths(cache)
                    foreach(name names opaLibraryCacheFile(cache lowerCase(name)))
                    foreach(name names
                        unless(failed
                            opaBoardGuard()
                            opaRequire(opaLibraryExclusivePath("psmpath" cache) &&
                                opaLibraryExclusivePath("padpath" cache)
                                "Exclusive library paths changed before loading.")
                            opaLibraryDependencyPaths(cache)
                            opaLibraryCacheFile(cache lowerCase(name))
                            attempted = t
                            returned = axlLoadSymbol("PACKAGE" lowerCase(name))
                            if(returned then
                                opaRequire(returned->objType == "symdef" &&
                                    returned->type == "PACKAGE" &&
                                    lowerCase(returned->name) == lowerCase(name)
                                    "Native library loader returned an unexpected definition.")
                            else failed = t)))
                    t) t)
            progn(
                ; Try both restorations even when the first one fails.
                message = opaError
                opaError = "Native psmpath restoration did not complete."
                restoredPsm = errset(opaLibraryRestorePath(psmpath) t)
                unless(restoredPsm && car(restoredPsm)
                    restoreError = strcat("psmpath: " opaLibraryErrorText(opaError)))
                opaError = "Native padpath restoration did not complete."
                restoredPad = errset(opaLibraryRestorePath(padpath) t)
                unless((restoredPad && car(restoredPad)) || restoreError
                    restoreError = strcat("padpath: " opaLibraryErrorText(opaError)))))
        opaError = "Native library setup readback did not complete."
        readback = errset(
            progn(
                opaRequire(restoredPsm && car(restoredPsm) && restoredPad && car(restoredPad)
                    if(restoreError then restoreError else "Library search-path restoration failed."))
                opaBoardGuard()
                axlDBRefreshId(nil)
                after = opaManagedReadFrame(t)
                opaLibraryProtected(before after names)
                when(!result && !attempted
                    opaRequire(equal(before->scene after->scene)
                        "Pre-load failure did not preserve the entire setup scene."))
                t) t)
        cond(
            (!readback || (!result && attempted)
                opaHalted = t
                list("indeterminate"
                    strcat("Library state or search-path restoration is unproven; writes halted. Cause: "
                        opaLibraryErrorText(if(!readback then opaError else message))
                        " No rollback was claimed.")
                    nil))
            (!result
                opaMutationBegan = nil
                list("rejected" opaLibraryErrorText(message) after->records))
            (t
                definitions = cadr(assoc("definitions" after->common))
                records = after->records
                foreach(name names
                    if(opaLibraryPresent(name definitions) then
                        loaded = cons(name loaded)
                        records = append(records list(list("library-loaded" name)))
                    else
                        missing = cons(name missing)
                        records = append(records list(list("library-missing" name)))))
                opaMutationBegan = nil
                if(missing then
                    if(!loaded && equal(before->scene after->scene) then
                        list("rejected"
                            "No requested definitions loaded; the complete original setup state was verified."
                            records)
                    else
                        list("library_partial"
                            "Definition loading stopped with verified partial state; not saved. Do not replay this approval."
                            records))
                else
                    list("libraries_loaded"
                        "Requested definitions are present in memory only; not placement acceptance or persistence."
                        records))))
    )
)

; Public commands are GENERAL gates. Only private callbacks enter interactive mode.
opaRequire(!(boundp('opaDispatchActive) && opaDispatchActive)
    "Do not reload the adapter during an active request.")
opaReloadHalted = if(boundp('opaLoadedNonce) && opaLoadedNonce == opaNonce &&
    boundp('opaHalted) then opaHalted else nil)
opaHalted = t

procedure(opaBootstrapGuard()
    let((parent leaf)
        opaRequire(boundp('opaRoot) && boundp('opaNonce) && boundp('opaBoardPath)
            "Trusted adapter bootstrap is missing.")
        opaField(opaRoot)
        opaRequire(opaID(opaNonce) "Invalid trusted session nonce.")
        parent = strcat(getShellEnvVar("LOCALAPPDATA") "\\OrCadPlacementAgent\\sessions\\")
        leaf = car(last(parseString(opaRoot "\\/")))
        opaRequire(equal(opaRoot strcat(parent leaf)) &&
            rexMatchp("^board-[A-Za-z0-9_-]+$" leaf) && isDir(opaRoot) &&
            equal(opaBoardPath strcat(opaRoot "\\working.brd"))
            "Adapter paths must name one dedicated local staged working board.")
        t
    )
)

procedure(opaBoardGuard()
    opaBootstrapGuard()
    opaRequire(equal(axlDesignType(t) "BOARD") &&
        equal(parseString(axlGetDrawingName() "\\/") parseString(opaBoardPath "\\/"))
        "The active database is not the exact staged working board.")
    t
)

procedure(opaInvalidate(event)
    opaSnapshots = nil
    t
)

procedure(opaExpected(identifier frame)
    let((entry)
        entry = assoc(identifier opaSnapshots)
        opaRequire(entry && nth(1 entry) == opaBoardPath &&
            nth(2 entry) == frame->scene "Snapshot expired or the complete native scene changed.")
        t
    )
)

procedure(opaCache(identifier frame)
    opaSnapshots = cons(list(identifier opaBoardPath frame->scene) opaSnapshots)
    when(length(opaSnapshots) > 16
        opaSnapshots = reverse(cdr(reverse(opaSnapshots))))
    t
)

procedure(opaClaim(identifier)
    let((path output)
        opaRequire(!isFile(opaPath(identifier ".result.csv")) "Request already completed.")
        path = opaPath(identifier ".claimed")
        when(isFile(path)
            opaHalted = t
            opaRequire(nil "Previously claimed request has no terminal result; stop and reconcile."))
        opaRequire(!isFile(opaPath(identifier ".result.partial"))
            "Partial prior result requires reconciliation.")
        output = outfile(path)
        opaRequire(output "Cannot claim the request.")
        fprintf(output "%s\n" opaNonce)
        close(output)
        t
    )
)

procedure(opaInspectPrivate()
    let((context result)
        opaRequire(opaDispatchActive && opaFrozen && nth(2 opaFrozen) == "inspect"
            "Private inspection requires a validated general gate.")
        context = opaFrozen
        opaFrozen = nil
        result = errset(opaReadFrame() t)
        opaDispatchResult = if(result then car(result) else nil)
        t
    )
)

procedure(opaApplyPrivate()
    let((context result)
        opaRequire(opaDispatchActive && opaFrozen && nth(2 opaFrozen) == "apply"
            "Private apply requires a validated general gate.")
        context = opaFrozen
        opaFrozen = nil
        result = errset(opaApplyTransaction(context) t)
        unless(result
            when(opaMutationBegan opaHalted = t))
        opaDispatchResult = if(result then car(result)
            else list(if(opaHalted then "indeterminate" else "rejected") opaError nil))
        t
    )
)

procedure(opaInspect(identifier)
    opaDispatchResult = nil
    opaFrozen = list(opaNonce identifier "inspect" nil)
    axlShell("opa__inspect")
    opaRequire(!opaFrozen "Native interactive inspection did not dispatch.")
    opaRequire(opaDispatchResult opaError)
    opaDispatchResult
)

procedure(opaSaveManaged(identifier params)
    let((before after destination result)
        before = opaInspect(identifier)
        opaExpected(nth(1 params) before)
        opaWritesAllowed(before)
        opaPlacementPolicy(before)
        destination = strcat(opaRoot "\\" nth(6 params))
        opaRequire(!isFile(destination) && destination != opaBoardPath
            "Managed revision already exists or aliases the working board.")
        opaRequire(axlOKToProceed() "Editor became busy before save.")
        opaBoardGuard()
        opaInvalidate(nil)
        opaMutationBegan = t
        result = errset(axlSaveDesign(?design destination ?noMru t ?writeModel t) t)
        if(result && car(result) && isFile(destination) then
            after = opaInspect(identifier)
            opaRequire(equal(before->scene after->scene)
                "Saved revision changed the in-memory scene or working-board identity.")
            opaMutationBegan = nil
            list("saved" "A separate new revision was saved with native checks."
                append(after->records list(list("saved" destination))))
        else
            opaHalted = t
            list("indeterminate"
                "Native revision save did not establish a verified result." nil))
    )
)

procedure(opaCommand(operation arguments)
    let((identifier params result outcome frame entered trusted)
        opaError = "Native operation failed; inspect the dedicated editor log."
        result = errset(
            progn(
                opaRequire(length(arguments) == 1 && opaID(car(arguments))
                    "Exactly one lowercase hexadecimal request ID is required.")
                identifier = car(arguments)
                opaBootstrapGuard()
                trusted = t
                opaRequire(!opaDispatchActive && axlOKToProceed()
                    "Editor is busy; active command was not finished.")
                opaRequire(!opaHalted "Adapter state is indeterminate; writes are halted.")
                opaClaim(identifier)
                params = opaReadRequest(identifier operation)
                opaBoardGuard()
                opaDispatchActive = t
                entered = t
                opaMutationBegan = nil
                cond(
                    (operation == "snapshot"
                        frame = opaInspect(identifier)
                        opaCache(identifier frame)
                        outcome = list("snapshot" "Fresh read-only native fixture snapshot."
                            append(frame->records list(list("snapshot" identifier)))))
                    (operation == "apply"
                        opaFrozen = list(opaNonce identifier operation copy(params))
                        opaDispatchResult = nil
                        axlShell("opa__apply")
                        opaRequire(!opaFrozen && opaDispatchResult
                            "Native undoable callback did not complete.")
                        outcome = opaDispatchResult)
                    (operation == "save"
                        outcome = opaSaveManaged(identifier params))
                    (t opaRequire(nil "Unknown adapter operation."))
                )
                t
            ) t)
        when(entered
            opaFrozen = nil
            opaDispatchActive = nil
            opaDispatchResult = nil)
        unless(result
            when(entered && opaMutationBegan opaHalted = t)
            outcome = list(if(opaHalted then "indeterminate" else "rejected") opaError nil))
        when(identifier && trusted && !isFile(opaPath(identifier ".result.csv"))
            unless(errset(opaResult(identifier car(outcome) cadr(outcome) caddr(outcome)) t)
                opaHalted = t
                axlMsgPut("OPA: terminal receipt publication failed; stop and reconcile.")))
        unless(identifier && trusted axlMsgPut(strcat("OPA: " opaError)))
        t
    )
)

procedure(opaSnapshot(@rest arguments) opaCommand("snapshot" arguments))
procedure(opaApply(@rest arguments) opaCommand("apply" arguments))
procedure(opaSave(@rest arguments) opaCommand("save" arguments))

procedure(opaViewFit(@rest arguments)
    let((identifier trusted result)
        opaError = "Display-only view fit failed."
        result = errset(
            progn(
                opaRequire(length(arguments) == 2 && opaID(car(arguments)) &&
                    opaID(cadr(arguments)) "View fit needs an exact request ID and session nonce.")
                identifier = car(arguments)
                opaBootstrapGuard()
                trusted = t
                opaRequire(cadr(arguments) == opaNonce "View-fit session changed.")
                opaBoardGuard()
                opaRequire(!opaDispatchActive && axlOKToProceed()
                    "Editor is busy; view fitting did not finish an active command.")
                opaRequire(!isFile(opaPath(identifier ".result.csv"))
                    "View-fit request already completed.")
                opaRequire(axlWindowFit() "Cannot fit the dedicated board view.")
                t
            ) t)
        when(identifier && trusted && !isFile(opaPath(identifier ".result.csv"))
            opaResult(identifier if(result then "snapshot" else "rejected")
                if(result then "Display-only view fit completed." else opaError) nil))
        unless(identifier && trusted axlMsgPut(strcat("OPA: " opaError)))
        t
    )
)

unless(boundp('opaDispatchActive) opaDispatchActive = nil)
opaRequire(!opaDispatchActive "Do not reload the adapter during an active request.")
opaSnapshots = nil
opaFrozen = nil
opaDispatchResult = nil
opaMutationBegan = nil
opaBootstrapGuard()
foreach(event '(open close save)
    ; Remove only this adapter's callback; other integrations remain untouched.
    axlTriggerClear(event 'opaInvalidate)
    opaRequire(axlTriggerSet(event 'opaInvalidate) "Cannot register snapshot invalidation."))
opaRequire(axlCmdRegister("opa__inspect" 'opaInspectPrivate ?cmdType "interactive")
    "Cannot register private read-only inspection.")
opaRequire(axlCmdRegister("opa__apply" 'opaApplyPrivate ?cmdType "interactive" ?undo t)
    "Cannot register private undoable apply.")
opaRequire(axlCmdRegister("opa_snapshot" 'opaSnapshot ?cmdType "general")
    "Cannot register snapshot gate.")
opaRequire(axlCmdRegister("opa_apply" 'opaApply ?cmdType "general")
    "Cannot register apply gate.")
opaRequire(axlCmdRegister("opa_save" 'opaSave ?cmdType "general")
    "Cannot register save gate.")
opaRequire(axlCmdRegister("opa_viewfit" 'opaViewFit ?cmdType "general")
    "Cannot register display-only fit gate.")
opaLoadedNonce = opaNonce
opaHalted = opaReloadHalted

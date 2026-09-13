; Diagnostic only; does not remove groups or change design constraints.
procedure(opaRoomConstraintsReadOnlyReport(identifier)
    let((design rows output path properties assignment count)
        opaRequire(opaID(identifier) && !opaDispatchActive && axlOKToProceed()
            "Room/constraint inspection needs an exact request and idle session.")
        opaBoardGuard()
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        opaRequire(length(design->components) <= 256 && length(design->groups) <= 256
            "Diagnostic exceeds component/group limits.")
        rows = list(list("scope" "room-and-constraint-inventory-only"))
        foreach(domain '(physical spacing sameNet electrical)
            rows = append(rows list(list("csets" symbolToString(domain)
                sprintf(nil "%L" axlCnsList(domain))))))
        rows = append(rows list(list("root-features"
            sprintf(nil "%d" length(design->netclass))
            sprintf(nil "%d" length(design->netgroup))
            sprintf(nil "%d" length(design->region))
            sprintf(nil "%d" length(design->module))
            sprintf(nil "%d" length(design->text)))))
        foreach(group design->groups
            when(group->type == "GENERIC"
                opaRequire(length(group->groupMembers) <= 16 "Generic group diagnostic is too large.")
                foreach(member group->groupMembers
                    rows = append(rows list(list("room-candidate"
                        sprintf(nil "%L" group->name) sprintf(nil "%L" member->layer)
                        sprintf(nil "%L" member->objType) sprintf(nil "%L" member->bBox)
                        sprintf(nil "%L" member->isRect) sprintf(nil "%L" opaProps(member))
                        sprintf(nil "%L" axlDBGetAttachedText(member))))))))
        count = 0
        foreach(component design->components
            when(component->symbol count = count + 1)
            properties = opaProps(component)
            assignment = assoc('ROOM properties)
            rows = append(rows list(list("component-room" component->name
                sprintf(nil "%L" assignment)
                sprintf(nil "%L" if(component->symbol then
                    assoc('ROOM opaProps(component->symbol)) else nil))))))
        rows = append(rows list(list("placed-count" sprintf(nil "%d" count)
            sprintf(nil "%d" length(design->components)))))
        path = opaPath(identifier ".room-constraints.csv")
        opaRequire(!isFile(path) "Diagnostic output already exists.")
        output = outfile(path)
        opaRequire(output "Cannot create diagnostic report.")
        unwindProtect(
            progn(
                fprintf(output "%s\n" buildString(mapcar('opaCsv
                    list("OPA_ROOMS_READONLY" "1" opaNonce identifier opaBoardPath)) ","))
                foreach(row rows fprintf(output "%s\n" buildString(mapcar('opaCsv row) ",")))
                fprintf(output "%s\n" buildString(mapcar('opaCsv list("end" identifier)) ",")))
            close(output))
        t
    )
)

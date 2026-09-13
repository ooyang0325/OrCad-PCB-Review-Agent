; Diagnostic only: group inventory is not a complete placement snapshot.
procedure(opaGroupsReadOnlyReport(identifier)
    let((design rows path output total)
        opaRequire(opaID(identifier) && !opaDispatchActive && axlOKToProceed()
            "Group inspection needs an exact request and idle session.")
        opaBoardGuard()
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        opaRequire(length(design->groups) <= 256 "Group diagnostic exceeds 256 groups.")
        rows = list(list("scope" "group-inventory-only-not-placement-approval"))
        total = 0
        foreach(group design->groups
            total = total + length(group->groupMembers)
            opaRequire(total <= 4096 "Group diagnostic exceeds 4096 memberships.")
            rows = append(rows list(list("group"
                sprintf(nil "%L" group->name) sprintf(nil "%L" group->type)
                sprintf(nil "%L" group->objType)
                sprintf(nil "%d" length(group->parentGroups))
                sprintf(nil "%d" length(group->groupMembers))
                sprintf(nil "%L" opaProps(group)))))
            foreach(member group->groupMembers
                rows = append(rows list(list("member"
                    sprintf(nil "%L" group->name) sprintf(nil "%L" member->objType)
                    sprintf(nil "%L" member->name) sprintf(nil "%L" member->refdes)
                    sprintf(nil "%L" member->layer) sprintf(nil "%L" member->type)
                    sprintf(nil "%d" length(member->parentGroups)))))))
        path = opaPath(identifier ".groups.csv")
        opaRequire(!isFile(path) "Group diagnostic output already exists.")
        output = outfile(path)
        opaRequire(output "Cannot create group diagnostic output.")
        unwindProtect(
            progn(
                fprintf(output "%s\n" buildString(mapcar('opaCsv
                    list("OPA_GROUPS_READONLY" "1" opaNonce identifier opaBoardPath)) ","))
                foreach(row rows fprintf(output "%s\n" buildString(mapcar('opaCsv row) ",")))
                fprintf(output "%s\n" buildString(mapcar('opaCsv list("end" identifier)) ",")))
            close(output))
        t
    )
)

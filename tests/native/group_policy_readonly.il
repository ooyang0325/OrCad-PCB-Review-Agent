; Read and compare protected group/Cset data, not a complete placement snapshot.
procedure(opaGroupPolicyReadOnlyReport(identifier)
    let((design groups rooms assignments policy repeated records path output outcome constraints rejected syntheticRooms)
        opaRequire(opaID(identifier) && !opaDispatchActive && axlOKToProceed()
            "Group-policy read needs an exact request and idle session.")
        opaBoardGuard()
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        opaError = "Group-policy read failed; inspect the native command log."
        outcome = errset(
            progn(
                constraints = opaManagedConstraints()
                axlDBRefreshId(nil)
                design = axlDBGetDesign()
                groups = opaManagedGroups(design)
                rooms = cadr(groups)
                groups = car(groups)
                assignments = opaManagedRoomAssignments(design)
                policy = list(list("groups" groups) list("rooms" rooms)
                    list("room-assignments" assignments)
                    list("constraints" constraints))
                repeated = opaManagedGroups(design)
                opaRequire(equal(groups car(repeated)) && equal(rooms cadr(repeated)) &&
                    equal(assignments opaManagedRoomAssignments(design)) &&
                    equal(constraints opaManagedConstraints())
                    "Read-only group or constraint data changed between reads.")
                records = opaManagedPolicyRecords(policy rooms assignments groups design)
                syntheticRooms = '(("box" "UC" ((0 0) (100000 100000))))
                opaManagedRoomCheck("U1" '((10000 10000) (90000 90000)) syntheticRooms
                    '(("U1" "" "UC") ("U1" "F1" "UC")))
                rejected = errset(opaManagedRoomCheck("U1" '((10000 10000) (110000 90000))
                    syntheticRooms '(("U1" "" "UC"))) nil)
                opaRequire(!rejected "Native room containment failed to reject an outside footprint.")
                rejected = errset(opaManagedRoomCheck("U1" '((10000 10000) (90000 90000))
                    syntheticRooms '(("U1" "" "UC") ("U1" "F1" "OTHER"))) nil)
                opaRequire(!rejected "Conflicting native room assignments were accepted.")
                opaManagedRoomCheck("U1" '((10000 10000) (90000 90000))
                    '(("POWER" "1" ((0 400000) (2000000 1700000)))) '(("U1" "" "POWER")))
                records = append(records list(list("check" "native-room-policy-lookup" "passed")))
                t) t)
        unless(outcome records = list(list("error" opaError)))
        path = opaPath(identifier ".group-policy.csv")
        opaRequire(!isFile(path) "Group-policy report already exists.")
        output = outfile(path)
        opaRequire(output "Cannot write group-policy diagnostic.")
        unwindProtect(
            progn(
                fprintf(output "%s\n" buildString(mapcar('opaCsv
                    list("OPA_GROUP_POLICY_READONLY" "1" opaNonce identifier opaBoardPath)) ","))
                foreach(component design->components
                    fprintf(output "%s\n" buildString(mapcar('opaCsv
                        list("component-name" component->name)) ",")))
                foreach(row records fprintf(output "%s\n" buildString(mapcar('opaCsv row) ",")))
                when(outcome
                    fprintf(output "%s\n" buildString(mapcar('opaCsv
                        list("check" "native-group-and-cset-repeatability" "passed")) ",")))
                fprintf(output "%s\n" buildString(mapcar('opaCsv list("end" identifier)) ",")))
            close(output))
        t
    )
)

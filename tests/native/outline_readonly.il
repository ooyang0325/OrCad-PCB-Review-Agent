; Bounded outline-only diagnostic. This is NOT a complete placement snapshot.
procedure(opaOutlineReadOnlyReport(identifier)
    let((design outline keepin path output rows outcome legacy)
        opaRequire(opaID(identifier) && !opaDispatchActive && axlOKToProceed()
            "Outline read needs an exact request and idle managed session.")
        opaBoardGuard()
        opaRequire(equal(axlDBGetDesignUnits() '("millimeters" 4 10000))
            "Outline diagnostic requires known millimeter DBUs.")
        axlDBRefreshId(nil)
        design = axlDBGetDesign()
        opaRequire(design->designOutline && design->keepinPlace &&
            length(axlDBGetShapes("BOARD GEOMETRY/DESIGN_OUTLINE")) == 1 &&
            length(axlDBGetShapes("PACKAGE KEEPIN/ALL")) == 1 &&
            !axlDBGetShapes("BOARD GEOMETRY/CUTOUT")
            "Outline-only read does not support missing boundaries, islands or cutouts.")
        outcome = errset(
            progn(
                outline = opaManagedBoundary(design->designOutline)
                keepin = opaManagedBoundary(design->keepinPlace)
                legacy = axlDBGetShapes("BOARD GEOMETRY/OUTLINE")
                opaRequire(length(legacy) <= 1 "Multiple legacy outline shapes are ambiguous.")
                when(legacy
                    opaRequire(equal(opaManagedBoundaryIdentity(opaManagedBoundary(car(legacy)))
                        opaManagedBoundaryIdentity(outline))
                        "Legacy OUTLINE and DESIGN_OUTLINE have conflicting native edges."))
                rows = list(list("boundary-model" "polygon-v1")
                    opaManagedBoxRecord("outline" nth(3 outline))
                    opaManagedBoxRecord("keepin" nth(3 keepin)))
                rows = append(rows opaManagedContourRecords("outline" outline))
                rows = append(rows opaManagedContourRecords("keepin" keepin))
                t) t)
        unless(outcome rows = list(list("error" opaError)))
        path = opaPath(identifier ".outline.csv")
        opaRequire(!isFile(path) "Outline diagnostic output already exists.")
        output = outfile(path)
        opaRequire(output "Cannot create outline diagnostic output.")
        unwindProtect(
            progn(
                fprintf(output "%s\n" buildString(mapcar('opaCsv
                    list("OPA_OUTLINE_READONLY" "1" opaNonce identifier opaBoardPath)) ","))
                foreach(row rows fprintf(output "%s\n" buildString(mapcar('opaCsv row) ",")))
                fprintf(output "%s\n" buildString(mapcar('opaCsv list("end" identifier)) ",")))
            close(output))
        t
    )
)

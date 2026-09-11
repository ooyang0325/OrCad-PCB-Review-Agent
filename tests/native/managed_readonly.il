; Optional live-reader acceptance on the original three-component fixture.
; Does not call placement, transactions, property writes, DRC update or Save.
procedure(opaManagedReadOnlyAcceptance(identifier)
    let((output path design bytes expected limited attachments repeat data definitions stacks
         functions stackup rows)
        opaRequire(opaID(identifier) && !opaDispatchActive
            "Read-only acceptance needs an exact ID and idle adapter.")
        opaBoardGuard()
        opaRequire(opaManagedMode() "Use the explicitly staged managed board model.")
        design = axlDBGetDesign()
        opaRequire(equal(opaSort(design->components~>name) '("R1" "R2" "R3")) &&
            equal(opaSort(design->symdefs~>name) '("OPA_FIXTURE_TWO_PIN"))
            "Live-reader acceptance is only for the original synthetic fixture.")
        path = opaPath(identifier ".managed-readonly.csv")
        opaRequire(!isFile(path) "Read-only acceptance result already exists.")
        bytes = opaManagedReadBytes(strcat(opaRoot "\\native-byte-fixture.bin") 512)
        expected = ""
        for(index 0 511 expected = strcat(expected sprintf(nil "%02x" mod(index 256))))
        opaRequire(car(bytes) == 512 && buildString(cadr(bytes) "") == expected
            "Native binary reading did not preserve all byte values.")
        rows = list(list("check" "binary-all-256-values" "passed"))
        limited = errset(opaManagedReadBytes(strcat(opaRoot "\\native-byte-fixture.bin") 511) nil)
        opaRequire(!limited "Oversized native byte input was not rejected.")
        rows = cons(list("check" "byte-limit-rejection" "passed") rows)
        attachments = opaManagedAttachments()
        repeat = opaManagedAttachments()
        opaRequire(equal(attachments repeat) && length(attachments) > 0
            "Native attachment content was not read repeatably.")
        rows = cons(list("check" "complete-attachment-repeatability" "passed") rows)
        stacks = opaManagedPadstacks(design)
        definitions = opaManagedDefinitions(design stacks)
        foreach(component design->components
            data = opaManagedComponent(component definitions stacks)
            opaRequire(equal(nth(4 data) component->name == "R3")
                "Logical placement fixed state differs from the fixture.")
            opaRequire(length(nth(12 data)) == 2 && nth(5 data)
                "Expected complete placed fixture pin inventory.")
            functions = opaManagedFunctions(component)
            opaRequire(length(functions) == 1 && length(nth(3 car(functions))) == 2
                "Native logical function mapping is incomplete."))
        rows = cons(list("check" "fixed-parent-versus-package-pins" "passed") rows)
        rows = cons(list("check" "logical-function-pin-associations" "passed") rows)
        stackup = opaManagedStackup(axlSubclassRoute())
        opaRequire(length(nth(2 stackup)) == 5
            "Synthetic cross-section must include both air surfaces and dielectric.")
        rows = cons(list("check" "surface-and-conductor-cross-section" "passed") rows)
        output = outfile(path)
        opaRequire(output "Cannot write live-reader acceptance result.")
        unwindProtect(
            progn(
                fprintf(output "%s\n" buildString(mapcar('opaCsv
                    list("OPA_NATIVE_READONLY" "1" opaNonce identifier opaBoardPath)) ","))
                foreach(row reverse(rows)
                    fprintf(output "%s\n" buildString(mapcar('opaCsv row) ",")))
                fprintf(output "%s\n" buildString(mapcar('opaCsv list("end" identifier)) ","))
            )
            close(output)
        )
        t
    )
)

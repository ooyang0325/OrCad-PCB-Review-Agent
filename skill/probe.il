; One-shot, read-only capability probe. Load via the staged bootstrap.
procedure(opaProbe()
    let((required missing design units version product drawing output
         functionName component)
        unless(boundp('opaProbeOutput)
            error("OPA: load the staged bootstrap before invoking opa_probe.\n")
        )
        when(isFile(opaProbeOutput)
            error("OPA: report already exists; stage a new probe directory.\n")
        )
        required = '(axlDBGetDesign axlDBGetDesignUnits axlVersion
                     axlGetDrawingName axlTransformObject axlCmdRegister
                     axlDBTransactionStart axlDBTransactionCommit
                     axlDBTransactionRollback axlDRCUpdate axlSaveDesign
                     axlStringCSVParse)
        foreach(functionName required
            unless(isCallable(functionName)
                missing = cons(functionName missing)
            )
        )
        when(missing
            error("OPA: required functions unavailable: %L\n" missing)
        )
        design = axlDBGetDesign()
        unless(design
            error("OPA: no readable board database is open.\n")
        )
        units = axlDBGetDesignUnits()
        unless(units
            error("OPA: board units could not be read.\n")
        )
        version = axlVersion('fullVersion)
        product = axlVersion('formalName)
        drawing = axlGetDrawingName()
        output = outfile(opaProbeOutput)
        unless(output
            error("OPA: cannot create the probe report.\n")
        )
        unwindProtect(
            progn(
                fprintf(output "probe_schema 1\n")
                fprintf(output "editor_version %L\n" version)
                fprintf(output "product_display_name %L\n" product)
                fprintf(output "drawing %L\n" drawing)
                fprintf(output "units %L\n" units)
                fprintf(output "component_count %d\n" length(design->components))
                foreach(component design->components
                    fprintf(output "component %L %L\n"
                            component->name component->package)
                )
                fprintf(output "write_operations_executed nil\n")
                fprintf(output "license_entitlement operator_confirmation_required\n")
                fprintf(output "probe_complete t\n")
            )
            close(output)
        )
        axlMsgPut(strcat("OPA: read-only probe report written to " opaProbeOutput))
        t
    )
)

axlCmdRegister("opa_probe" 'opaProbe ?cmdType "general")

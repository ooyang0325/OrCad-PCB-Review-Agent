; Data-only wire protocol. All entry points are bounded registered commands.
procedure(opaRequire(condition message)
    unless(condition
        opaError = message
        error("OPA: %s\n" message)
    )
    t
)

procedure(opaID(value)
    stringp(value) && strlen(value) == 32 &&
        !rexMatchp("[^0-9a-f]" value)
)

procedure(opaField(value)
    let((index code)
        opaRequire(stringp(value) "Wire field is not a string.")
        opaRequire(strlen(value) <= 8192 "Wire field exceeds size limit.")
        for(index 1 strlen(value)
            code = charToInt(stringToSymbol(substring(value index 1)))
            opaRequire(code >= 32 && code <= 126 "Non-ASCII or control character in wire field.")
        )
        value
    )
)

procedure(opaCsv(value)
    let((result index character)
        opaField(value)
        result = "\""
        for(index 1 strlen(value)
            character = substring(value index 1)
            result = strcat(result if(character == "\"" then "\"\"" else character))
        )
        strcat(result "\"")
    )
)

procedure(opaNumber(value)
    let((unsigned parts index character dots digits result)
        opaField(value)
        opaRequire(strlen(value) > 0 && strlen(value) <= 20 "Invalid decimal length.")
        unsigned = value
        when(substring(value 1 1) == "-"
            opaRequire(strlen(value) > 1 "Decimal contains only a sign.")
            unsigned = substring(value 2)
        )
        dots = 0
        digits = 0
        for(index 1 strlen(unsigned)
            character = substring(unsigned index 1)
            if(character == "." then
                dots = dots + 1
            else
                opaRequire(member(character '("0" "1" "2" "3" "4" "5" "6" "7" "8" "9"))
                           "Invalid decimal character.")
                digits = digits + 1
            )
        )
        opaRequire(dots <= 1 && digits > 0 "Invalid decimal notation.")
        opaRequire(substring(unsigned 1 1) != "." &&
                   substring(unsigned strlen(unsigned) 1) != "."
                   "Decimal needs digits on both sides of a point.")
        parts = parseString(unsigned ".")
        opaRequire(strlen(car(parts)) <= 9 "Decimal integer part is too large.")
        opaRequire(strlen(car(parts)) == 1 || substring(unsigned 1 1) != "0"
                   "Leading zeroes are not canonical decimals.")
        when(dots == 1
            opaRequire(strlen(cadr(parts)) <= 9 "Decimal precision exceeds protocol limit.")
        )
        result = atof(value)
        opaRequire(numberp(result) "Decimal conversion failed.")
        result
    )
)

procedure(opaPath(identifier suffix)
    opaRequire(opaID(identifier) "Invalid request identifier.")
    strcat(opaRoot "\\" identifier suffix)
)

procedure(opaReadRequest(identifier operation)
    let((port rows line row params)
        opaRequire(opaID(identifier) "Invalid request identifier.")
        opaRequire(!isFile(opaPath(identifier ".result.csv")) "Request already completed.")
        port = infile(opaPath(identifier ".request.csv"))
        opaRequire(port "Request file is missing.")
        unwindProtect(
            while(gets(line port)
                opaRequire(length(rows) < 3 && strlen(line) <= 1024 "Oversized request.")
                opaRequire(substring(line strlen(line) 1) == "\n" "Incomplete request row.")
                line = substring(line 1 strlen(line) - 1)
                when(strlen(line) > 0 && substring(line strlen(line) 1) == "\r"
                    line = substring(line 1 strlen(line) - 1)
                )
                opaField(line)
                opaRequire(!rexMatchp("\"" line) "Quoted request fields are not supported.")
                row = axlStringCSVParse(line)
                rows = append(rows list(row))
            )
            close(port)
        )
        opaRequire(length(rows) == 3 "Request requires exactly three rows.")
        opaRequire(equal(car(rows) list("OPA" "1" opaNonce identifier operation))
                   "Request version, session, ID or operation mismatch.")
        opaRequire(equal(caddr(rows) list("end" identifier)) "Invalid completion marker.")
        params = cadr(rows)
        opaRequire(length(params) == 7 && car(params) == "params" "Invalid parameters record.")
        if(operation == "snapshot" then
            opaRequire(equal(cdr(params) '("" "" "" "" "" "")) "Read request contains write parameters.")
        else
            opaRequire(opaID(nth(1 params)) "Expected snapshot identifier is required.")
            if(operation == "apply" then
                opaRequire(strlen(nth(2 params)) > 0 && strlen(nth(2 params)) <= 31 &&
                           !rexMatchp("[^A-Za-z0-9_]" nth(2 params)) &&
                           rexMatchp("^[A-Za-z]" nth(2 params))
                           "Invalid reference designator.")
                opaNumber(nth(3 params))
                opaNumber(nth(4 params))
                opaNumber(nth(5 params))
                opaRequire(nth(6 params) == "" "Apply cannot save a board.")
            else
                opaRequire(operation == "save" "Unknown operation.")
                opaRequire(equal(list(nth(2 params) nth(3 params) nth(4 params) nth(5 params))
                                 '("" "" "" "")) "Save cannot contain a transform.")
                opaRequire(strlen(nth(6 params)) == 45 &&
                           substring(nth(6 params) 1 9) == "revision-" &&
                           opaID(substring(nth(6 params) 10 32)) &&
                           substring(nth(6 params) 42) == ".brd" "Invalid revision filename.")
            )
        )
        params
    )
)

procedure(opaResult(identifier status message records)
    let((temporary destination output rows row values count total text)
        opaRequire(member(status '("snapshot" "applied" "rejected" "rolled_back"
                                   "saved" "indeterminate")) "Invalid terminal status.")
        temporary = opaPath(identifier ".result.partial")
        destination = opaPath(identifier ".result.csv")
        opaRequire(!isFile(destination) && !isFile(temporary) "Result already exists; do not overwrite.")
        rows = append(list(list("OPA" "1" opaNonce identifier status) list("message" message))
                      append(records list(list("end" identifier))))
        opaRequire(length(rows) <= 4096 "Result has too many records.")
        ; Validate all rows before opening the output, so malformed data never
        ; leaves a success-shaped partial result.
        values = nil
        total = 0
        foreach(row rows
            opaRequire(length(row) > 0 && length(row) <= 16 "Invalid result field count.")
            text = buildString(mapcar('opaCsv row) ",")
            total = total + strlen(text) + 1
            opaRequire(total <= 1048576 "Result exceeds size limit.")
            values = append(values list(text))
        )
        output = outfile(temporary)
        opaRequire(output "Cannot create result file.")
        unwindProtect(
            foreach(text values fprintf(output "%s\n" text))
            close(output)
        )
        opaRequire(!isFile(destination) "Result appeared concurrently.")
        opaRequire(renameFile(temporary destination) "Result publication failed.")
        t
    )
)

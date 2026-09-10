// Model-visible actions contain no shell strings, paths, or approval answers.
const sessionProperty = {
    type: "string",
    pattern: "^board-[A-Za-z0-9_-]{1,64}$",
    description: "Exact managed board-session name from the supplied context or session list.",
};
const proposalProperty = {
    type: "string",
    pattern: "^[0-9a-f]{64}$",
    description: "Exact visually grounded proposal identifier returned by prepare.",
};

function schema(properties, required = Object.keys(properties)) {
    return { type: "object", properties, required, additionalProperties: false };
}

function requireFields(args, fields) {
    if (!args || typeof args !== "object" || Array.isArray(args) ||
        Object.keys(args).length !== fields.length ||
        fields.some((field) => typeof args[field] !== "string")) {
        throw new Error("Unexpected or missing tool fields; approval answers cannot be supplied by the model.");
    }
    if (fields.includes("session") && !/^board-[A-Za-z0-9_-]{1,64}$/.test(args.session)) {
        throw new Error("Expected a managed session name, not a path.");
    }
    if (fields.includes("proposal") && !/^[0-9a-f]{64}$/.test(args.proposal)) {
        throw new Error("Expected the exact proposal identifier.");
    }
}

export function createPlacementTools({ run, requestInput, canPrompt, imageResult }) {
    function display(value) {
        return JSON.stringify(value, (_key, item) => {
            if (typeof item === "string" && item.startsWith("OPA-FIXTURE-1;")) {
                return {
                    opaque_scene_omitted_from_display: true,
                    instruction: "Use the persisted native receipt for complete machine-readable scene data.",
                };
            }
            return item;
        });
    }

    async function render(value) {
        let resultType = ["error", "indeterminate", "blocked", "inspection_pending"].includes(value.status) ||
            value.visual_error ? "failure" :
            ["rejected", "rolled_back"].includes(value.status) ? "rejected" : "success";
        const result = { textResultForLlm: display(value), resultType };
        if (value.visual) {
            try {
                result.binaryResultsForLlm = [await imageResult(value.visual)];
            } catch (error) {
                result.resultType = "failure";
                result.textResultForLlm = display({
                    ...value, image_error: error.message,
                    warning: "The native outcome above still stands. Do not retry a placement because its image is unavailable.",
                });
            }
        }
        return result;
    }

    function tool(name, description, parameters, action, fields) {
        return {
            name, description, parameters,
            handler: async (args) => {
                try {
                    requireFields(args, fields);
                    return await render(await run({ action, ...args }));
                } catch (error) {
                    return { resultType: "failure", textResultForLlm: JSON.stringify({
                        status: "error", error: error.message, retry_placement: false,
                    }) };
                }
            },
        };
    }

    const tools = [
        tool("pcb_sessions",
            "List recorded managed PCB sessions. A listed binding is not proof that its board is currently open; do not select an unrelated session.",
            schema({}), "sessions", []),
        tool("pcb_inspect",
            "Capture only the bound Cadence window and return its PNG plus fresh before/after snapshots. Visually inspect this image; pixels alone do not prove DRC or electrical correctness.",
            schema({ session: sessionProperty }), "inspect", ["session"]),
        tool("pcb_prepare_placement",
            "Prepare one exact fixture-component pose, with a current native image and snapshot evidence. Does not move or approve anything. Target angles are 0/90/180/270 degrees, absolute millimeters, component-origin pivot.",
            schema({
                session: sessionProperty,
                refdes: { type: "string", pattern: "^[A-Za-z][A-Za-z0-9_]{0,30}$" },
                x: { type: "string", description: "Absolute X in millimeters; plain finite decimal." },
                y: { type: "string", description: "Absolute Y in millimeters; plain finite decimal." },
                angle: { type: "string", enum: ["0", "90", "180", "270"] },
            }), "prepare", ["session", "refdes", "x", "y", "angle"]),
        tool("pcb_execution_status",
            "Read/reconcile the native outcome of one proposal without resending it. Use after timeout or missing visual output, never blindly retry a placement.",
            schema({ session: sessionProperty, proposal: proposalProperty }),
            "execution-status", ["session", "proposal"]),
    ];
    tools.push({
        name: "pcb_inspection_status",
        description: "Report a pending read-only snapshot after a capture timeout. Supply its exact request ID to reconcile only that snapshot's late result. Never resends commands or reconciles a pending placement.",
        parameters: schema({
            session: sessionProperty,
            request: {
                type: "string", pattern: "^[0-9a-f]{32}$",
                description: "Optional exact pending read-only request ID reported by this tool or execution status.",
            },
        }, ["session"]),
        handler: async (args) => {
            try {
                requireFields(args, args && "request" in args ? ["session", "request"] : ["session"]);
                if ("request" in args && !/^[0-9a-f]{32}$/.test(args.request)) {
                    throw new Error("Expected the exact pending read-only request ID.");
                }
                return await render(await run({ action: "inspection-status", ...args }));
            } catch (error) {
                return {
                    resultType: "failure", textResultForLlm: JSON.stringify({
                        status: "error", error: error.message, retry_placement: false,
                    }),
                };
            }
        },
    });
    tools.push({
        name: "pcb_apply_placement",
        description: "Ask the human through an interactive UI to approve one exact visually grounded proposal, then apply it in memory and return native outcome plus post-image. No model-supplied confirmation, auto-approval, arbitrary SKILL, or implicit save.",
        parameters: schema({ session: sessionProperty, proposal: proposalProperty }),
        handler: async (args) => {
            try {
                requireFields(args, ["session", "proposal"]);
                if (!canPrompt()) {
                    return {
                        resultType: "denied",
                        textResultForLlm: JSON.stringify({
                            status: "denied", dispatched: false,
                            reason: "This host cannot obtain interactive human approval. No native command was sent.",
                        }),
                    };
                }
                const description = await run({ action: "describe", ...args });
                if (description.status !== "prepared") return await render(description);
                const expected = `APPLY ${args.proposal}`;
                const answer = await requestInput(
                    `${description.summary}\nBoard copy: ${description.working_board}\n` +
                    `Visual observation: ${description.visual.observation_id}\n` +
                    `${description.warning}\n\nType ${expected} to approve exactly this proposal. ` +
                    "Cancel or leave blank to keep the board unchanged.",
                    { title: "Exact placement approval", minLength: 70, maxLength: 70 },
                );
                if (answer !== expected) {
                    return {
                        resultType: "denied",
                        textResultForLlm: JSON.stringify({
                            status: "denied", dispatched: false,
                            reason: "Exact human approval was not supplied. No Apply was sent.",
                        }),
                    };
                }
                return await render(await run({ action: "apply", ...args, confirmation: answer }));
            } catch (error) {
                return {
                    resultType: "failure",
                    textResultForLlm: JSON.stringify({
                        status: "error", error: error.message,
                        warning: "Do not infer rollback or retry. Query this proposal's execution status if approval was already submitted.",
                    }),
                };
            }
        },
    });
    return tools;
}

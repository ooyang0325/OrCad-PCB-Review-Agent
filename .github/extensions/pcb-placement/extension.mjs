import { joinSession } from "@github/copilot-sdk/extension";
import { spawn } from "node:child_process";
import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createPlacementTools } from "./operations.mjs";

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const python = path.join(workspace, ".venv", "Scripts", "python.exe");
const outputLimit = 2 * 1024 * 1024;

function run(request) {
    return new Promise((resolve, reject) => {
        const child = spawn(python, ["-m", "orcad_placement_agent.agent_tools"], {
            cwd: workspace, windowsHide: true, shell: false,
            stdio: ["pipe", "pipe", "pipe"],
            env: { ...process.env, PYTHONIOENCODING: "utf-8" },
        });
        let stdout = "";
        let stderr = "";
        let completed = false;
        const finish = (error, result) => {
            if (completed) return;
            completed = true;
            clearTimeout(timer);
            if (error) reject(error);
            else resolve(result);
        };
        const timer = setTimeout(() => {
            child.kill();
            finish(null, {
                status: "indeterminate", error: "Local worker exceeded its deadline.",
                warning: "Only the worker was stopped. A native operation may have completed; use execution status, not replay.",
            });
        }, 120000);
        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", (chunk) => {
            stdout += chunk;
            if (Buffer.byteLength(stdout, "utf8") > outputLimit) {
                child.kill();
                finish(new Error("Worker response exceeded the bounded output limit; reconcile any approved operation."));
            }
        });
        child.stderr.on("data", (chunk) => {
            if (stderr.length < 8192) stderr += chunk.slice(0, 8192 - stderr.length);
        });
        child.on("error", (error) => finish(new Error(`Cannot run the local controller: ${error.message}`)));
        child.stdin.on("error", (error) => finish(new Error(`Controller input failed: ${error.message}`)));
        child.on("close", (code) => {
            if (completed) return;
            try {
                const value = JSON.parse(stdout);
                if (!value || typeof value.status !== "string") throw new Error("Missing structured status.");
                if (code !== 0 && !["error", "indeterminate"].includes(value.status)) {
                    throw new Error("Worker exit and structured status disagree.");
                }
                finish(null, value);
            } catch (error) {
                finish(new Error(`Controller did not return a valid outcome: ${error.message}. ${stderr}`));
            }
        });
        child.stdin.end(JSON.stringify(request));
    });
}

async function imageResult(visual) {
    if (typeof process.env.LOCALAPPDATA !== "string" ||
        !/^[0-9a-f]{32}$/.test(visual.observation_id) ||
        typeof visual.image_path !== "string") {
        throw new Error("Invalid visual artifact metadata.");
    }
    const runtime = await realpath(path.join(process.env.LOCALAPPDATA, "OrCadPlacementAgent", "sessions"));
    const image = await realpath(visual.image_path);
    const relative = path.relative(runtime, image);
    const parts = relative.split(path.sep);
    if (parts.length !== 2 || !/^board-[A-Za-z0-9_-]{1,64}$/.test(parts[0]) ||
        parts[1] !== `visual-${visual.observation_id}.png`) {
        throw new Error("Visual artifact is outside a managed board session.");
    }
    if ((await stat(image)).size > 8 * 1024 * 1024) throw new Error("Visual image exceeds 8 MiB.");
    const bytes = await readFile(image);
    if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
        throw new Error("Visual artifact is not a PNG.");
    }
    return {
        type: "image", mimeType: "image/png", data: bytes.toString("base64"),
        description: `Native PCB observation ${visual.observation_id}; inspect alongside its fresh snapshot metadata.`,
    };
}

let session;
const tools = createPlacementTools({
    run, imageResult,
    canPrompt: async () => Boolean(session?.capabilities.ui?.elicitation) &&
        (await session.rpc.mode.get()) === "interactive",
    requestInput: (message, options) => session.ui.input(message, options),
});
session = await joinSession({ tools });

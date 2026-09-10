import os
from pathlib import Path
import shutil
import subprocess
import unittest


SCRIPT = r"""
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { createPlacementTools } = await import(pathToFileURL(process.argv[1]));
const digest = "a".repeat(64);
const args = { session: "board-fixture", proposal: digest };
const visual = { observation_id: "b".repeat(32), image_path: "fixture.png" };
function harness({ supported = true, answer = null, imageFailure = false } = {}) {
    const requests = [];
    const prompts = [];
    const tools = createPlacementTools({
        canPrompt: () => supported,
        requestInput: async (message, options) => {
            prompts.push({ message, options });
            return answer;
        },
        run: async (request) => {
            requests.push(request);
            return ["describe", "describe-save"].includes(request.action)
                ? { status: "prepared", summary: "R1 (10,10) -> (12,12), 90 degrees",
                    working_board: "working.brd", warning: "Memory only", visual }
                : { status: request.action === "apply" ? "applied" :
                    request.action === "apply-save" ? "saved" : "observed", visual };
        },
        imageResult: async () => {
            if (imageFailure) throw new Error("Image unavailable");
            return { type: "image", mimeType: "image/png", data: "test" };
        },
    });
    return { requests, prompts, tools, apply: tools.find(t => t.name === "pcb_apply_placement") };
}
let h = harness({ supported: false });
assert.equal((await h.apply.handler(args)).resultType, "denied");
assert.equal(h.requests.length, 0);
h = harness();
assert.equal((await h.apply.handler(args)).resultType, "denied");
assert.equal(h.requests.length, 1);
assert.equal(h.requests[0].action, "describe");
assert.equal(h.prompts[0].options.default, undefined);
h = harness({ answer: `APPLY ${digest}` });
assert.equal((await h.apply.handler({ ...args, confirmation: `APPLY ${digest}` })).resultType, "failure");
assert.equal(h.prompts.length, 0);
assert.equal(h.requests.length, 0);
h = harness({ answer: `APPLY ${digest}` });
let save = h.tools.find(t => t.name === "pcb_save_revision");
assert.equal((await save.handler(args)).resultType, "denied");
assert.equal(h.requests.some(r => r.action === "apply-save"), false);
h = harness({ answer: `SAVE ${digest}` });
save = h.tools.find(t => t.name === "pcb_save_revision");
assert.equal((await save.handler(args)).resultType, "success");
assert.equal(h.requests[1].action, "apply-save");
assert.equal(h.prompts[0].options.minLength, 69);
h = harness({ answer: "yes" });
assert.equal((await h.apply.handler(args)).resultType, "denied");
assert.equal(h.requests.some(r => r.action === "apply"), false);
h = harness({ answer: `APPLY ${digest}` });
const outcome = await h.apply.handler(args);
assert.equal(outcome.resultType, "success");
assert.equal(h.requests[1].action, "apply");
assert.equal(h.requests[1].confirmation, `APPLY ${digest}`);
assert.equal(outcome.binaryResultsForLlm[0].type, "image");
assert.match(h.prompts[0].message, /R1 \(10,10\)/);
assert.match(h.prompts[0].message, /Memory only/);
h = harness({ answer: `APPLY ${digest}`, imageFailure: true });
const failedImage = await h.apply.handler(args);
assert.equal(failedImage.resultType, "failure");
assert.equal(JSON.parse(failedImage.textResultForLlm).status, "applied");
assert.equal(h.requests.filter(r => r.action === "apply").length, 1);
for (const tool of h.tools) assert.equal(tool.parameters.additionalProperties, false);
assert.deepEqual(Object.keys(h.apply.parameters.properties), ["session", "proposal"]);
h = harness();
for (const [name, args, action] of [
    ["pcb_reference_catalog", {}, "reference-catalog"],
    ["pcb_reference_search", { query: "decoupling" }, "reference-search"],
    ["pcb_reference_rule", { card_id: "pt-example" }, "reference-rule"],
]) {
    const tool = h.tools.find(t => t.name === name);
    assert.ok(tool);
    assert.equal((await tool.handler(args)).resultType, "success");
    assert.equal(h.requests.at(-1).action, action);
    assert.equal((await tool.handler({ ...args, database: "outside" })).resultType, "failure");
}
assert.equal(h.prompts.length, 0);
let modeChecks = 0;
let dispatched = false;
const switched = createPlacementTools({
    canPrompt: async () => ++modeChecks === 1,
    requestInput: async () => `APPLY ${digest}`,
    imageResult: async () => ({ type: "image", mimeType: "image/png", data: "test" }),
    run: async (request) => {
        if (request.action === "apply") dispatched = true;
        return { status: "prepared", summary: "R1 exact move", working_board: "working.brd",
            warning: "Memory only", visual };
    },
}).find(t => t.name === "pcb_apply_placement");
assert.equal((await switched.handler(args)).resultType, "denied");
assert.equal(dispatched, false);
console.log("Bounded extension approval and image-outcome cases passed.");
"""


class ExtensionToolTests(unittest.TestCase):
    def test_model_cannot_supply_approval_or_bypass_missing_ui(self):
        node = os.environ.get("OPA_NODE") or shutil.which("node")
        if not node or not Path(node).is_file():
            self.skipTest("Set OPA_NODE to an existing Node.js 20+ executable for extension tests.")
        root = Path(__file__).resolve().parents[1]
        module = root / ".github" / "extensions" / "pcb-placement" / "operations.mjs"
        result = subprocess.run(
            [node, "--input-type=module", "-e", SCRIPT, str(module)],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from orcad_placement_agent.visuals import encode_png


AVAILABLE = importlib.util.find_spec("mcp") is not None
PROPOSAL = "a" * 64


class FakeActions:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.applied = set()
        self.visual = {"observation_id": "b" * 32, "image_path": str(root / "fixture.png")}

    def dispatch(self, request):
        self.calls.append(request)
        action = request["action"]
        if action == "describe":
            return {
                "status": "prepared", "summary": "R1: (10, 10) -> (12, 12), 90 degrees",
                "working_board": str(self.root / "working.brd"),
                "warning": "Memory only; not a save.", "visual": self.visual,
            }
        if action == "apply":
            if request["proposal"] in self.applied:
                return {"status": "error", "error": "Proposal approval was already consumed."}
            self.applied.add(request["proposal"])
            return {"status": "applied", "visual": self.visual, "receipt": {"status": "applied"}}
        if action == "sessions":
            return {"status": "listed", "sessions": []}
        return {"status": "observed", "visual": self.visual, "scene_native": "OPA-FIXTURE-1;opaque"}


@unittest.skipUnless(AVAILABLE, "Install the optional integrations extra for MCP tests.")
class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from orcad_placement_agent.mcp_server import create_server

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.actions = FakeActions(Path(self.temp.name))
        self.png = encode_png(2, 1, bytes([0, 0, 255, 0, 0, 255, 0, 0]))
        self.server = create_server(
            lambda: self.actions, image_reader=lambda _actions, _visual: self.png,
            allow_interactive_writes=True,
        )

    async def test_tool_catalog_hides_approval_and_exposes_images_and_recovery(self):
        from mcp import Client

        async with Client(self.server) as client:
            tools = (await client.list_tools()).tools
            names = {tool.name for tool in tools}
            self.assertEqual(names, {
                "pcb_sessions", "pcb_inspect", "pcb_prepare_placement", "pcb_apply_placement",
                "pcb_execution_status", "pcb_inspection_status", "pcb_reference_catalog",
                "pcb_reference_search", "pcb_reference_page",
            })
            apply = next(tool for tool in tools if tool.name == "pcb_apply_placement")
            self.assertEqual(set(apply.input_schema["properties"]), {"session", "proposal"})
            self.assertFalse(apply.annotations.read_only_hint)
            self.assertFalse(apply.annotations.idempotent_hint)
            result = await client.call_tool("pcb_inspect", {"session": "board-fixture"})
            self.assertFalse(result.is_error)
            image = next(block for block in result.content if block.type == "image")
            self.assertEqual(base64.b64decode(image.data), self.png)
            self.assertEqual(image.mime_type, "image/png")
            self.assertTrue(result.structured_content["scene_native"]["opaque_scene_omitted_from_display"])

    async def test_missing_elicitation_never_applies_in_either_protocol_mode(self):
        from mcp import Client, MCPError

        for mode in ("legacy", "auto"):
            with self.subTest(mode=mode):
                async with Client(self.server, mode=mode) as client:
                    with self.assertRaises(MCPError):
                        await client.call_tool(
                            "pcb_apply_placement", {"session": "board-fixture", "proposal": PROPOSAL}
                        )
        self.assertFalse(self.actions.applied)
        self.assertFalse(any(call["action"] == "apply" for call in self.actions.calls))

    async def test_default_install_cannot_write_even_with_an_auto_answering_client(self):
        from mcp import Client
        from mcp.types import ElicitResult
        from orcad_placement_agent.mcp_server import create_server

        prompts = []

        async def callback(_context, params):
            prompts.append(params)
            return ElicitResult(action="accept", content={"confirmation": f"APPLY {PROPOSAL}"})

        server = create_server(lambda: self.actions, image_reader=lambda _a, _v: self.png)
        async with Client(server, elicitation_callback=callback) as client:
            result = await client.call_tool("pcb_apply_placement", {
                "session": "board-fixture", "proposal": PROPOSAL,
                "allow_interactive_writes": True,
            })
            self.assertTrue(result.is_error)
        self.assertEqual(prompts, [])
        self.assertEqual(self.actions.calls, [])

    async def test_decline_cancel_and_wrong_answers_never_apply(self):
        from mcp import Client
        from mcp.types import ElicitResult

        for action, content in [
            ("decline", None), ("cancel", None),
            ("accept", {"confirmation": "APPLY " + "c" * 64}),
        ]:
            with self.subTest(action=action):
                async def callback(_context, params):
                    self.assertIn(f"APPLY {PROPOSAL}", params.message)
                    self.assertNotIn("default", params.requested_schema["properties"]["confirmation"])
                    return ElicitResult(action=action, content=content)

                async with Client(self.server, elicitation_callback=callback) as client:
                    result = await client.call_tool(
                        "pcb_apply_placement", {"session": "board-fixture", "proposal": PROPOSAL}
                    )
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content["status"], "denied")
        self.assertFalse(self.actions.applied)

    async def test_model_cannot_inject_the_hidden_approval_parameter(self):
        from mcp import Client
        from mcp.types import ElicitResult

        prompts = []

        async def callback(_context, params):
            prompts.append(params.message)
            return ElicitResult(action="decline")

        async with Client(self.server, elicitation_callback=callback) as client:
            result = await client.call_tool("pcb_apply_placement", {
                "session": "board-fixture", "proposal": PROPOSAL,
                "confirmation": f"APPLY {PROPOSAL}",
                "decision": {"action": "accept", "data": {"confirmation": f"APPLY {PROPOSAL}"}},
            })
            self.assertTrue(result.is_error)
        self.assertEqual(len(prompts), 1)
        self.assertFalse(self.actions.applied)

    async def test_exact_fake_ui_answer_is_the_only_path_to_fake_apply(self):
        from mcp import Client
        from mcp.types import ElicitResult

        for mode, proposal in [("legacy", "a" * 64), ("auto", "c" * 64)]:
            with self.subTest(mode=mode):
                prompts = []

                async def callback(_context, params):
                    prompts.append(params.message)
                    return ElicitResult(action="accept", content={"confirmation": f"APPLY {proposal}"})

                async with Client(self.server, mode=mode, elicitation_callback=callback) as client:
                    result = await client.call_tool(
                        "pcb_apply_placement", {"session": "board-fixture", "proposal": proposal}
                    )
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content["status"], "applied")
                self.assertEqual(len(prompts), 1)
        self.assertEqual(len(self.actions.applied), 2)

    async def test_image_failure_preserves_recorded_native_outcome(self):
        from mcp import Client
        from mcp.types import ElicitResult
        from orcad_placement_agent.mcp_server import create_server
        from orcad_placement_agent.visuals import VisualError

        def image(_actions, _visual):
            if self.actions.applied:
                raise VisualError("Post-image unavailable")
            return self.png

        async def callback(_context, _params):
            return ElicitResult(action="accept", content={"confirmation": f"APPLY {PROPOSAL}"})

        server = create_server(lambda: self.actions, image_reader=image, allow_interactive_writes=True)
        async with Client(server, elicitation_callback=callback) as client:
            result = await client.call_tool(
                "pcb_apply_placement", {"session": "board-fixture", "proposal": PROPOSAL}
            )
            self.assertTrue(result.is_error)
            self.assertEqual(result.structured_content["status"], "applied")
            self.assertIn("image_error", result.structured_content)
        self.assertEqual(len(self.actions.applied), 1)

    async def test_invalid_inputs_and_unconfigured_references_are_explicit(self):
        from mcp import Client

        async with Client(self.server) as client:
            result = await client.call_tool("pcb_inspect", {"session": "../outside"})
            self.assertTrue(result.is_error)
            self.assertEqual(self.actions.calls, [])
            result = await client.call_tool("pcb_reference_catalog", {})
            self.assertTrue(result.is_error)
            self.assertIn("knowledge", result.structured_content["error"])

    async def test_real_stdio_entrypoint_runs_without_repository_cwd(self):
        from mcp import Client, StdioServerParameters

        environment = dict(os.environ)
        environment.pop("OPA_KNOWLEDGE_DB", None)
        parameters = StdioServerParameters(
            command=sys.executable, args=["-I", "-X", "utf8", "-m", "orcad_placement_agent.mcp_server"],
            cwd=self.temp.name, env=environment,
        )
        async with Client(parameters, mode="legacy", read_timeout_seconds=15) as client:
            self.assertEqual(len((await client.list_tools()).tools), 9)
            result = await client.call_tool("pcb_reference_catalog", {})
            self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()

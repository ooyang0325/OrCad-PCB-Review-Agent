import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from orcad_placement_agent.installation import configuration, write_configurations


class InstallationConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.python = self.root / "Python with spaces" / "python.exe"
        self.python.parent.mkdir()
        self.python.write_bytes(b"configuration-only test placeholder")

    def test_codex_toml_has_exact_executable_and_separate_arguments(self):
        text = configuration("codex", self.python, self.root / "\u6587\u4ef6.sqlite3")
        server = tomllib.loads(text)["mcp_servers"]["orcad-placement"]
        self.assertEqual(server["command"], str(self.python))
        self.assertEqual(server["args"], [
            "-I", "-X", "utf8", "-m", "orcad_placement_agent.mcp_server",
            "--knowledge-db", str(self.root / "\u6587\u4ef6.sqlite3"),
        ])
        self.assertEqual(server["tool_timeout_sec"], 180)

    def test_claude_copilot_and_vscode_config_shapes(self):
        for client in ("claude", "copilot", "vscode"):
            data = json.loads(configuration(client, self.python))
            server = data["servers" if client == "vscode" else "mcpServers"]["orcad-placement"]
            self.assertEqual(server["command"], str(self.python))
            self.assertEqual(server["type"], "local" if client == "copilot" else "stdio")
            self.assertNotIn("approved", server)
            self.assertNotIn("confirmation", server)

    def test_snippets_are_idempotent_and_never_replace_different_content(self):
        paths = write_configurations(self.root / "generated", executable=self.python)
        self.assertEqual(len(paths), 4)
        self.assertEqual(write_configurations(self.root / "generated", executable=self.python), paths)
        paths[0].write_text("existing user content", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            write_configurations(self.root / "generated", executable=self.python)
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "existing user content")

    def test_unknown_client_or_missing_interpreter_is_rejected(self):
        with self.assertRaises(ValueError):
            configuration("unknown", self.python)
        with self.assertRaises(FileNotFoundError):
            configuration("codex", self.root / "missing.exe")


if __name__ == "__main__":
    unittest.main()

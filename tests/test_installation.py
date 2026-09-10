import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from orcad_placement_agent import __version__
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
            self.assertNotIn("--knowledge-db", server["args"])

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


class InstallerDefaultTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("installer_under_test", self.root / "scripts" / "install.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)

    def test_default_installer_omits_pdf_dependencies_and_database_configuration(self):
        root, installer = self.root, self.installer
        for books in (False, True):
            with self.subTest(books=books), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                environment = temporary / "fresh-runtime"
                calls = []

                def fake_run(arguments, **_options):
                    command = [str(item) for item in arguments]
                    calls.append(command)
                    if "venv" in command:
                        (environment / "Scripts").mkdir(parents=True)
                        (environment / "Scripts" / "python.exe").write_bytes(b"test interpreter")

                argv = ["install.py", "--environment-directory", str(environment)]
                if books:
                    argv += ["--books", str(temporary / "optional-books")]
                with (
                    patch.object(installer, "local_data", return_value=temporary),
                    patch.object(installer, "run", side_effect=fake_run),
                    patch.object(installer.subprocess, "run", return_value=Mock(stdout="")),
                    patch.object(installer.sys, "argv", argv),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    installer.main()
                config = next(command for command in calls if "integration-config" in command)
                self.assertEqual("--knowledge-db" in config, books)
                self.assertEqual(any("index" in command for command in calls), books)
                installs = [command[-1] for command in calls if "pip" in command]
                self.assertIn(str(root) + "[integrations]", installs)
                self.assertEqual(any("knowledge]" in target for target in installs), books)
                self.assertTrue((environment / ".orcad-placement-environment.json").is_file())

    def test_adding_books_preserves_existing_default_snippets(self):
        installer = self.installer
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = temporary / "runtime"
            python = environment / "Scripts" / "python.exe"

            def fake_run(arguments, **_options):
                command = [str(item) for item in arguments]
                if "venv" in command:
                    python.parent.mkdir(parents=True)
                    python.write_bytes(b"test interpreter")
                if "integration-config" in command:
                    output = Path(command[command.index("--output-directory") + 1])
                    database = Path(command[command.index("--knowledge-db") + 1]) if "--knowledge-db" in command else None
                    write_configurations(output, executable=python, knowledge_database=database)

            argv = ["install.py", "--environment-directory", str(environment)]
            with (
                patch.object(installer, "local_data", return_value=temporary),
                patch.object(installer, "run", side_effect=fake_run),
                patch.object(installer.subprocess, "run", side_effect=[Mock(stdout=""), Mock(stdout=__version__)]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with patch.object(installer.sys, "argv", argv):
                    installer.main()
                original = {path.name: path.read_bytes() for path in (environment / "client-configs").iterdir()}
                with patch.object(installer.sys, "argv", [*argv, "--books", str(temporary / "books")]):
                    installer.main()
            self.assertEqual(original, {path.name: path.read_bytes() for path in (environment / "client-configs").iterdir()})
            extra = environment / "client-configs-with-books" / "claude-mcp.json"
            self.assertIn("--knowledge-db", json.loads(extra.read_text())["mcpServers"]["orcad-placement"]["args"])


if __name__ == "__main__":
    unittest.main()

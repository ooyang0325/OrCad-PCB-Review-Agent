import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orcad_placement_agent.cli import main
from orcad_placement_agent.diagnostics import (
    ConfigurationError,
    default_runtime_directory,
    inspect_environment,
)


class EnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.editor = self.root / "cadence" / "tools" / "bin" / "allegro.exe"
        self.editor.parent.mkdir(parents=True)
        self.editor.write_bytes(b"test placeholder; not an executable")
        self.runtime = self.root / "sessions"

    def inspect(self):
        with patch("orcad_placement_agent.diagnostics.sys.platform", "win32"):
            return inspect_environment(self.root / "cadence", self.runtime)

    def test_environment_discovery_does_not_claim_live_access(self) -> None:
        report = self.inspect()
        self.assertTrue(report.ready)
        self.assertEqual(report.live_access, "unproven")
        self.assertFalse(self.runtime.exists())

    def test_missing_editor_is_explicit(self) -> None:
        self.editor.unlink()
        report = self.inspect()
        self.assertFalse(report.ready)
        self.assertIn("executable not found", report.issues[0])

    def test_unicode_runtime_is_rejected_without_rejecting_repository(self) -> None:
        self.runtime = self.root / "\u6587\u4ef6"
        report = self.inspect()
        self.assertFalse(report.ready)
        self.assertIn("ASCII-safe", report.issues[0])

    def test_runtime_cannot_be_an_existing_file(self) -> None:
        self.runtime.write_text("occupied", encoding="ascii")
        report = self.inspect()
        self.assertFalse(report.ready)
        self.assertIn("non-directory", report.issues[0])

    def test_other_platform_is_not_live_ready(self) -> None:
        with patch("orcad_placement_agent.diagnostics.sys.platform", "linux"):
            report = inspect_environment(self.root / "cadence", self.runtime)
        self.assertFalse(report.ready)
        self.assertIn("Windows only", report.issues[0])

    def test_default_runtime_is_user_local(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            self.assertEqual(
                default_runtime_directory(),
                self.root / "OrCadPlacementAgent" / "sessions",
            )

    def test_missing_local_app_data_requires_explicit_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigurationError):
                default_runtime_directory()

    def test_cli_json_separates_environment_from_live_access(self) -> None:
        output = io.StringIO()
        with (
            patch("orcad_placement_agent.diagnostics.sys.platform", "win32"),
            contextlib.redirect_stdout(output),
        ):
            code = main(
                [
                    "doctor",
                    "--cadence-root",
                    str(self.root / "cadence"),
                    "--runtime-dir",
                    str(self.runtime),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["environment_ready"])
        self.assertEqual(payload["live_access"], "unproven")

    def test_cli_returns_nonzero_for_missing_editor(self) -> None:
        self.editor.unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(
                [
                    "doctor",
                    "--cadence-root",
                    str(self.root / "cadence"),
                    "--runtime-dir",
                    str(self.runtime),
                ]
            )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from orcad_placement_agent.cli import main
from orcad_placement_agent.diagnostics import ConfigurationError
from orcad_placement_agent.probe import stage_probe


class ProbeStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "probe.il").write_text("; trusted test fixture\n", encoding="ascii")

    def test_stages_only_bootstrap_and_readonly_probe(self) -> None:
        result = stage_probe(self.runtime, self.skill)
        session = Path(result.session_directory)
        self.assertEqual(
            {path.name for path in session.iterdir()},
            {"probe.il", "bootstrap.il", "probe.scr"},
        )
        self.assertFalse(Path(result.report_file).exists())
        self.assertIn(
            json.dumps(result.report_file),
            Path(result.bootstrap_file).read_text(encoding="ascii"),
        )
        self.assertIn(
            result.load_command,
            Path(result.startup_script).read_text(encoding="ascii"),
        )

    def test_each_probe_uses_a_new_directory(self) -> None:
        first = stage_probe(self.runtime, self.skill)
        Path(first.report_file).write_text("old result", encoding="ascii")
        second = stage_probe(self.runtime, self.skill)
        self.assertNotEqual(first.session_directory, second.session_directory)
        self.assertEqual(
            Path(first.report_file).read_text(encoding="ascii"), "old result"
        )
        self.assertFalse(Path(second.report_file).exists())

    def test_unicode_source_path_is_supported(self) -> None:
        renamed = self.root / "\u6587\u4ef6"
        self.skill.rename(renamed)
        result = stage_probe(self.runtime, renamed)
        self.assertTrue(Path(result.bootstrap_file).exists())

    def test_unicode_runtime_is_rejected_before_creation(self) -> None:
        invalid = self.root / "\u6587\u4ef6"
        with self.assertRaises(ConfigurationError):
            stage_probe(invalid, self.skill)
        self.assertFalse(invalid.exists())

    def test_missing_source_does_not_create_runtime(self) -> None:
        with self.assertRaises(ConfigurationError):
            stage_probe(self.runtime, self.root / "missing")
        self.assertFalse(self.runtime.exists())

    def test_cli_staging_does_not_start_cadence_or_claim_live_access(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "stage-probe",
                    "--runtime-dir",
                    str(self.runtime),
                    "--skill-dir",
                    str(self.skill),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertFalse(Path(result["report_file"]).exists())


if __name__ == "__main__":
    unittest.main()
